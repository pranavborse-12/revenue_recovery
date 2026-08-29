"""
Recovery API.

    GET  /api/v1/recovery/cases
    GET  /api/v1/recovery/cases/{id}
    GET  /api/v1/recovery/stats
    POST /api/v1/recovery/cases/{id}/retry

Read-focused, exposing business state (cases, actions, aggregate stats),
not raw database rows. POST /retry is the one write endpoint -- a manual
override to trigger the next retry immediately instead of waiting for
its scheduled time, useful for demoing/testing the flow without waiting
out the real delay.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.db.session import get_db
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.schemas.recovery import (
    RecoveryCaseDetailOut,
    RecoveryCaseOut,
    RecoveryStatsOut,
    RetryNowResponse,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/recovery", tags=["recovery"])


@router.get("/cases", response_model=list[RecoveryCaseOut])
def list_recovery_cases(
    status_filter: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
) -> list[RecoveryCase]:
    stmt = select(RecoveryCase).order_by(RecoveryCase.created_at.desc()).limit(min(limit, 200))
    if status_filter:
        stmt = stmt.where(RecoveryCase.status == status_filter.upper())
    return list(db.scalars(stmt))


@router.get("/cases/{case_id}", response_model=RecoveryCaseDetailOut)
def get_recovery_case(case_id: int, db: Session = Depends(get_db)) -> RecoveryCaseDetailOut:
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")

    payment = db.get(Payment, case.payment_id)
    actions = list(
        db.scalars(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == case.id)
            .order_by(RecoveryAction.attempt_number)
        )
    )

    return RecoveryCaseDetailOut(
        id=case.id,
        payment_id=case.payment_id,
        failure_category=case.failure_category,
        amount=case.amount,
        status=case.status,
        current_strategy=case.current_strategy,
        attempt_count=case.attempt_count,
        created_at=case.created_at,
        updated_at=case.updated_at,
        resolved_at=case.resolved_at,
        actions=actions,
        razorpay_payment_id=payment.razorpay_payment_id if payment else "",
        razorpay_order_id=payment.razorpay_order_id if payment else None,
        currency=payment.currency if payment else "",
    )


@router.get("/stats", response_model=RecoveryStatsOut)
def get_recovery_stats(db: Session = Depends(get_db)) -> RecoveryStatsOut:
    total_failed_payments = db.scalar(
        select(func.count(Payment.id)).where(Payment.status.in_(("FAILED", "RETRYING")))
    ) or 0

    total_revenue_at_risk = db.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
            RecoveryCase.status.in_(("OPEN", "IN_PROGRESS"))
        )
    ) or 0

    total_recovered_revenue = db.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
            RecoveryCase.status == "RECOVERED"
        )
    ) or 0

    active_recovery_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(
            RecoveryCase.status.in_(("OPEN", "IN_PROGRESS"))
        )
    ) or 0

    recovered_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(RecoveryCase.status == "RECOVERED")
    ) or 0

    exhausted_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(RecoveryCase.status == "EXHAUSTED")
    ) or 0

    resolved = recovered_cases + exhausted_cases
    recovery_rate = (recovered_cases / resolved) if resolved > 0 else 0.0

    return RecoveryStatsOut(
        total_failed_payments=total_failed_payments,
        total_revenue_at_risk=total_revenue_at_risk,
        total_recovered_revenue=total_recovered_revenue,
        active_recovery_cases=active_recovery_cases,
        recovered_cases=recovered_cases,
        exhausted_cases=exhausted_cases,
        recovery_rate=round(recovery_rate, 4),
    )


@router.post("/cases/{case_id}/retry", response_model=RetryNowResponse)
def retry_recovery_case_now(case_id: int, db: Session = Depends(get_db)) -> RetryNowResponse:
    """
    Manually trigger the next pending action for a case immediately,
    instead of waiting for its scheduled ETA. Only valid for cases that
    are OPEN or IN_PROGRESS with a PENDING action -- anything else is
    rejected rather than silently ignored.
    """
    case = db.get(RecoveryCase, case_id)
    if case is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")

    if case.status not in ("OPEN", "IN_PROGRESS"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot retry a case in status {case.status}",
        )

    pending_action = db.scalars(
        select(RecoveryAction)
        .where(RecoveryAction.recovery_case_id == case.id, RecoveryAction.status == "PENDING")
        .order_by(RecoveryAction.attempt_number.desc())
    ).first()

    if pending_action is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No pending action to retry for this case",
        )

    from app.services.recovery_service import AUTOMATICALLY_EXECUTED_ACTION_TYPES

    if pending_action.action_type not in AUTOMATICALLY_EXECUTED_ACTION_TYPES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"Action type {pending_action.action_type} is not automatically "
                "executable in this phase (requires manual/notification handling) "
                "and cannot be triggered via this endpoint"
            ),
        )

    from app.services.recovery_service import _enqueue_action

    _enqueue_action(pending_action, immediate=True)

    logger.info(
        "Manually triggered immediate execution of recovery_action_id=%s "
        "(recovery_case_id=%s)",
        pending_action.id,
        case.id,
    )

    return RetryNowResponse(
        recovery_case_id=case.id,
        status="triggered",
        detail=f"Action {pending_action.id} enqueued for immediate execution",
    )