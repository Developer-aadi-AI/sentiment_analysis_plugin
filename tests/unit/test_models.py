import pytest
from pydantic import ValidationError

from review_responder import redact
from review_responder.adapters.base import map_record
from review_responder.models import Classification, ProcessResult, Review
from review_responder.store import ProcessedStore


def test_map_record_uses_field_map_and_keeps_extras():
    record = {"feedback_id": 7, "comment": "Nice", "stars": "4", "email": "", "order_id": "O-1"}
    review = map_record(
        record,
        {"id": "feedback_id", "text": "comment", "rating": "stars", "customer_email": "email"},
        "shop",
    )
    assert review.id == "7"
    assert review.text == "Nice"
    assert review.rating == 4.0
    assert review.customer_email is None
    assert review.source == "shop"
    assert review.metadata == {"order_id": "O-1"}


def test_map_record_without_map_uses_same_names():
    review = map_record({"id": "a", "text": "hi", "customer_name": "Bo"}, {}, "x")
    assert (review.id, review.text, review.customer_name) == ("a", "hi", "Bo")


def test_review_handles_none_text_and_blank_rating():
    review = Review(id=1, text=None, rating="")
    assert review.text == "" and review.rating is None


def test_classification_rejects_unknown_labels():
    with pytest.raises(ValidationError):
        Classification(
            sentiment="furious",
            tone="angry",
            urgency="low",
            issue_type="none",
            confidence=0.9,
            summary="x",
        )
    with pytest.raises(ValidationError):
        Classification(
            sentiment="negative",
            tone="angry",
            urgency="low",
            issue_type="none",
            confidence=1.5,
            summary="x",
        )


def test_redaction():
    assert redact.email("priya.sharma@example.com") == "p***@example.com"
    assert "priya" not in redact.text("mail me at priya@example.com please, thanks a lot")
    assert redact.text("x" * 100).endswith("(100 chars)")


def test_store_claim_send_is_once_only():
    store = ProcessedStore(":memory:")
    assert store.claim_send("r1") is True
    assert store.claim_send("r1") is False
    store.save(ProcessResult(review_id="r1", status="sent"))
    assert store.claim_send("r1") is False
    assert store.is_done("r1")


def test_store_error_and_dry_run_are_not_final():
    store = ProcessedStore(":memory:")
    store.save(ProcessResult(review_id="a", status="error"))
    store.save(ProcessResult(review_id="b", status="dry_run"))
    assert not store.is_done("a") and not store.is_done("b")
    assert store.claim_send("a") is True
