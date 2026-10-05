"""deliver: send via the ResponseSink (or hold / dry-run), then record the outcome."""

from __future__ import annotations

import logging
from typing import Any

from review_responder import redact
from review_responder.graph.state import Deps, ReviewState, audit
from review_responder.models import ProcessResult

log = logging.getLogger(__name__)


def decide_status(state: ReviewState, *, dry_run: bool, auto_send: bool) -> tuple[str, list[str]]:
    """Pure decision: what should happen to this review. Returns (status, reasons)."""
    reasons = list(dict.fromkeys(state.get("hold_reasons") or []))
    response = state.get("response")
    review = state["review"]
    if response is None:
        status = "held"
        reasons = reasons or ["no response generated"]
    elif response.needs_human_review or reasons:
        status = "held"
    elif not review.customer_email:
        status, reasons = "no_email", ["missing customer email"]
    elif not auto_send:
        status = "pending_approval"
    else:
        status = "sent"
    if dry_run:
        return "dry_run", [f"would be: {status}", *reasons]
    return status, reasons


def make_deliver(deps: Deps):
    async def deliver(state: ReviewState) -> dict[str, Any]:
        review = state["review"]
        response = state.get("response")
        s = deps.settings
        status, reasons = decide_status(state, dry_run=s.dry_run, auto_send=s.auto_send)

        if status == "sent":
            assert response is not None
            if not deps.store.claim_send(review.id):
                status, reasons = "skipped", ["already sent"]
            else:
                try:
                    await deps.sink.send(review, response)
                except Exception as exc:
                    status, reasons = "error", [f"send failed: {type(exc).__name__}"]
                    log.error("send failed for review %s: %s", review.id, type(exc).__name__)

        if status == "no_email":
            log.info("review %s: no customer email; draft kept, not delivered", review.id)

        result = ProcessResult(
            review_id=review.id,
            review=review,
            status=status,  # type: ignore[arg-type]
            response=response,
            classification=state.get("classification"),
            reasons=reasons,
        )
        entry = audit("deliver", status=status, reasons=reasons)
        deps.store.save(result, (state.get("audit") or []) + entry)
        if status not in ("dry_run", "error", "skipped"):
            try:
                await deps.source.mark_processed(review.id, result)
            except Exception as exc:
                log.warning("mark_processed failed for %s: %s", review.id, type(exc).__name__)

        log.info(
            "review %s → %s (%s) to=%s reasons=%s",
            review.id,
            status,
            response.response_type if response else "-",
            redact.email(review.customer_email),
            reasons,
        )
        return {"result": result, "audit": entry}

    return deliver
