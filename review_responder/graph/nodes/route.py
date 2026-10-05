"""Routing: pure functions, unit-testable without an LLM."""

from __future__ import annotations

from typing import Literal

from review_responder.models import Classification, Review

Route = Literal["appreciate", "apologize", "acknowledge", "hold"]

# Issue types that count as "a negative issue is present" for neutral reviews.
NEGATIVE_ISSUES = {"billing", "delivery", "product_quality", "bug", "support_experience", "other"}


def route_review(review: Review, classification: Classification | None) -> Route:
    """Phase 1: route on sentiment only.

    positive → appreciate; negative/mixed → apologize; neutral → acknowledge, unless a negative
    issue is present, in which case apologize. Empty/spam/abusive or unclassified → hold (no email).
    """
    if classification is None or not review.text.strip():
        return "hold"
    if classification.is_spam_or_abusive:
        return "hold"
    if classification.sentiment == "positive":
        return "appreciate"
    if classification.sentiment in ("negative", "mixed"):
        return "apologize"
    if classification.issue_type in NEGATIVE_ISSUES:
        return "apologize"
    return "acknowledge"
