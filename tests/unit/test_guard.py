import pytest
from conftest import cls, make_settings

from review_responder.graph.nodes.guard import check_draft
from review_responder.models import GeneratedResponse, Review

S = make_settings()
REVIEW = Review(
    id="1", text="Arrived broken", customer_name="Rahul Verma", customer_email="r@x.com"
)
GOOD_APOLOGY = (
    "Hi Rahul,\n\nI'm sorry your order arrived broken. We've shared this with our team. "
    "Reply with your order number and we'll look into it.\n\nBest regards,\nThe Demo Shop Team"
)


def resp(
    body: str = GOOD_APOLOGY, kind: str = "apology", subject: str = "We're sorry"
) -> GeneratedResponse:
    return GeneratedResponse(subject=subject, body=body, response_type=kind, model="m")


def test_clean_apology_passes():
    assert check_draft(resp(), REVIEW, cls("negative"), {}, S) == []


@pytest.mark.parametrize(
    ("extra", "failure"),
    [
        ("We will issue a full refund.", "uncommitted promise: refund"),
        ("Here is a 20% off coupon.", "uncommitted promise: discount"),
        ("You will hear from us within 2 days.", "uncommitted promise: timeline"),
        ("We'll send you a replacement.", "uncommitted promise: replacement"),
        ("Visit https://example.com/help.", "contains a link"),
        ("Contact jane.doe@internal.corp.", "contains an email address"),
        ("Regards, [Agent Name]", "contains a template placeholder"),
        ("Our sentiment model flagged this.", "mentions internal/AI details"),
    ],
)
def test_detects_unsafe_content(extra, failure):
    failures = check_draft(resp(GOOD_APOLOGY + "\n" + extra), REVIEW, cls("negative"), {}, S)
    assert failure in failures


def test_allowed_commitment_from_context_passes():
    body = GOOD_APOLOGY.replace("We've shared", "We've processed your refund and shared")
    ctx = {"allowed_commitments": ["refund"]}
    assert check_draft(resp(body), REVIEW, cls("negative"), ctx, S) == []
    assert "uncommitted promise: refund" in check_draft(resp(body), REVIEW, cls("negative"), {}, S)


def test_low_confidence_flagged():
    failures = check_draft(resp(), REVIEW, cls("negative", confidence=0.4), {}, S)
    assert any("low classifier confidence" in f for f in failures)


def test_missing_customer_name():
    body = GOOD_APOLOGY.replace("Hi Rahul", "Hi there")
    assert "customer name missing from greeting" in check_draft(
        resp(body), REVIEW, cls("negative"), {}, S
    )


def test_sentiment_mismatch():
    failures = check_draft(resp(kind="appreciation"), REVIEW, cls("negative"), {}, S)
    assert "response type appreciation does not match route" in failures
    assert "appreciation email apologises" in failures
    no_sorry = "Hi Rahul,\n\nThanks for your feedback.\n\nBest regards,\nThe Demo Shop Team"
    assert "apology email does not apologise" in check_draft(
        resp(no_sorry), REVIEW, cls("negative"), {}, S
    )


def test_apology_word_check_skipped_for_non_english():
    body = "Hola Rahul,\n\nLamentamos mucho lo ocurrido.\n\nSaludos,\nThe Demo Shop Team"
    assert check_draft(resp(body), REVIEW, cls("negative", language="es"), {}, S) == []


def test_length_limit():
    failures = check_draft(resp(GOOD_APOLOGY + "x" * 2000), REVIEW, cls("negative"), {}, S)
    assert any(f.startswith("body too long") for f in failures)


def test_sender_address_is_allowed():
    body = GOOD_APOLOGY + "\nYou can also write to support@example.com."
    assert check_draft(resp(body), REVIEW, cls("negative"), {}, S) == []
