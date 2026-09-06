"""
recovery_agent: one bounded decision-and-execute step for a recovery
case. Never calls itself, never loops -- it's invoked once per
deterministic decision point (see recovery_service.py's two call sites),
same as the audit-only version was, except now its result can gate what
the caller does next.

    build context + historical evidence
        -> 3 independent agent opinions (strategist/historical/critic)
        -> deterministic reconciliation (no 4th LLM call)
        -> validate_ai_recommendation() (unchanged policy gate)
        -> tool call -> record decision

Any failure anywhere in that chain (any/all agents unavailable, invalid
output, no confident reconciliation, policy rejection, tool precondition
failure, tool execution error) results in handled=False -- the caller
always has a safe, already-working deterministic path to fall back to.
AI confidence -- from any agent, or the reconciled result -- is never
authority; "handled=True" only ever happens after
validate_ai_recommendation() (the existing, unmodified policy check)
has already said yes.

Multi-agent design note: agents run independently off the same base
context (not a chat, not sequential turns) -- the critic additionally
receives the strategist's and historical analyst's own outputs, since a
critic that can't see what it's critiquing isn't a critic. Reconciliation
is a small deterministic function, not a 4th LLM call, per project
decision to prefer the simpler mechanism when it's equally effective.
"""

import json
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.retry_policy import get_retry_policy
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.payment import Payment
from app.models.recovery_case import TERMINAL_RECOVERY_CASE_STATUSES, RecoveryCase
from app.schemas.ai_recovery import AIRecommendation, CriticOutput, HistoricalAnalystOutput
from app.services import agent_tools, historical_intelligence, recovery_context
from app.services.agent_tools import AgentToolError
from app.services.ai_recovery_service import (
    CRITIC_SYSTEM_PROMPT,
    HISTORICAL_ANALYST_SYSTEM_PROMPT,
    STRATEGIST_SYSTEM_PROMPT,
    run_agent,
)

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentStepResult:
    handled: bool  # True only if a tool call was made AND succeeded
    decision_id: int | None = None


def agent_has_budget(db: Session, case: RecoveryCase) -> bool:
    """
    False whenever the agent should not even be asked: disabled, case
    already terminal, or its execution budget (RetryPolicy.max_attempts,
    counted by rows where executed=True -- only ever true on a "final"
    row, never a per-agent opinion row) is spent.
    """
    if not get_settings().AI_AGENT_ENABLED:
        return False
    if case.status in TERMINAL_RECOVERY_CASE_STATUSES:
        return False
    used = (
        db.scalar(
            select(func.count(AIRecoveryDecision.id)).where(
                AIRecoveryDecision.recovery_case_id == case.id,
                AIRecoveryDecision.executed.is_(True),
            )
        )
        or 0
    )
    return used < get_retry_policy().max_attempts


def _get_gateway():
    from app.services.payment_gateway import RazorpayPaymentGateway

    return RazorpayPaymentGateway()


def _record_agent_opinion(db, case, recovery_action_id, role, provider, model, opinion) -> None:
    """
    One audit row per agent, win or lose. A failed/unavailable agent
    still gets a row (recommended_action="NO_RESPONSE") so "one agent
    failed" / "all agents failed" is visible in the audit trail, not
    silently absent. Never executed=True -- only the "final" row can be.
    """
    if opinion is None:
        db.add(AIRecoveryDecision(
            recovery_case_id=case.id, organization_id=case.organization_id,
            recovery_action_id=recovery_action_id,
            recommended_action="NO_RESPONSE", recommended_delay_minutes=None,
            confidence=0.0, reason="agent call failed or returned invalid output",
            model=model, agent_role=role, provider=provider,
            accepted=False, rejection_reason="no usable response", executed=False,
        ))
        db.flush()
        return

    if isinstance(opinion, AIRecommendation):
        action, delay, confidence, reason = opinion.action, opinion.delay_minutes, opinion.confidence, opinion.reason
    elif isinstance(opinion, HistoricalAnalystOutput):
        action, delay, confidence, reason = opinion.action, None, opinion.confidence, opinion.reason
    else:  # CriticOutput -- no single "action" field; represent its verdict
        action = opinion.alternative_action or ("APPROVED" if opinion.approved else "REJECTED")
        delay, confidence, reason = None, opinion.confidence, f"{opinion.concerns} | {opinion.reason}"[:512]

    db.add(AIRecoveryDecision(
        recovery_case_id=case.id, organization_id=case.organization_id,
        recovery_action_id=recovery_action_id,
        recommended_action=action, recommended_delay_minutes=delay,
        confidence=confidence, reason=reason, model=model,
        agent_role=role, provider=provider, accepted=True, rejection_reason=None, executed=False,
    ))
    db.flush()


