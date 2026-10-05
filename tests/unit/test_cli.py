"""The CLI output used in public CI logs must never contain customer data."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from review_responder.cli import app

EXAMPLE_CSV = Path(__file__).parents[2] / "examples" / "feedback.csv"
FIELD_MAP = (
    '{"id":"feedback_id","text":"comment","rating":"stars",'
    '"customer_name":"name","customer_email":"email"}'
)


def test_quiet_run_has_no_customer_data_and_drafts_reads_store(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # no stray .env
    env = {
        "ADAPTER": "csv",
        "SOURCE_FILE": str(EXAMPLE_CSV),
        "SOURCE_FIELD_MAP": FIELD_MAP,
        "STATE_DB": str(tmp_path / "state.db"),
        "SINK": "console",
    }
    runner = CliRunner()
    result = runner.invoke(app, ["run", "--quiet", "--provider", "offline"], env=env)
    assert result.exit_code == 0, result.output
    assert "[1001] dry_run" in result.output
    for pii in ("@", "Priya", "Rahul", "headphones", "Subject:"):
        assert pii not in result.output

    drafts = runner.invoke(app, ["drafts", "--status", "dry_run"], env=env)
    assert drafts.exit_code == 0, drafts.output
    assert "priya@example.com" in drafts.output  # full detail only in the local view
