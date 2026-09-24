"""Raw-path behaviour: valid SQL over an invalid data contract."""

from __future__ import annotations

from decimal import Decimal

import duckdb

from ai_reliability_lab.raw_path import ask_raw


def scalar(backend, sql):
    with duckdb.connect(str(backend.path), read_only=True) as con:
        return con.execute(sql).fetchone()[0]


ONTARIO_AUGUST = (
    "region_code = 'ON' AND order_timestamp_utc >= '2026-08-01' "
    "AND order_timestamp_utc < '2026-09-01'"
)


def test_raw_revenue_is_above_target(broken_db, summary):
    raw = ask_raw(broken_db)
    assert raw.beat_target
    assert raw.revenue > raw.target
    assert raw.variance > 0
    assert raw.driver.variance_cad > 0
    assert str(raw.revenue) == summary["invariants"]["ontario_naive_raw_revenue"]


def test_duplicate_contributes_to_the_raw_result(broken_db, summary):
    raw = ask_raw(broken_db)
    duplicate_id = summary["invariants"]["duplicated_order_ids"][0]
    every_row = scalar(
        broken_db, f"SELECT SUM(gross_amount) FROM bronze_orders WHERE {ONTARIO_AUGUST}"
    )
    one_per_order = scalar(
        broken_db,
        "SELECT SUM(gross_amount) FROM (SELECT DISTINCT order_id, gross_amount FROM bronze_orders "
        f"WHERE {ONTARIO_AUGUST})",
    )
    duplicate_amount = scalar(
        broken_db, f"SELECT MAX(gross_amount) FROM bronze_orders WHERE order_id = '{duplicate_id}'"
    )
    assert raw.revenue == every_row
    assert raw.revenue - one_per_order == duplicate_amount > 0


def test_raw_path_ignores_returns(broken_db, repaired_db):
    before, after = ask_raw(broken_db), ask_raw(repaired_db)
    assert before.revenue == after.revenue  # the returns feed changed, the raw answer did not
    assert "not consulted" in before.governance["Returns"]
    body = " ".join(x for x in before.sql.splitlines() if not x.strip().startswith("--"))
    assert "returns" not in body.lower()


def test_raw_path_mishandles_currency_as_designed(broken_db):
    raw = ask_raw(broken_db)
    usd_rows = scalar(
        broken_db,
        f"SELECT COUNT(*) FROM bronze_orders WHERE {ONTARIO_AUGUST} AND currency_code = 'USD'",
    )
    assert usd_rows > 0
    assert raw.currencies_summed == ["CAD", "USD"]
    assert f"{usd_rows} non-CAD rows summed as if CAD" in raw.governance["Currency handling"]


class RowsBackend:
    name, label, read_only = "fake", "fake", True

    def __init__(self, rows):
        self.rows = rows

    def query(self, sql):
        return self.rows


def test_raw_answer_is_derived_from_query_results():
    rows = [
        {"category_code": "AAA", "category_name": "Alpha", "order_rows": 2, "non_cad_rows": 0,
         "revenue": Decimal("50.00"), "target_cad": Decimal("80.00"),
         "latest_ingested_at": "2026-09-26 17:30:00"},
        {"category_code": "BBB", "category_name": "Beta", "order_rows": 1, "non_cad_rows": 1,
         "revenue": Decimal("40.00"), "target_cad": Decimal("30.00"),
         "latest_ingested_at": "2026-09-26 17:00:00"},
    ]  # fmt: skip
    raw = ask_raw(RowsBackend(rows))
    assert raw.revenue == Decimal("90.00")
    assert raw.target == Decimal("110.00")
    assert not raw.beat_target
    assert raw.driver.category_name == "Alpha"
    assert raw.variance_pct == Decimal("-18.18")
