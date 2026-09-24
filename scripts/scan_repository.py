"""Repository hygiene scans used by CI: secrets and tool-attribution lines.

Usage:
    python scripts/scan_repository.py                 # both scans over tracked files
    python scripts/scan_repository.py --secrets
    python scripts/scan_repository.py --attribution --commits

The attribution scan looks for authorship or promotional attribution lines only. Ordinary
documentation that mentions a tool by name is not flagged.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".zip", ".pdf", ".pptx", ".duckdb", ".ico"}

SECRET_PATTERNS = {
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----"),
    "password assignment": re.compile(
        r"\b(?:password|passwd|pwd)\s*[=:]\s*['\"]?[^\s'\";{}]{4,}", re.IGNORECASE
    ),
    "storage account key": re.compile(r"AccountKey=[A-Za-z0-9+/=]{20,}"),
    "SAS signature": re.compile(r"[?&]sig=[A-Za-z0-9%+/=]{20,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "GitHub token": re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    "OpenAI-style key": re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_-]{20,}\b"),
    "Slack token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    "client secret": re.compile(r"client_secret\s*[=:]\s*['\"]?[^\s'\"]{8,}", re.IGNORECASE),
}

# Assembled from fragments so this file does not match its own patterns.
_TOOL = "Cl" + "aude"
ATTRIBUTION_PATTERNS = {
    "co-author trailer": re.compile(r"Co-Authored-By:\s*" + _TOOL, re.IGNORECASE),
    "generated-by line": re.compile(r"Generated (?:by|with) \[?" + _TOOL, re.IGNORECASE),
    "tool promo link": re.compile(re.escape(_TOOL.lower() + ".com/" + _TOOL.lower() + "-code")),
    "tool noreply address": re.compile(r"noreply@" + "anthropic" + r"\.com", re.IGNORECASE),
}


def tracked_files() -> list[Path]:
    try:
        output = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout
    except (OSError, subprocess.CalledProcessError):
        return [p for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts]
    return [ROOT / name for name in output.decode("utf-8").split("\0") if name]


def scan_text(label: str, text: str, patterns: dict[str, re.Pattern]) -> list[str]:
    findings = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for name, pattern in patterns.items():
            if pattern.search(line):
                findings.append(f"{label}:{line_number}: {name}")
    return findings


def scan_files(patterns: dict[str, re.Pattern]) -> list[str]:
    findings = []
    for path in tracked_files():
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings += scan_text(path.relative_to(ROOT).as_posix(), text, patterns)
    return findings


def scan_commit_messages() -> list[str]:
    try:
        log = subprocess.run(
            ["git", "log", "--format=%H%n%B%n==END=="],
            cwd=ROOT,
            capture_output=True,
            check=True,
            text=True,
            encoding="utf-8",
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        return [f"git log unavailable: {exc}"]
    findings = []
    for block in log.split("==END=="):
        lines = block.strip().splitlines()
        if lines:
            findings += scan_text(
                f"commit {lines[0][:10]}", "\n".join(lines[1:]), ATTRIBUTION_PATTERNS
            )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--secrets", action="store_true")
    parser.add_argument("--attribution", action="store_true")
    parser.add_argument("--commits", action="store_true", help="also scan commit messages")
    args = parser.parse_args()
    run_all = not (args.secrets or args.attribution)

    findings: list[str] = []
    if args.secrets or run_all:
        secret_findings = scan_files(SECRET_PATTERNS)
        print(f"Secret scan: {len(secret_findings)} finding(s)")
        findings += secret_findings
    if args.attribution or run_all:
        attribution = scan_files(ATTRIBUTION_PATTERNS)
        if args.commits or run_all:
            attribution += scan_commit_messages()
        print(f"Attribution scan: {len(attribution)} finding(s)")
        findings += attribution

    for finding in findings:
        print(f"  {finding}", file=sys.stderr)
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
