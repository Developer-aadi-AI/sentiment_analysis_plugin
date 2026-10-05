"""classify: one structured LLM call → Classification, retried on validation failure."""

from __future__ import annotations

import logging
from typing import Any

from review_responder import prompts
from review_responder.graph.state import Deps, ReviewState, audit
from review_responder.models import Classification

log = logging.getLogger(__name__)


def make_classify(deps: Deps):
    async def classify(state: ReviewState) -> dict[str, Any]:
        review = state["review"]
        if not review.text:
            return {"classification": None, "audit": audit("classify", skipped="empty review")}

        system, user = prompts.render(
            "classify",
            brand_name=deps.settings.brand_name,
            rating=review.rating if review.rating is not None else "not given",
            review_text=review.text,
        )
        attempts = deps.settings.llm_max_retries + 1
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                result = await deps.llm.structured(
                    system,
                    user,
                    Classification,
                    hints={"text": review.text, "rating": review.rating},
                )
                return {
                    "classification": result,
                    "audit": audit(
                        "classify",
                        attempt=attempt,
                        model=deps.llm.model_name,
                        classification=result.model_dump(),
                    ),
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "classify attempt %d/%d failed for %s: %s",
                    attempt,
                    attempts,
                    review.id,
                    type(exc).__name__,
                )

        return {
            "classification": None,
            "errors": [f"classification failed: {last_error}"],
            "hold_reasons": ["classification failed"],
            "audit": audit("classify", failed=last_error),
        }

    return classify
