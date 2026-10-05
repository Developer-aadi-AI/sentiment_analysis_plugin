"""Adapter interfaces: the only boundary between the core and a host app."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from review_responder.models import GeneratedResponse, ProcessResult, Review

REVIEW_FIELDS = ("id", "text", "rating", "customer_name", "customer_email", "created_at")


def map_record(record: dict[str, Any], field_map: dict[str, str], source: str) -> Review:
    """Map one host-app record into a `Review`.

    `field_map` is {internal_field: host_field}. Unmapped internal fields fall back to a host
    field of the same name. Every host field not used for a core field goes into `metadata`.
    """
    used: set[str] = set()
    data: dict[str, Any] = {"source": source}
    for field in REVIEW_FIELDS:
        host_key = field_map.get(field, field)
        if host_key in record:
            data[field] = record[host_key]
            used.add(host_key)
    data["metadata"] = {k: v for k, v in record.items() if k not in used}
    return Review.model_validate(data)


class FeedbackSource(ABC):
    """Reads reviews from a host app."""

    name: str = "base"

    @abstractmethod
    async def fetch_new(self) -> list[Review]:
        """Reviews not yet processed by this source's own bookkeeping (the core also dedupes)."""

    @abstractmethod
    async def get(self, review_id: str) -> Review | None: ...

    async def mark_processed(self, review_id: str, result: ProcessResult) -> None:
        """Write back to the host app, if it supports it. Default: no-op."""
        return None

    async def get_customer_context(self, review: Review) -> dict[str, Any]:
        """Safe, customer-facing context (order status, plan, allowed remedies…). Default: none.

        Only return data that may appear in an email. A key `allowed_commitments` (list[str])
        authorises the responder to mention those remedies (e.g. ["refund"])."""
        return {}


class ResponseSink(ABC):
    """Delivers a generated response through the host app's channel."""

    name: str = "base"

    @abstractmethod
    async def send(self, review: Review, response: GeneratedResponse) -> None: ...
