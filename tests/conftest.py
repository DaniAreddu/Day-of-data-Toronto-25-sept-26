from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from ai_reliability_lab.backends.duckdb import DuckDBBackend
from ai_reliability_lab.config import SAMPLE_DATA_DIR
from ai_reliability_lab.pipeline import reset_broken_scenario, run_governed_pipeline


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    """Never depend on a developer's .env, Fabric credentials or a running Ollama."""
    monkeypatch.setenv("DEMO_BACKEND", "duckdb")
    monkeypatch.setenv("NARRATOR", "deterministic")
    monkeypatch.setenv("DEMO_STATE_DIR", str(tmp_path / "state"))
    for name in ("FABRIC_SQL_SERVER", "FABRIC_SQL_DATABASE", "FABRIC_USER"):
        monkeypatch.setenv(name, "")
    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")


@pytest.fixture(scope="session")
def summary() -> dict:
    return json.loads((SAMPLE_DATA_DIR / "scenario_summary.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def broken_db(tmp_path_factory) -> DuckDBBackend:
    """Read-only use: the state right after 'Reset Broken Scenario'."""
    backend = DuckDBBackend(tmp_path_factory.mktemp("broken") / "lakehouse.duckdb")
    reset_broken_scenario(backend)
    return backend


@pytest.fixture(scope="session")
def repaired_db(tmp_path_factory) -> DuckDBBackend:
    """Read-only use: the state after reset followed by 'Run Governed Pipeline'."""
    backend = DuckDBBackend(tmp_path_factory.mktemp("repaired") / "lakehouse.duckdb")
    reset_broken_scenario(backend)
    run_governed_pipeline(backend)
    return backend


@pytest.fixture
def backend(tmp_path) -> DuckDBBackend:
    """A private database for tests that change state."""
    return DuckDBBackend(tmp_path / "lakehouse.duckdb")


@pytest.fixture
def inputs_copy(tmp_path) -> Path:
    """A writable copy of the canonical extracts (the committed fixtures are never mutated)."""
    target = tmp_path / "inputs"
    shutil.copytree(SAMPLE_DATA_DIR, target)
    return target
