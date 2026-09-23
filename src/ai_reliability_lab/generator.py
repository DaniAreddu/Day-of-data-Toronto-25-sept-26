"""Deterministic synthetic scenario generator.

Synthetic, production-inspired architecture scenario. It does not represent a real customer
deployment. Every value is produced from ``DEMO_SEED``; regenerating reproduces the committed
files byte for byte.

The generator guarantees the narrative mathematically instead of hoping for it:

1. generate orders, returns and FX rates;
2. compute the naive raw total (what the ungoverned path will sum);
3. compute the governed net total with an independent reference implementation;
4. derive the Ontario target strictly between the two and allocate it to categories so that
   Devices carries the largest governed shortfall;
5. verify every narrative invariant and refuse to write anything if one fails.

The application never reads the figures computed here. It recomputes everything from the
records through the raw and governed paths; tests check that both implementations agree.
"""

from __future__ import annotations

import csv
import hashlib
import json
import random
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from .clock import DEMO_CLOCK_UTC, DEMO_SEED, iso_z
from .config import SAMPLE_DATA_DIR
from .contracts import contract_metadata_rows, health_contract

CENT = Decimal("0.01")
MONTH_START = datetime(2026, 8, 1, tzinfo=UTC)
MONTH_DAYS = 31
TARGET_MONTH = "2026-08"

ORDERS_INGESTED_AT = datetime(2026, 9, 26, 17, 30, tzinfo=UTC)
RETURNS_REPAIRED_INGESTED_AT = datetime(2026, 9, 26, 17, 15, tzinfo=UTC)
# The SQL Server replication job silently stopped here: the broken extract is 60 hours old.
RETURNS_STALE_WATERMARK = datetime(2026, 9, 24, 6, 0, tzinfo=UTC)
FX_INGESTED_AT = datetime(2026, 9, 26, 17, 0, tzinfo=UTC)
# The treasury publisher failed for these dates in the broken reference extract.
FX_MISSING_DATES_BROKEN = (date(2026, 8, 20), date(2026, 8, 21))

# (code, name, key, order count, probability that an order is invoiced in USD)
REGIONS = (
    ("ON", "Ontario", 1, 420, 0.12),
    ("QC", "Québec", 2, 260, 0.05),
    ("BC", "British Columbia", 3, 240, 0.10),
    ("AB", "Alberta", 4, 200, 0.06),
)
# (code, name, key, order mix weight, amount range, probability of a return)
CATEGORIES = (
    ("DEV", "Devices", 1, 0.38, (350, 2400), 0.17),
    ("ACC", "Accessories", 2, 0.37, (25, 220), 0.07),
    ("SVC", "Services", 3, 0.25, (180, 1400), 0.03),
)
SEGMENTS = ("Consumer", "SMB", "Enterprise")
RETURN_REASONS = {
    "DEV": ("Defective", "Changed mind", "Wrong item"),
    "ACC": ("Changed mind", "Wrong item"),
    "SVC": ("Service cancelled",),
}
# Share of Ontario's (target - governed) gap carried by each category: Devices misses badly,
# Accessories and Services beat their plans modestly. Weights sum to 1.
ONTARIO_GAP_WEIGHTS = {"DEV": Decimal("1.30"), "ACC": Decimal("-0.12"), "SVC": Decimal("-0.18")}
ONTARIO_TARGET_POSITION = Decimal("0.42")  # target = governed + 42% of (naive - governed)

ORDER_COLUMNS = (
    "order_id",
    "event_id",
    "event_version",
    "order_timestamp_utc",
    "region_code",
    "category_code",
    "currency_code",
    "gross_amount",
    "customer_segment",
    "source_updated_at",
    "ingested_at",
)
RETURN_COLUMNS = (
    "return_id",
    "order_id",
    "return_timestamp_utc",
    "return_amount",
    "currency_code",
    "return_reason",
    "source_updated_at",
    "ingested_at",
)
FX_COLUMNS = (
    "rate_date",
    "from_currency",
    "to_currency",
    "rate",
    "published_at_utc",
    "ingested_at",
)
TARGET_COLUMNS = (
    "target_month",
    "region_code",
    "category_code",
    "target_cad",
    "approved_by_role",
    "approved_at_utc",
    "source_system",
)


class NarrativeInvariantError(RuntimeError):
    """The generated data would not tell the story the session depends on."""


