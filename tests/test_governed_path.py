"""Governed-path behaviour: fail closed while unhealthy, trusted answer after repair."""

from __future__ import annotations

import csv
import dataclasses
from decimal import Decimal

import duckdb
import pytest

from ai_reliability_lab.config import SAMPLE_DATA_DIR
from ai_reliability_lab.governed_path import (
    DataProductNotReady,
    ask_governed,
    query_governed_facts,
    read_health,
)
from ai_reliability_lab.models import GovernedAnswer, Refusal
from ai_reliability_lab.observability import list_runs
from ai_reliability_lab.pipeline import reset_broken_scenario, run_governed_pipeline
from ai_reliability_lab.queries import load_query


def rows(backend, sql):
    with duckdb.connect(str(backend.path), read_only=True) as con:
        cursor = con.execute(sql)
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, r, strict=True)) for r in cursor.fetchall()]


def test_governed_path_refuses_while_not_ready(broken_db):
    result = ask_governed(broken_db)
    assert isinstance(result, Refusal)
    assert result.health.status == "BLOCKED"
    assert result.message.startswith("I cannot provide a reliable answer because")
    assert "returns feed is stale" in result.message
    assert "currency conversion coverage is incomplete" in result.message
    assert "unknown order" in result.message
    assert "duplicate order event" in result.message  # detected, reported as non-blocking
    assert len(result.reasons) == 3


def test_health_exposes_required_evidence_before_repair(broken_db, summary):
    health = read_health(broken_db)
    inv = summary["invariants"]
    assert health.freshness_sla_minutes == 240
    assert health.returns_freshness_minutes == inv["broken_returns_freshness_minutes"] > 240
    assert health.duplicate_count == 1
    assert health.missing_fx_count == inv["broken_missing_fx_order_count"] > 0
    assert health.orphan_return_count == 1
    assert health.quarantined_rows == 1
    assert health.data_contract_version == "1.0.0"
    assert health.pipeline_run_id.startswith("run-")
    assert health.last_successful_refresh_utc is None


def test_the_application_cannot_bypass_the_quality_gate(broken_db):
    health = read_health(broken_db)
    with pytest.raises(DataProductNotReady):
        query_governed_facts(broken_db, health)
    # Forging a READY health object in application code still fails: the SQL gate holds.
    forged = dataclasses.replace(health, status="READY")
    with pytest.raises(DataProductNotReady):
        query_governed_facts(broken_db, forged)
    assert rows(broken_db, load_query("governed_answer")) == []
    assert rows(broken_db, load_query("category_variance")) == []
    assert rows(broken_db, "SELECT COUNT(*) AS n FROM gold_fact_sales") == [{"n": 0}]


@pytest.mark.parametrize("status", ["RUNNING", "FAILED", "BLOCKED"])
def test_any_status_other_than_ready_refuses(backend, status):
    reset_broken_scenario(backend)
    run_governed_pipeline(backend)
    with duckdb.connect(str(backend.path)) as con:
        con.execute("UPDATE gold_data_product_health SET status = ?", [status])
    result = ask_governed(backend)
    assert isinstance(result, Refusal)
    assert status in result.message


def test_duplicate_resolution_is_deterministic(backend, summary):
    duplicate_id = summary["invariants"]["duplicated_order_ids"][0]
    snapshots = []
    for _ in range(2):
        reset_broken_scenario(backend)
        run_governed_pipeline(backend)
        versions = rows(
            backend,
            "SELECT event_id, version_rank FROM silver_order_versions "
            f"WHERE order_id = '{duplicate_id}' ORDER BY version_rank",
        )
        silver = rows(backend, "SELECT * FROM silver_orders ORDER BY order_id")
        snapshots.append((versions, silver))
    assert snapshots[0] == snapshots[1]
    versions = snapshots[0][0]
    assert [v["version_rank"] for v in versions] == [1, 2]
    # Same version number: the later source_updated_at (the replayed event) wins.
    with (SAMPLE_DATA_DIR / "azure-sql" / "orders.csv").open(encoding="utf-8") as handle:
        events = [r for r in csv.DictReader(handle) if r["order_id"] == duplicate_id]
    latest = max(events, key=lambda r: r["source_updated_at"])
    assert versions[0]["event_id"] == latest["event_id"]
    assert rows(
        backend, f"SELECT COUNT(*) AS n FROM silver_orders WHERE order_id = '{duplicate_id}'"
    ) == [{"n": 1}]


def test_fx_conversion_uses_the_transaction_date(repaired_db):
    with (SAMPLE_DATA_DIR / "reference" / "fx_rates.repaired.csv").open(encoding="utf-8") as h:
        rates = {r["rate_date"]: Decimal(r["rate"]) for r in csv.DictReader(h)}
    usd = rows(
        repaired_db,
        "SELECT f.applied_fx_rate, d.calendar_date, f.gross_amount_original_currency, "
        "f.gross_revenue_cad FROM gold_fact_sales f JOIN gold_dim_date d USING (date_key) "
        "WHERE f.original_currency = 'USD'",
    )
    assert usd
    for row in usd:
        rate = rates[row["calendar_date"].isoformat()]
        assert row["applied_fx_rate"] == rate
        expected = (row["gross_amount_original_currency"] * rate).quantize(Decimal("0.01"))
        assert row["gross_revenue_cad"] == expected
    assert len(set(rates.values())) > 1  # a wrong date would produce a different rate


def test_returns_reduce_governed_revenue(repaired_db):
    answer = ask_governed(repaired_db)
    assert isinstance(answer, GovernedAnswer)
    assert answer.returns > 0
    assert answer.net_revenue == answer.gross_revenue - answer.returns


def test_orphan_returns_are_detected(broken_db, summary):
    orphan = summary["invariants"]["orphan_return_ids"][0]
    status = rows(
        broken_db,
        f"SELECT reconciliation_status FROM silver_returns WHERE return_id = '{orphan}'",
    )
    assert status == [{"reconciliation_status": "ORPHAN"}]
    assert read_health(broken_db).orphan_return_count == 1


def test_governed_answer_after_repair(repaired_db, summary):
    answer = ask_governed(repaired_db)
    inv = summary["invariants"]
    assert isinstance(answer, GovernedAnswer)
    assert not answer.beat_target
    assert answer.net_revenue < answer.target
    assert str(answer.net_revenue) == inv["ontario_governed_net_revenue_cad"]
    assert str(answer.target) == inv["ontario_target_cad"]
    assert answer.variance == answer.net_revenue - answer.target
    assert answer.largest_negative.category_name == "Devices"
    assert (
        str(answer.largest_negative.variance_cad)
        == inv["ontario_governed_variance_by_category"]["DEV"]
    )
    assert answer.metric_name == "net_revenue_cad"
    assert "minus accepted returns" in answer.metric_definition


def test_evidence_contains_run_id_refresh_and_lineage(repaired_db):
    answer = ask_governed(repaired_db)
    latest = list_runs(repaired_db)[0]
    assert answer.pipeline_run_id == latest.pipeline_run_id
    assert latest.status == "READY"
    assert answer.refresh_utc == latest.completed_at_utc
    assert answer.refresh_utc is not None
    assert answer.quality_status == "READY"
    assert answer.source_lineage == [
        "azure_sql.sales.orders",
        "sqlserver.dbo.returns",
        "treasury.reference.fx",
    ]
