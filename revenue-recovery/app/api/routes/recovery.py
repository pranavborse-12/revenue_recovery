"""
Recovery API.

    GET  /api/v1/recovery/cases
    GET  /api/v1/recovery/cases/{id}
    GET  /api/v1/recovery/stats
    POST /api/v1/recovery/cases/{id}/retry
    POST /api/v1/recovery/cases/{id}/recover-now   (Phase 3)

Phase 3 changes:
  - get_recovery_case now also returns the case's payment link (if any)
    and communication history.
  - get_recovery_stats now also reports awaiting_customer_cases, and
    "active"/"at risk" figures include AWAITING_CUSTOMER (via
    ACTIVE_RECOVERY_CASE_STATUSES) since that revenue is still at risk,
    just via a different recovery path.
  - New POST /cases/{id}/recover-now: manual override to (re)run
    customer-assisted recovery immediately for an AWAITING_CUSTOMER
    case, mirroring the existing /retry endpoint's purpose (bypass the
    normal trigger for demoing/testing/ops). No separate customer-facing
    endpoint is added -- Razorpay's own payment_link.short_url IS the
    secure public surface the customer uses; we don't need to build or
    expose one of our own.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.auth import get_current_organization_id, get_current_user
from app.db.session import get_db
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.payment import Payment
from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import ACTIVE_RECOVERY_CASE_STATUSES, RecoveryCase
from app.models.recovery_communication import RecoveryCommunication
from app.schemas.recovery import (
    AIInsightOut,
    CustomerRecoveryTriggerResponse,
    CustomerSummaryOut,
    BatchResultOut,
    HistoricalEvidenceOut,
    PaymentSummaryOut,
    RecoveryCaseDetailOut,
    RecoveryCaseOut,
    RecoveryDecisionOut,
    RecoveryStatsOut,
    RetryNowResponse,
)
from app.services import historical_intelligence

logger = get_logger(__name__)

router = APIRouter(prefix="/recovery", tags=["recovery"], dependencies=[Depends(get_current_user)])


@router.get("/cases", response_model=list[RecoveryCaseOut])
def list_recovery_cases(
    status_filter: str | None = None,
    limit: int = 50,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_organization_id),
) -> list[RecoveryCase]:
    stmt = (
        select(RecoveryCase)
        .where(RecoveryCase.organization_id == org_id)
        .order_by(RecoveryCase.created_at.desc())
        .limit(min(limit, 200))
    )
    if status_filter:
        stmt = stmt.where(RecoveryCase.status == status_filter.upper())

    cases = list(db.scalars(stmt))
    result: list[RecoveryCaseOut] = []
    for case in cases:
        payment = db.get(Payment, case.payment_id)
        decision = db.scalar(
            select(AIRecoveryDecision)
            .where(AIRecoveryDecision.recovery_case_id == case.id, AIRecoveryDecision.agent_role == "final")
            .order_by(AIRecoveryDecision.created_at.desc())
        )
        result.append(
            RecoveryCaseOut(
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
                customer_email=payment.customer_email if payment else None,
                customer_name=None,
                recovery_probability=float(decision.confidence) if decision else None,
                ai_recommendation=decision.recommended_action if decision else None,
                ai_confidence=float(decision.confidence) if decision else None,
            )
        )
    return result


@router.get("/cases/{case_id}", response_model=RecoveryCaseDetailOut)
def get_recovery_case(
    case_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_organization_id),
) -> RecoveryCaseDetailOut:
    case = db.get(RecoveryCase, case_id)
    if case is None or case.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")

    payment = db.get(Payment, case.payment_id)
    actions = list(
        db.scalars(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == case.id)
            .order_by(RecoveryAction.attempt_number)
        )
    )
    payment_link = db.scalars(
        select(PaymentLink)
        .where(PaymentLink.recovery_case_id == case.id)
        .order_by(PaymentLink.created_at.desc())
    ).first()
    communications = list(
        db.scalars(
            select(RecoveryCommunication)
            .where(RecoveryCommunication.recovery_case_id == case.id)
            .order_by(RecoveryCommunication.created_at)
        )
    )
    latest_decision = db.scalar(
        select(AIRecoveryDecision)
        .where(AIRecoveryDecision.recovery_case_id == case.id, AIRecoveryDecision.agent_role == "final")
        .order_by(AIRecoveryDecision.created_at.desc())
    )
    evidence = historical_intelligence.get_recovery_evidence(db, case.failure_category)
    evidence_breakdown = {
        action: {
            "attempts": data.attempts,
            "recovered": data.recovered,
            "recovery_rate": data.recovery_rate,
            "sample_size": data.sample_size,
        }
        for action, data in evidence.items()
    }
    similar_cases = sum(item["attempts"] for item in evidence_breakdown.values())
    successful_recoveries = sum(item["recovered"] for item in evidence_breakdown.values())
    best_strategy = None
    best_strategy_rate = None
    if evidence:
        best_strategy, best_strategy_data = max(
            evidence.items(), key=lambda item: item[1].recovery_rate if item[1].sample_size else 0
        )
        best_strategy_rate = best_strategy_data.recovery_rate
    customer = CustomerSummaryOut(
        name=None,
        email=payment.customer_email if payment else None,
        phone=payment.customer_contact if payment else None,
        customer_id=None,
        previous_recovery_history=None,
    )
    decision = RecoveryDecisionOut(
        recommended_action=latest_decision.recommended_action if latest_decision else None,
        current_strategy=case.current_strategy,
        attempt_number=case.attempt_count,
        accepted=latest_decision.accepted if latest_decision else None,
        executed=latest_decision.executed if latest_decision else None,
        actual_action_executed=(latest_decision.outcome if latest_decision and latest_decision.outcome else None),
        status=case.status,
        confidence=float(latest_decision.confidence) if latest_decision else None,
    )
    ai_insight = AIInsightOut(
        model=latest_decision.model if latest_decision else None,
        recommended_action=latest_decision.recommended_action if latest_decision else None,
        recommendation=latest_decision.recommended_action if latest_decision else None,
        confidence=float(latest_decision.confidence) if latest_decision else None,
        reason=latest_decision.reason if latest_decision else None,
        supporting_evidence=latest_decision.reason if latest_decision else None,
        decision_timestamp=latest_decision.created_at if latest_decision else None,
    )
    historical_evidence = HistoricalEvidenceOut(
        similar_cases=similar_cases or None,
        successful_recoveries=successful_recoveries or None,
        historical_recovery_rate=(successful_recoveries / similar_cases) if similar_cases else None,
        best_strategy=best_strategy,
        best_strategy_recovery_rate=best_strategy_rate,
        action_breakdown=evidence_breakdown,
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
        customer_email=payment.customer_email if payment else None,
        customer_name=None,
        recovery_probability=float(latest_decision.confidence) if latest_decision else None,
        ai_recommendation=latest_decision.recommended_action if latest_decision else None,
        ai_confidence=float(latest_decision.confidence) if latest_decision else None,
        actions=actions,
        razorpay_payment_id=payment.razorpay_payment_id if payment else "",
        razorpay_order_id=payment.razorpay_order_id if payment else None,
        currency=payment.currency if payment else "",
        payment_link=payment_link,
        communications=communications,
        customer=customer,
        payment=PaymentSummaryOut(
            payment_id=payment.razorpay_payment_id if payment else "",
            order_id=payment.razorpay_order_id if payment else None,
            amount=case.amount,
            currency=payment.currency if payment else "",
            status=payment.status if payment else "",
            failure_category=case.failure_category,
            failure_reason=payment.failure_reason if payment else None,
            failure_code=payment.failure_code if payment else None,
            created_at=payment.razorpay_created_at if payment else None,
        ),
        decision=decision,
        ai_insight=ai_insight,
        historical_evidence=historical_evidence,
    )


@router.get("/stats", response_model=RecoveryStatsOut)
def get_recovery_stats(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_organization_id),
) -> RecoveryStatsOut:
    total_failed_payments = db.scalar(
        select(func.count(Payment.id)).where(
            Payment.status.in_(("FAILED", "RETRYING")), Payment.organization_id == org_id
        )
    ) or 0

    total_revenue_at_risk = db.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
            RecoveryCase.status.in_(ACTIVE_RECOVERY_CASE_STATUSES),
            RecoveryCase.organization_id == org_id,
        )
    ) or 0

    total_recovered_revenue = db.scalar(
        select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
            RecoveryCase.status == "RECOVERED", RecoveryCase.organization_id == org_id
        )
    ) or 0

    active_recovery_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(
            RecoveryCase.status.in_(ACTIVE_RECOVERY_CASE_STATUSES),
            RecoveryCase.organization_id == org_id,
        )
    ) or 0

    awaiting_customer_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(
            RecoveryCase.status == "AWAITING_CUSTOMER", RecoveryCase.organization_id == org_id
        )
    ) or 0

    recovered_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(
            RecoveryCase.status == "RECOVERED", RecoveryCase.organization_id == org_id
        )
    ) or 0

    exhausted_cases = db.scalar(
        select(func.count(RecoveryCase.id)).where(
            RecoveryCase.status == "EXHAUSTED", RecoveryCase.organization_id == org_id
        )
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
        awaiting_customer_cases=awaiting_customer_cases,
        recovery_rate=round(recovery_rate, 4),
    )


@router.post("/cases/{case_id}/retry", response_model=RetryNowResponse)
def retry_recovery_case_now(
    case_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_organization_id),
) -> RetryNowResponse:
    """Unchanged from Phase 2, plus organization scoping."""
    case = db.get(RecoveryCase, case_id)
    if case is None or case.organization_id != org_id:
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
        "Manually triggered immediate execution of recovery_action_id=%s (recovery_case_id=%s)",
        pending_action.id, case.id,
    )

    return RetryNowResponse(
        recovery_case_id=case.id,
        status="triggered",
        detail=f"Action {pending_action.id} enqueued for immediate execution",
    )


@router.post("/cases/{case_id}/recover-now", response_model=CustomerRecoveryTriggerResponse)
def trigger_customer_recovery_now(
    case_id: int,
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_organization_id),
) -> CustomerRecoveryTriggerResponse:
    """
    Manually (re)trigger customer-assisted recovery for an
    AWAITING_CUSTOMER case -- normally this fires automatically the
    moment a case enters that status (see recovery_service.
    _route_exhausted_case), so this exists only as an ops/demo override,
    same purpose as the existing /retry endpoint for RETRY_PAYMENT cases.
    Idempotent: if a payment link/email already exist, the task reuses
    them rather than creating duplicates.
    """
    case = db.get(RecoveryCase, case_id)
    if case is None or case.organization_id != org_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Recovery case not found")

    if case.status != "AWAITING_CUSTOMER":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot trigger customer recovery for a case in status {case.status}",
        )

    from app.tasks.customer_recovery_tasks import run_customer_recovery

    run_customer_recovery.apply_async(args=[case.id], countdown=0)

    logger.info("Manually triggered customer recovery for recovery_case_id=%s", case.id)

    return CustomerRecoveryTriggerResponse(
        recovery_case_id=case.id,
        status="triggered",
        detail="Customer recovery (payment link + email) enqueued for immediate execution",
    )


@router.get("/batch", response_model=BatchResultOut)
def get_batch_result(
    db: Session = Depends(get_db),
    org_id: int = Depends(get_current_organization_id),
) -> BatchResultOut:
    """
    Read-only report over every RecoveryCase and AIRecoveryDecision that
    already exists -- NOT a trigger to run/simulate anything. Per the
    project brief, batch measurement should reflect real executed
    outcomes, not a second execution path.
    """
    from app.services.batch_recovery import run_batch

    result = run_batch(db, org_id)
    return BatchResultOut(**result.__dict__)