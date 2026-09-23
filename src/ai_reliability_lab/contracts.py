"""Machine-readable data contracts (YAML) and the typed values the pipeline depends on."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from .config import CONTRACTS_DIR

CONTRACT_FILES = {
    "orders": "orders.contract.yml",
    "returns": "returns.contract.yml",
    "fx_rates": "fx_rates.contract.yml",
    "net_revenue": "net_revenue.metric.yml",
    "data_product_health": "data_product_health.contract.yml",
}

REQUIRED_METRIC_FIELDS = (
    "metric",
    "display_name",
    "definition",
    "formula",
    "owner_role",
    "grain",
    "dimensions",
    "accepted_currencies",
    "freshness_sla_minutes",
    "quality_requirements",
    "security_classification",
    "data_contract_version",
)


class ContractError(ValueError):
    """A contract file is missing, unreadable or incomplete."""


def load_contract(name: str, directory: Path = CONTRACTS_DIR) -> dict[str, Any]:
    path = directory / CONTRACT_FILES[name]
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ContractError(f"Contract file not found: {path}") from exc
    if not isinstance(data, dict):
        raise ContractError(f"Contract {path} must be a YAML mapping")
    return data


@dataclass(frozen=True)
class CheckSpec:
    name: str
    severity: str  # BLOCKING | WARNING
    description: str
    threshold: str


@dataclass(frozen=True)
class HealthContract:
    data_product: str
    version: str
    orders_freshness_sla_minutes: int
    returns_freshness_sla_minutes: int
    accepted_currencies: tuple[str, ...]
    max_category_return_rate_pct: int
    volume_anomaly_factor: int
    checks: tuple[CheckSpec, ...]

    def severity(self, check_name: str) -> str:
        for check in self.checks:
            if check.name == check_name:
                return check.severity
        raise ContractError(f"Check {check_name} is not declared in the health contract")

    def spec(self, check_name: str) -> CheckSpec:
        return next(c for c in self.checks if c.name == check_name)


@cache
def health_contract(directory: Path = CONTRACTS_DIR) -> HealthContract:
    raw = load_contract("data_product_health", directory)
    params = raw["parameters"]
    checks = tuple(
        CheckSpec(c["name"], c["severity"], c["description"], str(c["threshold"]))
        for c in raw["checks"]
    )
    for check in checks:
        if check.severity not in ("BLOCKING", "WARNING"):
            raise ContractError(f"{check.name}: severity must be BLOCKING or WARNING")
    return HealthContract(
        data_product=raw["data_product"],
        version=str(raw["data_contract_version"]),
        orders_freshness_sla_minutes=int(params["orders_freshness_sla_minutes"]),
        returns_freshness_sla_minutes=int(params["returns_freshness_sla_minutes"]),
        accepted_currencies=tuple(params["accepted_currencies"]),
        max_category_return_rate_pct=int(params["max_category_return_rate_pct"]),
        volume_anomaly_factor=int(params["volume_anomaly_factor"]),
        checks=checks,
    )


@cache
def metric_contract(directory: Path = CONTRACTS_DIR) -> dict[str, Any]:
    raw = load_contract("net_revenue", directory)
    missing = [field for field in REQUIRED_METRIC_FIELDS if field not in raw]
    if missing:
        raise ContractError(f"Metric contract is missing fields: {', '.join(missing)}")
    return raw


def contract_metadata_rows(directory: Path = CONTRACTS_DIR) -> list[dict[str, str]]:
    """Flatten the values the Fabric notebook needs, so it can stay YAML-free."""
    health = health_contract(directory)
    metric = metric_contract(directory)
    values = {
        "data_contract_version": health.version,
        "metric_name": metric["metric"],
        "metric_version": str(metric["version"]),
        "orders_freshness_sla_minutes": str(health.orders_freshness_sla_minutes),
        "returns_freshness_sla_minutes": str(health.returns_freshness_sla_minutes),
        "accepted_currencies": "|".join(health.accepted_currencies),
        "max_category_return_rate_pct": str(health.max_category_return_rate_pct),
        "volume_anomaly_factor": str(health.volume_anomaly_factor),
    }
    rows = [
        {"contract": health.data_product, "key": key, "value": value}
        for key, value in values.items()
    ]
    rows += [
        {"contract": health.data_product, "key": f"severity.{c.name}", "value": c.severity}
        for c in health.checks
    ]
    return rows
