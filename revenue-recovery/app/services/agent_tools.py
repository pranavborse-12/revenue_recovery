"""
Agent tools: the only functions the recovery agent is allowed to call to
actually change anything. Each one is a thin wrapper around an existing
Phase 2/3 service function -- no tool reimplements recovery logic, it
only adds the guard needed to make it safe for an AI-originated call and
the state transition needed to hand off out of the automatic loop.

Every tool raises AgentToolError on a precondition failure or an
external-service failure. recovery_agent.py treats any raised error the
same way: log it, record it, fall through to the deterministic default
for that round. A tool NEVER silently succeeds when its precondition
isn't met.
"""

from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.models.recovery_case import RecoveryCase
from app.services import customer_recovery_service
from app.services.customer_recovery_service import NoCustomerEmailError, PaymentLinkProviderError
from app.services.email_provider import EmailProvider
from app.services.payment_gateway import PaymentGateway


class AgentToolError(Exception):
    """Raised by any agent tool on a precondition failure or execution failure."""


def retry_payment(db: Session, case: RecoveryCase) -> str:
    """Schedule one more automatic retry -- literally the same function on_payment_failed uses."""
    if case.status not in ("OPEN", "IN_PROGRESS"):
        raise AgentToolError(f"case status {case.status} does not permit another retry")

    from app.services.recovery_service import _schedule_next_action  # local import: avoid circularity

    action = _schedule_next_action(db, case, case.current_strategy or "RETRY_PAYMENT")
    if action is None:
        raise AgentToolError("retry policy is already exhausted for this case")
    return f"scheduled retry attempt_number={action.attempt_number}"


def send_recovery_email(
    db: Session, case: RecoveryCase, payment: Payment, gateway: PaymentGateway, email_provider: EmailProvider
) -> str:
    """Ensure a payment link exists and send the recovery email -- reuses the full Phase 3 sequence."""
    if case.status not in ("OPEN", "IN_PROGRESS", "AWAITING_CUSTOMER"):
        raise AgentToolError(f"case status {case.status} not eligible for customer recovery")
    if case.status != "AWAITING_CUSTOMER":
        case.transition_to("AWAITING_CUSTOMER")

    try:
        customer_recovery_service.start_customer_recovery(db, case, payment, gateway, email_provider)
    except (PaymentLinkProviderError, NoCustomerEmailError) as exc:
        raise AgentToolError(f"customer recovery failed: {exc}") from exc
    return "customer recovery (payment link + email) executed"