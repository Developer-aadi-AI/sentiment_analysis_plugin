"""Responder: the public entry point that ties a source, sink, store and the graph together."""

from __future__ import annotations

import asyncio
import logging

from review_responder.adapters import get_sink, get_source
from review_responder.adapters.base import FeedbackSource, ResponseSink
from review_responder.config import Settings, get_settings
from review_responder.graph.build import build_graph
from review_responder.graph.state import Deps, audit
from review_responder.llm import LLMClient, get_llm
from review_responder.models import ProcessResult, Review
from review_responder.store import ProcessedStore

log = logging.getLogger(__name__)


class Responder:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm: LLMClient | None = None,
        source: FeedbackSource | None = None,
        sink: ResponseSink | None = None,
        store: ProcessedStore | None = None,
    ) -> None:
        settings = settings or get_settings()
        self.deps = Deps(
            llm=llm or get_llm(settings),
            source=source or get_source(settings),
            sink=sink or get_sink(settings),
            store=store or ProcessedStore(settings.state_db),
            settings=settings,
        )
        self.graph = build_graph(self.deps)
        self._run_lock = asyncio.Lock()

    @property
    def settings(self) -> Settings:
        return self.deps.settings

    async def process(self, review: Review, *, force: bool = False) -> ProcessResult:
        """Run one review through the graph. Already-processed reviews are skipped unless
        `force`; even then a review that was already emailed is never emailed again."""
        if not force and self.deps.store.is_done(review.id):
            return ProcessResult(
                review_id=review.id, status="skipped", reasons=["already processed"]
            )
        state = await self.graph.ainvoke({"review": review})
        return state["result"]

    def _needs_processing(self, review_id: str) -> bool:
        store = self.deps.store
        if store.is_done(review_id):
            return False
        # In dry-run, a review already drafted is not re-drafted on every run (that would spend
        # LLM credit for nothing). Once DRY_RUN=false it is processed for real.
        return not (self.settings.dry_run and store.status(review_id) == "dry_run")

    async def run_once(self, limit: int | None = None) -> list[ProcessResult]:
        async with self._run_lock:  # webhook, poller and /run never overlap
            reviews = await self.deps.source.fetch_new()
            todo = [r for r in reviews if self._needs_processing(r.id)]
            if limit is not None:
                todo = todo[:limit]
            log.info("fetched %d reviews, %d to process", len(reviews), len(todo))
            return [await self.process(r) for r in todo]

    async def replay(self, review_id: str) -> ProcessResult:
        review = await self.deps.source.get(review_id)
        if review is None:
            stored = self.deps.store.get(review_id)
            review = stored.review if stored else None
        if review is None:
            raise LookupError(f"review {review_id} not found")
        return await self.process(review, force=True)

    async def approve(self, review_id: str) -> ProcessResult:
        """Send a draft that is waiting for human approval (or was held and reviewed)."""
        stored = self.deps.store.get(review_id)
        if stored is None or stored.status not in ("pending_approval", "held"):
            raise LookupError(f"review {review_id} has no draft awaiting approval")
        if stored.response is None or stored.review is None:
            raise ValueError(f"review {review_id} has no draft to send")
        if not stored.review.customer_email:
            raise ValueError(f"review {review_id} has no customer email")
        if self.settings.dry_run:
            raise RuntimeError("DRY_RUN=true; set DRY_RUN=false to send approved emails")
        if not self.deps.store.claim_send(review_id):
            return stored.model_copy(update={"status": "skipped", "reasons": ["already sent"]})

        try:
            await self.deps.sink.send(stored.review, stored.response)
            result = stored.model_copy(update={"status": "sent", "reasons": ["approved by human"]})
        except Exception as exc:
            self.deps.store.save(stored, self.deps.store.get_audit(review_id))  # release claim
            raise RuntimeError(f"send failed: {type(exc).__name__}") from exc
        self.deps.store.save(
            result, self.deps.store.get_audit(review_id) + audit("approve", status="sent")
        )
        await self.deps.source.mark_processed(review_id, result)
        return result

    def pending(self) -> list[ProcessResult]:
        return self.deps.store.list_by_status("pending_approval") + self.deps.store.list_by_status(
            "held"
        )
