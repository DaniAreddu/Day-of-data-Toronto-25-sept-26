"""Execute the real Fabric notebook source against a DuckDB-backed Spark stand-in.

This proves the notebook's control flow, contract handling, fail-closed behaviour and results
match the local pipeline. It does not prove Spark- or Delta-specific behaviour; that is
validated by running the notebook in Fabric (docs/fabric-setup.md).
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

import duckdb
import pytest

from ai_reliability_lab.config import SAMPLE_DATA_DIR

from .fake_spark import FakeSpark, install_pyspark_module

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fabric" / "notebooks" / "BuildTrustedLayer.py"


def code_cells() -> list[tuple[bool, str]]:
    spec = importlib.util.spec_from_file_location(
        "builder", ROOT / "scripts" / "build_fabric_notebook.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    cells = builder.parse_cells(SOURCE.read_text(encoding="utf-8"))
    return [
        ("parameters" in cell["tags"], "\n".join(cell["lines"]))
        for cell in cells
        if cell["kind"] == "code"
    ]


def run_notebook(con: duckdb.DuckDBPyConnection, scenario_mode: str) -> dict:
    """Run cells in order, injecting parameters after the parameters cell (like a pipeline)."""
    install_pyspark_module()
    namespace = {"spark": FakeSpark(con), "display": lambda *_: None, "__name__": "notebook"}
    for is_parameters, source in code_cells():
        exec(compile(source, str(SOURCE), "exec"), namespace)
        if is_parameters:
            namespace["scenario_mode"] = scenario_mode
            namespace["data_root"] = SAMPLE_DATA_DIR.as_posix()
    return namespace


def one(con, sql):
    return con.execute(sql).fetchone()


def test_notebook_broken_mode_fails_closed_with_evidence():
    con = duckdb.connect()
    with pytest.raises(RuntimeError, match="net_revenue_cad is BLOCKED"):
        run_notebook(con, "broken")
    status, reasons = one(con, "SELECT status, blocking_reasons FROM gold_data_product_health")
    assert status == "BLOCKED"
    assert (
        "RETURNS_FRESHNESS" in reasons and "MISSING_FX" in reasons and "ORPHAN_RETURNS" in reasons
    )
    assert one(con, "SELECT COUNT(*) FROM gold_fact_sales") == (0,)
    assert one(con, "SELECT status FROM gold_pipeline_runs") == ("BLOCKED",)


def test_notebook_repaired_mode_matches_the_local_pipeline(repaired_db, summary):
    con = duckdb.connect()
    with pytest.raises(RuntimeError):
        run_notebook(con, "broken")
    run_notebook(con, "repaired")  # idempotent rerun on top of the broken state

    assert one(con, "SELECT status FROM gold_data_product_health") == ("READY",)
    runs = con.execute("SELECT status FROM gold_pipeline_runs ORDER BY started_at_utc").fetchall()
    assert [r[0] for r in runs] == ["BLOCKED", "READY"]

    governed = (SAMPLE_DATA_DIR.parent / "fabric" / "sql" / "governed_answer.sql").read_text(
        encoding="utf-8"
    )
    net, target = one(
        con, f"SELECT net_revenue_cad, target_cad FROM ({governed.rstrip().rstrip(';')})"
    )
    assert net == Decimal(summary["invariants"]["ontario_governed_net_revenue_cad"])
    assert target == Decimal(summary["invariants"]["ontario_target_cad"])

    with duckdb.connect(str(repaired_db.path), read_only=True) as local:
        for table in ("silver_reconciled_sales", "silver_quarantine", "gold_dim_date"):
            columns = "* EXCLUDE (pipeline_run_id)" if table == "silver_quarantine" else "*"
            query = f"SELECT {columns} FROM {table} ORDER BY ALL"
            assert con.execute(query).fetchall() == local.execute(query).fetchall(), table
        fact = "SELECT * EXCLUDE (pipeline_run_id) FROM gold_fact_sales ORDER BY order_key"
        assert con.execute(fact).fetchall() == local.execute(fact).fetchall()
