"""Acts 2 and 3: the governed path. It checks data-product health before answering.

The refusal is enforced here, in data-access code, not in a prompt:

    if health.status != "READY":
        return refusal

``query_governed_facts`` re-checks the gate itself, and the governed SQL returns no rows
unless the health row says READY, so no caller can bypass the gate.
"""

from __future__ import annotations

from decimal import Decimal

from .backends.base import Backend
from .clock import parse_utc
from .contracts import metric_contract
from .models import (
    DATA_PRODUCT,
    CategoryVariance,
    GovernedAnswer,
    HealthReport,
    Refusal,
)
from .queries import load_query


class DataProductNotReady(RuntimeError):
    """Raised when governed facts are requested from a data product that is not READY."""


def _split(value: str | None) -> list[str]:
    return [part.strip() for part in (value or "").split(" | ") if part.strip()]


def _int(value: object) -> int:
    return int(value) if value is not None else 0


def read_health(backend: Backend) -> HealthReport | None:
    rows = backend.query(load_query("platform_health"))
    if not rows:
        return None
    row = rows[0]
    return HealthReport(
        data_product=row["data_product"],
        status=row["status"],
        data_contract_version=row["data_contract_version"],
        scenario_mode=row["scenario_mode"],
        as_of_utc=parse_utc(row["as_of_utc"]),
        orders_freshness_minutes=row["orders_freshness_minutes"],
        returns_freshness_minutes=row["returns_freshness_minutes"],
        freshness_sla_minutes=_int(row["freshness_sla_minutes"]),
        duplicate_count=_int(row["duplicate_count"]),
        missing_fx_count=_int(row["missing_fx_count"]),
        orphan_return_count=_int(row["orphan_return_count"]),
        missing_key_count=_int(row["missing_key_count"]),
        unsupported_currency_count=_int(row["unsupported_currency_count"]),
        quarantined_rows=_int(row["quarantined_rows"]),
        blocking_reasons=_split(row["blocking_reasons"]),
        warning_reasons=_split(row["warning_reasons"]),
        pipeline_run_id=row["pipeline_run_id"],
        last_successful_refresh_utc=parse_utc(row["last_successful_refresh_utc"]),
        evaluated_at_utc=parse_utc(row["evaluated_at_utc"]),
    )


def _reason_text(reason: str) -> str:
    """'RETURNS_FRESHNESS: returns feed is stale ...' -> 'returns feed is stale ...'"""
    return reason.split(": ", 1)[1] if ": " in reason else reason


def _join(parts: list[str]) -> str:
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def refuse(health: HealthReport | None, extra_reason: str | None = None) -> Refusal:
    if health is None:
        placeholder = HealthReport(
            data_product=DATA_PRODUCT,
            status="UNKNOWN",
            data_contract_version="unknown",
            scenario_mode="unknown",
            as_of_utc=None,
            orders_freshness_minutes=None,
            returns_freshness_minutes=None,
            freshness_sla_minutes=0,
            duplicate_count=0,
            missing_fx_count=0,
            orphan_return_count=0,
            missing_key_count=0,
            unsupported_currency_count=0,
            quarantined_rows=0,
            blocking_reasons=["NO_HEALTH_RECORD: no data-product health record exists"],
            warning_reasons=[],
            pipeline_run_id="none",
            last_successful_refresh_utc=None,
            evaluated_at_utc=None,
        )
        return refuse(placeholder, extra_reason)

    reasons = [_reason_text(r) for r in health.blocking_reasons]
    if extra_reason:
        reasons.append(extra_reason)
    if not reasons:
        reasons = [f"the data product status is {health.status}, not READY"]
    message = (
        f"I cannot provide a reliable answer because {_join(reasons)}. "
        f"Data product {health.data_product} is {health.status}; "
        "no business figure is served until every blocking check passes."
    )
    detected = [_reason_text(w) for w in health.warning_reasons]
    if detected:
        message += f" Non-blocking findings: {_join(detected)}."
    return Refusal(health=health, reasons=reasons, message=message)


def query_governed_facts(backend: Backend, health: HealthReport) -> GovernedAnswer:
    if not health.is_ready:
        raise DataProductNotReady(f"{health.data_product} is {health.status}, not READY")

    governed_sql = load_query("governed_answer")
    category_sql = load_query("category_variance")
    lineage_sql = load_query("source_lineage")
    rows = backend.query(governed_sql)
    if not rows or rows[0]["net_revenue_cad"] is None:
        raise DataProductNotReady("the governed query returned no READY rows")
    totals = rows[0]
    if totals["pipeline_run_id"] != health.pipeline_run_id:
        raise DataProductNotReady("health changed while answering; ask again")

    categories = [
        CategoryVariance(
            category_code=row["category_code"],
            category_name=row["category_name"],
            actual_cad=Decimal(row["net_revenue_cad"]),
            target_cad=Decimal(row["target_cad"]),
        )
        for row in backend.query(category_sql)
    ]
    negatives = [c for c in categories if c.variance_cad < 0]
    largest_negative = min(negatives, key=lambda c: c.variance_cad) if negatives else None
    lineage = sorted(
        {
            system
            for row in backend.query(lineage_sql)
            for system in (
                row["order_source_system"],
                row["returns_source_system"],
                row["fx_source_system"],
            )
            if system not in ("no return", "none (CAD)")
        }
    )
    metric = metric_contract()
    net = Decimal(totals["net_revenue_cad"])
    target = Decimal(totals["target_cad"])

    return GovernedAnswer(
        net_revenue=net,
        gross_revenue=Decimal(totals["gross_revenue_cad"]),
        returns=Decimal(totals["returns_cad"]),
        target=target,
        variance=Decimal(totals["variance_cad"]),
        variance_pct=Decimal(totals["variance_pct"]).quantize(Decimal("0.01")),
        beat_target=net > target,
        largest_negative=largest_negative,
        categories=categories,
        metric_name=metric["metric"],
        metric_display_name=metric["display_name"],
        metric_definition=metric["definition"],
        metric_version=str(metric["version"]),
        data_contract_version=totals["data_contract_version"],
        refresh_utc=parse_utc(totals["last_successful_refresh_utc"]),
        pipeline_run_id=totals["pipeline_run_id"],
        quality_status=totals["status"],
        source_lineage=lineage,
        sql={
            "governed_answer.sql": governed_sql,
            "category_variance.sql": category_sql,
            "source_lineage.sql": lineage_sql,
        },
    )


def ask_governed(backend: Backend) -> GovernedAnswer | Refusal:
    health = read_health(backend)
    if health is None or health.status != "READY":
        return refuse(health)
    try:
        return query_governed_facts(backend, health)
    except DataProductNotReady as exc:
        return refuse(read_health(backend), str(exc))
