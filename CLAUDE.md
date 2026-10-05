# CLAUDE.md

Guidance for Claude when working in this repository.

## What this project is

**Review Responder** is a pluggable add-on that attaches to any existing app, reads its customer feedback/review data, and replies to each review with a context-aware, LLM-generated response.

It is built as a **LangGraph** workflow that:

1. Ingests a review from the host app (via an adapter).
2. Classifies it on four axes: **sentiment**, **tone**, **urgency**, **issue type**.
3. Routes it to the right response branch based on that classification.
4. Generates a response with an LLM, using the classification plus any customer/order context the host app exposes.
5. Delivers the response back through the host app's channel (email first).

The core never knows which app it is running against. Everything app-specific lives in an adapter.

## Current scope (Phase 1)

Phase 1 is deliberately narrow: **send an email based on sentiment.**

- **Positive** review → appreciation email (thank the customer, reference what they liked).
- **Negative** review → apology email (acknowledge the specific problem, state next step).
- **Neutral / mixed** → short acknowledgement email; if any negative issue is present, treat as negative.

Tone, urgency and issue type are still classified in Phase 1 and passed to the LLM as context, but they do **not** yet create separate routes. Do not build Phase 2+ features (escalation, ticket creation, multi-channel replies, public review-site replies) unless asked.

### Roadmap (for context only)

- Phase 2: urgency-based routing (high urgency → human escalation queue + holding reply).
- Phase 3: issue-type routing (billing, delivery, bug, product quality, support experience) with issue-specific prompts and actions.
- Phase 4: additional channels (in-app reply, public review platforms, Slack/ticketing).

## Architecture

```
Host app ──► Adapter (source) ──► LangGraph workflow ──► Adapter (sink) ──► Host app / email
                                       │
              ingest → classify → route → generate → guard → deliver
```

### Adapter layer (the "add-on" boundary)

The add-on connects to a host app through two small interfaces in `review_responder/adapters/base.py`:

- `FeedbackSource` — fetch new reviews (`fetch_new()`), fetch one (`get(review_id)`), mark processed (`mark_processed(review_id, result)`), optionally fetch customer context (`get_customer_context(review)`).
- `ResponseSink` — deliver a response (`send(review, response)`); for Phase 1 this is an email sender.

Rules:
- Every adapter maps the host app's data into the internal `Review` model. No host-specific fields leak past the adapter.
- Adapters are selected by config (`ADAPTER=...`), never by `if app == ...` branches in core code.
- Provide at least: `csv` / `json` file adapter (local dev), `webhook` adapter (host app POSTs reviews), `sql` adapter (read from a feedback table), and a `smtp` email sink.
- New host app = new adapter file + config entry. Core and graph code should not change.

### Internal models (`review_responder/models.py`)

Use Pydantic v2.

- `Review`: `id`, `source`, `text`, `rating` (optional), `customer_name`, `customer_email`, `created_at`, `metadata: dict`.
- `Classification`: `sentiment` (`positive|neutral|negative|mixed`), `tone` (e.g. `angry|frustrated|disappointed|calm|happy|enthusiastic|sarcastic`), `urgency` (`low|medium|high|critical`), `issue_type` (`none|billing|delivery|product_quality|bug|support_experience|feature_request|other`), `confidence: float`, `summary: str`.
- `GeneratedResponse`: `subject`, `body`, `response_type` (`appreciation|apology|acknowledgement`), `model`, `needs_human_review: bool`.

### LangGraph workflow (`review_responder/graph/`)

State is a single typed dict/Pydantic model (`ReviewState`) holding the `Review`, `Classification`, customer context, `GeneratedResponse`, errors and an audit trail.

Nodes, each in its own file under `graph/nodes/`:

| Node | Responsibility |
|---|---|
| `ingest` | Validate and normalise the incoming `Review`; load customer context from the source adapter. |
| `classify` | One LLM call with structured output returning a `Classification`. Use the star rating as a signal but let text win on conflict. |
| `route` | Conditional edge. Phase 1: `positive → appreciate`, `negative/mixed → apologize`, `neutral → acknowledge`. |
| `generate_appreciation` / `generate_apology` / `generate_acknowledgement` | Produce the email subject + body using the matching prompt template. |
| `guard` | Check the draft: no invented refunds/discounts/promises, no internal data, correct customer name, length limits, matches sentiment. Low classifier confidence or failed checks → `needs_human_review = True`. |
| `deliver` | Send via `ResponseSink` unless held for review or in dry-run; then `mark_processed`. |

