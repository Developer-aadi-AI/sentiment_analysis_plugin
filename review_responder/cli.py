"""CLI: run once over a source, dry-run, replay a review, approve held drafts."""

from __future__ import annotations

import asyncio
import json
import logging

import typer
from dotenv import load_dotenv

from review_responder.config import Settings
from review_responder.models import ProcessResult
from review_responder.service import Responder
from review_responder.store import ProcessedStore

app = typer.Typer(
    help="Review Responder: classify reviews and reply by email.", no_args_is_help=True
)


def _responder(dry_run: bool | None, provider: str | None) -> Responder:
    load_dotenv(override=False)  # export provider keys (ANTHROPIC_API_KEY, ...) to the SDKs
    overrides: dict[str, object] = {}
    if dry_run is not None:
        overrides["dry_run"] = dry_run
    if provider:
        overrides["llm_provider"] = provider
    return Responder(Settings(**overrides))  # type: ignore[arg-type]


def _store() -> ProcessedStore:
    """Read-only commands need only the state store, not an LLM or a source."""
    load_dotenv(override=False)
    return ProcessedStore(Settings().state_db)


def _print_quiet(result: ProcessResult) -> None:
    """One line, no customer data: safe for public CI logs."""
    c, r = result.classification, result.response
    typer.echo(
        f"[{result.review_id}] {result.status}"
        f" sentiment={c.sentiment if c else '-'} email={r.response_type if r else '-'}"
        f" reasons={'; '.join(result.reasons) or '-'}"
    )


def _print(result: ProcessResult, show_body: bool = True) -> None:
    c = result.classification
    typer.secho(f"\n[{result.review_id}] {result.status.upper()}", bold=True)
    if c:
        typer.echo(
            f"  sentiment={c.sentiment} tone={c.tone} urgency={c.urgency} "
            f"issue={c.issue_type} confidence={c.confidence:.2f} lang={c.language}"
        )
    if result.reasons:
        typer.echo(f"  reasons: {'; '.join(result.reasons)}")
    if result.response and show_body:
        r = result.response
        to = result.review.customer_email if result.review else None
        typer.echo(f"  type: {r.response_type}   to: {to or '-'}")
        typer.echo(f"  Subject: {r.subject}")
        typer.echo("  " + r.body.replace("\n", "\n  "))


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v")) -> None:
    logging.basicConfig(
        level=logging.INFO if verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )


@app.command()
def run(
    dry_run: bool | None = typer.Option(
        None, "--dry-run/--no-dry-run", help="Override DRY_RUN for this run."
    ),
    limit: int | None = typer.Option(None, help="Process at most N reviews."),
    provider: str | None = typer.Option(None, help="Override LLM_PROVIDER (e.g. offline)."),
    as_json: bool = typer.Option(False, "--json", help="Print results as JSON."),
    quiet: bool = typer.Option(
        False, "--quiet", "-q", help="One line per review, no customer data (for CI logs)."
    ),
) -> None:
    """Process new reviews from the configured source."""
    responder = _responder(dry_run, provider)
    results = asyncio.run(responder.run_once(limit))
    if as_json:
        typer.echo(json.dumps([r.model_dump(mode="json") for r in results], indent=2))
        return
    for r in results:
        if quiet:
            _print_quiet(r)
        else:
            _print(r)
    counts: dict[str, int] = {}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1
    typer.secho(f"\nprocessed {len(results)}: {counts}", fg=typer.colors.GREEN)


@app.command()
def replay(
    review_id: str,
    dry_run: bool | None = typer.Option(None, "--dry-run/--no-dry-run"),
    provider: str | None = typer.Option(None),
) -> None:
    """Re-run one review through the graph (never re-sends an already-sent email)."""
    _print(asyncio.run(_responder(dry_run, provider).replay(review_id)))


@app.command()
def pending() -> None:
    """List drafts awaiting approval or held for human review."""
    store = _store()
    items = store.list_by_status("pending_approval") + store.list_by_status("held")
    if not items:
        typer.echo("nothing pending")
    for r in items:
        _print(r)


@app.command()
def drafts(
    status: str | None = typer.Option(
        None, help="Only this status (dry_run, pending_approval, held, sent, ...)."
    ),
) -> None:
    """Show stored results and drafts from the state store."""
    items = _store().list_by_status(status)
    if not items:
        typer.echo("nothing stored")
    for r in items:
        _print(r)


@app.command()
def approve(review_id: str) -> None:
    """Send a pending/held draft after human review. Requires DRY_RUN=false."""
    _print(asyncio.run(_responder(None, None).approve(review_id)), show_body=False)


if __name__ == "__main__":
    app()