def _reconcile(
    strategist: AIRecommendation | None,
    historian: HistoricalAnalystOutput | None,
    critic: CriticOutput | None,
) -> AIRecommendation | None:
    """
    Deterministic reconciliation, no 4th LLM call:
      1. Critic explicitly rejects (approved=False):
         - with an alternative_action -> use it (the critic wins a veto).
         - with no alternative -> no confident recommendation (don't
           guess which of the other two to trust after a rejection).
      2. Critic approves (or was unavailable) and strategist+historian
         agree -> use that action; confidence = weighted average,
         favoring the evidence-grounded historian slightly.
      3. Only one of strategist/historian available -> use it as-is.
      4. Strategist and historian disagree -> prefer the historian
         (evidence over opinion), confidence discounted for disagreement.
      5. Neither available -> None.
    """
    if critic is not None and not critic.approved:
        if critic.alternative_action is not None:
            return AIRecommendation(
                action=critic.alternative_action, delay_minutes=None, confidence=critic.confidence,
                reason=f"Critic override: {critic.reason}"[:512],
            )
        return None

    if strategist is not None and historian is not None:
        if strategist.action == historian.action:
            confidence = round(0.4 * strategist.confidence + 0.6 * historian.confidence, 4)
            return AIRecommendation(
                action=strategist.action, delay_minutes=strategist.delay_minutes, confidence=confidence,
                reason=f"Strategist and Historical Analyst agree: {historian.reason}"[:512],
            )
        confidence = round(historian.confidence * 0.85, 4)
        return AIRecommendation(
            action=historian.action, delay_minutes=None, confidence=confidence,
            reason=f"Evidence favored over strategist opinion: {historian.reason}"[:512],
        )

    sole = strategist or historian
    if sole is None:
        return None
    delay = sole.delay_minutes if isinstance(sole, AIRecommendation) else None
    return AIRecommendation(action=sole.action, delay_minutes=delay, confidence=sole.confidence, reason=sole.reason)


def get_multi_agent_recommendation(
    db: Session, case: RecoveryCase, *, recovery_action_id: int | None
) -> AIRecommendation | None:
    """
    Runs the 3 agents independently (not sequential turns), records one
    audit row per agent, and returns the deterministically reconciled
    result -- or None if no confident recommendation emerged. Does NOT
    write the "final" audit row itself; the caller (try_agent_intervention)
    does that after policy validation, same as before this change.
    """
    settings = get_settings()
    if not settings.AI_ENABLED:
        return None

    action_id_filter = (
        AIRecoveryDecision.recovery_action_id.is_(None)
        if recovery_action_id is None
        else AIRecoveryDecision.recovery_action_id == recovery_action_id
    )
    already_decided = db.scalars(
        select(AIRecoveryDecision.id).where(
            AIRecoveryDecision.recovery_case_id == case.id,
            AIRecoveryDecision.agent_role == "final",
            action_id_filter,
        )
    ).first()
    if already_decided is not None:
        logger.info(
            "recovery_case_id=%s: final AI decision already recorded for "
            "recovery_action_id=%s -- skipping duplicate agent run",
            case.id, recovery_action_id,
        )
        return None
    
    context = recovery_context.build_recovery_context(db, case)
    evidence = historical_intelligence.get_recovery_evidence(db, case.failure_category)
    evidence_dict = historical_intelligence.evidence_to_prompt_dict(evidence)
    base_payload = json.dumps({**context, "historical_evidence": evidence_dict})
    strategist_model = (
        settings.OPENROUTER_MODEL
        if settings.AI_STRATEGIST_PROVIDER == "openrouter"
        else settings.AI_MODEL
    )

    strategist = run_agent(
        provider=settings.AI_STRATEGIST_PROVIDER, model=strategist_model,
        system_prompt=STRATEGIST_SYSTEM_PROMPT, user_content=base_payload, schema=AIRecommendation,
    )
    _record_agent_opinion(db, case, recovery_action_id, "strategist", settings.AI_STRATEGIST_PROVIDER, strategist_model, strategist)

    historian = run_agent(
        provider=settings.AI_HISTORICAL_PROVIDER, model=settings.AI_HISTORICAL_MODEL,
        system_prompt=HISTORICAL_ANALYST_SYSTEM_PROMPT, user_content=base_payload, schema=HistoricalAnalystOutput,
    )
    _record_agent_opinion(db, case, recovery_action_id, "historical_analyst", settings.AI_HISTORICAL_PROVIDER, settings.AI_HISTORICAL_MODEL, historian)

    critic_payload = json.dumps({
        **context, "historical_evidence": evidence_dict,
        "strategist_recommendation": strategist.model_dump() if strategist else None,
        "historical_analyst_recommendation": historian.model_dump() if historian else None,
    })
    critic = run_agent(
        provider=settings.AI_CRITIC_PROVIDER, model=settings.AI_CRITIC_MODEL,
        system_prompt=CRITIC_SYSTEM_PROMPT, user_content=critic_payload, schema=CriticOutput,
    )
    _record_agent_opinion(db, case, recovery_action_id, "critic", settings.AI_CRITIC_PROVIDER, settings.AI_CRITIC_MODEL, critic)

    return _reconcile(strategist, historian, critic)


