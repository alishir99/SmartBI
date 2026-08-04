"""Sending one kind of mail: a password-reset link.

Two backends, chosen by `MAIL_BACKEND`. `log` writes the message to the application log and
sends nothing - which is what a demo, a local run and every test want, and which means the
reset flow is exercisable end to end without an SMTP account. `smtp` sends for real over
stdlib `smtplib`.

No provider SDK. One transactional message over SMTP is the entire requirement; an SDK would
add a dependency, an account and a second way for this to fail. When volume or deliverability
starts to matter, this is the one function to swap.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import settings

logger = logging.getLogger(__name__)


class MailNotConfigured(RuntimeError):
    """`MAIL_BACKEND=smtp` with no host to send through."""


def send(*, to: str, subject: str, body: str) -> None:
    """Deliver one plain-text message, or raise.

    Callers must decide what a failure means to them. The reset route deliberately swallows it:
    a mail outage must not become a way to find out which addresses have accounts.
    """
    if settings.mail_backend == "log":
        # The full body, so the link is copy-pasteable out of `docker compose logs api`. This is
        # a development transport and the log is a development log; the `smtp` backend never
        # writes the body anywhere.
        logger.info("", extra={"event": "mail.logged", "to": to, "subject": subject,
                               "body": body})
        return

    if not settings.smtp_host:
        raise MailNotConfigured("MAIL_BACKEND=smtp but SMTP_HOST is empty")

    message = EmailMessage()
    message["From"] = settings.mail_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_user:
            smtp.login(settings.smtp_user, settings.smtp_password)
        smtp.send_message(message)

    # The address, never the body: a reset link in a log is a reset link anyone with log access
    # can use, which is the whole point of it being short-lived and single-use.
    logger.info("", extra={"event": "mail.sent", "to": to, "subject": subject})
