"""Outbound email — verification codes in the MVP, transactional later.

Two backends today:
- "console": log the message body to stdout. Dev + tests use this so no SMTP
  credentials are needed to iterate on the flow.
- "smtp": send via SMTP. Reads EMAIL_SMTP_* from settings. Runs the blocking
  smtplib call inside a thread so it doesn't stall the event loop.

The Protocol pattern mirrors `providers/llm.py` and `providers/transcription.py`
— makes it easy to add a Resend/Postmark/SES backend later without touching
callers.
"""
from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage
from typing import Protocol

from app.config import settings

logger = logging.getLogger(__name__)


class EmailProvider(Protocol):
    async def send(self, *, to: str, subject: str, body: str) -> None: ...


class ConsoleEmailProvider:
    """Dev/test provider — writes the email to logs instead of sending it."""

    async def send(self, *, to: str, subject: str, body: str) -> None:
        logger.warning(
            "[email:console] to=%s subject=%s\n---BODY---\n%s\n---END---",
            to,
            subject,
            body,
        )


class SmtpEmailProvider:
    async def send(self, *, to: str, subject: str, body: str) -> None:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to
        msg.set_content(body)

        def _send() -> None:
            host = settings.EMAIL_SMTP_HOST
            port = settings.EMAIL_SMTP_PORT
            if not host:
                raise RuntimeError("EMAIL_SMTP_HOST is not configured")
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                if settings.EMAIL_SMTP_USE_TLS:
                    smtp.starttls()
                if settings.EMAIL_SMTP_USER:
                    smtp.login(settings.EMAIL_SMTP_USER, settings.EMAIL_SMTP_PASSWORD or "")
                smtp.send_message(msg)

        await asyncio.to_thread(_send)


def get_email_provider() -> EmailProvider:
    kind = (settings.EMAIL_PROVIDER or "console").lower()
    if kind == "smtp":
        return SmtpEmailProvider()
    return ConsoleEmailProvider()


async def send_verification_email(to: str, code: str) -> None:
    """Send the 6-digit code with a short expiry hint."""
    prov = get_email_provider()
    subject = f"{settings.EMAIL_FROM_NAME}: your verification code"
    body = (
        f"Your verification code is: {code}\n\n"
        f"It expires in {settings.EMAIL_VERIFY_TTL_MIN} minutes.\n\n"
        f"If you didn't request this, you can ignore this email."
    )
    await prov.send(to=to, subject=subject, body=body)
