"""Tests for app.services.payment_service."""

from app.models.payment import Payment
from app.schemas.webhook import RazorpayPaymentEntity
from app.services.payment_service import upsert_payment_from_event


def _entity(**overrides) -> RazorpayPaymentEntity:
    defaults = dict(
        id="pay_Test001",
        order_id="order_Test001",
        amount=8500000,
        currency="INR",
        status="failed",
        method="card",
        email="test@example.com",
        contact="+911234567890",
        error_code="BAD_REQUEST_ERROR",
        error_description="Payment failed due to insufficient funds.",
        created_at=1735689600,
    )
    defaults.update(overrides)
    return RazorpayPaymentEntity(**defaults)


class TestUpsertPaymentFromEvent:
    def test_new_failed_payment_creates_payment_row(self, db_session):
        result = upsert_payment_from_event(db_session, "payment.failed", _entity())
        db_session.commit()

        assert result.is_new is True
        assert result.newly_failed is True
        assert result.payment.status == "FAILED"
        assert result.payment.failure_category == "INSUFFICIENT_FUNDS"
        assert result.payment.razorpay_payment_id == "pay_Test001"

    def test_reprocessing_same_payment_id_updates_not_duplicates(self, db_session):
        upsert_payment_from_event(db_session, "payment.failed", _entity())
        db_session.commit()

        result = upsert_payment_from_event(db_session, "payment.failed", _entity())
        db_session.commit()

        assert result.is_new is False
        count = db_session.query(Payment).filter_by(razorpay_payment_id="pay_Test001").count()
        assert count == 1

    def test_second_failed_event_for_same_payment_is_not_newly_failed(self, db_session):
        upsert_payment_from_event(db_session, "payment.failed", _entity())
        db_session.commit()

        result = upsert_payment_from_event(db_session, "payment.failed", _entity())
        db_session.commit()

        # already FAILED -> transitioning FAILED again isn't a NEW failure
        assert result.newly_failed is False

    def test_captured_payment_moves_to_success(self, db_session):
        entity = _entity(
            id="pay_Captured001", status="captured", error_code=None, error_description=None
        )
        result = upsert_payment_from_event(db_session, "payment.captured", entity)
        db_session.commit()

        assert result.payment.status == "SUCCESS"

    def test_captured_after_failed_on_same_order_is_linked_as_retry(self, db_session):
        failed_entity = _entity(id="pay_Failed001", order_id="order_Shared001")
        failed_result = upsert_payment_from_event(db_session, "payment.failed", failed_entity)
        db_session.commit()

        captured_entity = _entity(
            id="pay_Retry001",
            order_id="order_Shared001",
            status="captured",
            error_code=None,
            error_description=None,
        )
        captured_result = upsert_payment_from_event(
            db_session, "payment.captured", captured_entity
        )
        db_session.commit()

        assert captured_result.linked_retry_of is not None
        assert captured_result.linked_retry_of.id == failed_result.payment.id
        assert captured_result.payment.retried_from_payment_id == failed_result.payment.id

    def test_captured_on_different_order_is_not_linked(self, db_session):
        failed_entity = _entity(id="pay_Failed002", order_id="order_A")
        upsert_payment_from_event(db_session, "payment.failed", failed_entity)
        db_session.commit()

        captured_entity = _entity(
            id="pay_Unrelated001",
            order_id="order_B",
            status="captured",
            error_code=None,
            error_description=None,
        )
        result = upsert_payment_from_event(db_session, "payment.captured", captured_entity)
        db_session.commit()

        assert result.linked_retry_of is None

    def test_captured_with_no_prior_failure_is_not_linked(self, db_session):
        entity = _entity(
            id="pay_FirstTry001",
            order_id="order_Fresh001",
            status="captured",
            error_code=None,
            error_description=None,
        )
        result = upsert_payment_from_event(db_session, "payment.captured", entity)
        db_session.commit()

        assert result.linked_retry_of is None
