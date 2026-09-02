"""Multi-agent tests: independent opinions, disagreement, reconciliation, fallback."""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.payment import Payment
from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.schemas.ai_recovery import AIRecommendation, CriticOutput, HistoricalAnalystOutput
from app.services import historical_intelligence, recovery_agent


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _case(db, amount=1000, category="INSUFFICIENT_FUNDS"):
    payment = Payment(razorpay_payment_id=f"pay_{id(object())}", amount=amount, currency="INR",
                       status="FAILED", razorpay_created_at=datetime.now(timezone.utc))
    db.add(payment); db.flush()
    case = RecoveryCase(payment_id=payment.id, failure_category=category, amount=amount,
                         status="IN_PROGRESS", current_strategy="RETRY_PAYMENT", attempt_count=1)
    db.add(case); db.flush()
    return case


# --- Reconciliation rules ---

def test_reconcile_agreement_averages_confidence():
    s = AIRecommendation(action="SEND_PAYMENT_LINK", confidence=0.8, reason="s")
    h = HistoricalAnalystOutput(action="SEND_PAYMENT_LINK", confidence=0.9, supporting_evidence="n=100", reason="h")
    result = recovery_agent._reconcile(s, h, None)
    assert result.action == "SEND_PAYMENT_LINK"
    assert result.confidence == round(0.4 * 0.8 + 0.6 * 0.9, 4)


def test_reconcile_disagreement_prefers_historian():
    s = AIRecommendation(action="RETRY_PAYMENT", delay_minutes=60, confidence=0.7, reason="s")
    h = HistoricalAnalystOutput(action="SEND_PAYMENT_LINK", confidence=0.9, supporting_evidence="n=500", reason="h")
    result = recovery_agent._reconcile(s, h, None)
    assert result.action == "SEND_PAYMENT_LINK"
    assert result.confidence < 0.9


def test_reconcile_critic_veto_with_alternative_wins():
    s = AIRecommendation(action="RETRY_PAYMENT", delay_minutes=60, confidence=0.9, reason="s")
    h = HistoricalAnalystOutput(action="RETRY_PAYMENT", confidence=0.9, supporting_evidence="n=10", reason="h")
    c = CriticOutput(approved=False, concerns="already retried twice", alternative_action="SEND_PAYMENT_LINK",
                      confidence=0.75, reason="retry exhausted evidence")
    result = recovery_agent._reconcile(s, h, c)
    assert result.action == "SEND_PAYMENT_LINK"


def test_reconcile_critic_veto_without_alternative_yields_none():
    s = AIRecommendation(action="RETRY_PAYMENT", delay_minutes=60, confidence=0.9, reason="s")
    c = CriticOutput(approved=False, concerns="unclear", alternative_action=None, confidence=0.5, reason="x")
    assert recovery_agent._reconcile(s, None, c) is None


def test_reconcile_all_unavailable_yields_none():
    assert recovery_agent._reconcile(None, None, None) is None


def test_reconcile_single_agent_available():
    h = HistoricalAnalystOutput(action="WAIT", confidence=0.3, supporting_evidence="n=2", reason="too little data")
    result = recovery_agent._reconcile(None, h, None)
    assert result.action == "WAIT"
    assert result.confidence == 0.3


# --- get_multi_agent_recommendation: records per-agent audit rows even on total failure ---

def test_multi_agent_disabled_returns_none_and_writes_nothing(db, monkeypatch):
    case = _case(db)
    monkeypatch.setattr(recovery_agent, "get_settings", lambda: type("S", (), {"AI_ENABLED": False})())

    result = recovery_agent.get_multi_agent_recommendation(db, case, recovery_action_id=None)

    assert result is None
    from app.models.ai_recovery_decision import AIRecoveryDecision
    assert db.query(AIRecoveryDecision).count() == 0


def test_multi_agent_all_providers_fail_records_no_response_rows(db, monkeypatch):
    case = _case(db)
    monkeypatch.setattr(recovery_agent, "get_settings",
                         lambda: type("S", (), {"AI_ENABLED": True, "AI_STRATEGIST_PROVIDER": "mistral",
                                                 "AI_MODEL": "m", "AI_HISTORICAL_PROVIDER": "groq",
                                                 "AI_HISTORICAL_MODEL": "h", "AI_CRITIC_PROVIDER": "groq",
                                                 "AI_CRITIC_MODEL": "c"})())
    monkeypatch.setattr(recovery_agent, "run_agent", lambda **kwargs: None)

    result = recovery_agent.get_multi_agent_recommendation(db, case, recovery_action_id=None)

    assert result is None
    from app.models.ai_recovery_decision import AIRecoveryDecision
    rows = db.query(AIRecoveryDecision).filter_by(recovery_case_id=case.id).all()
    assert len(rows) == 3  # one per agent, even though every one failed
    assert all(r.recommended_action == "NO_RESPONSE" for r in rows)
    assert all(r.executed is False for r in rows)


# --- Historical intelligence: aggregation correctness ---

def test_historical_evidence_retry_and_link(db):
    case = _case(db, category="INSUFFICIENT_FUNDS")
    db.add(RecoveryAction(recovery_case_id=case.id, action_type="RETRY_PAYMENT", status="FAILED",
                           attempt_number=1, scheduled_at=datetime.now(timezone.utc),
                           executed_at=datetime.now(timezone.utc)))
    db.add(RecoveryAction(recovery_case_id=case.id, action_type="RETRY_PAYMENT", status="SUCCESS",
                           attempt_number=2, scheduled_at=datetime.now(timezone.utc),
                           executed_at=datetime.now(timezone.utc)))
    db.add(PaymentLink(recovery_case_id=case.id, razorpay_payment_link_id="plink_1",
                        razorpay_short_url="https://x", amount=1000, currency="INR", status="PAID"))
    case.status = "RECOVERED"
    db.flush()

    evidence = historical_intelligence.get_recovery_evidence(db, "INSUFFICIENT_FUNDS")

    assert evidence["RETRY_PAYMENT"].attempts == 2
    assert evidence["RETRY_PAYMENT"].recovered == 1
    assert evidence["SEND_PAYMENT_LINK"].attempts == 1
    assert evidence["SEND_PAYMENT_LINK"].recovered == 1


def test_historical_evidence_missing_action_is_absent_not_zero(db):
    _case(db, category="BANK_DECLINED")
    evidence = historical_intelligence.get_recovery_evidence(db, "BANK_DECLINED")
    assert "SEND_PAYMENT_LINK" not in evidence  # untested, not 0%