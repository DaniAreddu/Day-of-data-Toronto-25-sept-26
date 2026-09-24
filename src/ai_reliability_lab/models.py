"""Typed results passed between the data paths, the narrator and the UI."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

QUESTION = (
    "Did Ontario beat its August 2026 revenue target, and which product category drove the result?"
)
REGION_CODE = "ON"
REGION_NAME = "Ontario"
REPORTING_MONTH = "2026-08"
DATA_PRODUCT = "net_revenue_cad"


@dataclass(frozen=True)
class CategoryVariance:
    category_code: str
    category_name: str
    actual_cad: Decimal
    target_cad: Decimal

    @property
    def variance_cad(self) -> Decimal:
        return self.actual_cad - self.target_cad


@dataclass(frozen=True)
class RawAnswer:
    """The ungoverned answer: valid SQL over an invalid data contract."""

    revenue: Decimal
    target: Decimal
    variance: Decimal
    variance_pct: Decimal
    beat_target: bool
    driver: CategoryVariance
    categories: list[CategoryVariance]
    sql: str
    rows_scanned: int
    currencies_summed: list[str]
    latest_orders_ingested_at_utc: datetime | None
    governance: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class HealthReport:
    data_product: str
    status: str
    data_contract_version: str
    scenario_mode: str
    as_of_utc: datetime | None
    orders_freshness_minutes: int | None
    returns_freshness_minutes: int | None
    freshness_sla_minutes: int
    duplicate_count: int
    missing_fx_count: int
    orphan_return_count: int
    missing_key_count: int
    unsupported_currency_count: int
    quarantined_rows: int
    blocking_reasons: list[str]
    warning_reasons: list[str]
    pipeline_run_id: str
    last_successful_refresh_utc: datetime | None
    evaluated_at_utc: datetime | None

    @property
    def is_ready(self) -> bool:
        return self.status == "READY"


@dataclass(frozen=True)
class Refusal:
    """The governed path declined to answer. Produced by code, never by a model."""

    health: HealthReport
    reasons: list[str]
    message: str


@dataclass(frozen=True)
class GovernedAnswer:
    net_revenue: Decimal
    gross_revenue: Decimal
    returns: Decimal
    target: Decimal
    variance: Decimal
    variance_pct: Decimal
    beat_target: bool
    largest_negative: CategoryVariance | None
    categories: list[CategoryVariance]
    metric_name: str
    metric_display_name: str
    metric_definition: str
    metric_version: str
    data_contract_version: str
    refresh_utc: datetime | None
    pipeline_run_id: str
    quality_status: str
    source_lineage: list[str]
    sql: dict[str, str]


@dataclass(frozen=True)
class QualityResult:
    check_name: str
    severity: str
    observed_value: int
    threshold: str
    status: str
    detail: str


def to_facts(value: Any) -> Any:
    """Convert a result into JSON-safe facts for a narrator (Decimal -> str, datetime -> ISO)."""
    if hasattr(value, "__dataclass_fields__"):
        value = asdict(value)
    if isinstance(value, dict):
        return {k: to_facts(v) for k, v in value.items() if k != "sql"}
    if isinstance(value, list):
        return [to_facts(v) for v in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    return value
