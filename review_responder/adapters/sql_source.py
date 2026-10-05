"""SQL source: reads a feedback table from any SQLAlchemy-supported database."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from sqlalchemy import create_engine, text

from review_responder.adapters.base import FeedbackSource, map_record
from review_responder.config import Settings
from review_responder.models import ProcessResult, Review

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


def _ident(name: str) -> str:
    if not _IDENT.match(name):
        raise ValueError(f"Invalid SQL identifier: {name!r}")
    return name


class SqlSource(FeedbackSource):
    """
    - SOURCE_TABLE: table (or view) holding feedback; columns mapped via SOURCE_FIELD_MAP.
    - SOURCE_PROCESSED_COLUMN (optional): nullable column we set to the result status. When set,
      only rows where it IS NULL are fetched. Leave unset for read-only access.
    - SOURCE_CONTEXT_QUERY (optional): SQL returning one row of safe customer context, with
      bind params :review_id and :customer_email.
    """

    def __init__(
        self,
        db_url: str,
        table: str,
        field_map: dict[str, str],
        source_name: str,
        processed_column: str | None = None,
        context_query: str | None = None,
    ) -> None:
        self.engine = create_engine(db_url)
        self.table = _ident(table)
        self.field_map = field_map
        self.name = source_name
        self.processed_column = _ident(processed_column) if processed_column else None
        self.context_query = context_query
        self.id_column = _ident(field_map.get("id", "id"))

    @classmethod
    def from_settings(cls, settings: Settings) -> SqlSource:
        if not settings.source_db_url:
            raise ValueError("SOURCE_DB_URL must be set for the sql adapter")
        return cls(
            settings.source_db_url,
            settings.source_table,
            settings.source_field_map,
            settings.source_name,
            settings.source_processed_column,
            settings.source_context_query,
        )

    def _query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            return [dict(r._mapping) for r in conn.execute(text(sql), params or {})]

    async def fetch_new(self) -> list[Review]:
        sql = f"SELECT * FROM {self.table}"
        if self.processed_column:
            sql += f" WHERE {self.processed_column} IS NULL"
        rows = await asyncio.to_thread(self._query, sql)
        return [map_record(r, self.field_map, self.name) for r in rows]

    async def get(self, review_id: str) -> Review | None:
        sql = f"SELECT * FROM {self.table} WHERE {self.id_column} = :id"
        rows = await asyncio.to_thread(self._query, sql, {"id": review_id})
        return map_record(rows[0], self.field_map, self.name) if rows else None

    async def mark_processed(self, review_id: str, result: ProcessResult) -> None:
        if not self.processed_column:
            return

        def _update() -> None:
            with self.engine.begin() as conn:
                conn.execute(
                    text(
                        f"UPDATE {self.table} SET {self.processed_column} = :status "
                        f"WHERE {self.id_column} = :id"
                    ),
                    {"status": result.status, "id": review_id},
                )

        await asyncio.to_thread(_update)

    async def get_customer_context(self, review: Review) -> dict[str, Any]:
        if not self.context_query:
            return {}
        rows = await asyncio.to_thread(
            self._query,
            self.context_query,
            {"review_id": review.id, "customer_email": review.customer_email},
        )
        return rows[0] if rows else {}