Graph construction lives in `graph/build.py` (`build_graph() -> CompiledGraph`). Keep routing logic in pure functions so it can be unit-tested without an LLM.

### Prompts (`review_responder/prompts/`)

- One template per node, stored as files, not inline strings.
- Prompts receive: review text, classification, customer name, brand voice settings from config, and any safe customer context.
- Brand voice (company name, sign-off, tone guidelines, things never to promise) comes from config so each host app can customise it.

## Project layout

```
review_responder/
  adapters/        base.py, csv_source.py, webhook_source.py, sql_source.py, smtp_sink.py
  graph/           build.py, state.py, nodes/
  prompts/         classify.md, appreciation.md, apology.md, acknowledgement.md
  models.py
  config.py        settings via pydantic-settings
  llm.py           LLM client factory (provider-agnostic)
  api.py           FastAPI app: webhook ingest + manual trigger + health
  cli.py           run once over a source, dry-run, replay a review
tests/
  unit/            routing, guard, adapters, models
  graph/           graph runs with a fake LLM
  fixtures/        sample reviews (positive, negative, mixed, sarcastic, non-English)
```

## Tech stack

- Python 3.11+
- LangGraph + LangChain core for the workflow and structured LLM output
- Pydantic v2, pydantic-settings
- FastAPI (webhook/API mode), Typer (CLI)
- SMTP via `aiosmtplib` (or a transactional email provider behind the same `ResponseSink` interface)
- pytest, ruff, mypy

## Commands

```bash
uv sync                                   # install deps
uv run pytest                             # all tests
uv run pytest tests/unit                  # fast tests, no LLM
uv run ruff check . && uv run ruff format .
uv run mypy review_responder
uv run review-responder run --dry-run     # process new reviews, print emails, send nothing
uv run review-responder replay <review_id>
uv run uvicorn review_responder.api:app --reload
```

## Configuration

All settings come from environment variables (see `.env.example`). Never hard-code keys.

- `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`
- `ADAPTER` (source adapter name) and adapter-specific settings (`SOURCE_DB_URL`, `SOURCE_FILE`, `WEBHOOK_SECRET`)
- `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `EMAIL_FROM`
- `BRAND_NAME`, `BRAND_SIGNOFF`, `BRAND_VOICE`
- `DRY_RUN` (default `true`), `AUTO_SEND` (default `false`), `MIN_CONFIDENCE` (default `0.7`)

## Rules for working in this codebase

- **Safe by default.** `DRY_RUN=true` and `AUTO_SEND=false` are the defaults. Never change defaults so that emails go out automatically without an explicit config flag.
- **Never invent commitments.** Responses must not offer refunds, discounts, compensation, or timelines unless the host app's context explicitly provides them.
- **Idempotency.** A review must never get two emails. Check `mark_processed` / a processed-ID store before delivering.
- **PII.** Do not log full review text or email addresses at info level. Redact in logs; keep full data only in the audit trail.
- **Structured output.** Classification must use schema-validated structured output, with a retry on validation failure, then fall back to `needs_human_review`.
- **Provider-agnostic LLM.** Go through `llm.py`; do not import a specific provider SDK in nodes.
- **Tests without network.** Unit and graph tests use a fake LLM and fake adapters. Real-LLM evals go in `tests/evals/` and are opt-in (`-m evals`).
- **Adding an adapter:** implement the base interface, register it in `adapters/__init__.py`, add a fixture and a contract test that runs the shared adapter test suite.
- **Adding a route:** add the classification value, the routing case in `route`, a node + prompt, and tests for the routing function and the generated output shape.
- Type hints everywhere; keep nodes small and pure apart from I/O at the edges (`ingest`, `deliver`).

## Edge cases to handle

- Rating and text disagree (5 stars, angry text) → trust text, flag lower confidence.
- Sarcasm ("Great, arrived broken again") → negative.
- Mixed reviews → apology for the problem, brief thanks for the positives.
- Empty, spam, or abusive reviews → no email; mark for human review.
- Non-English reviews → reply in the review's language.
- Missing customer email → classify and draft, but skip delivery and log it.
