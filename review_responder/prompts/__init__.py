"""Prompt templates live as .md files next to this module. Placeholders use {name} syntax."""

from __future__ import annotations

from functools import cache
from importlib.resources import files
from typing import Any


@cache
def load(name: str) -> str:
    return (files(__package__) / f"{name}.md").read_text(encoding="utf-8")


def render(name: str, **values: Any) -> tuple[str, str]:
    """Return (system, user). Templates split the two with a line containing only `---user---`."""
    template = load(name)
    system, _, user = template.partition("\n---user---\n")
    return system.format_map(values).strip(), user.format_map(values).strip()
