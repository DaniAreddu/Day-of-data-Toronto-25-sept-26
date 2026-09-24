"""Command-line version of the demo sequence (useful for rehearsal and CI smoke tests)."""

from __future__ import annotations

import argparse
import sys

from .backends.base import Backend, BackendUnavailable
from .backends.duckdb import DuckDBBackend
from .backends.fabric import FabricBackend
from .clock import DEMO_CLOCK_UTC, format_utc
from .config import Settings, get_settings
from .governed_path import ask_governed, read_health
from .models import QUESTION, Refusal
from .narration import OllamaNarrator, narrate
from .pipeline import reset_broken_scenario, run_governed_pipeline
from .raw_path import ask_raw


def make_backend(settings: Settings) -> Backend:
    if settings.backend == "fabric":
        return FabricBackend(
            settings.fabric_server,
            settings.fabric_database,
            settings.fabric_user,
            settings.fabric_odbc_driver,
        )
    return DuckDBBackend(settings.duckdb_path)


def _local(backend: Backend) -> DuckDBBackend:
    if not isinstance(backend, DuckDBBackend):
        raise SystemExit(
            "The Fabric backend is read-only: run the RefreshEnterpriseData pipeline in Fabric."
        )
    return backend


def _say(result, settings: Settings) -> None:
    ollama = None
    if settings.narrator == "ollama":
        ollama = OllamaNarrator(settings.ollama_url, settings.ollama_model)
    narration = narrate(result, settings.narrator, ollama)
    print(f"[{narration.label}]")
    if narration.fallback_reason:
        print(f"  note: {narration.fallback_reason}")
    print(f"  {narration.text}")


def use_utf8_console() -> None:
    """Windows consoles default to a legacy code page; narration uses Unicode signs."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    use_utf8_console()
    parser = argparse.ArgumentParser(prog="ai-reliability-lab", description=__doc__)
    parser.add_argument(
        "command",
        choices=["reset", "ask-raw", "health", "run-pipeline", "ask-governed", "demo"],
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    backend = make_backend(settings)

    try:
        if args.command in ("reset", "demo"):
            run = reset_broken_scenario(_local(backend)).run
            print(f"Reset: {run.pipeline_run_id} -> {run.status}")
        if args.command == "demo":
            print(f"Question: {QUESTION}")
            print(f"Scenario as-of (fixed demo clock): {format_utc(DEMO_CLOCK_UTC)}")
        if args.command in ("ask-raw", "demo"):
            print("\nAct 1 - raw system")
            _say(ask_raw(backend), settings)
        if args.command in ("health", "demo"):
            health = read_health(backend)
            print("\nPlatform health")
            if health is None:
                print("  no health record")
            else:
                print(f"  status {health.status}, run {health.pipeline_run_id}")
                for reason in health.blocking_reasons:
                    print(f"  BLOCKING {reason}")
                for reason in health.warning_reasons:
                    print(f"  WARNING  {reason}")
        if args.command == "demo":
            print("\nAct 2 - governed system before repair")
            _say(ask_governed(backend), settings)
        if args.command in ("run-pipeline", "demo"):
            run = run_governed_pipeline(_local(backend)).run
            print(f"\nPipeline {run.pipeline_run_id} -> {run.status} in {run.duration_ms} ms")
        if args.command in ("ask-governed", "demo"):
            print("\nAct 3 - governed system" if args.command == "demo" else "Governed system")
            result = ask_governed(backend)
            _say(result, settings)
            if isinstance(result, Refusal) and args.command == "ask-governed":
                return 3
    except BackendUnavailable as exc:
        print(f"Backend unavailable: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
