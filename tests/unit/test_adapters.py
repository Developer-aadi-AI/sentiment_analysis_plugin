"""Shared adapter contract suite. Every FeedbackSource must pass it; add new adapters to SOURCES."""

from __future__ import annotations

import csv
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from conftest import make_settings
from sqlalchemy import create_engine, text

from review_responder.adapters import SINKS, get_sink, get_source
from review_responder.adapters.file_source import FileSource
from review_responder.adapters.smtp_sink import SmtpSink
from review_responder.adapters.sql_source import SqlSource
from review_responder.adapters.webhook_source import WebhookSource
from review_responder.models import GeneratedResponse, ProcessResult, Review

# The same host-app data, in the host app's own field names.
RECORDS = [
    {
        "fid": "1",
        "comment": "Love it!",
        "stars": "5",
        "who": "Ann",
        "mail": "ann@example.com",
        "plan": "pro",
    },
    {
        "fid": "2",
        "comment": "Broken on arrival",
        "stars": "1",
        "who": "Ben",
        "mail": "ben@example.com",
        "plan": "free",
    },
]
FIELD_MAP = {
    "id": "fid",
    "text": "comment",
    "rating": "stars",
    "customer_name": "who",
    "customer_email": "mail",
}


def make_csv(tmp_path: Path):
    path = tmp_path / "f.csv"
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(RECORDS[0]))
        w.writeheader()
        w.writerows(RECORDS)
    return FileSource(str(path), FIELD_MAP, "csv-app")


def make_json(tmp_path: Path):
    path = tmp_path / "f.json"
    path.write_text(json.dumps({"reviews": RECORDS}), encoding="utf-8")
    return FileSource(str(path), FIELD_MAP, "json-app")


def make_sql(tmp_path: Path):
    url = f"sqlite:///{tmp_path / 'app.db'}"
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE feedback (fid TEXT, comment TEXT, stars INT, who TEXT, mail TEXT, "
                "plan TEXT, "
                "replied TEXT)"
            )
        )
        for r in RECORDS:
            conn.execute(
                text(
                    "INSERT INTO feedback (fid, comment, stars, who, mail, plan) "
                    "VALUES (:fid, :comment, :stars, :who, :mail, :plan)"
                ),
                r,
            )
    return SqlSource(
        url,
        "feedback",
        FIELD_MAP,
        "sql-app",
        processed_column="replied",
        context_query="SELECT plan FROM feedback WHERE fid = :review_id",
    )


def make_webhook(tmp_path: Path):
    source = WebhookSource(FIELD_MAP, "hook-app", secret=None)
    for r in RECORDS:
        source.push(r)
    return source


SOURCES = {"csv": make_csv, "json": make_json, "sql": make_sql, "webhook": make_webhook}


@pytest.fixture(params=sorted(SOURCES))
def source(request, tmp_path):
    return SOURCES[request.param](tmp_path)


async def test_contract_fetch_maps_fields(source):
    reviews = sorted(await source.fetch_new(), key=lambda r: r.id)
    assert [r.id for r in reviews] == ["1", "2"]
    first = reviews[0]
    assert isinstance(first, Review)
    assert first.text == "Love it!"
    assert first.rating == 5
    assert first.customer_name == "Ann"
    assert first.customer_email == "ann@example.com"
    assert first.metadata.get("plan") == "pro"


async def test_contract_get(source):
    await source.fetch_new()
    review = await source.get("2")
    assert review is not None and review.text == "Broken on arrival"
    assert await source.get("missing") is None


async def test_contract_mark_processed_and_context(source):
    review = (await source.fetch_new())[0]
    await source.mark_processed(review.id, ProcessResult(review_id=review.id, status="sent"))
    context = await source.get_customer_context(review)
    assert isinstance(context, dict)


async def test_sql_processed_column_filters_rows(tmp_path):
    source = make_sql(tmp_path)
    await source.mark_processed("1", ProcessResult(review_id="1", status="sent"))
    assert [r.id for r in await source.fetch_new()] == ["2"]
    assert await source.get_customer_context(Review(id="2", text="x")) == {"plan": "free"}


def test_sql_rejects_bad_identifiers(tmp_path):
    with pytest.raises(ValueError):
        SqlSource(f"sqlite:///{tmp_path / 'x.db'}", "feedback; DROP TABLE x", {}, "s")


def test_webhook_signature():
    source = WebhookSource({}, "app", secret="s3cret")
    body = b'{"id": "1", "text": "hi"}'
    sig = "sha256=" + hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    assert source.verify(body, sig)
    assert not source.verify(body, "sha256=bad")
    assert not source.verify(body, None)


async def test_webhook_fetch_drains_queue():
    source = make_webhook(Path("."))
    assert len(await source.fetch_new()) == 2
    assert await source.fetch_new() == []
    assert (await source.get("1")) is not None


def test_registry_selects_by_config(tmp_path):
    src = get_source(make_settings(adapter="json", source_file=str(tmp_path / "x.json")))
    assert isinstance(src, FileSource)
    with pytest.raises(ValueError):
        get_source(make_settings(adapter="nope"))
    assert set(SINKS) >= {"smtp", "console"}
    assert isinstance(get_sink(make_settings(sink="smtp")), SmtpSink)


def test_smtp_builds_message():
    sink = SmtpSink(make_settings(email_from="care@shop.com"))
    review = Review(id="9", text="x", customer_email="ann@example.com")
    msg = sink.build_message(
        review,
        GeneratedResponse(
            subject="Thanks!", body="Hi Ann", response_type="appreciation", model="m"
        ),
    )
    assert msg["To"] == "ann@example.com" and msg["From"] == "care@shop.com"
    assert msg["X-Review-Id"] == "9" and "Hi Ann" in msg.get_content()
    with pytest.raises(ValueError):
        sink.build_message(
            Review(id="1", text="x"),
            GeneratedResponse(subject="s", body="b", response_type="appreciation", model="m"),
        )
