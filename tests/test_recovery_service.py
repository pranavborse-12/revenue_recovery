"""Tests for app.services.recovery_service."""

from datetime import datetime, timezone

from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.services import recovery_service


def _make_failed_payment(db_session, **overrides) -> Payment:
    defaults = dict(
        razorpay_payment_id="pay_Test001",
        razorpay_order_id="order_Test001",
        amount=8500000,
        currency="INR",
        status="FAILED",
        failure_category="INSUFFICIENT_FUNDS",
        razorpay_created_at=datetime.now(timezone.utc),
    )
    defaults.update(overrides)
    payment = Payment(**defaults)
    db_session.add(payment)
    db_session.flush()
    return payment


class TestOnPaymentFailed:
    def test_creates_open_case_with_selected_strategy(self, db_session):
        payment = _make_failed_payment(db_session)

        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        assert decision.is_new_case is True
        assert decision.recovery_case.status == "IN_PROGRESS"  # opened then scheduled
        assert decision.recovery_case.current_strategy == "RETRY_PAYMENT"
        assert decision.recovery_case.attempt_count == 1

    def test_unknown_category_selects_manual_review(self, db_session):
        payment = _make_failed_payment(db_session, failure_category="UNKNOWN")

        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        assert decision.recovery_case.current_strategy == "MANUAL_REVIEW"
        # MANUAL_REVIEW is not auto-executed -> no Celery dispatch, but the
        # action row itself is still created for visibility.
        assert decision.recovery_action is not None
        assert decision.recovery_action.status == "PENDING"

    def test_second_call_for_same_payment_reuses_open_case(self, db_session, stub_celery_dispatch):
        payment = _make_failed_payment(db_session)

        first = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()
        second = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        assert second.is_new_case is False
        assert second.recovery_case.id == first.recovery_case.id
        count = db_session.query(RecoveryCase).filter_by(payment_id=payment.id).count()
        assert count == 1

    def test_retry_payment_strategy_enqueues_via_celery(self, db_session, stub_celery_dispatch):
        payment = _make_failed_payment(db_session)

        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        assert decision.recovery_action.id in stub_celery_dispatch.calls

    def test_manual_review_strategy_does_not_enqueue_via_celery(
        self, db_session, stub_celery_dispatch
    ):
        payment = _make_failed_payment(db_session, failure_category="UNKNOWN")

        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        assert decision.recovery_action.id not in stub_celery_dispatch.calls


class TestOnPaymentCapturedViaRetry:
    def test_recovers_open_case_and_cancels_pending_actions(self, db_session):
        payment = _make_failed_payment(db_session)
        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        case = recovery_service.on_payment_captured_via_retry(db_session, payment)
        db_session.commit()

        assert case is not None
        assert case.status == "RECOVERED"
        assert case.resolved_at is not None

        action = db_session.get(RecoveryAction, decision.recovery_action.id)
        assert action.status == "CANCELLED"

    def test_returns_none_when_no_open_case_exists(self, db_session):
        payment = _make_failed_payment(db_session, status="SUCCESS")
        result = recovery_service.on_payment_captured_via_retry(db_session, payment)
        assert result is None


class TestRecordActionResult:
    def test_success_marks_case_recovered(self, db_session, stub_celery_dispatch):
        payment = _make_failed_payment(db_session)
        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        case = recovery_service.record_action_result(
            db_session, decision.recovery_action, succeeded=True, detail="retry succeeded"
        )
        db_session.commit()

        assert case.status == "RECOVERED"
        assert decision.recovery_action.status == "SUCCESS"

    def test_awaiting_webhook_marks_action_success_without_recovering_case(
        self, db_session, stub_celery_dispatch
    ):
        payment = _make_failed_payment(db_session)
        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        case = recovery_service.record_action_result(
            db_session,
            decision.recovery_action,
            succeeded=True,
            detail="payment link created: https://rzp.io/i/example",
            awaiting_webhook=True,
        )
        db_session.commit()

        assert case.status == "IN_PROGRESS"
        assert decision.recovery_action.status == "SUCCESS"
        assert decision.recovery_action.executed_at is not None
        assert decision.recovery_action.result == "payment link created: https://rzp.io/i/example"

    def test_failure_with_attempts_remaining_schedules_next_action(
        self, db_session, stub_celery_dispatch
    ):
        payment = _make_failed_payment(db_session)
        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        case = recovery_service.record_action_result(
            db_session,
            decision.recovery_action,
            succeeded=False,
            detail="insufficient funds again",
        )
        db_session.commit()

        assert case.status == "IN_PROGRESS"
        assert case.attempt_count == 2
        actions = db_session.query(RecoveryAction).filter_by(recovery_case_id=case.id).all()
        assert len(actions) == 2
        assert actions[0].status == "FAILED"
        assert actions[1].status == "PENDING"

    def test_exhausts_case_after_max_attempts(self, db_session, stub_celery_dispatch):
        payment = _make_failed_payment(db_session)
        decision = recovery_service.on_payment_failed(db_session, payment)
        db_session.commit()

        # Default policy has 3 attempts (RETRY_DELAY_MINUTES=[30, 360, 1440]).
        # Fail attempt 1 (already scheduled by on_payment_failed), then
        # attempt 2, then attempt 3 -> should exhaust.
        current_action = decision.recovery_action
        case = None
        for _ in range(3):
            case = recovery_service.record_action_result(
                db_session, current_action, succeeded=False, detail="declined"
            )
            db_session.commit()
            if case.status == "EXHAUSTED":
                break
            pending = (
                db_session.query(RecoveryAction)
                .filter_by(recovery_case_id=case.id, status="PENDING")
                .order_by(RecoveryAction.attempt_number.desc())
                .first()
            )
            current_action = pending

        assert case.status == "AWAITING_CUSTOMER"
        assert case.resolved_at is None
        assert case.attempt_count == 3
