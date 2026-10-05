"""ingest: validate/normalise the review and load safe customer context."""

from __future__ import annotations

import logging
import re
from typing import Any

from review_responder.graph.state import Deps, ReviewState, audit

log = logging.getLogger(__name__)

_WS = re.compile(r"[ \t]+")


def make_ingest(deps: Deps):
    async def ingest(state: ReviewState) -> dict[str, Any]:
        review = state["review"]
        text = "\n".join(_WS.sub(" ", line).strip() for line in review.text.strip().splitlines())
        review = review.model_copy(update={"text": text})
        hold: list[str] = []
        if not text:
            hold.append("empty review")

        context: dict[str, Any] = {}
        try:
            context = await deps.source.get_customer_context(review) or {}
        except Exception as exc:  # context is optional; never fail the review over it
            log.warning("customer context lookup failed for %s: %s", review.id, type(exc).__name__)

        return {
            "review": review,
            "customer_context": context,
            "hold_reasons": hold,
            "audit": audit("ingest", review=review.model_dump(mode="json"), context=context),
        }

    return ingest
