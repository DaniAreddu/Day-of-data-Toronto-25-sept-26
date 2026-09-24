"""Contract tests: YAML parses, required fields exist and the rules are enforced."""

from __future__ import annotations

from datetime import timedelta

import pytest

from ai_reliability_lab.contracts import (
    CONTRACT_FILES,
    REQUIRED_METRIC_FIELDS,
    health_contract,
    load_contract,
    metric_contract,
)
from ai_reliability_lab.generator import RETURNS_REPAIRED_INGESTED_AT
from ai_reliability_lab.governed_path import ask_governed
from ai_reliability_lab.models import Refusal
from ai_reliability_lab.pipeline import run_pipeline
from ai_reliability_lab.quality import LATEST_INGESTION_SQL, QUALITY_CHECK_SQL

EXPECTED_BLOCKING = {
    "ORDERS_FRESHNESS",
    "RETURNS_FRESHNESS",
    "DUPLICATE_BUSINESS_KEYS",
    "MISSING_FX",
    "ORPHAN_RETURNS",
    "MISSING_REQUIRED_KEYS",
    "UNSUPPORTED_CURRENCY",
}


@pytest.mark.parametrize("name", sorted(CONTRACT_FILES))
def test_contracts_parse(name):
    data = load_contract(name)
    assert isinstance(data, dict) and data


def test_source_contracts_have_owner_version_and_columns():
    for name in ("orders", "returns", "fx_rates"):
        data = load_contract(name)
        assert data["version"] == "1.0.0"
        assert data["owner_role"]
        assert data["columns"]
        assert data["security_classification"]


def test_metric_contract_has_required_fields():
    metric = metric_contract()
    for field in REQUIRED_METRIC_FIELDS:
        assert metric.get(field) not in (None, "", []), field
    assert metric["accepted_currencies"] == ["CAD", "USD"]


def test_metric_definition_is_stable():
    metric = metric_contract()
    assert metric["metric"] == "net_revenue_cad"
    assert metric["definition"] == (
        "Gross order revenue converted to CAD at the transaction-date FX rate, minus accepted "
        "returns converted to CAD at the FX rate of the original order transaction date."
    )
    assert metric["data_contract_version"] == "1.0.0"


def test_health_contract_declares_blocking_and_warning_checks():
    contract = health_contract()
    blocking = {c.name for c in contract.checks if c.severity == "BLOCKING"}
    warnings = {c.name for c in contract.checks if c.severity == "WARNING"}
    assert blocking == EXPECTED_BLOCKING
    assert {"QUARANTINED_ROWS", "HIGH_RETURN_RATE", "VOLUME_ANOMALY"} <= warnings
    implemented = set(QUALITY_CHECK_SQL) | set(LATEST_INGESTION_SQL)
    assert {c.name for c in contract.checks} == implemented


def test_four_hour_returns_freshness_sla_is_enforced(backend):
    assert health_contract().returns_freshness_sla_minutes == 240
    just_inside = RETURNS_REPAIRED_INGESTED_AT + timedelta(minutes=239)
    run = run_pipeline(backend, "repaired", as_of=just_inside, reset=True).run
    assert run.status == "READY"
    just_outside = RETURNS_REPAIRED_INGESTED_AT + timedelta(minutes=241)
    run = run_pipeline(backend, "repaired", as_of=just_outside, reset=True).run
    assert run.status == "BLOCKED"
    assert [r.split(":")[0] for r in run.failure_reasons] == ["RETURNS_FRESHNESS"]


def append_order(inputs, **overrides):
    path = inputs / "azure-sql" / "orders.csv"
    row = {
        "order_id": "SO-202608-99999",
        "event_id": "CDC-99999999",
        "event_version": "1",
        "order_timestamp_utc": "2026-08-10T12:00:00Z",
        "region_code": "ON",
        "category_code": "DEV",
        "currency_code": "CAD",
        "gross_amount": "100.00",
        "customer_segment": "SMB",
        "source_updated_at": "2026-08-10T12:00:00Z",
        "ingested_at": "2026-09-26T17:30:00Z",
    }
    row.update(overrides)
    with path.open("a", encoding="utf-8", newline="") as handle:
        handle.write(",".join(row.values()) + "\n")


def test_unsupported_currency_blocks_readiness(backend, inputs_copy):
    append_order(inputs_copy, currency_code="EUR")
    run = run_pipeline(backend, "repaired", inputs_dir=inputs_copy, reset=True).run
    assert run.status == "BLOCKED"
    assert [r.split(":")[0] for r in run.failure_reasons] == ["UNSUPPORTED_CURRENCY"]
    assert isinstance(ask_governed(backend), Refusal)


def test_unknown_region_blocks_readiness(backend, inputs_copy):
    append_order(inputs_copy, region_code="ZZ")
    run = run_pipeline(backend, "repaired", inputs_dir=inputs_copy, reset=True).run
    assert run.status == "BLOCKED"
    assert [r.split(":")[0] for r in run.failure_reasons] == ["MISSING_REQUIRED_KEYS"]


def test_canonical_fixtures_are_not_mutated(inputs_copy):
    from ai_reliability_lab.config import SAMPLE_DATA_DIR

    append_order(inputs_copy)
    original = (SAMPLE_DATA_DIR / "azure-sql" / "orders.csv").read_bytes()
    assert b"SO-202608-99999" not in original
