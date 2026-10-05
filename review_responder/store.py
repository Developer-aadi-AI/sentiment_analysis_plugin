"""Processed-review store: guarantees one email per review and keeps the audit trail.

SQLite via the stdlib, so it works with every adapter (including read-only host databases).
"""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from review_responder.models import ProcessResult

# Statuses that mean "done, never process automatically again".
FINAL_STATUSES = {"sent", "pending_approval", "held", "skipped", "no_email"}


class ProcessedStore:
    def __init__(self, path: str) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """CREATE TABLE IF NOT EXISTS processed (
                    review_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    audit_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )"""
            )
            self._conn.commit()

    def status(self, review_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM processed WHERE review_id = ?", (review_id,)
            ).fetchone()
        return row[0] if row else None

    def is_done(self, review_id: str) -> bool:
        return self.status(review_id) in FINAL_STATUSES

    def save(self, result: ProcessResult, audit: list[dict[str, Any]] | None = None) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO processed (review_id, status, result_json, audit_json, updated_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(review_id) DO UPDATE SET
                     status = excluded.status, result_json = excluded.result_json,
                     audit_json = excluded.audit_json, updated_at = excluded.updated_at""",
                (
                    result.review_id,
                    result.status,
                    result.model_dump_json(),
                    json.dumps(audit or [], default=str),
                    datetime.now(UTC).isoformat(),
                ),
            )
            self._conn.commit()

    def claim_send(self, review_id: str) -> bool:
        """Atomically reserve a review for sending. Returns False if it was already sent."""
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM processed WHERE review_id = ?", (review_id,)
            ).fetchone()
            if row and row[0] in ("sent", "sending"):
                return False
            self._conn.execute(
                """INSERT INTO processed (review_id, status, result_json, audit_json, updated_at)
                   VALUES (?, 'sending', '{}', '[]', ?)
                   ON CONFLICT(review_id) DO UPDATE SET status = 'sending',
                     updated_at = excluded.updated_at""",
                (review_id, datetime.now(UTC).isoformat()),
            )
            self._conn.commit()
        return True

    def get(self, review_id: str) -> ProcessResult | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT result_json FROM processed WHERE review_id = ?", (review_id,)
            ).fetchone()
        if not row or row[0] == "{}":
            return None
        return ProcessResult.model_validate_json(row[0])

    def get_audit(self, review_id: str) -> list[dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT audit_json FROM processed WHERE review_id = ?", (review_id,)
            ).fetchone()
        return json.loads(row[0]) if row else []

    def list_by_status(self, status: str) -> list[ProcessResult]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT result_json FROM processed WHERE status = ? ORDER BY updated_at",
                (status,),
            ).fetchall()
        return [ProcessResult.model_validate_json(r[0]) for r in rows if r[0] != "{}"]
