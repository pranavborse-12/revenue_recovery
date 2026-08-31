"""Offline coverage for Razorpay Standard Checkout integration."""

import hashlib
import hmac

from app.api.routes.payments import get_payment_gateway
from app.main import app
from app.models.payment import Payment
from app.services.payment_gateway import CheckoutOrderResult
from tests.conftest import make_payment_captured_payload, make_payment_failed_payload, sign


class FakeCheckoutGateway:
    def __init__(self, *, failure: bool = False):
        self.failure = failure
        self.calls: list[dict] = []

    def create_checkout_order(self, *, amount: int, currency: str, receipt: str) -> CheckoutOrderResult:
        self.calls.append({"amount": amount, "currency": currency, "receipt": receipt})
        if self.failure:
            return CheckoutOrderResult(status="failed", detail="simulated Razorpay failure")
        return CheckoutOrderResult(
            status="created",
            detail="created",
            razorpay_order_id=f"order_Checkout{len(self.calls):03d}",
            amount=amount,
            currency=currency,
        )


def _install_gateway(gateway: FakeCheckoutGateway) -> None:
    app.dependency_overrides[get_payment_gateway] = lambda: gateway


def _checkout_signature(order_id: str, payment_id: str, secret: str = "checkout_test_secret") -> str:
    return hmac.new(
        secret.encode("utf-8"), f"{order_id}|{payment_id}".encode("utf-8"), hashlib.sha256
    ).hexdigest()


def _create_order(client, gateway: FakeCheckoutGateway, amount: str = "100.25") -> dict:
    _install_gateway(gateway)
    response = client.post("/api/v1/payments/checkout/orders", json={"amount_rupees": amount})
    assert response.status_code == 201
    return response.json()


class TestCheckoutOrderCreation:
    def test_creates_inr_order_in_paise_and_persists_pending_payment(self, client, db_engine):
        gateway = FakeCheckoutGateway()
        order = _create_order(client, gateway)

        assert order["order_id"] == "order_Checkout001"
        assert order["amount"] == 10025
        assert order["currency"] == "INR"
        assert order["key_id"].startswith("rzp_test_")
        assert gateway.calls[0]["amount"] == 10025
        assert gateway.calls[0]["currency"] == "INR"
        assert gateway.calls[0]["receipt"].startswith("checkout_")

        from sqlalchemy.orm import sessionmaker

        with sessionmaker(bind=db_engine)() as db:
            payment = db.query(Payment).one()
            assert payment.razorpay_order_id == order["order_id"]
            assert payment.razorpay_payment_id.startswith("checkout_")
            assert payment.status == "PENDING"

    def test_rejects_invalid_amount(self, client):
        response = client.post("/api/v1/payments/checkout/orders", json={"amount_rupees": "0"})
        assert response.status_code == 422

    def test_reports_razorpay_order_creation_failure(self, client):
        _install_gateway(FakeCheckoutGateway(failure=True))
        response = client.post("/api/v1/payments/checkout/orders", json={"amount_rupees": "10"})
        assert response.status_code == 502
        assert response.json()["detail"] == "Unable to create Razorpay order"


class TestCheckoutVerification:
    def test_valid_signature_records_payment_id_but_waits_for_webhook(self, client, db_engine, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "checkout_test_secret")
        gateway = FakeCheckoutGateway()
        order = _create_order(client, gateway)
        payment_id = "pay_CheckoutVerified001"

        response = client.post(
            "/api/v1/payments/checkout/verify",
            json={
                "razorpay_order_id": order["order_id"],
                "razorpay_payment_id": payment_id,
                "razorpay_signature": _checkout_signature(order["order_id"], payment_id),
            },
        )

        assert response.status_code == 200
        assert response.json()["status"] == "verified_pending_webhook"
        from sqlalchemy.orm import sessionmaker

        with sessionmaker(bind=db_engine)() as db:
            payment = db.query(Payment).one()
            assert payment.razorpay_payment_id == payment_id
            assert payment.status == "PENDING"

    def test_rejects_invalid_or_missing_signature_fields(self, client, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "checkout_test_secret")
        order = _create_order(client, FakeCheckoutGateway())
        invalid = client.post(
            "/api/v1/payments/checkout/verify",
            json={
                "razorpay_order_id": order["order_id"],
                "razorpay_payment_id": "pay_BadSignature001",
                "razorpay_signature": "not-valid",
            },
        )
        assert invalid.status_code == 400

        missing = client.post(
            "/api/v1/payments/checkout/verify",
            json={"razorpay_order_id": order["order_id"], "razorpay_payment_id": "pay_Missing001"},
        )
        assert missing.status_code == 422

    def test_rejects_signature_for_a_different_order(self, client, monkeypatch):
        monkeypatch.setenv("RAZORPAY_KEY_SECRET", "checkout_test_secret")
        order = _create_order(client, FakeCheckoutGateway())
        response = client.post(
            "/api/v1/payments/checkout/verify",
            json={
                "razorpay_order_id": order["order_id"],
                "razorpay_payment_id": "pay_Mismatched001",
                "razorpay_signature": _checkout_signature("order_Different", "pay_Mismatched001"),
            },
        )
        assert response.status_code == 400


class TestCheckoutWebhooks:
    def test_captured_webhook_updates_the_pending_checkout_payment(self, client, db_engine, monkeypatch):
        order = _create_order(client, FakeCheckoutGateway(), amount="50.00")
        # Captures without a recovery case enqueue a correlation task; keep this test offline.
        from app.tasks.customer_recovery_tasks import resolve_unmatched_capture

        monkeypatch.setattr(resolve_unmatched_capture, "apply_async", lambda **kwargs: None)
        event = make_payment_captured_payload(
            payment_id="pay_CheckoutCaptured001", order_id=order["order_id"], amount=5000
        )
        raw_body, signature = sign(event)
        response = client.post(
            "/api/v1/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": "evt_CheckoutCaptured001",
            },
        )
        assert response.status_code == 200

        from sqlalchemy.orm import sessionmaker

        with sessionmaker(bind=db_engine)() as db:
            payment = db.query(Payment).one()
            assert payment.razorpay_payment_id == "pay_CheckoutCaptured001"
            assert payment.status == "SUCCESS"

    def test_failed_webhook_creates_the_existing_recovery_workflow(self, client, db_engine):
        order = _create_order(client, FakeCheckoutGateway(), amount="50.00")
        event = make_payment_failed_payload(
            payment_id="pay_CheckoutFailed001", order_id=order["order_id"], amount=5000
        )
        raw_body, signature = sign(event)
        response = client.post(
            "/api/v1/webhooks/razorpay",
            content=raw_body,
            headers={
                "Content-Type": "application/json",
                "X-Razorpay-Signature": signature,
                "X-Razorpay-Event-Id": "evt_CheckoutFailed001",
            },
        )
        assert response.status_code == 200

        from app.models.recovery_case import RecoveryCase
        from sqlalchemy.orm import sessionmaker

        with sessionmaker(bind=db_engine)() as db:
            payment = db.query(Payment).one()
            assert payment.status == "FAILED"
            case = db.query(RecoveryCase).one()
            assert case.payment_id == payment.id