def q2(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _round_to(value: Decimal, step: int) -> Decimal:
    return (value / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


@dataclass
class Scenario:
    orders: list[dict]
    returns_repaired: list[dict]
    returns_broken: list[dict]
    fx_repaired: list[dict]
    fx_broken: list[dict]
    targets: list[dict]
    summary: dict


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / 100


def _generate_orders(rng: random.Random) -> list[dict]:
    drafts = []
    weights = [c[3] for c in CATEGORIES]
    for region_code, _, _, count, usd_share in REGIONS:
        for _ in range(count):
            category = rng.choices(CATEGORIES, weights=weights)[0]
            low, high = category[4]
            drafts.append(
                {
                    "ts": MONTH_START + timedelta(seconds=rng.randint(0, MONTH_DAYS * 86400 - 1)),
                    "region_code": region_code,
                    "category_code": category[0],
                    "currency_code": "USD" if rng.random() < usd_share else "CAD",
                    "gross_amount": _money(rng, low, high),
                    "customer_segment": rng.choice(SEGMENTS),
                    "update_lag": rng.randint(0, 600),
                }
            )
    # One zero-value integration test order: excluded by the quarantine rule, not by luck.
    drafts.append(
        {
            "ts": datetime(2026, 8, 12, 9, 0, tzinfo=UTC),
            "region_code": "ON",
            "category_code": "ACC",
            "currency_code": "CAD",
            "gross_amount": Decimal("0.00"),
            "customer_segment": "Internal Test",
            "update_lag": 0,
        }
    )
    drafts.sort(key=lambda d: (d["ts"], d["region_code"], d["category_code"], d["gross_amount"]))

    orders = []
    for number, draft in enumerate(drafts, start=1):
        orders.append(
            {
                "order_id": f"SO-202608-{number:05d}",
                "event_id": f"CDC-{number:08d}",
                "event_version": 1,
                "order_timestamp_utc": draft["ts"],
                "region_code": draft["region_code"],
                "category_code": draft["category_code"],
                "currency_code": draft["currency_code"],
                "gross_amount": draft["gross_amount"],
                "customer_segment": draft["customer_segment"],
                "source_updated_at": draft["ts"] + timedelta(seconds=draft["update_lag"]),
                "ingested_at": ORDERS_INGESTED_AT,
            }
        )

    # The duplicate: a retried CDC batch replayed Ontario's largest CAD Devices order with a
    # new event id and a touched source_updated_at. Same order_id, same version, same amount.
    original = max(
        (
            o
            for o in orders
            if o["region_code"] == "ON" and o["category_code"] == "DEV"
            if o["currency_code"] == "CAD"
        ),
        key=lambda o: (o["gross_amount"], o["order_id"]),
    )
    replay = dict(original)
    replay["event_id"] = f"CDC-{len(orders) + 1:08d}"
    replay["source_updated_at"] = original["source_updated_at"] + timedelta(seconds=90)
    orders.insert(orders.index(original) + 1, replay)
    return orders


def _generate_returns(rng: random.Random, orders: list[dict]) -> list[dict]:
    probability = {c[0]: c[5] for c in CATEGORIES}
    latest_return = DEMO_CLOCK_UTC - timedelta(hours=6)
    drafts = []
    seen = set()
    for order in orders:
        if order["order_id"] in seen or order["gross_amount"] <= 0:
            continue
        seen.add(order["order_id"])
        if rng.random() >= probability[order["category_code"]]:
            continue
        ts = order["order_timestamp_utc"] + timedelta(seconds=rng.randint(86400, 30 * 86400))
        full_refund = rng.random() < 0.7
        share = Decimal(100) if full_refund else Decimal(rng.randint(20, 60))
        amount = q2(order["gross_amount"] * share / 100)
        reason = rng.choice(RETURN_REASONS[order["category_code"]])
        lag = rng.randint(60, 3600)
        if ts > latest_return:
            continue
        drafts.append((ts, order, amount, reason, lag))
    drafts.sort(key=lambda d: (d[0], d[1]["order_id"]))
    return [
        {
            "return_id": f"RMA-{number:06d}",
            "order_id": order["order_id"],
            "return_timestamp_utc": ts,
            "return_amount": amount,
            "currency_code": order["currency_code"],
            "return_reason": reason,
            "source_updated_at": ts + timedelta(seconds=lag),
            "ingested_at": RETURNS_REPAIRED_INGESTED_AT,
        }
        for number, (ts, order, amount, reason, lag) in enumerate(drafts, start=1)
    ]


def _stale_returns(returns: list[dict], orders_by_id: dict[str, dict]) -> list[dict]:
    """The broken extract: replication stopped at the watermark and one key is malformed."""
    stale = [
        dict(r, ingested_at=RETURNS_STALE_WATERMARK)
        for r in returns
        if r["source_updated_at"] <= RETURNS_STALE_WATERMARK
    ]
    # A legacy key-mapping view emitted Ontario's first Devices return with the old key format.
    victim = next(
        r
        for r in stale
        if orders_by_id[r["order_id"]]["region_code"] == "ON"
        and orders_by_id[r["order_id"]]["category_code"] == "DEV"
    )
    victim["order_id"] = victim["order_id"].replace("-", "")
    return stale


def _generate_fx(rng: random.Random) -> list[dict]:
    rate = Decimal("1.3710")
    rows = []
    for offset in range(MONTH_DAYS):
        day = (MONTH_START + timedelta(days=offset)).date()
        rate = (rate + Decimal(rng.randint(-40, 40)) / 10000).quantize(Decimal("0.0001"))
        rows.append(
            {
                "rate_date": day,
                "from_currency": "USD",
                "to_currency": "CAD",
                "rate": rate.quantize(Decimal("0.000001")),
                "published_at_utc": datetime(day.year, day.month, day.day, 21, 0, tzinfo=UTC),
                "ingested_at": FX_INGESTED_AT,
            }
        )
    return rows


def _latest_versions(orders: list[dict]) -> list[dict]:
    """Reference implementation of the Silver deduplication policy."""
    best: dict[str, dict] = {}
    for order in orders:
        key = (
            order["event_version"],
            order["source_updated_at"],
            order["ingested_at"],
            order["event_id"],
        )
        current = best.get(order["order_id"])
        if current is None or key > current[0]:
            best[order["order_id"]] = (key, order)
    return [order for _, order in best.values()]


def governed_net_by_region_category(
    orders: list[dict], returns: list[dict], fx: list[dict]
) -> dict[tuple[str, str], Decimal]:
    """Independent reference calculation of Net Revenue CAD (repaired inputs)."""
    rates = {(r["rate_date"], r["from_currency"]): r["rate"] for r in fx}
    governed = [
        o
        for o in _latest_versions(orders)
        if o["customer_segment"] != "Internal Test" and o["gross_amount"] > 0
    ]
    by_id = {o["order_id"]: o for o in governed}
    returned: dict[str, Decimal] = defaultdict(Decimal)
    for r in returns:
        order = by_id.get(r["order_id"])
        if order and r["currency_code"] == order["currency_code"] and r["return_amount"] > 0:
            returned[r["order_id"]] += r["return_amount"]
    totals: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for o in governed:
        if o["currency_code"] == "CAD":
            rate = Decimal(1)
        else:
            rate = rates[(o["order_timestamp_utc"].date(), o["currency_code"])]
        net = q2(o["gross_amount"] * rate) - q2(returned[o["order_id"]] * rate)
        totals[(o["region_code"], o["category_code"])] += net
    return dict(totals)


def naive_raw_by_category(orders: list[dict], region_code: str) -> dict[str, Decimal]:
    """What the ungoverned path sums: every raw row, any currency, no returns."""
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for o in orders:
        if o["region_code"] == region_code:
            totals[o["category_code"]] += o["gross_amount"]
    return dict(totals)


def _derive_targets(
    rng: random.Random, governed: dict[tuple[str, str], Decimal], naive_on: Decimal
) -> list[dict]:
    categories = [c[0] for c in CATEGORIES]
    targets: dict[tuple[str, str], Decimal] = {}

    governed_on = sum(governed[("ON", c)] for c in categories)
    if not naive_on > governed_on:
        raise NarrativeInvariantError("naive raw revenue must exceed governed revenue")
    ontario_target = _round_to(
        governed_on + ONTARIO_TARGET_POSITION * (naive_on - governed_on), 1000
    )
    if not naive_on > ontario_target > governed_on:
        raise NarrativeInvariantError("no whole-thousand target fits between raw and governed")
    shortfall = ontario_target - governed_on
    for c in ("ACC", "SVC"):
        targets[("ON", c)] = _round_to(
            governed[("ON", c)] + ONTARIO_GAP_WEIGHTS[c] * shortfall, 100
        )
    targets[("ON", "DEV")] = ontario_target - targets[("ON", "ACC")] - targets[("ON", "SVC")]

    for region_code, *_ in REGIONS[1:]:
        governed_region = sum(governed[(region_code, c)] for c in categories)
        factor = Decimal(rng.randint(970, 1030)) / 1000
        region_target = _round_to(governed_region * factor, 1000)
        allocated = Decimal(0)
        for c in categories[1:]:
            share = governed[(region_code, c)] / governed_region
            targets[(region_code, c)] = _round_to(region_target * share, 100)
            allocated += targets[(region_code, c)]
        targets[(region_code, categories[0])] = region_target - allocated

    return [
        {
            "target_month": TARGET_MONTH,
            "region_code": region_code,
            "category_code": c,
            "target_cad": q2(targets[(region_code, c)]),
            "approved_by_role": "Finance Business Owner (FP&A)",
            "approved_at_utc": datetime(2026, 7, 15, 14, 0, tzinfo=UTC),
            "source_system": "finance.planning",
        }
        for region_code, *_ in REGIONS
        for c in categories
    ]


def _verify_invariants(
    orders: list[dict],
    returns_broken: list[dict],
    returns_repaired: list[dict],
    fx_broken: list[dict],
    fx_repaired: list[dict],
    targets: list[dict],
    governed: dict[tuple[str, str], Decimal],
) -> dict:
    failures = []
    sla = health_contract().returns_freshness_sla_minutes

    ids = [o["order_id"] for o in orders]
    duplicated = sorted({i for i in ids if ids.count(i) > 1})
    if len(duplicated) != 1:
        failures.append(f"expected exactly one duplicated order, found {len(duplicated)}")

    broken_age = (DEMO_CLOCK_UTC - max(r["ingested_at"] for r in returns_broken)).total_seconds()
    repaired_age = (
        DEMO_CLOCK_UTC - max(r["ingested_at"] for r in returns_repaired)
    ).total_seconds()
    if broken_age / 60 <= sla:
        failures.append("broken returns extract must violate the freshness SLA")
    if repaired_age / 60 > sla:
        failures.append("repaired returns extract must satisfy the freshness SLA")

    order_ids = set(ids)
    orphans = [r for r in returns_broken if r["order_id"] not in order_ids]
    if len(orphans) != 1:
        failures.append(f"expected one orphan return in the broken extract, found {len(orphans)}")
    if any(r["order_id"] not in order_ids for r in returns_repaired):
        failures.append("repaired returns must have no orphan")

    usd_days = {o["order_timestamp_utc"].date() for o in orders if o["currency_code"] == "USD"}
    broken_days = {r["rate_date"] for r in fx_broken}
    repaired_days = {r["rate_date"] for r in fx_repaired}
    missing_broken = sorted(
        o["order_id"]
        for o in _latest_versions(orders)
        if o["currency_code"] == "USD" and o["order_timestamp_utc"].date() not in broken_days
    )
    if not missing_broken:
        failures.append("broken FX extract must leave at least one USD order unconvertible")
    if not any(o["region_code"] == "ON" and o["order_id"] in missing_broken for o in orders):
        failures.append("broken FX gap must affect Ontario")
    if not usd_days <= repaired_days:
        failures.append("repaired FX extract must cover every USD transaction date")

    target = {(t["region_code"], t["category_code"]): t["target_cad"] for t in targets}
    categories = [c[0] for c in CATEGORIES]
    naive_by_cat = naive_raw_by_category(orders, "ON")
    naive_on = sum(naive_by_cat.values())
    governed_on = sum(governed[("ON", c)] for c in categories)
    target_on = sum(target[("ON", c)] for c in categories)
    if not naive_on > target_on > governed_on:
        failures.append("required invariant naive_raw_revenue > target > governed_net_revenue")

    governed_var = {c: governed[("ON", c)] - target[("ON", c)] for c in categories}
    worst = min(governed_var, key=governed_var.get)
    if worst != "DEV" or governed_var["DEV"] >= 0:
        failures.append("Devices must be the largest negative governed contributor")
    raw_var = {c: naive_by_cat[c] - target[("ON", c)] for c in categories}
    raw_driver = max(raw_var, key=raw_var.get)
    if raw_var[raw_driver] <= 0:
        failures.append("the raw path must find a positive category driver")

    if failures:
        raise NarrativeInvariantError("; ".join(failures))

    return {
        "ontario_naive_raw_revenue": str(naive_on),
        "ontario_target_cad": str(target_on),
        "ontario_governed_net_revenue_cad": str(governed_on),
        "ontario_governed_variance_by_category": {c: str(v) for c, v in governed_var.items()},
        "ontario_raw_variance_by_category": {c: str(v) for c, v in raw_var.items()},
        "raw_positive_driver": raw_driver,
        "governed_largest_negative_category": worst,
        "duplicated_order_ids": duplicated,
        "orphan_return_ids": [r["return_id"] for r in orphans],
        "broken_missing_fx_order_count": len(missing_broken),
        "broken_returns_freshness_minutes": int(broken_age // 60),
        "repaired_returns_freshness_minutes": int(repaired_age // 60),
    }


def build_scenario(seed: int = DEMO_SEED) -> Scenario:
    rng = random.Random(seed)
    orders = _generate_orders(rng)
    returns_repaired = _generate_returns(rng, orders)
    orders_by_id = {o["order_id"]: o for o in orders}
    returns_broken = _stale_returns(returns_repaired, orders_by_id)
    fx_repaired = _generate_fx(rng)
    fx_broken = [r for r in fx_repaired if r["rate_date"] not in FX_MISSING_DATES_BROKEN]

    governed = governed_net_by_region_category(orders, returns_repaired, fx_repaired)
    naive_on = sum(naive_raw_by_category(orders, "ON").values())
    targets = _derive_targets(rng, governed, naive_on)
    checks = _verify_invariants(
        orders, returns_broken, returns_repaired, fx_broken, fx_repaired, targets, governed
    )
    summary = {
        "description": (
            "Reference figures computed by the generator's independent implementation. "
            "Used only by tests and verification; the application never reads this file."
        ),
        "disclaimer": (
            "A synthetic, production-inspired architecture scenario. "
            "It does not represent a real customer deployment."
        ),
        "seed": seed,
        "demo_clock_utc": iso_z(DEMO_CLOCK_UTC),
        "question": (
            "Did Ontario beat its August 2026 revenue target, "
            "and which product category drove the result?"
        ),
        "invariants": checks,
    }
    return Scenario(
        orders, returns_repaired, returns_broken, fx_repaired, fx_broken, targets, summary
    )


def _cell(value: object) -> str:
    if isinstance(value, datetime):
        return iso_z(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _write_csv(path: Path, columns: tuple[str, ...], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(columns)
        for row in rows:
            writer.writerow([_cell(row[c]) for c in columns])


def _reference_tables() -> dict[str, tuple[tuple[str, ...], list[dict]]]:
    regions = [
        {"region_key": k, "region_code": c, "region_name": n, "country_code": "CA"}
        for c, n, k, *_ in REGIONS
    ]
    categories = [
        {"category_key": k, "category_code": c, "category_name": n} for c, n, k, *_ in CATEGORIES
    ]
    calendar = []
    for offset in range(MONTH_DAYS):
        day = (MONTH_START + timedelta(days=offset)).date()
        calendar.append(
            {
                "date_key": int(day.strftime("%Y%m%d")),
                "calendar_date": day,
                "year": day.year,
                "month": day.month,
                "day_of_month": day.day,
                "year_month": day.strftime("%Y-%m"),
                "month_name": day.strftime("%B"),
                "day_name": day.strftime("%A"),
            }
        )
    metadata = contract_metadata_rows()
    return {
        "regions.csv": (("region_key", "region_code", "region_name", "country_code"), regions),
        "categories.csv": (("category_key", "category_code", "category_name"), categories),
        "calendar.csv": (tuple(calendar[0]), calendar),
        "data_contract_metadata.csv": (("contract", "key", "value"), metadata),
    }


def write_scenario(scenario: Scenario, output_dir: Path = SAMPLE_DATA_DIR) -> list[Path]:
    files = {
        "azure-sql/orders.csv": (ORDER_COLUMNS, scenario.orders),
        "sql-server/returns.broken.csv": (RETURN_COLUMNS, scenario.returns_broken),
        "sql-server/returns.repaired.csv": (RETURN_COLUMNS, scenario.returns_repaired),
        "reference/fx_rates.broken.csv": (FX_COLUMNS, scenario.fx_broken),
        "reference/fx_rates.repaired.csv": (FX_COLUMNS, scenario.fx_repaired),
        "reference/targets.csv": (TARGET_COLUMNS, scenario.targets),
    }
    files.update({f"reference/{n}": spec for n, spec in _reference_tables().items()})
    written = []
    for relative, (columns, rows) in files.items():
        path = output_dir / relative
        _write_csv(path, columns, rows)
        written.append(path)

    summary = dict(scenario.summary)
    summary["files"] = {
        p.relative_to(output_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in written
    }
    summary_path = output_dir / "scenario_summary.json"
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return [*written, summary_path]


def generate(output_dir: Path = SAMPLE_DATA_DIR, seed: int = DEMO_SEED) -> Scenario:
    scenario = build_scenario(seed)
    write_scenario(scenario, output_dir)
    return scenario
