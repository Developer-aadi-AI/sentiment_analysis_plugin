# Review Responder

A pluggable add-on that attaches to any app, reads its customer reviews, and replies by email with a context-aware LLM response. It's built as a **LangGraph** workflow:

```
Host app ──► Adapter (source) ──► ingest → classify → route ─┬─ generate_appreciation ─┐
                                                             ├─ generate_apology ──────┼─► guard → deliver ──► Adapter (sink) ──► email
                                                             ├─ generate_acknowledgement┘
                                                             └─ hold (spam / empty / failed) ─────► deliver
```

Each review is classified on **sentiment, tone, urgency and issue type**. Phase 1 routes on sentiment only:

| Sentiment | Email |
|---|---|
| positive | **appreciation**: thanks the customer and references what they liked |
| negative, mixed, or neutral with a complaint | **apology**: names the specific problem and gives a next step |
| neutral | **acknowledgement** |
| empty / spam / abusive / unclassifiable | none; held for a human |

Tone, urgency and issue type are passed to the LLM as context.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate             # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -e ".[dev,anthropic]"  # or openai / groq / google / ollama
copy .env.example .env             # then set LLM_API_KEY etc.

# Try it with no API key: rule-based "offline" LLM, prints emails, sends nothing
review-responder run --provider offline

# With the real LLM from .env
review-responder run --dry-run
```

## Plugging into your app

The core never knows which app it's attached to. You choose an adapter with `ADAPTER` and map your field names with `SOURCE_FIELD_MAP`. You don't need to change any code.

| `ADAPTER` | Use when | Key settings |
|---|---|---|
| `csv` / `json` | Your app can export feedback to a file | `SOURCE_FILE` |
| `sql` | Feedback lives in a database table (Postgres, MySQL, SQLite…) | `SOURCE_DB_URL`, `SOURCE_TABLE`, optional `SOURCE_PROCESSED_COLUMN`, `SOURCE_CONTEXT_QUERY` |
| `webhook` | Your app can POST each new review | `WEBHOOK_SECRET`; run the API server |

**Field mapping.** `SOURCE_FIELD_MAP` maps internal fields to your column names. For example, if your table has `feedback_id, comment, stars, name, email`:

```
SOURCE_FIELD_MAP={"id":"feedback_id","text":"comment","rating":"stars","customer_name":"name","customer_email":"email"}
```

Any column you don't map is kept in `Review.metadata`.

**Customer context (optional).** The sql adapter's `SOURCE_CONTEXT_QUERY` can return safe facts the email may mention, such as order status or plan. If the context includes `allowed_commitments` (e.g. `refund`), the responder is allowed to mention that remedy. Without it, the guard blocks any email that promises refunds, discounts, compensation, replacements or timelines.

**Webhook.** With `ADAPTER=webhook`, run `uvicorn review_responder.api:app` and have your app POST JSON (one object or a list, in your own field names) to `/webhook/reviews`. If `WEBHOOK_SECRET` is set, the request must carry `X-Signature: sha256=<hex HMAC-SHA256 of the raw body>`.

**A new kind of app.** Write a class that implements `FeedbackSource` (`adapters/base.py`) and register it in `adapters/__init__.py`. The graph doesn't change.

## Safety model

The defaults are `DRY_RUN=true` and `AUTO_SEND=false`.

| `DRY_RUN` | `AUTO_SEND` | Behaviour |
|---|---|---|
| true | any | Classify and draft, print the result, send nothing, record nothing as final |
| false | false | Drafts are stored as `pending_approval`; send with `review-responder approve <id>` |
| false | true | Drafts that pass the guard are emailed automatically |

A draft is **held** for a human (never sent automatically) if any of these is true:

- classifier confidence is below `MIN_CONFIDENCE`
- the draft promises something not listed in `allowed_commitments`
- the draft contains links, email addresses, placeholders, or AI/internal wording
- the customer's name is missing from the greeting
- the draft is too long
- the email type doesn't match the sentiment

A review is never emailed twice. A SQLite store (`STATE_DB`) tracks processed IDs and claims each send atomically.

Logs redact email addresses and review text. The full data is kept only in the audit trail inside the store.

## Commands

```bash
review-responder run [--dry-run/--no-dry-run] [--limit N] [--provider offline] [--json]
review-responder replay <review_id>     # re-run one review (an already-sent email is never re-sent)
review-responder pending                # drafts awaiting approval or held
review-responder approve <review_id>    # send after human review (needs DRY_RUN=false)

uvicorn review_responder.api:app --reload
#   GET  /health
#   POST /webhook/reviews
#   POST /run   GET /pending   POST /reviews/{id}/approve   POST /reviews/{id}/replay
#   (admin endpoints need `Authorization: Bearer $ADMIN_TOKEN`, or localhost if unset)

pytest                                  # unit + graph tests, no network
pytest -m evals                         # real-LLM evals (needs an API key)
```

## Deployment

See [deploy/DEPLOY_ORACLE.md](deploy/DEPLOY_ORACLE.md) for an always-on, $0 setup on Oracle Cloud Always Free with Docker.

## LLM providers

All LLM calls go through `review_responder/llm.py`, which uses LangChain's `init_chat_model`. Set `LLM_PROVIDER` and `LLM_MODEL`, and install the matching extra:

| Provider | `LLM_PROVIDER` | Example `LLM_MODEL` | Extra |
|---|---|---|---|
| Anthropic (default) | `anthropic` | `claude-opus-5-5` | `.[anthropic]` |
| OpenAI | `openai` | `gpt-4o-mini` | `.[openai]` |
| Groq (free tier) | `groq` | `openai/gpt-oss-120b` | `.[groq]` |
| Google | `google_genai` | `gemini-2.5-flash` | `.[google]` |
| Ollama (local) | `ollama` | `llama3.1` | `.[ollama]` |
| None (rule-based demo) | `offline` | – | – |

Structured output uses native JSON-schema mode on Anthropic and OpenAI, and function calling on the others. Override with `LLM_STRUCTURED_METHOD`.
