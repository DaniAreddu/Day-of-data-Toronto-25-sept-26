"""Pipeline-run and data-product-health records (no paid monitoring service required).

The same fields are written by the Fabric notebook, so the application, the SQL endpoint and
any enterprise alerting integration read one shared vocabulary.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from .backends.base import Backend
from .clock import parse_utc
from .medallion import OBSERVABILITY_SCHEMAS
from .queries import load_query

STATUSES = ("RUNNING", "BLOCKED", "FAILED", "READY")
SCENARIO_MODES = ("broken", "repaired")


@dataclass(frozen=True)
class PipelineRun:
    pipeline_run_id: str
    scenario_mode: str
    started_at_utc: datetime | None
    completed_at_utc: datetime | None
    status: str
    bronze_order_rows: int
    bronze_return_rows: int
    silver_sales_rows: int
    quarantined_rows: int
    duplicate_count: int
    missing_fx_count: int
    orphan_return_count: int
    freshness_minutes: int | None
    data_contract_version: str
    failure_reasons: list[str]
    warning_reasons: list[str]
    duration_ms: int


def new_run_id(started: datetime, scenario_mode: str) -> str:
    return f"run-{started:%Y%m%dT%H%M%SZ}-{scenario_mode}-{uuid.uuid4().hex[:6]}"


def create_table_ddl(table: str) -> str:
    columns = ", ".join(f"{name} {kind}" for name, kind in OBSERVABILITY_SCHEMAS[table])
    return f"CREATE TABLE IF NOT EXISTS {table} ({columns})"


def column_names(table: str) -> list[str]:
    return [name for name, _ in OBSERVABILITY_SCHEMAS[table]]


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(" | ") if part.strip()]


def row_to_run(row: dict) -> PipelineRun:
    return PipelineRun(
        pipeline_run_id=row["pipeline_run_id"],
        scenario_mode=row["scenario_mode"],
        started_at_utc=parse_utc(row["started_at_utc"]),
        completed_at_utc=parse_utc(row["completed_at_utc"]),
        status=row["status"],
        bronze_order_rows=int(row["bronze_order_rows"] or 0),
        bronze_return_rows=int(row["bronze_return_rows"] or 0),
        silver_sales_rows=int(row["silver_sales_rows"] or 0),
        quarantined_rows=int(row["quarantined_rows"] or 0),
        duplicate_count=int(row["duplicate_count"] or 0),
        missing_fx_count=int(row["missing_fx_count"] or 0),
        orphan_return_count=int(row["orphan_return_count"] or 0),
        freshness_minutes=row["freshness_minutes"],
        data_contract_version=row["data_contract_version"],
        failure_reasons=_split(row["failure_reasons"]),
        warning_reasons=_split(row["warning_reasons"]),
        duration_ms=int(row["duration_ms"] or 0),
    )


def list_runs(backend: Backend) -> list[PipelineRun]:
    return [row_to_run(row) for row in backend.query(load_query("pipeline_evidence"))]


def quality_results(backend: Backend) -> list[dict]:
    return backend.query(load_query("quality_results"))
