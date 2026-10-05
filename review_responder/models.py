"""Internal data models. Adapters map host-app data into these; nothing host-specific leaks past."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Sentiment = Literal["positive", "neutral", "negative", "mixed"]
Tone = Literal[
    "angry", "frustrated", "disappointed", "calm", "happy", "enthusiastic", "sarcastic", "neutral"
]
Urgency = Literal["low", "medium", "high", "critical"]
IssueType = Literal[
    "none",
    "billing",
    "delivery",
    "product_quality",
    "bug",
    "support_experience",
    "feature_request",
    "other",
]
ResponseType = Literal["appreciation", "apology", "acknowledgement"]


class Review(BaseModel):
    id: str
    source: str = "unknown"
    text: str = ""
    rating: float | None = None
    customer_name: str | None = None
    customer_email: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id", mode="before")
    @classmethod
    def _id_to_str(cls, v: Any) -> str:
        return str(v)

    @field_validator("text", mode="before")
    @classmethod
    def _text_to_str(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @field_validator("customer_name", "customer_email", mode="before")
    @classmethod
    def _blank_to_none(cls, v: Any) -> Any:
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @field_validator("rating", mode="before")
    @classmethod
    def _rating(cls, v: Any) -> Any:
        if v in ("", None):
            return None
        return v


class Classification(BaseModel):
    """Structured output of the classify node."""

    sentiment: Sentiment
    tone: Tone
    urgency: Urgency
    issue_type: IssueType
    confidence: float = Field(ge=0.0, le=1.0, description="0-1 confidence in the sentiment label")
    summary: str = Field(description="One-sentence neutral summary of the review")
    language: str = Field(
        default="en", description="ISO 639-1 code of the language the review is written in"
    )
    is_spam_or_abusive: bool = Field(
        default=False, description="True if the review is spam, gibberish, or abusive"
    )


class EmailDraft(BaseModel):
    """Structured output of the generate nodes."""

    subject: str = Field(description="Email subject line, under 80 characters")
    body: str = Field(description="Plain-text email body including greeting and sign-off")


class GeneratedResponse(BaseModel):
    subject: str
    body: str
    response_type: ResponseType
    model: str
    needs_human_review: bool = False


class ProcessResult(BaseModel):
    """What happened to a review; passed to FeedbackSource.mark_processed and the audit store."""

    review_id: str
    review: Review | None = None
    status: Literal["sent", "dry_run", "pending_approval", "held", "skipped", "no_email", "error"]
    response: GeneratedResponse | None = None
    classification: Classification | None = None
    reasons: list[str] = Field(default_factory=list)
