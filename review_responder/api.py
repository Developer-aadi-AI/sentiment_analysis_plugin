"""FastAPI app: webhook ingest, manual trigger, approvals, health.

Run with: uvicorn review_responder.api:app
"""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, Header, HTTPException, Request

from review_responder.adapters.webhook_source import WebhookSource
from review_responder.models import ProcessResult
from review_responder.service import Responder

log = logging.getLogger(__name__)


@lru_cache
def get_responder() -> Responder:
    return Responder()


async def poll_forever(responder: Responder, interval: int) -> None:
    while True:
        try:
            results = await responder.run_once()
            if results:
                log.info("poll processed %d reviews", len(results))
        except Exception as exc:  # keep polling; one bad run must not kill the server
            log.error("poll failed: %s", type(exc).__name__)
        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    fmt = "%(asctime)s %(levelname)s %(name)s: %(message)s"
    logging.basicConfig(level=logging.INFO, format=fmt)
    responder = get_responder()
    interval = responder.settings.poll_interval_seconds
    task = None
    if interval > 0 and responder.settings.adapter != "webhook":
        log.info("polling %s source every %ds", responder.settings.adapter, interval)
        task = asyncio.create_task(poll_forever(responder, interval))
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Review Responder", version="0.1.0", lifespan=lifespan)


def require_admin(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Admin endpoints need `Authorization: Bearer $ADMIN_TOKEN`. With no ADMIN_TOKEN set they
    are only reachable from localhost."""
    token = get_responder().settings.admin_token
    if token:
        given = (authorization or "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given, token.get_secret_value()):
            raise HTTPException(401, "invalid admin token")
    elif not request.client or request.client.host not in (
        "127.0.0.1",
        "::1",
        "localhost",
        "testclient",
    ):
        raise HTTPException(403, "set ADMIN_TOKEN to use admin endpoints remotely")


admin = [Depends(require_admin)]


@app.get("/health")
async def health() -> dict[str, Any]:
    s = get_responder().settings
    return {
        "status": "ok",
        "adapter": s.adapter,
        "sink": s.sink,
        "llm": f"{s.llm_provider}:{s.llm_model}",
        "dry_run": s.dry_run,
        "auto_send": s.auto_send,
    }


@app.post("/webhook/reviews", status_code=202)
async def webhook(
    request: Request,
    background: BackgroundTasks,
    x_signature: str | None = Header(default=None),
) -> dict[str, Any]:
    """Host app pushes one review object, or a list of them, in its own field names."""
    responder = get_responder()
    source = responder.deps.source
    if not isinstance(source, WebhookSource):
        raise HTTPException(409, "ADAPTER is not 'webhook'")
    body = await request.body()
    if not source.verify(body, x_signature):
        raise HTTPException(401, "invalid signature")
    try:
        payload = json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(400, "invalid JSON") from exc
    records = payload if isinstance(payload, list) else [payload]
    try:
        reviews = [source.push(r) for r in records]
    except Exception as exc:
        raise HTTPException(422, f"could not map review: {exc}") from exc
    background.add_task(responder.run_once)
    return {"accepted": [r.id for r in reviews]}


@app.post("/run", dependencies=admin)
async def run(limit: int | None = None) -> list[ProcessResult]:
    """Manually trigger processing of new reviews from the configured source."""
    return await get_responder().run_once(limit)


@app.post("/reviews/{review_id}/replay", dependencies=admin)
async def replay(review_id: str) -> ProcessResult:
    try:
        return await get_responder().replay(review_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@app.get("/pending", dependencies=admin)
async def pending() -> list[ProcessResult]:
    return get_responder().pending()


@app.post("/reviews/{review_id}/approve", dependencies=admin)
async def approve(review_id: str) -> ProcessResult:
    try:
        return await get_responder().approve(review_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc
