from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from conftest import FakeLLM, FakeSink, make_settings
from fastapi.testclient import TestClient

from review_responder import api
from review_responder.adapters.webhook_source import WebhookSource
from review_responder.service import Responder
from review_responder.store import ProcessedStore


@pytest.fixture
def client(monkeypatch):
    settings = make_settings(
        adapter="webhook",
        webhook_secret="hook",
        admin_token="admin",
        dry_run=False,
        auto_send=True,
        source_field_map={"text": "comment", "customer_email": "email", "customer_name": "name"},
    )
    sink = FakeSink()
    responder = Responder(
        settings,
        llm=FakeLLM(),
        source=WebhookSource.from_settings(settings),
        sink=sink,
        store=ProcessedStore(":memory:"),
    )
    monkeypatch.setattr(api, "get_responder", lambda: responder)
    c = TestClient(api.app)
    c.sink = sink
    return c


def signed(payload) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    sig = hmac.new(b"hook", body, hashlib.sha256).hexdigest()
    return body, {"X-Signature": f"sha256={sig}", "Content-Type": "application/json"}


def test_health(client):
    assert client.get("/health").json()["adapter"] == "webhook"


def test_webhook_ingests_and_replies(client):
    body, headers = signed(
        {
            "id": "w1",
            "comment": "Love it, amazing quality!",
            "name": "Ann",
            "email": "ann@example.com",
        }
    )
    r = client.post("/webhook/reviews", content=body, headers=headers)
    assert r.status_code == 202 and r.json() == {"accepted": ["w1"]}
    assert len(client.sink.sent) == 1  # background task ran
    assert client.sink.sent[0][1].response_type == "appreciation"


def test_webhook_rejects_bad_signature(client):
    r = client.post(
        "/webhook/reviews", content=b'{"id": "x"}', headers={"X-Signature": "sha256=no"}
    )
    assert r.status_code == 401


def test_admin_endpoints_need_token(client):
    assert client.get("/pending").status_code == 401
    r = client.get("/pending", headers={"Authorization": "Bearer admin"})
    assert r.status_code == 200 and r.json() == []
