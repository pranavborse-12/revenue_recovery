"""Tests for GET/POST /api/v1/recovery/*."""

from tests.conftest import make_payment_failed_payload, sign

WEBHOOK_URL = "/api/v1/webhooks/razorpay"
RECOVERY_URL = "/api/v1/recovery"


def _post_webhook(client, body_dict, event_id):
    raw_body, signature = sign(body_dict)
    return client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature,
            "X-Razorpay-Event-Id": event_id,
        },
    )


def _create_failed_payment_with_case(client, payment_id="pay_ApiTest001", amount=5000000):
    payload = make_payment_failed_payload(payment_id=payment_id, amount=amount)
    _post_webhook(client, payload, event_id=f"evt_{payment_id}")


class TestListRecoveryCases:
    def test_lists_created_cases(self, client):
        _create_failed_payment_with_case(client, payment_id="pay_List001")

        response = client.get(f"{RECOVERY_URL}/cases")
        assert response.status_code == 200
        cases = response.json()
        assert len(cases) == 1
        assert cases[0]["status"] == "IN_PROGRESS"
        assert cases[0]["current_strategy"] == "RETRY_PAYMENT"

    def test_empty_when_no_cases_exist(self, client):
        response = client.get(f"{RECOVERY_URL}/cases")
        assert response.status_code == 200
        assert response.json() == []

    def test_filters_by_status(self, client):
        _create_failed_payment_with_case(client, payment_id="pay_Filter001")

        matching = client.get(f"{RECOVERY_URL}/cases", params={"status_filter": "IN_PROGRESS"})
        assert len(matching.json()) == 1

        non_matching = client.get(f"{RECOVERY_URL}/cases", params={"status_filter": "RECOVERED"})
        assert len(non_matching.json()) == 0


class TestGetRecoveryCaseDetail:
    def test_returns_case_with_actions(self, client):
        _create_failed_payment_with_case(client, payment_id="pay_Detail001")

        case_id = client.get(f"{RECOVERY_URL}/cases").json()[0]["id"]
        response = client.get(f"{RECOVERY_URL}/cases/{case_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["razorpay_payment_id"] == "pay_Detail001"
        assert len(body["actions"]) == 1
        assert body["actions"][0]["action_type"] == "RETRY_PAYMENT"

    def test_returns_customer_and_ai_intelligence(self, client, db_engine):
        _create_failed_payment_with_case(client, payment_id="pay_Intel001")

        from sqlalchemy.orm import sessionmaker

        from app.models.ai_recovery_decision import AIRecoveryDecision
        from app.models.payment import Payment
        from app.models.recovery_case import RecoveryCase

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            case = db.query(RecoveryCase).one()
            db.add(
                AIRecoveryDecision(
                    recovery_case_id=case.id,
                    recommended_action="SEND_PAYMENT_LINK",
                    recommended_delay_minutes=60,
                    confidence=0.91,
                    reason="Historical reuse of payment links recovered similar bank-declined payments.",
                    model="mistral-small-latest",
                    agent_role="final",
                    provider="mistral",
                    accepted=True,
                    rejection_reason=None,
                    executed=True,
                    outcome="payment link created",
                )
            )
            db.commit()

        case_id = client.get(f"{RECOVERY_URL}/cases").json()[0]["id"]
        response = client.get(f"{RECOVERY_URL}/cases/{case_id}")

        assert response.status_code == 200
        body = response.json()
        assert body["customer"]["email"] == "test.customer@example.com"
        assert body["recovery_probability"] == 0.91
        assert body["ai_insight"]["recommended_action"] == "SEND_PAYMENT_LINK"
        assert body["ai_insight"]["confidence"] == 0.91
        assert body["ai_insight"]["model"] == "mistral-small-latest"
        assert body["historical_evidence"] is not None

    def test_404_for_nonexistent_case(self, client):
        response = client.get(f"{RECOVERY_URL}/cases/999999")
        assert response.status_code == 404


class TestRecoveryStats:
    def test_reflects_open_case(self, client):
        _create_failed_payment_with_case(client, payment_id="pay_Stats001", amount=8500000)

        response = client.get(f"{RECOVERY_URL}/stats")
        assert response.status_code == 200
        stats = response.json()
        assert stats["active_recovery_cases"] == 1
        assert stats["total_revenue_at_risk"] == 8500000
        assert stats["recovered_cases"] == 0
        assert stats["recovery_rate"] == 0.0

    def test_zero_state_when_nothing_has_happened(self, client):
        response = client.get(f"{RECOVERY_URL}/stats")
        assert response.status_code == 200
        stats = response.json()
        assert stats["active_recovery_cases"] == 0
        assert stats["total_revenue_at_risk"] == 0
        assert stats["recovery_rate"] == 0.0


class TestRetryCaseNow:
    def test_triggers_pending_action(self, client, stub_celery_dispatch):
        _create_failed_payment_with_case(client, payment_id="pay_RetryNow001")
        case_id = client.get(f"{RECOVERY_URL}/cases").json()[0]["id"]

        response = client.post(f"{RECOVERY_URL}/cases/{case_id}/retry")
        assert response.status_code == 200
        assert response.json()["status"] == "triggered"

    def test_404_for_nonexistent_case(self, client):
        response = client.post(f"{RECOVERY_URL}/cases/999999/retry")
        assert response.status_code == 404

    def test_409_when_no_pending_action(self, client, db_engine):
        """A case whose only action was already cancelled (e.g. resolved
        via a retry webhook) has nothing left to manually trigger."""
        _create_failed_payment_with_case(client, payment_id="pay_NoPending001")

        from sqlalchemy.orm import sessionmaker

        from app.models.recovery_action import RecoveryAction
        from app.models.recovery_case import RecoveryCase

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            case = db.query(RecoveryCase).one()
            action = db.query(RecoveryAction).filter_by(recovery_case_id=case.id).one()
            action.status = "CANCELLED"  # direct write OK in test setup, bypassing the model
            db.commit()
            case_id = case.id

        response = client.post(f"{RECOVERY_URL}/cases/{case_id}/retry")
        assert response.status_code == 409
