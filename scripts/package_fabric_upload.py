"""Build dist/fabric-upload/ (and dist/fabric-upload.zip) with only what Fabric needs.

Contents: synthetic source CSVs (broken and repaired), the notebook, SQL queries, DAX measures
and setup guides. Never included: .env, local databases, caches, Git metadata or app code.
"""

from __future__ import annotations

import argparse
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PACKAGE = DIST / "fabric-upload"

COPY = {
    "data/azure-sql": ROOT / "sample-data" / "azure-sql",
    "data/sql-server": ROOT / "sample-data" / "sql-server",
    "data/reference": ROOT / "sample-data" / "reference",
    "notebooks/BuildTrustedLayer.ipynb": ROOT / "fabric" / "notebooks" / "BuildTrustedLayer.ipynb",
    "sql": ROOT / "fabric" / "sql",
    "semantic-model": ROOT / "fabric" / "semantic-model",
    "pipeline/manual-setup.md": ROOT / "fabric" / "pipeline" / "manual-setup.md",
    "FABRIC_ASSETS.md": ROOT / "fabric" / "README.md",
    "FABRIC_SETUP_GUIDE.md": ROOT / "docs" / "fabric-setup.md",
}
ALLOWED_SUFFIXES = {".csv", ".ipynb", ".sql", ".dax", ".md"}


def build(make_zip: bool = True) -> list[Path]:
    if PACKAGE.exists():
        shutil.rmtree(PACKAGE)
    for target, source in COPY.items():
        destination = PACKAGE / target
        files = sorted(source.rglob("*")) if source.is_dir() else [source]
        for file in files:
            if not file.is_file() or file.suffix not in ALLOWED_SUFFIXES:
                continue
            out = destination / file.relative_to(source) if source.is_dir() else destination
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(file, out)
    packaged = sorted(p for p in PACKAGE.rglob("*") if p.is_file())
    if make_zip:
        archive = DIST / "fabric-upload.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in packaged:
                zf.write(file, file.relative_to(DIST).as_posix())
    return packaged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-zip", action="store_true", help="skip dist/fabric-upload.zip")
    args = parser.parse_args()
    files = build(make_zip=not args.no_zip)
    for file in files:
        print(file.relative_to(ROOT).as_posix())
    print(f"{len(files)} files in {PACKAGE.relative_to(ROOT).as_posix()}/")
    print("Upload the 'data' folder to the Lakehouse Files area so Files/data/... exists.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
