"""Email sinks: SMTP for real delivery, console for local runs."""

from __future__ import annotations

from email.message import EmailMessage

import aiosmtplib

from review_responder.adapters.base import ResponseSink
from review_responder.config import Settings
from review_responder.models import GeneratedResponse, Review


class SmtpSink(ResponseSink):
    name = "smtp"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @classmethod
    def from_settings(cls, settings: Settings) -> SmtpSink:
        return cls(settings)

    def build_message(self, review: Review, response: GeneratedResponse) -> EmailMessage:
        if not review.customer_email:
            raise ValueError("Review has no customer email")
        msg = EmailMessage()
        msg["From"] = self.settings.email_from
        msg["To"] = review.customer_email
        msg["Subject"] = response.subject
        msg["X-Review-Id"] = review.id
        msg.set_content(response.body)
        return msg

    async def send(self, review: Review, response: GeneratedResponse) -> None:
        s = self.settings
        await aiosmtplib.send(
            self.build_message(review, response),
            hostname=s.smtp_host,
            port=s.smtp_port,
            username=s.smtp_user or None,
            password=s.smtp_password.get_secret_value() if s.smtp_password else None,
            start_tls=s.smtp_starttls,
        )


class ConsoleSink(ResponseSink):
    """Prints the email instead of sending it."""

    name = "console"

    def __init__(self, settings: Settings | None = None) -> None:
        self.sent: list[tuple[Review, GeneratedResponse]] = []

    @classmethod
    def from_settings(cls, settings: Settings) -> ConsoleSink:
        return cls(settings)

    async def send(self, review: Review, response: GeneratedResponse) -> None:
        self.sent.append((review, response))
        print(f"--- email to {review.customer_email} ---\nSubject: {response.subject}\n")
        print(response.body)
        print("--- end ---\n")
