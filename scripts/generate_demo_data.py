"""Regenerate the committed synthetic sample data (deterministic, byte-for-byte).

Usage:
    python scripts/generate_demo_data.py          # rewrite sample-data/
    python scripts/generate_demo_data.py --check  # fail if committed data differs
"""

from __future__ import annotations

import argparse
import filecmp
import sys
import tempfile
from pathlib import Path

from ai_reliability_lab.clock import DEMO_CLOCK_UTC, DEMO_SEED, iso_z
from ai_reliability_lab.config import SAMPLE_DATA_DIR
from ai_reliability_lab.generator import NarrativeInvariantError, generate


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify instead of writing")
    args = parser.parse_args()

    print(f"Seed {DEMO_SEED}, demo clock {iso_z(DEMO_CLOCK_UTC)}")
    try:
        if not args.check:
            scenario = generate(SAMPLE_DATA_DIR)
            inv = scenario.summary["invariants"]
            print(f"Wrote {SAMPLE_DATA_DIR}")
            print(
                f"Ontario naive raw {inv['ontario_naive_raw_revenue']}"
                f" > target {inv['ontario_target_cad']}"
                f" > governed {inv['ontario_governed_net_revenue_cad']}"
            )
            return 0

        with tempfile.TemporaryDirectory() as tmp:
            generate(Path(tmp))
            fresh = sorted(p.relative_to(tmp) for p in Path(tmp).rglob("*") if p.is_file())
            mismatched = [
                str(rel)
                for rel in fresh
                if not (SAMPLE_DATA_DIR / rel).is_file()
                or not filecmp.cmp(Path(tmp) / rel, SAMPLE_DATA_DIR / rel, shallow=False)
            ]
    except NarrativeInvariantError as exc:
        print(f"Narrative invariant failed: {exc}", file=sys.stderr)
        return 2

    if mismatched:
        print("Committed sample data differs from a fresh generation:", file=sys.stderr)
        for name in mismatched:
            print(f"  {name}", file=sys.stderr)
        print("Run: python scripts/generate_demo_data.py", file=sys.stderr)
        return 1
    print(f"OK: {len(fresh)} files reproduce byte for byte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
