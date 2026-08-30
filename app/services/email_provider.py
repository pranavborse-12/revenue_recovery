"""
EmailProvider: boundary between recovery-email business logic
(customer_recovery_service.py) and the mechanism used to send email.
Mirrors payment_gateway.py's real/mock split.

ConsoleEmailProvider is the default (EMAIL_PROVIDER unset or not "smtp")
so the recovery flow is fully exercisable in dev/tests without SMTP
credentials. Only one real provider (SMTP, stdlib smtplib -- no extra
SDK) is implemented, per the project brief's "do not add multiple email
vendors."
"""

from email.mime.text import MIMEText
import smtplib

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailSendError(Exception):
    """Raised when sending an email fails."""


class EmailProvider:
    def send(self, *, to: str, subject: str, body: str) -> str | None:
        """Send an email; return a provider message id if available."""
        raise NotImplementedError


class ConsoleEmailProvider(EmailProvider):
    def send(self, *, to: str, subject: str, body: str) -> str | None:
        logger.info("[console email provider] to=%s subject=%s", to, subject)
        return None


class SMTPEmailProvider(EmailProvider):
    def __init__(
        self, *, host: str, port: int, username: str, password: str, use_tls: bool, from_addr: str
    ):
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._from_addr = from_addr

    def send(self, *, to: str, subject: str, body: str) -> str | None:
        msg = MIMEText(body, "plain", "utf-8")
        msg["Subject"] = subject
        msg["From"] = self._from_addr
        msg["To"] = to

        try:
            with smtplib.SMTP(self._host, self._port, timeout=10) as server:
                if self._use_tls:
                    server.starttls()
                if self._username:
                    server.login(self._username, self._password)
                server.sendmail(self._from_addr, [to], msg.as_string())
        except Exception as exc:  # smtplib raises several distinct exception types
            raise EmailSendError(str(exc)) from exc

        return None  # smtplib doesn't return a provider message id


def get_email_provider() -> EmailProvider:
    settings = get_settings()
    if settings.EMAIL_PROVIDER == "smtp":
        return SMTPEmailProvider(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USERNAME,
            password=settings.SMTP_PASSWORD,
            use_tls=settings.SMTP_USE_TLS,
            from_addr=settings.EMAIL_FROM,
        )
    return ConsoleEmailProvider()