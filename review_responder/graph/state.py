"""Graph state and the dependencies injected into nodes."""

from __future__ import annotations

import operator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated, Any, TypedDict

from review_responder.adapters.base import FeedbackSource, ResponseSink
from review_responder.config import Settings
from review_responder.llm import LLMClient
from review_responder.models import Classification, GeneratedResponse, ProcessResult, Review
from review_responder.store import ProcessedStore


class ReviewState(TypedDict, total=False):
    review: Review
    customer_context: dict[str, Any]
    classification: Classification | None
    response: GeneratedResponse | None
    hold_reasons: Annotated[list[str], operator.add]
    errors: Annotated[list[str], operator.add]
    audit: Annotated[list[dict[str, Any]], operator.add]
    result: ProcessResult


@dataclass
class Deps:
    llm: LLMClient
    source: FeedbackSource
    sink: ResponseSink
    store: ProcessedStore
    settings: Settings


def audit(node: str, **data: Any) -> list[dict[str, Any]]:
    """One audit-trail entry (full data allowed here; it is never logged)."""
    return [{"node": node, "at": datetime.now(UTC).isoformat(), **data}]
