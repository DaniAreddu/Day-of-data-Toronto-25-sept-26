"""Act 1: the ungoverned path. Every figure is derived from the query result rows."""

from __future__ import annotations

from decimal import Decimal

from .backends.base import Backend
from .clock import parse_utc
from .models import CategoryVariance, RawAnswer
from .queries import load_query

PCT = Decimal("0.01")


def ask_raw(backend: Backend) -> RawAnswer:
    sql = load_query("raw_answer")
    rows = backend.query(sql)
    if not rows:
        raise LookupError("The raw query returned no rows for Ontario, August 2026")

    categories = [
        CategoryVariance(
            category_code=row["category_code"],
            category_name=row["category_name"],
            actual_cad=Decimal(row["revenue"]),  # labelled CAD by the raw system, wrongly
            target_cad=Decimal(row["target_cad"]),
        )
        for row in rows
    ]
    revenue = sum((c.actual_cad for c in categories), Decimal(0))
    target = sum((c.target_cad for c in categories), Decimal(0))
    variance = revenue - target
    beat_target = revenue > target
    if beat_target:
        driver = max(categories, key=lambda c: c.variance_cad)
    else:
        driver = min(categories, key=lambda c: c.variance_cad)
    non_cad_rows = sum(int(row["non_cad_rows"]) for row in rows)
    latest = max(parse_utc(row["latest_ingested_at"]) for row in rows)

    return RawAnswer(
        revenue=revenue,
        target=target,
        variance=variance,
        variance_pct=(variance * 100 / target).quantize(PCT),
        beat_target=beat_target,
        driver=driver,
        categories=sorted(categories, key=lambda c: c.variance_cad, reverse=True),
        sql=sql,
        rows_scanned=sum(int(row["order_rows"]) for row in rows),
        currencies_summed=["CAD", "USD"] if non_cad_rows else ["CAD"],
        latest_orders_ingested_at_utc=latest,
        governance={
            "Approved metric definition": "none: 'revenue' is whatever SUM(gross_amount) returns",
            "Currency handling": f"none: {non_cad_rows} non-CAD rows summed as if CAD",
            "Deduplication": "none: raw landing rows read directly",
            "Returns": "not consulted",
            "Freshness check": "none",
            "Data-product health gate": "none",
            "Lineage / run id": "none",
        },
    )
