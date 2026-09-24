"""Configuration from environment variables only (optionally seeded from a local .env)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SAMPLE_DATA_DIR = REPO_ROOT / "sample-data"
CONTRACTS_DIR = REPO_ROOT / "contracts"
FABRIC_SQL_DIR = REPO_ROOT / "fabric" / "sql"

BACKENDS = ("duckdb", "fabric")
NARRATORS = ("deterministic", "ollama")


def load_dotenv(path: Path = REPO_ROOT / ".env") -> None:
    """Minimal .env loader. Existing environment variables always win."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    backend: str
    narrator: str
    state_dir: Path
    fabric_server: str
    fabric_database: str
    fabric_user: str
    fabric_odbc_driver: str
    ollama_url: str
    ollama_model: str

    @property
    def duckdb_path(self) -> Path:
        return self.state_dir / "lakehouse.duckdb"


def _choice(name: str, default: str, allowed: tuple[str, ...]) -> str:
    value = os.environ.get(name, default).strip().lower() or default
    if value not in allowed:
        raise ValueError(f"{name}={value!r} is not supported; use one of {', '.join(allowed)}")
    return value


def get_settings() -> Settings:
    load_dotenv()
    state_dir = Path(os.environ.get("DEMO_STATE_DIR", ".demo-state"))
    if not state_dir.is_absolute():
        state_dir = REPO_ROOT / state_dir
    return Settings(
        backend=_choice("DEMO_BACKEND", "duckdb", BACKENDS),
        narrator=_choice("NARRATOR", "deterministic", NARRATORS),
        state_dir=state_dir,
        fabric_server=os.environ.get("FABRIC_SQL_SERVER", "").strip(),
        fabric_database=os.environ.get("FABRIC_SQL_DATABASE", "").strip(),
        fabric_user=os.environ.get("FABRIC_USER", "").strip(),
        fabric_odbc_driver=os.environ.get("FABRIC_ODBC_DRIVER", "ODBC Driver 18 for SQL Server"),
        ollama_url=os.environ.get("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        ollama_model=os.environ.get("OLLAMA_MODEL", "llama3.2:3b"),
    )
