from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any, TypeVar

import pytest
from pydantic import BaseModel

from review_responder.adapters.base import FeedbackSource, ResponseSink
from review_responder.config import Settings
from review_responder.llm_offline import OfflineLLM
from review_responder.models import (
    Classification,
    EmailDraft,
    GeneratedResponse,
    ProcessResult,
    Review,
)
from review_responder.service import Responder
from review_responder.store import ProcessedStore

FIXTURES = Path(__file__).parent / "fixtures"
T = TypeVar("T", bound=BaseModel)


def load_reviews() -> dict[str, Review]:
    data = json.loads((FIXTURES / "reviews.json").read_text(encoding="utf-8"))
    return {r["id"]: Review.model_validate(r) for r in data}


def cls(sentiment: str = "positive", **kw: Any) -> Classification:
    base: dict[str, Any] = dict(
        sentiment=sentiment,
        tone="happy" if sentiment == "positive" else "frustrated",
        urgency="low",
        issue_type="none" if sentiment == "positive" else "delivery",
        confidence=0.9,
        summary="Customer feedback.",
        language="en",
    )
    base.update(kw)
    return Classification(**base)


class FakeLLM:
    """Scripted fake. Defaults to the offline rule-based behaviour; override per review text."""

    model_name = "fake:test"

    def __init__(
        self,
        classifications: dict[str, Classification] | None = None,
        draft_fn: Callable[[dict[str, Any]], EmailDraft] | None = None,
        fail_classify: int = 0,
    ) -> None:
        self.classifications = classifications or {}
        self.draft_fn = draft_fn
        self.fail_classify = fail_classify
        self.calls: list[str] = []
        self._offline = OfflineLLM()

    async def structured(self, system: str, user: str, schema: type[T], *, hints=None) -> T:
        hints = hints or {}
        self.calls.append(schema.__name__)
        if schema is Classification:
            if self.fail_classify > 0:
                self.fail_classify -= 1
                Classification.model_validate({"sentiment": "furious"})  # raises ValidationError
            text = hints.get("text", "")
            if text in self.classifications:
                return self.classifications[text]  # type: ignore[return-value]
        if schema is EmailDraft and self.draft_fn:
            return self.draft_fn(hints)  # type: ignore[return-value]
        return await self._offline.structured(system, user, schema, hints=hints)


class FakeSource(FeedbackSource):
    name = "fake"

    def __init__(self, reviews: list[Review], context: dict[str, Any] | None = None) -> None:
        self.reviews = {r.id: r for r in reviews}
        self.context = context or {}
        self.marked: dict[str, ProcessResult] = {}

    async def fetch_new(self) -> list[Review]:
        return [r for r in self.reviews.values() if r.id not in self.marked]

    async def get(self, review_id: str) -> Review | None:
        return self.reviews.get(review_id)

    async def mark_processed(self, review_id: str, result: ProcessResult) -> None:
        self.marked[review_id] = result

    async def get_customer_context(self, review: Review) -> dict[str, Any]:
        return self.context


class FakeSink(ResponseSink):
    name = "fake"

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[tuple[Review, GeneratedResponse]] = []
        self.fail = fail

    async def send(self, review: Review, response: GeneratedResponse) -> None:
        if self.fail:
            raise ConnectionError("smtp down")
        self.sent.append((review, response))


def make_settings(**kw: Any) -> Settings:
    base: dict[str, Any] = dict(
        _env_file=None,
        brand_name="Demo Shop",
        brand_signoff="The Demo Shop Team",
        email_from="support@example.com",
        state_db=":memory:",
        llm_max_retries=1,
    )
    base.update(kw)
    return Settings(**base)


@pytest.fixture
def reviews() -> dict[str, Review]:
    return load_reviews()


@pytest.fixture
def build() -> Callable[..., tuple[Responder, FakeSource, FakeSink, FakeLLM]]:
    def _build(
        reviews: list[Review],
        *,
        llm: FakeLLM | None = None,
        sink: FakeSink | None = None,
        context: dict[str, Any] | None = None,
        **settings: Any,
    ):
        source = FakeSource(reviews, context)
        sink = sink or FakeSink()
        llm = llm or FakeLLM()
        s = make_settings(**settings)
        responder = Responder(
            s, llm=llm, source=source, sink=sink, store=ProcessedStore(":memory:")
        )
        return responder, source, sink, llm

    return _build
