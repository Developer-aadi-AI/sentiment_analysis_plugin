"""Shared implementation of the three generate_* nodes."""

from __future__ import annotations

import json
import logging
from typing import Any

from review_responder import prompts
from review_responder.graph.state import Deps, ReviewState, audit
from review_responder.models import EmailDraft, GeneratedResponse, ResponseType

log = logging.getLogger(__name__)

TEMPLATE = {
    "appreciation": "appreciation",
    "apology": "apology",
    "acknowledgement": "acknowledgement",
}


def allowed_commitments(context: dict[str, Any]) -> list[str]:
    value = context.get("allowed_commitments") or []
    if isinstance(value, str):
        value = [v.strip() for v in value.split(",") if v.strip()]
    return [str(v) for v in value]


def make_generate(deps: Deps, response_type: ResponseType):
    async def generate(state: ReviewState) -> dict[str, Any]:
        review = state["review"]
        c = state["classification"]
        assert c is not None, "router only sends classified reviews here"
        context = state.get("customer_context") or {}
        s = deps.settings
        allowed = allowed_commitments(context)
        values = {
            "brand_name": s.brand_name,
            "brand_voice": s.brand_voice,
            "brand_signoff": s.brand_signoff,
            "never_promise": s.brand_never_promise,
            "allowed_commitments": ", ".join(allowed) if allowed else "none",
            "customer_name": review.customer_name or "unknown",
            "greeting_name": review.customer_name or "a friendly generic greeting, no name",
            "sentiment": c.sentiment,
            "tone": c.tone,
            "urgency": c.urgency,
            "issue_type": c.issue_type,
            "summary": c.summary,
            "language": c.language,
            "customer_context": json.dumps(context, default=str) if context else "none",
            "review_text": review.text,
        }
        system, user = prompts.render(TEMPLATE[response_type], **values)
        hints = {**values, "response_type": response_type, "customer_name": review.customer_name}

        attempts = s.llm_max_retries + 1
        last_error = ""
        for _ in range(attempts):
            try:
                draft = await deps.llm.structured(system, user, EmailDraft, hints=hints)
                response = GeneratedResponse(
                    subject=draft.subject.strip(),
                    body=draft.body.strip(),
                    response_type=response_type,
                    model=deps.llm.model_name,
                )
                return {
                    "response": response,
                    "audit": audit(f"generate_{response_type}", response=response.model_dump()),
                }
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                log.warning(
                    "generate_%s failed for %s: %s", response_type, review.id, type(exc).__name__
                )

        return {
            "response": None,
            "errors": [f"generation failed: {last_error}"],
            "hold_reasons": ["generation failed"],
            "audit": audit(f"generate_{response_type}", failed=last_error),
        }

    return generate
