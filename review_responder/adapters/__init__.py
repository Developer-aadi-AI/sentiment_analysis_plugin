"""Adapter registry. A new host app = a new adapter file + an entry here; the core never changes."""

from __future__ import annotations

from collections.abc import Callable

from review_responder.adapters.base import FeedbackSource, ResponseSink, map_record
from review_responder.adapters.file_source import FileSource
from review_responder.adapters.smtp_sink import ConsoleSink, SmtpSink
from review_responder.adapters.sql_source import SqlSource
from review_responder.adapters.webhook_source import WebhookSource
from review_responder.config import Settings

SOURCES: dict[str, Callable[[Settings], FeedbackSource]] = {
    "csv": FileSource.from_settings,
    "json": FileSource.from_settings,
    "webhook": WebhookSource.from_settings,
    "sql": SqlSource.from_settings,
}

SINKS: dict[str, Callable[[Settings], ResponseSink]] = {
    "smtp": SmtpSink.from_settings,
    "console": ConsoleSink.from_settings,
}


def get_source(settings: Settings) -> FeedbackSource:
    try:
        return SOURCES[settings.adapter](settings)
    except KeyError:
        choices = sorted(SOURCES)
        raise ValueError(f"Unknown ADAPTER {settings.adapter!r}; choose from {choices}") from None


def get_sink(settings: Settings) -> ResponseSink:
    try:
        return SINKS[settings.sink](settings)
    except KeyError:
        raise ValueError(f"Unknown SINK {settings.sink!r}; choose from {sorted(SINKS)}") from None


__all__ = [
    "FeedbackSource",
    "ResponseSink",
    "map_record",
    "get_source",
    "get_sink",
    "SOURCES",
    "SINKS",
]
