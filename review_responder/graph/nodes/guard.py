"""guard: deterministic checks on the draft before anything can be sent."""

from __future__ import annotations

import re
from typing import Any

from review_responder.config import Settings
from review_responder.graph.nodes.generate import allowed_commitments
from review_responder.graph.nodes.route import route_review
from review_responder.graph.state import Deps, ReviewState, audit
from review_responder.models import Classification, GeneratedResponse, Review

# term → pattern. A term is allowed only if the host app put it in `allowed_commitments`.
COMMITMENT_PATTERNS: dict[str, re.Pattern[str]] = {
    "refund": re.compile(r"\brefund\w*|\bmoney back\b|\breimburs\w*", re.I),
    "discount": re.compile(
        r"\bdiscount\w*|\bcoupon\w*|\bvoucher\w*|\bpromo code\b|\b\d+\s?% off\b", re.I
    ),
    "compensation": re.compile(
        r"\bcompensat\w*|\bstore credit\b|\bgoodwill\b|\bfree of charge\b", re.I
    ),
    "replacement": re.compile(
        r"\b(send|ship)(ing)? (you )?a (new|replacement)\b|\breplacement\b", re.I
    ),
    "timeline": re.compile(
        r"\bwithin \d+\s?(hours?|days?|weeks?)\b|\b\d+\s?(business|working) days\b"
        r"|\bby (tomorrow|tonight|monday|tuesday|wednesday|thursday|friday)\b|\bguarantee\w*\b",
        re.I,
    ),
}
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_URL = re.compile(r"https?://|www\.", re.I)
_PLACEHOLDER = re.compile(r"\[[A-Za-z _]+\]|\{\{|\}\}|<[A-Za-z_ ]+>")
_INTERNAL = re.compile(
    r"\b(as an ai|language model|sentiment|classif\w+|confidence score|urgency|issue_type)\b", re.I
)
_APOLOGY = re.compile(r"\b(sorry|apologi[sz]e|apologies)\b", re.I)

ROUTE_TO_TYPE = {
    "appreciate": "appreciation",
    "apologize": "apology",
    "acknowledge": "acknowledgement",
}


def check_draft(
    response: GeneratedResponse,
    review: Review,
    classification: Classification,
    context: dict[str, Any],
    settings: Settings,
) -> list[str]:
    """Return a list of failed checks (empty = OK)."""
    failures: list[str] = []
    body, subject = response.body, response.subject
    text = f"{subject}\n{body}"

    if classification.confidence < settings.min_confidence:
        failures.append(f"low classifier confidence ({classification.confidence:.2f})")

    if not subject.strip() or not body.strip():
        failures.append("empty subject or body")
    if len(body) > settings.max_body_chars:
        failures.append(f"body too long ({len(body)} > {settings.max_body_chars})")
    if len(subject) > settings.max_subject_chars:
        failures.append(f"subject too long ({len(subject)} > {settings.max_subject_chars})")

    allowed = " ".join(allowed_commitments(context)).lower()
    for term, pattern in COMMITMENT_PATTERNS.items():
        if term not in allowed and pattern.search(text):
            failures.append(f"uncommitted promise: {term}")

    other_emails = {e for e in _EMAIL.findall(text) if e.lower() != settings.email_from.lower()}
    if other_emails:
        failures.append("contains an email address")
    if _URL.search(text):
        failures.append("contains a link")
    if _PLACEHOLDER.search(text):
        failures.append("contains a template placeholder")
    if _INTERNAL.search(text):
        failures.append("mentions internal/AI details")

    if review.customer_name:
        first = review.customer_name.split()[0]
        if first.lower() not in body.lower():
            failures.append("customer name missing from greeting")

    expected = ROUTE_TO_TYPE.get(route_review(review, classification))
    if expected != response.response_type:
        failures.append(f"response type {response.response_type} does not match route")
    if classification.language == "en":
        if response.response_type == "apology" and not _APOLOGY.search(body):
            failures.append("apology email does not apologise")
        if response.response_type == "appreciation" and _APOLOGY.search(body):
            failures.append("appreciation email apologises")

    return failures


def make_guard(deps: Deps):
    async def guard(state: ReviewState) -> dict[str, Any]:
        response = state.get("response")
        classification = state.get("classification")
        if response is None or classification is None:
            return {"audit": audit("guard", skipped="nothing to check")}
        failures = check_draft(
            response,
            state["review"],
            classification,
            state.get("customer_context") or {},
            deps.settings,
        )
        if failures:
            response = response.model_copy(update={"needs_human_review": True})
        return {
            "response": response,
            "hold_reasons": failures,
            "audit": audit("guard", failures=failures),
        }

    return guard
