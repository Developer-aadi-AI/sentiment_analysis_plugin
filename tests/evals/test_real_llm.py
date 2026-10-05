"""Real-LLM evals. Opt-in: `pytest -m evals` with LLM_PROVIDER / LLM_MODEL / LLM_API_KEY set.

They run the whole graph in dry-run mode against the fixture reviews and check the
classification and the email that would be sent.
"""

from __future__ import annotations

import pytest
from conftest import FakeSink, FakeSource, load_reviews

from review_responder.config import Settings
from review_responder.service import Responder
from review_responder.store import ProcessedStore

pytestmark = pytest.mark.evals

EXPECTED = {
    "pos-1": ("positive", "appreciation"),
    "neg-1": ("negative", "apology"),
    "mixed-1": ("mixed", "apology"),
    "sarcastic-1": ("negative", "apology"),
    "es-1": ("negative", "apology"),
}


@pytest.fixture(scope="module")
async def results():
    reviews = load_reviews()
    settings = Settings(
        dry_run=True,
        state_db=":memory:",
        brand_name="Demo Shop",
        brand_signoff="The Demo Shop Team",
    )
    responder = Responder(
        settings,
        source=FakeSource([reviews[k] for k in EXPECTED]),
        sink=FakeSink(),
        store=ProcessedStore(":memory:"),
    )
    return {r.review_id: r for r in await responder.run_once()}


@pytest.mark.parametrize("review_id", sorted(EXPECTED))
async def test_routing_and_guard(results, review_id):
    sentiment, kind = EXPECTED[review_id]
    r = results[review_id]
    assert r.classification is not None
    if review_id == "sarcastic-1":
        assert r.classification.sentiment in ("negative", "mixed")
    else:
        assert r.classification.sentiment == sentiment
    assert r.response is not None and r.response.response_type == kind
    guard_failures = [x for x in r.reasons[1:] if "confidence" not in x]
    assert guard_failures == [], guard_failures


async def test_replies_in_review_language(results):
    r = results["es-1"]
    assert r.classification.language == "es"
    assert any(w in r.response.body.lower() for w in ("lamentamos", "sentimos", "disculpa", "hola"))
