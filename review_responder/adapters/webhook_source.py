"""Webhook source: the host app POSTs reviews to /webhook/reviews (see api.py)."""

from __future__ import annotations

import hashlib
import hmac
from collections import OrderedDict
from typing import Any

from review_responder.adapters.base import FeedbackSource, map_record
from review_responder.config import Settings
from review_responder.models import Review


class WebhookSource(FeedbackSource):
    """Holds pushed reviews in memory until they are fetched.

    Signature: the host app sends `X-Signature: sha256=<hex hmac of raw body with WEBHOOK_SECRET>`.
    """

    def __init__(self, field_map: dict[str, str], source_name: str, secret: str | None) -> None:
        self.field_map = field_map
        self.name = source_name
        self._secret = secret
        self._pending: OrderedDict[str, Review] = OrderedDict()
        self._seen: dict[str, Review] = {}

    @classmethod
    def from_settings(cls, settings: Settings) -> WebhookSource:
        secret = settings.webhook_secret.get_secret_value() if settings.webhook_secret else None
        return cls(settings.source_field_map, settings.source_name, secret)

    def verify(self, body: bytes, signature: str | None) -> bool:
        if not self._secret:
            return True
        if not signature:
            return False
        expected = hmac.new(self._secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(signature.removeprefix("sha256="), expected)

    def push(self, record: dict[str, Any]) -> Review:
        review = map_record(record, self.field_map, self.name)
        self._pending[review.id] = review
        self._seen[review.id] = review
        return review

    async def fetch_new(self) -> list[Review]:
        reviews = list(self._pending.values())
        self._pending.clear()
        return reviews

    async def get(self, review_id: str) -> Review | None:
        return self._seen.get(review_id)
