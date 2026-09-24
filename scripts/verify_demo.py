"""Rehearse the whole demo offline and verify every narrative invariant.

Runs in a temporary state directory (your .demo-state is untouched), needs no network, Fabric
or Ollama, and exits non-zero if any act does not behave as the talk requires.

Usage:  python scripts/verify_demo.py
"""

from __future__ import annotations

import sys
import tempfile
import time
from pathlib import Path

from ai_reliability_lab.backends.duckdb import DuckDBBackend
from ai_reliability_lab.cli import use_utf8_console
from ai_reliability_lab.clock import DEMO_CLOCK_UTC, DEMO_SEED, format_utc
from ai_reliability_lab.generator import build_scenario
from ai_reliability_lab.governed_path import ask_governed
from ai_reliability_lab.models import QUESTION, GovernedAnswer, Refusal
from ai_reliability_lab.narration import narrate
from ai_reliability_lab.pipeline import reset_broken_scenario, run_governed_pipeline
from ai_reliability_lab.raw_path import ask_raw


def main() -> int:
    use_utf8_console()
    failures: list[str] = []

    def check(condition: bool, message: str) -> None:
        print(f"  [{'ok' if condition else 'FAIL'}] {message}")
        if not condition:
            failures.append(message)

    print(f"Question: {QUESTION}")
    print(f"Seed {DEMO_SEED}; scenario as-of {format_utc(DEMO_CLOCK_UTC)}\n")
    reference = build_scenario().summary["invariants"]

    with tempfile.TemporaryDirectory() as tmp:
        backend = DuckDBBackend(Path(tmp) / "lakehouse.duckdb")

        started = time.perf_counter()
        reset = reset_broken_scenario(backend).run
        reset_seconds = time.perf_counter() - started
        print("Reset Broken Scenario")
        check(reset.status == "BLOCKED", f"health is BLOCKED after reset ({reset.pipeline_run_id})")
        check(reset_seconds < 30, f"reset completed in {reset_seconds:.1f}s (< 30s)")

        print("\nAct 1: raw system")
        raw = ask_raw(backend)
        print(f"  {narrate(raw).text}")
        check(raw.beat_target, "raw answer claims Ontario beat the target")
        check(
            raw.driver.variance_cad > 0, f"raw names a positive driver ({raw.driver.category_name})"
        )
        check(
            str(raw.revenue) == reference["ontario_naive_raw_revenue"],
            "raw figure matches the generator's independent calculation",
        )

        print("\nAct 2: governed system before repair")
        refusal = ask_governed(backend)
        print(f"  {narrate(refusal).text}")
        check(isinstance(refusal, Refusal), "governed path refuses while BLOCKED")
        if isinstance(refusal, Refusal):
            codes = [r.split(":")[0] for r in refusal.health.blocking_reasons]
            check(
                codes == ["RETURNS_FRESHNESS", "MISSING_FX", "ORPHAN_RETURNS"],
                f"blocking reasons: {', '.join(codes)}",
            )
            check(refusal.health.duplicate_count == 1, "duplicate order detected")

        print("\nRun Governed Pipeline")
        repaired = run_governed_pipeline(backend).run
        check(repaired.status == "READY", f"health is READY ({repaired.pipeline_run_id})")

        print("\nAct 3: governed system after repair")
        answer = ask_governed(backend)
        check(isinstance(answer, GovernedAnswer), "governed path answers when READY")
        if isinstance(answer, GovernedAnswer):
            print(f"  {narrate(answer).text}")
            check(not answer.beat_target, "governed answer: Ontario missed the target")
            check(raw.revenue > answer.target > answer.net_revenue, "naive > target > governed")
            worst = answer.largest_negative
            check(
                worst is not None and worst.category_name == "Devices",
                "Devices is the largest negative category",
            )
            check(
                str(answer.net_revenue) == reference["ontario_governed_net_revenue_cad"],
                "governed figure matches the generator's independent calculation",
            )
            check(answer.pipeline_run_id == repaired.pipeline_run_id, "evidence carries run id")
            check(answer.refresh_utc is not None, "evidence carries refresh timestamp")

        print("\nIdempotency")
        again = reset_broken_scenario(backend).run
        check(again.status == "BLOCKED", "a second reset restores the broken state")
        check(isinstance(ask_governed(backend), Refusal), "refusal is restored after reset")

    if failures:
        print(f"\n{len(failures)} check(s) failed.", file=sys.stderr)
        return 1
    print("\nAll demo checks passed (offline, deterministic narrator, DuckDB backend).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
