"""Generate fabric/notebooks/BuildTrustedLayer.ipynb from its percent-format .py source.

Usage:
    python scripts/build_fabric_notebook.py          # write the .ipynb
    python scripts/build_fabric_notebook.py --check  # fail if the committed .ipynb is stale

The notebook carries no Fabric workspace, Lakehouse or item identifiers: the Lakehouse is
attached manually after import (see fabric/README.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fabric" / "notebooks" / "BuildTrustedLayer.py"
TARGET = ROOT / "fabric" / "notebooks" / "BuildTrustedLayer.ipynb"
CELL_MARKER = re.compile(r"^# %%(?P<rest>.*)$")


def _trim(lines: list[str]) -> list[str]:
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def parse_cells(text: str) -> list[dict]:
    cells: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        marker = CELL_MARKER.match(line)
        if marker:
            rest = marker.group("rest")
            current = {
                "kind": "markdown" if "[markdown]" in rest else "code",
                "tags": ["parameters"] if 'tags=["parameters"]' in rest else [],
                "lines": [],
            }
            cells.append(current)
        elif current is not None:
            current["lines"].append(line)
    return cells


def build_notebook(text: str) -> dict:
    nb_cells = []
    for index, cell in enumerate(parse_cells(text), start=1):
        lines = _trim(cell["lines"])
        if cell["kind"] == "markdown":
            lines = [line[2:] if line.startswith("# ") else line.lstrip("#") for line in lines]
        source = [line + "\n" for line in lines]
        if source:
            source[-1] = source[-1].rstrip("\n")
        base = {"id": f"cell-{index:02d}", "metadata": {}, "source": source}
        if cell["tags"]:
            base["metadata"] = {"tags": cell["tags"]}
        if cell["kind"] == "markdown":
            nb_cells.append({"cell_type": "markdown", **base})
        else:
            nb_cells.append({"cell_type": "code", "execution_count": None, "outputs": [], **base})
    return {
        "cells": nb_cells,
        "metadata": {
            "kernel_info": {"name": "synapse_pyspark"},
            "kernelspec": {
                "display_name": "Synapse PySpark",
                "language": "Python",
                "name": "synapse_pyspark",
            },
            "language_info": {"name": "python"},
            "description": "AI Reliability Lab: builds the governed net_revenue_cad data product.",
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }


def render() -> str:
    notebook = build_notebook(SOURCE.read_text(encoding="utf-8"))
    return json.dumps(notebook, indent=1, ensure_ascii=False) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    content = render()
    if args.check:
        if not TARGET.is_file() or TARGET.read_text(encoding="utf-8") != content:
            print(
                f"{TARGET} is stale. Run: python scripts/build_fabric_notebook.py", file=sys.stderr
            )
            return 1
        json.loads(TARGET.read_text(encoding="utf-8"))
        print(f"OK: {TARGET.relative_to(ROOT)} is valid JSON and matches its source.")
        return 0
    TARGET.write_text(content, encoding="utf-8", newline="\n")
    print(f"Wrote {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
