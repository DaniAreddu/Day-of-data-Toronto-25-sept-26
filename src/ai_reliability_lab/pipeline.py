"""The governed pipeline, executed locally with DuckDB.

Bronze (as received) -> Silver (technical correctness) -> quality gates -> Gold (published only
when every blocking check passes) -> health and run records. The transforms and checks are the
same statements the Fabric notebook runs.

Reset = run in ``broken`` mode on a freshly created database. Repair = run in ``repaired``
mode. Both are idempotent: rerunning them produces the same data and health state.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import duckdb

from .backends.duckdb import DuckDBBackend
from .clock import DEMO_CLOCK_UTC, wall_clock_utc
from .config import SAMPLE_DATA_DIR
from .contracts import HealthContract, health_contract
from .medallion import (
    BRONZE_SOURCES,
    GOLD_DIMENSION_TRANSFORMS,
    GOLD_FACT_TRANSFORMS,
    SILVER_TRANSFORMS,
)
from .models import DATA_PRODUCT
from .observability import (
    SCENARIO_MODES,
    PipelineRun,
    column_names,
    create_table_ddl,
    new_run_id,
    row_to_run,
)
from .quality import format_sql, run_quality_checks, summarise_health


class PipelineFailed(RuntimeError):
    """The pipeline itself failed (as opposed to finishing BLOCKED)."""


@dataclass(frozen=True)
class PipelineResult:
    run: PipelineRun
    quality_results: list[dict]


def pipeline_params(contract: HealthContract, run_id: str, scenario_mode: str) -> dict:
    return {
        "run_id": run_id,
        "scenario_mode": scenario_mode,
        "accepted_currencies": list(contract.accepted_currencies),
        "orders_freshness_sla_minutes": contract.orders_freshness_sla_minutes,
        "returns_freshness_sla_minutes": contract.returns_freshness_sla_minutes,
        "max_category_return_rate_pct": contract.max_category_return_rate_pct,
        "volume_anomaly_factor": contract.volume_anomaly_factor,
    }


def _naive_utc(value: datetime | None) -> datetime | None:
    return None if value is None else value.replace(tzinfo=None)


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def load_bronze(con: duckdb.DuckDBPyConnection, inputs_dir: Path, scenario_mode: str) -> None:
    for source in BRONZE_SOURCES:
        relative = source["path"].format(scenario_mode=scenario_mode)
        path = inputs_dir / relative
        if not path.is_file():
            raise FileNotFoundError(f"Missing source extract {path}")
        columns = ", ".join(f"{_quote(name)}: {_quote(kind)}" for name, kind in source["columns"])
        lineage = ""
        if "source_system" not in {name for name, _ in source["columns"]}:
            lineage = f", {_quote(source['source_system'])} AS source_system"
        con.execute(
            f"CREATE OR REPLACE TABLE {source['table']} AS "
            f"SELECT *{lineage}, {_quote(relative)} AS source_file "
            f"FROM read_csv({_quote(path.as_posix())}, header = true, columns = {{{columns}}})"
        )


def _create(con: duckdb.DuckDBPyConnection, table: str, sql: str, *, publish: bool = True) -> None:
    body = sql if publish else f"SELECT * FROM ({sql}) AS unpublished WHERE 1 = 0"
    con.execute(f"CREATE OR REPLACE TABLE {table} AS {body}")


def _scalar(con: duckdb.DuckDBPyConnection, sql: str):
    row = con.execute(sql).fetchone()
    return None if row is None else row[0]


def _insert(con: duckdb.DuckDBPyConnection, table: str, record: dict) -> None:
    names = column_names(table)
    placeholders = ", ".join("?" for _ in names)
    con.execute(
        f"INSERT INTO {table} ({', '.join(names)}) VALUES ({placeholders})",
        [record.get(name) for name in names],
    )


def _write_health(con: duckdb.DuckDBPyConnection, record: dict) -> None:
    con.execute("DELETE FROM gold_data_product_health WHERE data_product = ?", [DATA_PRODUCT])
    _insert(con, "gold_data_product_health", record)


def _update_run(con: duckdb.DuckDBPyConnection, run_id: str, fields: dict) -> None:
    assignments = ", ".join(f"{name} = ?" for name in fields)
    con.execute(
        f"UPDATE gold_pipeline_runs SET {assignments} WHERE pipeline_run_id = ?",
        [*fields.values(), run_id],
    )


def _last_success(con: duckdb.DuckDBPyConnection) -> datetime | None:
    return _scalar(
        con, "SELECT MAX(completed_at_utc) FROM gold_pipeline_runs WHERE status = 'READY'"
    )


def run_pipeline(
    backend: DuckDBBackend,
    scenario_mode: str,
    *,
    inputs_dir: Path = SAMPLE_DATA_DIR,
    as_of: datetime = DEMO_CLOCK_UTC,
    reset: bool = False,
) -> PipelineResult:
    if scenario_mode not in SCENARIO_MODES:
        raise ValueError(f"scenario_mode must be one of {SCENARIO_MODES}, not {scenario_mode!r}")
    if reset:
        backend.delete()

    contract = health_contract()
    started = wall_clock_utc()
    clock_start = time.perf_counter()
    run_id = new_run_id(started, scenario_mode)
    params = pipeline_params(contract, run_id, scenario_mode)
    severities = {check.name: check.severity for check in contract.checks}
    health_base = {
        "data_product": DATA_PRODUCT,
        "data_contract_version": contract.version,
        "scenario_mode": scenario_mode,
        "as_of_utc": _naive_utc(as_of),
        "freshness_sla_minutes": contract.returns_freshness_sla_minutes,
        "pipeline_run_id": run_id,
    }

    with backend.connect() as con:
        for table in ("silver_quality_results", "gold_data_product_health", "gold_pipeline_runs"):
            con.execute(create_table_ddl(table))
        previous_success = _last_success(con)
        _insert(
            con,
            "gold_pipeline_runs",
            {
                "pipeline_run_id": run_id,
                "scenario_mode": scenario_mode,
                "started_at_utc": _naive_utc(started),
                "status": "RUNNING",
                "data_contract_version": contract.version,
            },
        )
        _write_health(
            con,
            {
                **health_base,
                "status": "RUNNING",
                "last_successful_refresh_utc": previous_success,
                "evaluated_at_utc": _naive_utc(started),
            },
        )

        try:
            con.begin()
            load_bronze(con, inputs_dir, scenario_mode)
            for table, sql in SILVER_TRANSFORMS + GOLD_DIMENSION_TRANSFORMS:
                _create(con, table, format_sql(sql, params))
            results = run_quality_checks(lambda sql: _scalar(con, sql), params, severities, as_of)
            health = summarise_health(results)
            publish = health["status"] == "READY"
            for table, sql in GOLD_FACT_TRANSFORMS:
                _create(con, table, format_sql(sql, params), publish=publish)
            evaluated = wall_clock_utc()
            for result in results:
                _insert(
                    con,
                    "silver_quality_results",
                    {
                        **result,
                        "pipeline_run_id": run_id,
                        "evaluated_at_utc": _naive_utc(evaluated),
                    },
                )
            counts = {
                "bronze_order_rows": _scalar(con, "SELECT COUNT(*) FROM bronze_orders"),
                "bronze_return_rows": _scalar(con, "SELECT COUNT(*) FROM bronze_returns"),
                "silver_sales_rows": _scalar(con, "SELECT COUNT(*) FROM silver_reconciled_sales"),
            }
            con.commit()
        except Exception as exc:
            con.rollback()
            reason = f"PIPELINE_ERROR: {type(exc).__name__}: {exc}"
            completed = wall_clock_utc()
            _update_run(
                con,
                run_id,
                {
                    "status": "FAILED",
                    "completed_at_utc": _naive_utc(completed),
                    "failure_reasons": reason,
                    "duration_ms": int((time.perf_counter() - clock_start) * 1000),
                },
            )
            _write_health(
                con,
                {
                    **health_base,
                    "status": "FAILED",
                    "blocking_reasons": reason,
                    "last_successful_refresh_utc": previous_success,
                    "evaluated_at_utc": _naive_utc(completed),
                },
            )
            raise PipelineFailed(reason) from exc

        completed = wall_clock_utc()
        freshness = [
            m
            for m in (health["orders_freshness_minutes"], health["returns_freshness_minutes"])
            if m is not None
        ]
        _update_run(
            con,
            run_id,
            {
                "status": health["status"],
                "completed_at_utc": _naive_utc(completed),
                **counts,
                "quarantined_rows": health["quarantined_rows"],
                "duplicate_count": health["duplicate_count"],
                "missing_fx_count": health["missing_fx_count"],
                "orphan_return_count": health["orphan_return_count"],
                "freshness_minutes": max(freshness) if freshness else None,
                "failure_reasons": health["blocking_reasons"],
                "warning_reasons": health["warning_reasons"],
                "duration_ms": int((time.perf_counter() - clock_start) * 1000),
            },
        )
        last_success = _naive_utc(completed) if publish else previous_success
        _write_health(
            con,
            {
                **health_base,
                **health,
                "last_successful_refresh_utc": last_success,
                "evaluated_at_utc": _naive_utc(completed),
            },
        )
        cursor = con.execute("SELECT * FROM gold_pipeline_runs WHERE pipeline_run_id = ?", [run_id])
        names = [d[0] for d in cursor.description]
        run = row_to_run(dict(zip(names, cursor.fetchone(), strict=True)))

    return PipelineResult(run=run, quality_results=results)


def reset_broken_scenario(backend: DuckDBBackend, **kwargs) -> PipelineResult:
    """Recreate the working database from the canonical broken extracts."""
    return run_pipeline(backend, "broken", reset=True, **kwargs)


def run_governed_pipeline(backend: DuckDBBackend, **kwargs) -> PipelineResult:
    """Ingest the repaired extracts and rebuild Silver and Gold."""
    return run_pipeline(backend, "repaired", **kwargs)
