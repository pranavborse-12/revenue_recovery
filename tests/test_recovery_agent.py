"""
Live-agent tests. All AI calls mocked (a small fake AIRecoveryService),
no real Mistral calls, per the project brief.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.payment import Payment
from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.schemas.ai_recovery import AIRecommendation
from app.services import agent_tools, batch_recovery, recovery_agent
from app.services.payment_gateway import MockPaymentGateway


class FakeEmailProvider:
    def send(self, *, to, subject, body):
        return "fake-id"


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _case_with_payment(db, amount=10000, attempt_count=0, strategy="RETRY_PAYMENT"):
    payment = Payment(
        razorpay_payment_id=f"pay_{id(object())}", razorpay_order_id="order_x",
        customer_email="c@example.com", amount=amount, currency="INR", status="FAILED",
        razorpay_created_at=datetime.now(timezone.utc),
    )
    db.add(payment)
    db.flush()
    case = RecoveryCase(
        payment_id=payment.id, failure_category="BANK_DECLINED", amount=amount,
        status="IN_PROGRESS", current_strategy=strategy, attempt_count=attempt_count,
    )
    db.add(case)
    db.flush()
    return case, payment


# --- Budget enforcement ---

def test_agent_has_no_budget_when_disabled(db, monkeypatch):
    monkeypatch.setattr(recovery_agent, "get_settings", lambda: type("S", (), {"AI_AGENT_ENABLED": False})())

    case, _ = _case_with_payment(db)
    assert recovery_agent.agent_has_budget(db, case) is False


def test_agent_budget_counts_only_executed_rows(db, monkeypatch):
    from app.core import retry_policy
    monkeypatch.setattr(recovery_agent, "get_settings", lambda: type("S", (), {"AI_AGENT_ENABLED": True})())
    monkeypatch.setattr(recovery_agent, "get_retry_policy", lambda: retry_policy.RetryPolicy(delay_minutes=[1, 1]))

    case, _ = _case_with_payment(db)
    db.add(AIRecoveryDecision(
        recovery_case_id=case.id, recommended_action="WAIT", confidence=0.5, reason="x",
        model="m", accepted=True, executed=False,  # not-executed row: should NOT count
    ))
    db.flush()
    assert recovery_agent.agent_has_budget(db, case) is True  # 0 executed < 2

    db.add(AIRecoveryDecision(
        recovery_case_id=case.id, recommended_action="RETRY_PAYMENT", confidence=0.5, reason="x",
        model="m", accepted=True, executed=True, outcome="scheduled",
    ))
    db.flush()
    assert recovery_agent.agent_has_budget(db, case) is True  # 1 executed < 2

    db.add(AIRecoveryDecision(
        recovery_case_id=case.id, recommended_action="RETRY_PAYMENT", confidence=0.5, reason="x",
        model="m", accepted=True, executed=True, outcome="scheduled",
    ))
    db.flush()
    assert recovery_agent.agent_has_budget(db, case) is False  # 2 executed >= 2


def test_agent_has_no_budget_for_terminal_case(db, monkeypatch):
    monkeypatch.setattr(recovery_agent, "get_settings", lambda: type("S", (), {"AI_AGENT_ENABLED": True})())

    case, _ = _case_with_payment(db)
    case.status = "RECOVERED"
    assert recovery_agent.agent_has_budget(db, case) is False


# --- Tool reuse and correctness ---

def test_retry_payment_tool_reuses_schedule_next_action(db, monkeypatch):
    from app.core import retry_policy
    from app.services import recovery_service

    monkeypatch.setattr(recovery_service, "get_retry_policy", lambda: retry_policy.RetryPolicy(delay_minutes=[30, 360]))
    monkeypatch.setattr(recovery_service, "_enqueue_action", lambda *a, **k: None)

    case, _ = _case_with_payment(db, attempt_count=0)
    outcome = agent_tools.retry_payment(db, case)

    assert "attempt_number=1" in outcome
    assert case.attempt_count == 1  # same field _schedule_next_action always increments
    assert case.status == "IN_PROGRESS"


def test_send_recovery_email_tool_transitions_and_executes(db):
    case, payment = _case_with_payment(db)
    gateway = MockPaymentGateway()
    email_provider = FakeEmailProvider()

    outcome = agent_tools.send_recovery_email(db, case, payment, gateway, email_provider)

    assert case.status == "AWAITING_CUSTOMER"
    assert "executed" in outcome
    assert db.query(PaymentLink).filter_by(recovery_case_id=case.id).count() == 1


def test_tool_rejects_ineligible_case_status(db):
    case, payment = _case_with_payment(db)
    case.status = "RECOVERED"
    gateway = MockPaymentGateway()

    with pytest.raises(agent_tools.AgentToolError):
        agent_tools.send_recovery_email(db, case, payment, gateway, FakeEmailProvider())


# --- Agent step: policy rejection and tool failure both fall through safely ---

def test_try_agent_intervention_falls_through_when_policy_rejects(db, monkeypatch):
    case, _ = _case_with_payment(db)
    case.attempt_count = 99  # forces validate_ai_recommendation to reject RETRY_PAYMENT
    rec = AIRecommendation(action="RETRY_PAYMENT", delay_minutes=60, confidence=0.9, reason="x")
    monkeypatch.setattr(recovery_agent, "get_multi_agent_recommendation", lambda *a, **k: rec)

    result = recovery_agent.try_agent_intervention(db, case, recovery_action_id=None)

    assert result.handled is False
    decision = db.query(AIRecoveryDecision).filter_by(recovery_case_id=case.id).one()
    assert decision.accepted is False
    assert decision.executed is False


def test_try_agent_intervention_wait_never_counts_as_handled(db, monkeypatch):
    case, _ = _case_with_payment(db)
    rec = AIRecommendation(action="WAIT", confidence=0.4, reason="not enough data")
    monkeypatch.setattr(recovery_agent, "get_multi_agent_recommendation", lambda *a, **k: rec)

    result = recovery_agent.try_agent_intervention(db, case, recovery_action_id=None)

    assert result.handled is False
    decision = db.query(AIRecoveryDecision).filter_by(recovery_case_id=case.id).one()
    assert decision.executed is False


def test_try_agent_intervention_tool_failure_still_falls_through(db, monkeypatch):
    case, payment = _case_with_payment(db)
    rec = AIRecommendation(action="SEND_PAYMENT_LINK", confidence=0.8, reason="x")
    monkeypatch.setattr(recovery_agent, "get_multi_agent_recommendation", lambda *a, **k: rec)

    def _boom(*a, **k):
        raise agent_tools.AgentToolError("simulated Razorpay outage")

    monkeypatch.setattr(agent_tools, "send_recovery_email", _boom)

    result = recovery_agent.try_agent_intervention(db, case, recovery_action_id=None)

    assert result.handled is False  # tool failed -> deterministic default must still run
    decision = db.query(AIRecoveryDecision).filter_by(recovery_case_id=case.id).one()
    assert decision.executed is True  # attempt WAS made -> consumes budget
    assert "simulated Razorpay outage" in decision.outcome


def test_try_agent_intervention_manual_review_transitions_to_exhausted(db, monkeypatch):
    case, _ = _case_with_payment(db)
    rec = AIRecommendation(action="MANUAL_REVIEW", confidence=0.6, reason="ambiguous")
    monkeypatch.setattr(recovery_agent, "get_multi_agent_recommendation", lambda *a, **k: rec)

    result = recovery_agent.try_agent_intervention(db, case, recovery_action_id=None)

    assert result.handled is True
    assert case.status == "EXHAUSTED"


# --- Batch: no double-counting revenue across multiple attempts ---

def test_batch_does_not_double_count_revenue_across_attempts(db):
    case, payment = _case_with_payment(db, amount=1000)
    for n in range(1, 4):
        db.add(RecoveryAction(
            recovery_case_id=case.id, action_type="RETRY_PAYMENT", status="FAILED" if n < 3 else "SUCCESS",
            attempt_number=n, scheduled_at=datetime.now(timezone.utc), executed_at=datetime.now(timezone.utc),
        ))
    case.status = "RECOVERED"
    db.flush()

    result = batch_recovery.run_batch(db)

    assert result.recovered_revenue == 1000  # NOT 3000
    assert result.retries_executed == 3  # attempt count is still tracked separately