"""Observability: run records, status transitions and failure evidence."""

from __future__ import annotations

import re

import pytest

from ai_reliability_lab import pipeline as pipeline_module
from ai_reliability_lab.governed_path import ask_governed, read_health
from ai_reliability_lab.models import Refusal
from ai_reliability_lab.observability import list_runs
from ai_reliability_lab.pipeline import (
    PipelineFailed,
    reset_broken_scenario,
    run_governed_pipeline,
)


def test_status_transitions_blocked_then_ready(backend):
    first = reset_broken_scenario(backend).run
    assert first.status == "BLOCKED"
    assert read_health(backend).status == "BLOCKED"
    second = run_governed_pipeline(backend).run
    assert second.status == "READY"
    health = read_health(backend)
    assert health.status == "READY"
    assert health.last_successful_refresh_utc == second.completed_at_utc
    assert [r.status for r in list_runs(backend)] == ["READY", "BLOCKED"]


def test_reset_is_idempotent_and_clears_run_history(backend):
    reset_broken_scenario(backend)
    run_governed_pipeline(backend)
    reset_broken_scenario(backend)
    runs = list_runs(backend)
    assert [r.status for r in runs] == ["BLOCKED"]
    assert read_health(backend).last_successful_refresh_utc is None
    assert isinstance(ask_governed(backend), Refusal)


def test_repair_is_idempotent(backend):
    reset_broken_scenario(backend)
    run_governed_pipeline(backend)
    first = ask_governed(backend)
    run_governed_pipeline(backend)
    second = ask_governed(backend)
    assert first.net_revenue == second.net_revenue
    assert first.pipeline_run_id != second.pipeline_run_id


def test_row_counts_are_populated(broken_db, repaired_db):
    broken = list_runs(broken_db)[0]
    repaired = list_runs(repaired_db)[0]
    assert broken.bronze_order_rows == repaired.bronze_order_rows == 1122
    assert 0 < broken.bronze_return_rows < repaired.bronze_return_rows
    assert repaired.silver_sales_rows == 1120  # minus one duplicate, minus one quarantined row
    assert repaired.quarantined_rows == 1
    assert repaired.duplicate_count == 1
    assert broken.missing_fx_count > 0 and repaired.missing_fx_count == 0


def test_failure_reasons_are_preserved(broken_db):
    run = list_runs(broken_db)[0]
    health = read_health(broken_db)
    assert run.failure_reasons == health.blocking_reasons
    assert [r.split(":")[0] for r in run.failure_reasons] == [
        "RETURNS_FRESHNESS",
        "MISSING_FX",
        "ORPHAN_RETURNS",
    ]
    assert run.freshness_minutes == health.returns_freshness_minutes


def test_duration_is_nonnegative_and_run_id_present(repaired_db):
    for run in list_runs(repaired_db):
        assert run.duration_ms >= 0
        assert re.fullmatch(r"run-\d{8}T\d{6}Z-(broken|repaired)-[0-9a-f]{6}", run.pipeline_run_id)
        assert run.completed_at_utc >= run.started_at_utc
        assert run.data_contract_version == "1.0.0"


def test_running_status_is_recorded_before_work_starts(backend, monkeypatch):
    seen = {}
    original = pipeline_module.load_bronze

    def spy(con, inputs_dir, scenario_mode):
        seen["health"] = con.execute("SELECT status FROM gold_data_product_health").fetchone()[0]
        seen["run"] = con.execute("SELECT status FROM gold_pipeline_runs").fetchone()[0]
        return original(con, inputs_dir, scenario_mode)

    monkeypatch.setattr(pipeline_module, "load_bronze", spy)
    reset_broken_scenario(backend)
    assert seen == {"health": "RUNNING", "run": "RUNNING"}


def test_pipeline_failure_is_recorded_as_failed(backend, monkeypatch):
    reset_broken_scenario(backend)
    run_governed_pipeline(backend)

    def explode(*_args):
        raise FileNotFoundError("repaired returns extract missing")

    monkeypatch.setattr(pipeline_module, "load_bronze", explode)
    with pytest.raises(PipelineFailed, match="repaired returns extract missing"):
        run_governed_pipeline(backend)
    latest = list_runs(backend)[0]
    assert latest.status == "FAILED"
    assert "repaired returns extract missing" in latest.failure_reasons[0]
    health = read_health(backend)
    assert health.status == "FAILED"
    assert isinstance(ask_governed(backend), Refusal)
