"""Rule-based stand-in for an LLM (LLM_PROVIDER=offline).

Lets you run the whole pipeline end to end with no API key or network — useful for demos,
wiring up a new adapter, and as the default fake in tests. Quality is intentionally basic.
"""

from __future__ import annotations

import re
from typing import Any, TypeVar

from pydantic import BaseModel

from review_responder.models import Classification, EmailDraft

T = TypeVar("T", bound=BaseModel)

_POS = {
    "love",
    "great",
    "excellent",
    "amazing",
    "awesome",
    "perfect",
    "happy",
    "fantastic",
    "recommend",
    "thanks",
    "thank",
    "wonderful",
    "fast",
    "best",
    "helpful",
    "good",
}
_NEG = {
    "broken",
    "bad",
    "terrible",
    "awful",
    "late",
    "never",
    "refund",
    "worst",
    "disappointed",
    "angry",
    "poor",
    "damaged",
    "missing",
    "rude",
    "slow",
    "crash",
    "crashes",
    "bug",
    "charged",
    "wrong",
    "not",
    "again",
    "useless",
    "hate",
    "waste",
    "error",
}
_ISSUES = {
    "billing": {"charged", "charge", "invoice", "billing", "refund", "payment", "price"},
    "delivery": {"delivery", "shipping", "arrived", "late", "package", "courier", "shipped"},
    "bug": {"crash", "crashes", "bug", "error", "app", "login", "freezes"},
    "product_quality": {"broken", "damaged", "quality", "defective", "cheap", "faulty"},
    "support_experience": {"support", "agent", "rude", "service", "waited", "hold"},
    "feature_request": {"wish", "would", "feature", "add", "please"},
}
_SARCASM = re.compile(
    r"\b(great|wonderful|perfect|fantastic)\b[,!.]?\s+.*\b(again|broken|late)\b", re.I
)


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z']+", text.lower())


def classify(text: str, rating: float | None) -> Classification:
    words = _words(text)
    if not words:
        return Classification(
            sentiment="neutral",
            tone="neutral",
            urgency="low",
            issue_type="none",
            confidence=0.2,
            summary="Empty review.",
            is_spam_or_abusive=True,
        )
    pos = sum(w in _POS for w in words)
    neg = sum(w in _NEG for w in words)
    sarcastic = bool(_SARCASM.search(text))
    if sarcastic:
        pos, neg = 0, neg + 2
    if pos and neg >= 2:
        sentiment = "mixed"
    elif neg > pos:
        sentiment = "negative"
    elif pos > neg:
        sentiment = "positive"
    elif rating is not None:
        sentiment = "positive" if rating >= 4 else "negative" if rating <= 2 else "neutral"
    else:
        sentiment = "neutral"

    issue = "none"
    if sentiment != "positive":
        best = max(_ISSUES.items(), key=lambda kv: sum(w in kv[1] for w in words))
        if sum(w in best[1] for w in words):
            issue = best[0]

    tone = {
        "positive": "happy",
        "negative": "frustrated",
        "mixed": "disappointed",
        "neutral": "calm",
    }[sentiment]
    if sarcastic:
        tone = "sarcastic"
    urgency = (
        "high"
        if sentiment == "negative" and neg >= 3
        else ("medium" if sentiment in ("negative", "mixed") else "low")
    )
    confidence = min(0.95, 0.55 + 0.1 * abs(pos - neg))
    rating_conflict = rating is not None and (
        (rating >= 4 and sentiment == "negative") or (rating <= 2 and sentiment == "positive")
    )
    if rating_conflict:
        confidence = min(confidence, 0.6)
    summary = text.strip().split(".")[0][:140]
    return Classification.model_validate(
        {
            "sentiment": sentiment,
            "tone": tone,
            "urgency": urgency,
            "issue_type": issue,
            "confidence": round(confidence, 2),
            "summary": summary,
        }
    )


def draft(hints: dict[str, Any]) -> EmailDraft:
    name = hints.get("customer_name") or "there"
    brand = hints.get("brand_name", "our team")
    signoff = hints.get("brand_signoff", "The Team")
    summary = hints.get("summary", "your feedback")
    kind = hints.get("response_type")
    if kind == "appreciation":
        subject = f"Thank you for your kind words, {name}!"
        middle = (
            f"Thank you so much for taking the time to share your experience with {brand}. "
            f'We\'re really glad to hear it: "{summary}". Feedback like yours means a lot to us.'
        )
    elif kind == "apology":
        subject = f"We're sorry about your experience, {name}"
        middle = (
            f"Thank you for telling us about this, and I'm sorry we let you down. "
            f'We\'ve noted the problem you described ("{summary}") and shared it with the team '
            f"responsible. If you reply to this email with any extra details, we'll look into it."
        )
    else:
        subject = f"Thanks for your feedback, {name}"
        middle = (
            f"Thank you for sharing your feedback with {brand}. We've passed it on to the team."
        )
    body = f"Hi {name},\n\n{middle}\n\nBest regards,\n{signoff}"
    return EmailDraft(subject=subject, body=body)


class OfflineLLM:
    model_name = "offline:rule-based"

    async def structured(
        self, system: str, user: str, schema: type[T], *, hints: dict[str, Any] | None = None
    ) -> T:
        hints = hints or {}
        if schema is Classification:
            return classify(hints.get("text", ""), hints.get("rating"))  # type: ignore[return-value]
        if schema is EmailDraft:
            return draft(hints)  # type: ignore[return-value]
        raise TypeError(f"OfflineLLM cannot produce {schema.__name__}")
