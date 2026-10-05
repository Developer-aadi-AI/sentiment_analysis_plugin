"""End-to-end graph runs with a fake LLM, fake source and fake sink. No network."""

from __future__ import annotations

from conftest import FakeLLM, FakeSink, cls

from review_responder.models import EmailDraft


async def test_positive_review_gets_appreciation(build, reviews):
    responder, source, sink, _ = build([reviews["pos-1"]], dry_run=False, auto_send=True)
    [result] = await responder.run_once()
    assert result.status == "sent", result.reasons
    assert result.response.response_type == "appreciation"
    assert "Priya" in result.response.body
    assert len(sink.sent) == 1
    assert source.marked["pos-1"].status == "sent"


async def test_negative_review_gets_apology(build, reviews):
    responder, _, sink, _ = build([reviews["neg-1"]], dry_run=False, auto_send=True)
    [result] = await responder.run_once()
    assert result.status == "sent", result.reasons
    assert result.response.response_type == "apology"
    assert "sorry" in result.response.body.lower()


async def test_mixed_and_sarcastic_get_apology(build, reviews):
    responder, _, _, _ = build([reviews["mixed-1"], reviews["sarcastic-1"]])
    results = {r.review_id: r for r in await responder.run_once()}
    assert results["mixed-1"].response.response_type == "apology"
    assert results["sarcastic-1"].classification.tone == "sarcastic"
    assert results["sarcastic-1"].response.response_type == "apology"


async def test_neutral_gets_acknowledgement(build, reviews):
    review = reviews["neutral-1"]
    llm = FakeLLM({review.text: cls("neutral", issue_type="none", tone="calm")})
    responder, _, _, _ = build([review], llm=llm)
    [result] = await responder.run_once()
    assert result.response.response_type == "acknowledgement"


async def test_dry_run_sends_nothing_and_stays_reprocessable(build, reviews):
    responder, source, sink, _ = build([reviews["pos-1"]])  # defaults: DRY_RUN=true
    [result] = await responder.run_once()
    assert result.status == "dry_run"
    assert result.reasons[0] == "would be: pending_approval"
    assert sink.sent == [] and source.marked == {}
    assert await responder.run_once() == []  # not re-drafted (no wasted LLM calls)
    responder.deps.settings.dry_run = False
    [real] = await responder.run_once()  # processed for real once dry-run is off
    assert real.status == "pending_approval"


async def test_default_real_run_waits_for_approval(build, reviews):
    responder, _, sink, _ = build([reviews["pos-1"]], dry_run=False)  # AUTO_SEND=false
    [result] = await responder.run_once()
    assert result.status == "pending_approval"
    assert sink.sent == []
    assert [p.review_id for p in responder.pending()] == ["pos-1"]

    approved = await responder.approve("pos-1")
    assert approved.status == "sent" and len(sink.sent) == 1
    assert responder.pending() == []


async def test_never_emails_twice(build, reviews):
    responder, _, sink, _ = build([reviews["neg-1"]], dry_run=False, auto_send=True)
    await responder.run_once()
    assert await responder.run_once() == []  # already processed
    replayed = await responder.replay("neg-1")  # forced re-run
    assert replayed.status == "skipped" and replayed.reasons == ["already sent"]
    assert len(sink.sent) == 1


async def test_empty_and_spam_reviews_are_held_without_email(build, reviews):
    spam = reviews["spam-1"]
    llm = FakeLLM({spam.text: cls("neutral", is_spam_or_abusive=True)})
    responder, _, sink, llm = build(
        [reviews["empty-1"], spam], llm=llm, dry_run=False, auto_send=True
    )
    results = {r.review_id: r for r in await responder.run_once()}
    assert results["empty-1"].status == "held" and "empty review" in results["empty-1"].reasons
    assert (
        results["spam-1"].status == "held" and "spam or abusive review" in results["spam-1"].reasons
    )
    assert results["empty-1"].response is None and results["spam-1"].response is None
    assert sink.sent == []
    assert "EmailDraft" not in llm.calls


async def test_missing_email_drafts_but_does_not_deliver(build, reviews):
    responder, _, sink, _ = build([reviews["noemail-1"]], dry_run=False, auto_send=True)
    [result] = await responder.run_once()
    assert result.status == "no_email"
    assert result.response is not None and result.response.response_type == "appreciation"
    assert sink.sent == []


async def test_rating_text_conflict_low_confidence_is_held(build, reviews):
    review = reviews["neg-1"].model_copy(update={"rating": 5})
    llm = FakeLLM({review.text: cls("negative", confidence=0.5)})
    responder, _, sink, _ = build([review], llm=llm, dry_run=False, auto_send=True)
    [result] = await responder.run_once()
    assert result.status == "held"
    assert result.response.needs_human_review
    assert any("low classifier confidence" in r for r in result.reasons)
    assert sink.sent == []


async def test_classifier_retries_then_succeeds(build, reviews):
    llm = FakeLLM(fail_classify=1)
    responder, _, _, llm = build([reviews["pos-1"]], llm=llm)
    [result] = await responder.run_once()
    assert result.classification is not None
    assert llm.calls.count("Classification") == 2


async def test_classifier_failure_falls_back_to_human_review(build, reviews):
    llm = FakeLLM(fail_classify=10)
    responder, _, sink, _ = build([reviews["pos-1"]], llm=llm, dry_run=False, auto_send=True)
    [result] = await responder.run_once()
    assert result.status == "held"
    assert "classification failed" in result.reasons
    assert sink.sent == []


async def test_guard_blocks_invented_refund(build, reviews):
    def promise(h):
        return EmailDraft(
            subject="Sorry",
            body=f"Hi {h['customer_name'].split()[0]},\n\nSo sorry! We will refund you "
            "in full.\n\nBest regards,\nThe Demo Shop Team",
        )

    responder, _, sink, _ = build(
        [reviews["neg-1"]], llm=FakeLLM(draft_fn=promise), dry_run=False, auto_send=True
    )
    [result] = await responder.run_once()
    assert result.status == "held"
    assert "uncommitted promise: refund" in result.reasons
    assert sink.sent == []


async def test_refund_allowed_when_host_context_authorises_it(build, reviews):
    def promise(h):
        return EmailDraft(
            subject="Sorry",
            body="Hi Rahul,\n\nSorry! Your refund has been issued."
            "\n\nBest regards,\nThe Demo Shop Team",
        )

    responder, _, sink, _ = build(
        [reviews["neg-1"]],
        llm=FakeLLM(draft_fn=promise),
        dry_run=False,
        auto_send=True,
        context={"allowed_commitments": ["refund"], "order_status": "refunded"},
    )
    [result] = await responder.run_once()
    assert result.status == "sent", result.reasons


async def test_send_failure_is_retryable(build, reviews):
    responder, _, sink, _ = build(
        [reviews["pos-1"]], sink=FakeSink(fail=True), dry_run=False, auto_send=True
    )
    [result] = await responder.run_once()
    assert result.status == "error"
    responder.deps.sink = FakeSink()  # SMTP back up
    [retry] = await responder.run_once()
    assert retry.status == "sent"


async def test_audit_trail_records_every_node(build, reviews):
    responder, _, _, _ = build([reviews["neg-1"]], dry_run=False)
    await responder.run_once()
    nodes = [e["node"] for e in responder.deps.store.get_audit("neg-1")]
    assert nodes == ["ingest", "classify", "generate_apology", "guard", "deliver"]
