"""PII redaction for log lines. Full data lives only in the audit trail."""

from __future__ import annotations

import re

_EMAIL = re.compile(r"([A-Za-z0-9._%+-])[A-Za-z0-9._%+-]*@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def email(value: str | None) -> str:
    if not value:
        return "<none>"
    return _EMAIL.sub(r"\1***@\2", value)


def text(value: str | None, keep: int = 24) -> str:
    if not value:
        return "<empty>"
    value = _EMAIL.sub(r"\1***@\2", value)
    return value if len(value) <= keep else f"{value[:keep]}… ({len(value)} chars)"
