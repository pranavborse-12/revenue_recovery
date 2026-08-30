"""
CustomerRecoveryService: coordinates the customer-assisted recovery path
once automatic RETRY_PAYMENT attempts are exhausted.

    RecoveryCase (AWAITING_CUSTOMER)
          |
    create_payment_link()   -- idempotent, one active link per case
          |
    send_recovery_email()   -- idempotent, one active communication per
                                case+type
    (customer pays the Razorpay-hosted link -- no separate customer-
     facing URL/token of ours is needed; Razorpay's own short_url IS the
     secure public surface)
          |
    payment.captured webhook -> existing Phase 1/2 pipeline
    (payment_service retry-link detection + recovery_service.
     on_payment_captured_via_retry, UNCHANGED) -> RECOVERED

This module does not decide when a case becomes RECOVERED -- that stays
in recovery_service.py, exactly as in Phase 2.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger

from app.models.payment import Payment
from app.models.payment_link import ACTIVE_PAYMENT_LINK_STATUSES, PaymentLink
from app.models.recovery_case import RecoveryCase
from app.models.recovery_communication import ACTIVE_COMMUNICATION_STATUSES, RecoveryCommunication
from app.services.email_provider import EmailProvider, EmailSendError
from app.services.payment_gateway import PaymentGateway


logger = get_logger(__name__)


class RecoveryCaseNotEligible(Exception):
    """Raised when a case's status doesn't allow the requested action."""


class PaymentLinkProviderError(Exception):
    """Raised when Razorpay fails to create the payment link."""


class NoCustomerEmailError(Exception):
    """Raised when the payment has no customer_email on file."""

    def __init__(self, recovery_case_id: int):
        self.recovery_case_id = recovery_case_id
        super().__init__(f"recovery_case_id={recovery_case_id} has no customer email on file")


@dataclass(frozen=True)
class PaymentLinkCreationResult:
    payment_link: PaymentLink
    is_new: bool


@dataclass(frozen=True)
class EmailSendResult:
    communication: RecoveryCommunication
    is_new: bool
    sent: bool


def create_payment_link(
    db: Session, case: RecoveryCase, payment: Payment, gateway: PaymentGateway
) -> PaymentLinkCreationResult:
    """
    Create a customer-facing Razorpay payment link for this case, or
    return the existing active one if one already exists.

    The existing-link check runs BEFORE calling Razorpay, so a duplicate
    request never reaches the provider at all. The partial unique index
    on payment_links (recovery_case_id) WHERE status='CREATED' (see the
    migration) backstops the race this check alone can't close (two
    concurrent Celery task runs, both past the check before either
    commits).
    """
    if case.status != "AWAITING_CUSTOMER":
        raise RecoveryCaseNotEligible(
            f"recovery_case_id={case.id} is status={case.status}, not AWAITING_CUSTOMER"
        )

    existing = db.scalars(
        select(PaymentLink).where(
            PaymentLink.recovery_case_id == case.id,
            PaymentLink.status.in_(ACTIVE_PAYMENT_LINK_STATUSES),
        )
    ).first()
    if existing is not None:
        logger.info(
            "Reusing existing active payment_link_id=%s for recovery_case_id=%s",
            existing.id, case.id,
        )
        return PaymentLinkCreationResult(payment_link=existing, is_new=False)

    result = gateway.create_payment_link(
        amount=payment.amount,
        currency=payment.currency,
        description=(
            f"Complete your payment (order {payment.razorpay_order_id or payment.razorpay_payment_id})"
        ),
        customer_contact=payment.customer_contact,
        customer_email=payment.customer_email,
    )

    if result.status != "created":
        logger.warning(
            "Payment link creation failed for recovery_case_id=%s: %s", case.id, result.detail
        )
        raise PaymentLinkProviderError(result.detail)

    link = PaymentLink(
        recovery_case_id=case.id,
        razorpay_payment_link_id=result.razorpay_payment_link_id,
        razorpay_short_url=result.short_url,
        amount=payment.amount,
        currency=payment.currency,
        status="CREATED",
        expires_at=result.expires_at,
    )
    db.add(link)
    db.flush()
    logger.info("Created payment_link_id=%s for recovery_case_id=%s", link.id, case.id)
    return PaymentLinkCreationResult(payment_link=link, is_new=True)


def _build_recovery_email(payment: Payment, payment_link: PaymentLink) -> tuple[str, str]:
    """
    Build the (subject, body) of the recovery email. Deterministic,
    plain text, no templating engine and no AI-generated content, per
    the project brief.
    """
    amount_display = f"{payment_link.amount / 100:.2f} {payment_link.currency}"
    order_ref = payment.razorpay_order_id or payment.razorpay_payment_id
    subject = "Action needed: complete your payment"
    body = (
        f"We were unable to complete your payment of {amount_display} "
        f"(reference: {order_ref}).\n\n"
        f"You can complete it securely here:\n{payment_link.razorpay_short_url}\n\n"
        "If you've already paid, you can ignore this message.\n\n"
        "Need help? Reply to this email and we'll assist you."
    )
    return subject, body

def _resolve_recovery_email(payment: Payment) -> str | None:
    """
    Resolve the email address used for outbound recovery delivery.

    Razorpay Test Mode may provide the synthetic `void@razorpay.com`
    address on failed payments. When a test override is configured,
    use it only for the outbound recovery email.

    The original payment.customer_email value is left unchanged.
    """
    settings = get_settings()

    if (
        payment.customer_email == "void@razorpay.com"
        and settings.TEST_RECOVERY_EMAIL_OVERRIDE
    ):
        return settings.TEST_RECOVERY_EMAIL_OVERRIDE

    return payment.customer_email

def send_recovery_email(
    db: Session,
    case: RecoveryCase,
    payment: Payment,
    payment_link: PaymentLink,
    email_provider: EmailProvider,
) -> EmailSendResult:
    """
    Send the recovery email, or return the existing active communication
    if one was already sent/queued for this case+type.

    Documented edge case (unavoidable without a distributed transaction):
    if email_provider.send() succeeds but the following db.flush()/commit
    fails, the customer has received a real email while our own record
    still shows PENDING. A subsequent retry in that narrow window could
    resend. Acceptable for Phase 3's scope.
    """
    existing = db.scalars(
        select(RecoveryCommunication).where(
            RecoveryCommunication.recovery_case_id == case.id,
            RecoveryCommunication.type == "PAYMENT_LINK",
            RecoveryCommunication.status.in_(ACTIVE_COMMUNICATION_STATUSES),
        )
    ).first()
    if existing is not None:
        logger.info(
            "recovery_case_id=%s already has an active PAYMENT_LINK communication "
            "(id=%s, status=%s) -- preventing duplicate notification",
            case.id, existing.id, existing.status,
        )
        return EmailSendResult(communication=existing, is_new=False, sent=existing.status == "SENT")

    recipient = _resolve_recovery_email(payment)
    if not recipient:
        raise NoCustomerEmailError(case.id)

    communication = RecoveryCommunication(
        recovery_case_id=case.id, channel="EMAIL", type="PAYMENT_LINK", status="PENDING"
    )
    db.add(communication)
    db.flush()  # protected by the partial unique index against a concurrent duplicate

    subject, body = _build_recovery_email(payment, payment_link)

    try:
        provider_message_id = email_provider.send(
            to=recipient, subject=subject, body=body)
    except EmailSendError as exc:
        communication.status = "FAILED"
        logger.warning(
            "Recovery email failed for recovery_case_id=%s: %s", case.id, exc
        )
        return EmailSendResult(communication=communication, is_new=True, sent=False)

    from datetime import datetime, timezone

    communication.status = "SENT"
    communication.provider_message_id = provider_message_id
    communication.sent_at = datetime.now(timezone.utc)
    logger.info("Recovery email sent for recovery_case_id=%s", case.id)
    return EmailSendResult(communication=communication, is_new=True, sent=True)


def start_customer_recovery(
    db: Session, case: RecoveryCase, payment: Payment, gateway: PaymentGateway, email_provider: EmailProvider
) -> None:
    """
    Full customer-recovery sequence for one AWAITING_CUSTOMER case:
    create (or reuse) the payment link, then send (or skip, if already
    sent) the recovery email. Called from the Celery task
    (app/tasks/customer_recovery_tasks.py) -- kept as a plain function
    here so it stays unit-testable without Celery.
    """
    link_result = create_payment_link(db, case, payment, gateway)
    send_recovery_email(db, case, payment, link_result.payment_link, email_provider)