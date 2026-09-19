import logging
import smtplib
from email.mime.text import MIMEText

from app.core.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, body: str) -> None:
    """
    Sends a plain-text email via SMTP if configured. If SMTP_HOST is unset, logs the
    message instead of sending it -- lets email-dependent flows (password reset) be
    fully exercised without real SMTP credentials, and upgrades to real sending the
    moment those credentials are added to backend/.env, with no code change.
    """
    if not settings.SMTP_HOST:
        logger.warning("SMTP not configured; email NOT sent. to=%s subject=%r\n%s", to, subject, body)
        return

    message = MIMEText(body)
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM
    message["To"] = to

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
        if settings.SMTP_USE_TLS:
            server.starttls()
        if settings.SMTP_USER:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, [to], message.as_string())
    logger.info("Sent email to %s: %s", to, subject)
