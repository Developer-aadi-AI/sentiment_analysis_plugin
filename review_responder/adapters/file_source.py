"""CSV / JSON file source, for local development and for apps that can export feedback."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from review_responder.adapters.base import FeedbackSource, map_record
from review_responder.config import Settings
from review_responder.models import Review


class FileSource(FeedbackSource):
    """Reads every record from the file each time; dedupe is handled by the core's store.

    JSON may be a list of objects, or an object with a `reviews` list.
    """

    def __init__(self, path: str, field_map: dict[str, str], source_name: str) -> None:
        self.path = Path(path)
        self.field_map = field_map
        self.name = source_name

    @classmethod
    def from_settings(cls, settings: Settings) -> FileSource:
        if not settings.source_file:
            raise ValueError("SOURCE_FILE must be set for the csv/json adapter")
        return cls(settings.source_file, settings.source_field_map, settings.source_name)

    def _records(self) -> list[dict[str, Any]]:
        if self.path.suffix.lower() == ".csv":
            with self.path.open(newline="", encoding="utf-8-sig") as f:
                return list(csv.DictReader(f))
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data = data.get("reviews", [])
        return list(data)

    async def fetch_new(self) -> list[Review]:
        return [map_record(r, self.field_map, self.name) for r in self._records()]

    async def get(self, review_id: str) -> Review | None:
        for review in await self.fetch_new():
            if review.id == review_id:
                return review
        return None
