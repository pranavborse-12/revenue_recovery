"""
RecoveryService: decides what happens after a payment failure, and owns
the RecoveryCase / RecoveryAction lifecycle.

    Payment Failure
          |
    Failure Classification (failure_classifier.py)
          |
    Recovery Strategy (this module: STRATEGY_BY_CATEGORY)
          |
    RecoveryCase created/updated + RecoveryAction scheduled

Phase 3 change (the only behavioral change in this file): both places
that used to send an exhausted case straight to EXHAUSTED now go through
_route_exhausted_case(), which sends RETRY_PAYMENT-strategy cases to
AWAITING_CUSTOMER and kicks off customer-assisted recovery instead. Every
other strategy (MANUAL_REVIEW, REQUEST_PAYMENT_METHOD_UPDATE) still goes
straight to EXHAUSTED, unchanged from Phase 2 -- those were never
auto-executed, so there is no "automatic recovery exhausted" event for
them to react to.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.retry_policy import get_retry_policy
from app.models.payment import Payment
from app.models.payment_link import ACTIVE_PAYMENT_LINK_STATUSES, PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import TERMINAL_RECOVERY_CASE_STATUSES, RecoveryCase

logger = get_logger(__name__)

STRATEGY_BY_CATEGORY: dict[str, str] = {
    "INSUFFICIENT_FUNDS": "RETRY_PAYMENT",
    "TEMPORARY_NETWORK_ERROR": "RETRY_PAYMENT",
    "BANK_DECLINED": "RETRY_PAYMENT",
    "PAYMENT_METHOD_EXPIRED": "REQUEST_PAYMENT_METHOD_UPDATE",
    "PAYMENT_METHOD_INVALID": "REQUEST_PAYMENT_METHOD_UPDATE",
    "UNKNOWN": "MANUAL_REVIEW",
}

AUTOMATICALLY_EXECUTED_ACTION_TYPES = {"RETRY_PAYMENT"}

# Strategies whose exhaustion should route to customer-assisted recovery
# (Phase 3) rather than straight to EXHAUSTED.
STRATEGIES_ELIGIBLE_FOR_CUSTOMER_RECOVERY = {"RETRY_PAYMENT"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RecoveryDecision:
    recovery_case: RecoveryCase
    recovery_action: RecoveryAction | None
    is_new_case: bool


def on_payment_failed(db: Session, payment: Payment) -> RecoveryDecision:
    """Unchanged from Phase 2."""
    existing_case = db.scalars(
        select(RecoveryCase).where(
            RecoveryCase.payment_id == payment.id,
            RecoveryCase.status.not_in(TERMINAL_RECOVERY_CASE_STATUSES),
        )
    ).first()

    if existing_case is not None:
        logger.info(
            "Reusing existing open recovery_case_id=%s for payment_id=%s "
            "(status=%s) -- not creating a duplicate",
            existing_case.id, payment.id, existing_case.status,
        )
        return RecoveryDecision(recovery_case=existing_case, recovery_action=None, is_new_case=False)

    category = payment.failure_category or "UNKNOWN"
    strategy = STRATEGY_BY_CATEGORY.get(category, "MANUAL_REVIEW")

    case = RecoveryCase(
        payment_id=payment.id,
        failure_category=category,
        amount=payment.amount,
        status="OPEN",
        current_strategy=strategy,
    )
    db.add(case)
    db.flush()

    logger.info(
        "Opened recovery_case_id=%s for payment_id=%s category=%s strategy=%s",
        case.id, payment.id, category, strategy,
    )

    action = _schedule_next_action(db, case, strategy)
    return RecoveryDecision(recovery_case=case, recovery_action=action, is_new_case=True)


def on_payment_captured_via_retry(db: Session, resolved_payment: Payment) -> RecoveryCase | None:
    """
    Unchanged core logic from Phase 2, with one Phase 3 addition: if the
    resolved case has an active customer-recovery PaymentLink, mark it
    PAID -- purely for accurate record-keeping, does not affect the
    RECOVERED decision itself (which is unchanged and already correct
    without this).
    """
    case = db.scalars(
        select(RecoveryCase).where(
            RecoveryCase.payment_id == resolved_payment.id,
            RecoveryCase.status.not_in(TERMINAL_RECOVERY_CASE_STATUSES),
        )
    ).first()
    if case is None:
        return None

    for action in db.scalars(
        select(RecoveryAction).where(
            RecoveryAction.recovery_case_id == case.id,
            RecoveryAction.status.in_(("PENDING", "PROCESSING")),
        )
    ):
        action.transition_to("CANCELLED")

    if case.status == "OPEN":
        case.transition_to("IN_PROGRESS")
    case.transition_to("RECOVERED")

    active_link = db.scalars(
        select(PaymentLink).where(
            PaymentLink.recovery_case_id == case.id,
            PaymentLink.status.in_(ACTIVE_PAYMENT_LINK_STATUSES),
        )
    ).first()
    if active_link is not None:
        active_link.transition_to("PAID")

    logger.info(
        "recovery_case_id=%s RECOVERED via retry resolving prior payment_id=%s",
        case.id, resolved_payment.id,
    )
    return case


def record_action_result(
    db: Session,
    action: RecoveryAction,
    *,
    succeeded: bool,
    detail: str,
    awaiting_webhook: bool = False,
) -> RecoveryCase:
    """Persist an action outcome while preserving the Phase 2 webhook-driven success path.

    When a RETRY_PAYMENT creates a Razorpay payment link but has not yet received a
    payment.captured/payment.failed webhook, the action itself is considered executed
    and should be marked as SUCCESS so it is not left stuck in PROCESSING. The case
    remains IN_PROGRESS until the webhook resolves it; this is not a recovery success yet.
    """
    if action.status == "PENDING":
        action.transition_to("PROCESSING")
    action.transition_to("SUCCESS" if succeeded else "FAILED")
    action.executed_at = _utcnow()
    action.result = detail

    case = db.get(RecoveryCase, action.recovery_case_id)
    assert case is not None

    policy = get_retry_policy()

    if awaiting_webhook:
        logger.info(
            "recovery_case_id=%s action_id=%s reached awaiting_webhook after execute; "
            "checking exhaustion policy before leaving case in %s",
            case.id, action.id, case.status,
        )
        if policy.is_exhausted(case.attempt_count):
            _route_exhausted_case(db, case)
        return case

    if succeeded:
        case.transition_to("RECOVERED")
        logger.info("recovery_case_id=%s RECOVERED (action_id=%s succeeded)", case.id, action.id)
        return case

    if policy.is_exhausted(case.attempt_count):
        _route_exhausted_case(db, case)
        return case

    logger.info(
        "recovery_case_id=%s action_id=%s failed (%s); scheduling next attempt",
        case.id, action.id, detail,
    )
    _schedule_next_action(db, case, case.current_strategy or "MANUAL_REVIEW")
    return case


def _route_exhausted_case(db: Session, case: RecoveryCase) -> None:
    """
    Phase 3: a case whose automatic recovery is exhausted goes to
    AWAITING_CUSTOMER (and customer-assisted recovery is enqueued) if its
    strategy is one Phase 3 handles; otherwise it goes straight to
    EXHAUSTED, exactly as in Phase 2.
    """
    if case.current_strategy in STRATEGIES_ELIGIBLE_FOR_CUSTOMER_RECOVERY:
        case.transition_to("AWAITING_CUSTOMER")
        logger.info(
            "recovery_case_id=%s AWAITING_CUSTOMER (automatic recovery exhausted, "
            "strategy=%s) -- starting customer-assisted recovery",
            case.id, case.current_strategy,
        )
        _enqueue_customer_recovery(case)
    else:
        case.transition_to("EXHAUSTED")
        logger.info(
            "recovery_case_id=%s EXHAUSTED after %d attempts (strategy=%s not "
            "eligible for customer-assisted recovery)",
            case.id, case.attempt_count, case.current_strategy,
        )


def _schedule_next_action(db: Session, case: RecoveryCase, strategy: str) -> RecoveryAction | None:
    """Unchanged from Phase 2, except its own exhaustion branch also calls _route_exhausted_case."""
    policy = get_retry_policy()
    next_attempt_number = case.attempt_count + 1

    if policy.is_exhausted(case.attempt_count):
        _route_exhausted_case(db, case)
        return None

    scheduled_at = policy.scheduled_at_for_attempt(next_attempt_number)

    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=strategy,
        status="PENDING",
        attempt_number=next_attempt_number,
        scheduled_at=scheduled_at,
    )
    db.add(action)
    case.attempt_count = next_attempt_number
    if case.status == "OPEN":
        case.transition_to("IN_PROGRESS")
    db.flush()

    if strategy in AUTOMATICALLY_EXECUTED_ACTION_TYPES:
        _enqueue_action(action)
    else:
        logger.info(
            "recovery_action_id=%s type=%s created but not auto-executed "
            "(requires manual/notification handling, out of Phase 2 scope)",
            action.id, strategy,
        )

    return action


def _enqueue_action(action: RecoveryAction, *, immediate: bool = False) -> None:
    """Unchanged from Phase 2."""
    from app.tasks.recovery_tasks import execute_recovery_action

    if immediate:
        execute_recovery_action.apply_async(args=[action.id], countdown=0)
    else:
        execute_recovery_action.apply_async(args=[action.id], eta=action.scheduled_at)


def _enqueue_customer_recovery(case: RecoveryCase, *, immediate: bool = True) -> None:
    """
    Phase 3: hand a newly-AWAITING_CUSTOMER case off to Celery. Imported
    locally for the same reason _enqueue_action is -- keeps this module
    importable/testable without a Celery broker.
    """
    from app.tasks.customer_recovery_tasks import run_customer_recovery

    if immediate:
        run_customer_recovery.apply_async(args=[case.id], countdown=0)
    else:
        run_customer_recovery.apply_async(args=[case.id])


# --- Payment-Link correlation (fallback for the same-order match) ---

# Upper bound on how many active PaymentLinks a single unmatched capture
# will check against Razorpay. Bounds the fallback's cost regardless of
# how many recovery cases are simultaneously AWAITING_CUSTOMER -- it is
# not a limit on correctness (a genuine match is still found as long as
# it's among the oldest N), just a deliberate ceiling on API calls per
# event. 25 comfortably covers realistic concurrent-recovery volume for
# this project; raise it only if that assumption stops holding.
MAX_PAYMENT_LINK_CANDIDATES = 25


@dataclass(frozen=True)
class PaymentLinkResolution:
    status: str  # "matched" | "not_matched" | "retry"
    resolved_payment: Payment | None = None


def resolve_via_payment_link(db: Session, captured_payment: Payment, gateway) -> PaymentLinkResolution:
    """
    Fallback correlation for a captured payment that _find_prior_failed_
    payment_on_order() (payment_service.py, unchanged) already found no
    same-order match for. Only called from that "no match" branch -- see
    webhook_service._run_payment_recovery_pipeline -- never in place of
    the same-order check, which stays first and unmodified.

    Bounded scan of our OWN active PaymentLink rows (never a blind
    Razorpay-side search), checking each against Razorpay's
    payments[] via gateway.check_payment_link_paid() -- the one
    confirmed Razorpay-maintained pointer from a Payment Link to the
    payment that resolved it (see payment_gateway.py; order_id and
    invoice_id on the payment entity were both confirmed unusable for
    this during live debugging).

    Never matches on amount/email/phone/description -- an unrelated
    captured payment must never attach to someone else's recovery case.
    If any candidate's Razorpay call errors, that is NOT treated as a
    non-match: we don't yet know, so the caller should retry rather than
    give up. Only a positive response from Razorpay for every checked
    candidate counts as "not_matched".
    """
    candidates = list(
        db.scalars(
            select(PaymentLink)
            .where(PaymentLink.status.in_(ACTIVE_PAYMENT_LINK_STATUSES))
            .order_by(PaymentLink.created_at)
            .limit(MAX_PAYMENT_LINK_CANDIDATES)
        )
    )

    if not candidates:
        return PaymentLinkResolution(status="not_matched")

    had_error = False
    for link in candidates:
        result = gateway.check_payment_link_paid(
            razorpay_payment_link_id=link.razorpay_payment_link_id,
            razorpay_payment_id=captured_payment.razorpay_payment_id,
        )
        if result.status == "error":
            had_error = True
            logger.warning(
                "resolve_via_payment_link: Razorpay check failed for payment_link_id=%s "
                "while resolving payment_id=%s -- will retry rather than treat as unmatched",
                link.id, captured_payment.id,
            )
            continue
        if result.status == "matched":
            case = db.get(RecoveryCase, link.recovery_case_id)
            original_payment = db.get(Payment, case.payment_id)
            logger.info(
                "resolve_via_payment_link: payment_id=%s matched payment_link_id=%s "
                "(recovery_case_id=%s) -- resolves original payment_id=%s",
                captured_payment.id, link.id, case.id, original_payment.id,
            )
            captured_payment.retried_from_payment_id = original_payment.id
            return PaymentLinkResolution(status="matched", resolved_payment=original_payment)

    if had_error:
        return PaymentLinkResolution(status="retry")

    logger.info(
        "resolve_via_payment_link: payment_id=%s matched none of %d active payment link(s) "
        "-- leaving unresolved (not guessing)",
        captured_payment.id, len(candidates),
    )
    return PaymentLinkResolution(status="not_matched")