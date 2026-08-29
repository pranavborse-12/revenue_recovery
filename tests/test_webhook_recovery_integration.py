"""
Integration tests: webhook event -> payment state -> recovery case ->
recovery action, exercised through the real HTTP endpoint (not by
calling service functions directly), matching the project brief's
required demonstration scenario.
"""

from sqlalchemy.orm import sessionmaker

from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from tests.conftest import make_payment_captured_payload, make_payment_failed_payload, sign

WEBHOOK_URL = "/api/v1/webhooks/razorpay"


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


class TestWebhookToRecoveryPipeline:
    def test_failed_payment_webhook_creates_payment_and_recovery_case(self, client, db_engine):
        payload = make_payment_failed_payload(
            payment_id="pay_Pipeline001", order_id="order_Pipeline001", amount=8500000
        )

        response = _post_webhook(client, payload, event_id="evt_Pipeline001")
        assert response.status_code == 200
        assert response.json()["status"] == "processed"

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            payment = db.query(Payment).filter_by(razorpay_payment_id="pay_Pipeline001").one()
            assert payment.status == "FAILED"
            assert payment.failure_category == "INSUFFICIENT_FUNDS"

            case = db.query(RecoveryCase).filter_by(payment_id=payment.id).one()
            assert case.status == "IN_PROGRESS"
            assert case.current_strategy == "RETRY_PAYMENT"

            actions = db.query(RecoveryAction).filter_by(recovery_case_id=case.id).all()
            assert len(actions) == 1
            assert actions[0].status == "PENDING"
            assert actions[0].attempt_number == 1

    def test_duplicate_webhook_delivery_does_not_create_duplicate_recovery_case(
        self, client, db_engine
    ):
        """The brief's exact scenario: payment.failed delivered 3 times
        must not create 3 payments / 3 recovery cases / 3 retry chains."""
        payload = make_payment_failed_payload(
            payment_id="pay_Dup001", order_id="order_Dup001", amount=1000000
        )

        for _ in range(3):
            response = _post_webhook(client, payload, event_id="evt_SameEventId001")
            assert response.status_code == 200

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            payments = db.query(Payment).filter_by(razorpay_payment_id="pay_Dup001").all()
            assert len(payments) == 1

            cases = db.query(RecoveryCase).filter_by(payment_id=payments[0].id).all()
            assert len(cases) == 1

            actions = db.query(RecoveryAction).filter_by(recovery_case_id=cases[0].id).all()
            assert len(actions) == 1  # only the FIRST delivery should have scheduled anything

    def test_retry_capture_on_same_order_resolves_recovery_case(self, client, db_engine):
        failed_payload = make_payment_failed_payload(
            payment_id="pay_RetryFlow001", order_id="order_RetryFlow001", amount=2000000
        )
        _post_webhook(client, failed_payload, event_id="evt_RetryFlowFailed001")

        captured_payload = make_payment_captured_payload(
            payment_id="pay_RetryFlowSuccess001",
            order_id="order_RetryFlow001",  # SAME order as the failure
            amount=2000000,
        )
        response = _post_webhook(client, captured_payload, event_id="evt_RetryFlowCaptured001")
        assert response.status_code == 200

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            failed_payment = (
                db.query(Payment).filter_by(razorpay_payment_id="pay_RetryFlow001").one()
            )
            case = db.query(RecoveryCase).filter_by(payment_id=failed_payment.id).one()
            assert case.status == "RECOVERED"

            captured_payment = (
                db.query(Payment)
                .filter_by(razorpay_payment_id="pay_RetryFlowSuccess001")
                .one()
            )
            assert captured_payment.retried_from_payment_id == failed_payment.id

    def test_unrelated_captured_payment_does_not_affect_other_orders_case(
        self, client, db_engine
    ):
        failed_payload = make_payment_failed_payload(
            payment_id="pay_Isolated001", order_id="order_Isolated001", amount=3000000
        )
        _post_webhook(client, failed_payload, event_id="evt_IsolatedFailed001")

        unrelated_captured = make_payment_captured_payload(
            payment_id="pay_Unrelated999", order_id="order_DifferentOrder999", amount=100000
        )
        _post_webhook(client, unrelated_captured, event_id="evt_UnrelatedCaptured001")

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            payment = db.query(Payment).filter_by(razorpay_payment_id="pay_Isolated001").one()
            case = db.query(RecoveryCase).filter_by(payment_id=payment.id).one()
            assert case.status == "IN_PROGRESS"  # untouched by the unrelated capture
