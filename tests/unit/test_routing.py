import pytest
from conftest import cls

from review_responder.graph.nodes.route import route_review
from review_responder.models import Review

R = Review(id="1", text="some text")


@pytest.mark.parametrize(
    ("classification", "expected"),
    [
        (cls("positive"), "appreciate"),
        (cls("negative"), "apologize"),
        (cls("mixed"), "apologize"),
        (cls("neutral", issue_type="none"), "acknowledge"),
        (cls("neutral", issue_type="feature_request"), "acknowledge"),
        (cls("neutral", issue_type="billing"), "apologize"),
        (cls("neutral", issue_type="other"), "apologize"),
        (cls("positive", is_spam_or_abusive=True), "hold"),
        (None, "hold"),
    ],
)
def test_route(classification, expected):
    assert route_review(R, classification) == expected


def test_empty_text_holds_even_if_classified():
    assert route_review(Review(id="2", text="  "), cls("positive")) == "hold"
