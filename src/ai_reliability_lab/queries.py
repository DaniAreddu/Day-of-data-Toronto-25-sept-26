"""The on-screen SQL files in fabric/sql are the single source of every served query."""

from __future__ import annotations

from functools import cache

from .config import FABRIC_SQL_DIR

QUERY_NAMES = (
    "raw_answer",
    "platform_health",
    "governed_answer",
    "category_variance",
    "source_lineage",
    "pipeline_evidence",
    "quality_results",
)


@cache
def load_query(name: str) -> str:
    if name not in QUERY_NAMES:
        raise KeyError(f"Unknown query {name!r}")
    return (FABRIC_SQL_DIR / f"{name}.sql").read_text(encoding="utf-8")