def try_agent_intervention(
    db: Session, case: RecoveryCase, *, recovery_action_id: int | None
) -> AgentStepResult:
    """
    Caller MUST have already confirmed agent_has_budget(db, case) is
    True. Doesn't re-check it here to avoid a second, possibly-stale
    query in the same call -- the caller's check and this call happen in
    the same transaction/moment.
    """
    from app.services.email_provider import get_email_provider
    from app.services.recovery_service import validate_ai_recommendation

    recommendation = get_multi_agent_recommendation(db, case, recovery_action_id=recovery_action_id)
    if recommendation is None:
        return AgentStepResult(handled=False)

    accepted, rejection_reason = validate_ai_recommendation(case, recommendation)
    final_model = "multi-agent"

    if not accepted or recommendation.action == "WAIT":
        db.add(
            AIRecoveryDecision(
                recovery_case_id=case.id, organization_id=case.organization_id,
                recovery_action_id=recovery_action_id,
                recommended_action=recommendation.action, recommended_delay_minutes=recommendation.delay_minutes,
                confidence=recommendation.confidence, reason=recommendation.reason, model=final_model,
                agent_role="final", provider=None,
                accepted=accepted, rejection_reason=rejection_reason if not accepted else "WAIT: deferred",
                executed=False,
            )
        )
        db.flush()
        return AgentStepResult(handled=False)

    payment = db.get(Payment, case.payment_id)
    gateway = _get_gateway()
    email_provider = get_email_provider()

    try:
        if recommendation.action == "RETRY_PAYMENT":
            outcome = agent_tools.retry_payment(db, case)
        elif recommendation.action == "SEND_PAYMENT_LINK":
            outcome = agent_tools.send_recovery_email(db, case, payment, gateway, email_provider)
        elif recommendation.action == "MANUAL_REVIEW":
            if case.status in ("OPEN", "IN_PROGRESS", "AWAITING_CUSTOMER"):
                case.transition_to("EXHAUSTED")
            outcome = "manual review: case marked EXHAUSTED for human follow-up"
        else:  # pragma: no cover -- schema already restricts to known actions
            raise AgentToolError(f"no tool for action {recommendation.action}")
        succeeded = True
    except AgentToolError as exc:
        logger.warning("recovery_case_id=%s agent tool failed: %s", case.id, exc)
        outcome = str(exc)
        succeeded = False

    decision = AIRecoveryDecision(
        recovery_case_id=case.id, organization_id=case.organization_id,
        recovery_action_id=recovery_action_id,
        recommended_action=recommendation.action, recommended_delay_minutes=recommendation.delay_minutes,
        confidence=recommendation.confidence, reason=recommendation.reason, model=final_model,
        agent_role="final", provider=None,
        accepted=True, rejection_reason=None, executed=True, outcome=outcome,
    )
    db.add(decision)
    db.flush()

    logger.info(
        "recovery_case_id=%s agent executed action=%s succeeded=%s outcome=%s",
        case.id, recommendation.action, succeeded, outcome,
    )
    return AgentStepResult(handled=succeeded, decision_id=decision.id)