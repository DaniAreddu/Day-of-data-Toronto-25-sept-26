"""Dataset invariants: the synthetic scenario must be reproducible and tell the right story."""

from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from decimal import Decimal

import pytest

from ai_reliability_lab import generator
from ai_reliability_lab.clock import DEMO_CLOCK_UTC, DEMO_SEED, minutes_between, parse_utc
from ai_reliability_lab.config import SAMPLE_DATA_DIR
from ai_reliability_lab.contracts import health_contract


def read(relative: str) -> list[dict]:
    with (SAMPLE_DATA_DIR / relative).open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def header(relative: str) -> tuple[str, ...]:
    with (SAMPLE_DATA_DIR / relative).open(encoding="utf-8", newline="") as handle:
        return tuple(next(csv.reader(handle)))


def test_generation_is_deterministic_and_matches_committed_files(tmp_path):
    first = generator.build_scenario(DEMO_SEED)
    second = generator.build_scenario(DEMO_SEED)
    assert first.summary == second.summary
    assert first.orders == second.orders

    generator.generate(tmp_path)
    fresh = sorted(p.relative_to(tmp_path) for p in tmp_path.rglob("*") if p.is_file())
    assert fresh, "generator wrote nothing"
    for relative in fresh:
        committed = SAMPLE_DATA_DIR / relative
        assert committed.read_bytes() == (tmp_path / relative).read_bytes(), relative


def test_schemas_are_stable():
    assert header("azure-sql/orders.csv") == generator.ORDER_COLUMNS
    assert header("sql-server/returns.broken.csv") == generator.RETURN_COLUMNS
    assert header("sql-server/returns.repaired.csv") == generator.RETURN_COLUMNS
    assert header("reference/fx_rates.broken.csv") == generator.FX_COLUMNS
    assert header("reference/fx_rates.repaired.csv") == generator.FX_COLUMNS
    assert header("reference/targets.csv") == generator.TARGET_COLUMNS
    assert header("reference/regions.csv") == (
        "region_key",
        "region_code",
        "region_name",
        "country_code",
    )


def test_all_timestamps_are_explicit_utc():
    for row in read("azure-sql/orders.csv")[:50]:
        for column in ("order_timestamp_utc", "source_updated_at", "ingested_at"):
            assert row[column].endswith("Z"), (column, row[column])


def test_broken_input_contains_exactly_one_duplicated_order():
    counts = Counter(row["order_id"] for row in read("azure-sql/orders.csv"))
    duplicated = [order_id for order_id, n in counts.items() if n > 1]
    assert len(duplicated) == 1
    assert counts[duplicated[0]] == 2


def test_broken_returns_are_stale_and_repaired_returns_are_fresh():
    sla = health_contract().returns_freshness_sla_minutes
    stale = max(parse_utc(r["ingested_at"]) for r in read("sql-server/returns.broken.csv"))
    fresh = max(parse_utc(r["ingested_at"]) for r in read("sql-server/returns.repaired.csv"))
    assert minutes_between(stale, DEMO_CLOCK_UTC) > sla
    assert minutes_between(fresh, DEMO_CLOCK_UTC) <= sla


def usd_order_dates() -> set[date]:
    return {
        parse_utc(r["order_timestamp_utc"]).date()
        for r in read("azure-sql/orders.csv")
        if r["currency_code"] == "USD"
    }


def test_broken_fx_coverage_is_incomplete():
    covered = {date.fromisoformat(r["rate_date"]) for r in read("reference/fx_rates.broken.csv")}
    assert usd_order_dates() - covered


def test_repaired_fx_coverage_is_complete():
    covered = {date.fromisoformat(r["rate_date"]) for r in read("reference/fx_rates.repaired.csv")}
    assert usd_order_dates() <= covered


def test_target_sits_between_naive_and_governed(summary):
    inv = summary["invariants"]
    naive = Decimal(inv["ontario_naive_raw_revenue"])
    target = Decimal(inv["ontario_target_cad"])
    governed = Decimal(inv["ontario_governed_net_revenue_cad"])
    assert naive > target > governed
    targets = [r for r in read("reference/targets.csv") if r["region_code"] == "ON"]
    assert sum(Decimal(r["target_cad"]) for r in targets) == target


def test_devices_is_the_largest_negative_governed_contributor(summary):
    variance = {
        k: Decimal(v)
        for k, v in summary["invariants"]["ontario_governed_variance_by_category"].items()
    }
    assert min(variance, key=variance.get) == "DEV"
    assert variance["DEV"] < 0


def test_generation_fails_when_the_narrative_cannot_hold(monkeypatch):
    monkeypatch.setattr(generator, "ONTARIO_TARGET_POSITION", Decimal("1.5"))
    with pytest.raises(generator.NarrativeInvariantError):
        generator.build_scenario(DEMO_SEED)


def test_seed_and_clock_are_documented(summary):
    assert summary["seed"] == DEMO_SEED == 20260926
    assert summary["demo_clock_utc"] == "2026-09-26T18:00:00Z"
