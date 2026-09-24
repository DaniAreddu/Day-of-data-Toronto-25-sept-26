"""Documentation guards: correct date, honest labels, figures that match the data."""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = [
    ROOT / "README.md",
    *sorted((ROOT / "docs").glob("*.md")),
    *sorted((ROOT / "demo").glob("*.md")),
    *sorted((ROOT / "architecture").glob("*.md")),
    *sorted((ROOT / "fabric").rglob("*.md")),
    ROOT / "slides" / "README.md",
]
WRONG_DATE = re.compile(
    r"\b25(th)?\s+(of\s+)?sept(ember)?\b|\bsept(ember)?\s+25\b|2026-09-25", re.IGNORECASE
)
DISCLAIMER = "does not represent a real customer deployment"


def money(value: str, signed: bool = False) -> str:
    amount = Decimal(value)
    sign = ("+" if amount >= 0 else "−") if signed else ""
    return f"{sign}CAD {abs(amount):,.2f}"


@pytest.mark.parametrize("path", DOCS, ids=lambda p: p.relative_to(ROOT).as_posix())
def test_docs_exist_and_use_the_correct_date(path):
    text = path.read_text(encoding="utf-8")
    assert text.strip(), path
    assert not WRONG_DATE.search(text), WRONG_DATE.search(text).group(0)


def prose(path: Path) -> str:
    """Markdown text with line wrapping and blockquote markers removed."""
    return " ".join(path.read_text(encoding="utf-8").replace("\n>", "\n").split())


def test_readme_title_and_metadata():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.startswith(
        "# Why AI Projects Fail: Data Platform Lessons Every Architect Should Know\n"
    )
    for fact in ("Day of Data Toronto 2026", "Saturday, 26 September 2026", "Room B", DISCLAIMER):
        assert fact in prose(ROOT / "README.md"), fact


def test_synthetic_disclaimer_is_prominent():
    for relative in (
        "README.md",
        "fabric/README.md",
        "docs/fabric-setup.md",
        "demo/DEMO_RUNBOOK.md",
    ):
        assert DISCLAIMER in prose(ROOT / relative), relative


def test_documented_expected_results_match_the_generated_data(summary):
    inv = summary["invariants"]
    text = (ROOT / "fabric" / "README.md").read_text(encoding="utf-8")
    raw_variance = Decimal(inv["ontario_naive_raw_revenue"]) - Decimal(inv["ontario_target_cad"])
    gov_variance = Decimal(inv["ontario_governed_net_revenue_cad"]) - Decimal(
        inv["ontario_target_cad"]
    )
    for expected in (
        money(inv["ontario_naive_raw_revenue"]),
        money(inv["ontario_target_cad"]),
        money(inv["ontario_governed_net_revenue_cad"]),
        money(str(raw_variance), signed=True),
        money(str(gov_variance), signed=True),
        money(inv["ontario_raw_variance_by_category"]["DEV"], signed=True),
        money(inv["ontario_governed_variance_by_category"]["DEV"], signed=True),
        f"{inv['broken_returns_freshness_minutes']:,} minutes",
        f"{inv['broken_missing_fx_order_count']} orders without",
    ):
        assert expected in text, expected
