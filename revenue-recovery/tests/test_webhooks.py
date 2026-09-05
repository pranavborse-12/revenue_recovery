"""
Tests for POST /api/v1/webhooks/razorpay.

Covers every case the project brief calls out explicitly:
    - valid signature -> accepted
    - invalid signature -> rejected
    - unsupported event -> handled safely (acknowledged, not processed)
    - duplicate event -> not processed twice
    - malformed payload -> fails safely

None of these tests talk to the real Razorpay API or a real Razorpay
account -- signatures are generated locally with the same HMAC-SHA256
algorithm Razorpay documents (see tests/conftest.py::sign).
"""

from app.models.webhook_event import WebhookEvent
from tests.conftest import make_payment_captured_payload, make_payment_failed_payload, sign

WEBHOOK_URL = "/api/v1/webhooks/razorpay"


def _post_webhook(client, body_dict, event_id="evt_Test0000000001", signature=None):
    raw_body, valid_signature = sign(body_dict)
    return client.post(
        WEBHOOK_URL,
        content=raw_body,
        headers={
            "Content-Type": "application/json",
            "X-Razorpay-Signature": signature if signature is not None else valid_signature,
            "X-Razorpay-Event-Id": event_id,
        },
    )


class TestValidSignature:
    def test_valid_signature_payment_failed_is_processed(self, client, db_engine):
        payload = make_payment_failed_payload()

        response = _post_webhook(client, payload, event_id="evt_ValidFailed001")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "processed"
        assert body["event_type"] == "payment.failed"
        assert body["event_id"] == "evt_ValidFailed001"

    def test_valid_signature_payment_captured_is_processed(self, client):
        payload = make_payment_captured_payload()

        response = _post_webhook(client, payload, event_id="evt_ValidCaptured001")

        assert response.status_code == 200
        assert response.json()["status"] == "processed"

    def test_processed_event_is_persisted_with_expected_fields(self, client, db_engine):
        payload = make_payment_failed_payload(
            payment_id="pay_Persist001", order_id="order_Persist001", amount=8500000
        )

        response = _post_webhook(client, payload, event_id="evt_Persist001")
        assert response.status_code == 200

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            stored = db.query(WebhookEvent).filter_by(event_id="evt_Persist001").one()
            assert stored.provider == "razorpay"
            assert stored.event_type == "payment.failed"
            assert stored.status == "processed"
            assert stored.processed_at is not None
            assert stored.payload["payload"]["payment"]["entity"]["id"] == "pay_Persist001"
            assert stored.payload["payload"]["payment"]["entity"]["amount"] == 8500000


class TestInvalidSignature:
    def test_invalid_signature_is_rejected(self, client):
        payload = make_payment_failed_payload()

        response = _post_webhook(
            client, payload, event_id="evt_BadSig001", signature="0" * 64
        )

        assert response.status_code == 400
        assert "signature" in response.json()["detail"].lower()

    def test_missing_signature_header_is_rejected(self, client):
        payload = make_payment_failed_payload()
        raw_body, _ = sign(payload)

        response = client.post(
            WEBHOOK_URL,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Event-Id": "evt_NoSig001",
                # X-Razorpay-Signature intentionally omitted
            },
        )

        assert response.status_code == 400

    def test_rejected_signature_is_not_persisted(self, client, db_engine):
        payload = make_payment_failed_payload()
        _post_webhook(client, payload, event_id="evt_RejectedNotStored", signature="deadbeef")

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            stored = (
                db.query(WebhookEvent).filter_by(event_id="evt_RejectedNotStored").first()
            )
            assert stored is None


class TestUnsupportedEvent:
    def test_unsupported_event_type_is_acknowledged_not_processed(self, client):
        payload = make_payment_failed_payload()
        payload["event"] = "payment.authorized"  # not in SUPPORTED_EVENT_TYPES

        response = _post_webhook(client, payload, event_id="evt_Unsupported001")

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ignored_unsupported"
        assert body["event_type"] == "payment.authorized"

    def test_unsupported_event_is_still_stored_for_audit(self, client, db_engine):
        payload = make_payment_failed_payload()
        payload["event"] = "refund.created"

        _post_webhook(client, payload, event_id="evt_Unsupported002")

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            stored = db.query(WebhookEvent).filter_by(event_id="evt_Unsupported002").one()
            assert stored.status == "acknowledged"


class TestDuplicateEvent:
    def test_duplicate_event_id_is_not_processed_twice(self, client, db_engine):
        payload = make_payment_failed_payload()

        first = _post_webhook(client, payload, event_id="evt_Duplicate001")
        second = _post_webhook(client, payload, event_id="evt_Duplicate001")

        assert first.status_code == 200
        assert first.json()["status"] == "processed"

        assert second.status_code == 200
        assert second.json()["status"] == "ignored_duplicate"

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            count = (
                db.query(WebhookEvent).filter_by(event_id="evt_Duplicate001").count()
            )
            assert count == 1  # only one row, despite two deliveries

    def test_duplicate_detection_is_scoped_to_event_id_not_payload(self, client):
        """Two different event_ids for the same payment should both process --
        idempotency is keyed on event_id, not on payment content, since a
        single payment can legitimately produce multiple distinct events
        (e.g. failed then later captured on retry)."""
        payload = make_payment_failed_payload(payment_id="pay_SamePayment001")

        first = _post_webhook(client, payload, event_id="evt_First001")
        second = _post_webhook(client, payload, event_id="evt_Second001")

        assert first.json()["status"] == "processed"
        assert second.json()["status"] == "processed"


class TestMalformedPayload:
    def test_malformed_json_fails_safely(self, client):
        raw_body = b"{not valid json,,,"
        from tests.conftest import _manual_hmac_sha256, TEST_WEBHOOK_SECRET

        signature = _manual_hmac_sha256(raw_body, TEST_WEBHOOK_SECRET)

        response = client.post(
            WEBHOOK_URL,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": "evt_Malformed001",
            },
        )

        assert response.status_code == 400

    def test_valid_json_missing_required_fields_fails_safely(self, client):
        payload = {"entity": "event", "event": "payment.failed"}  # missing "payload", "created_at"
        response = _post_webhook(client, payload, event_id="evt_MissingFields001")

        assert response.status_code == 400

    def test_malformed_payload_is_not_persisted(self, client, db_engine):
        raw_body = b'{"entity": "event", "event": "payment.failed"}'
        from tests.conftest import _manual_hmac_sha256, TEST_WEBHOOK_SECRET

        signature = _manual_hmac_sha256(raw_body, TEST_WEBHOOK_SECRET)

        client.post(
            WEBHOOK_URL,
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": "evt_MalformedNotStored",
            },
        )

        from sqlalchemy.orm import sessionmaker

        Session = sessionmaker(bind=db_engine)
        with Session() as db:
            stored = (
                db.query(WebhookEvent).filter_by(event_id="evt_MalformedNotStored").first()
            )
            assert stored is None
