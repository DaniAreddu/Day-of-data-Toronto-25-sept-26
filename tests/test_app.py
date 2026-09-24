"""Application smoke tests with Streamlit's AppTest (no browser, network, Fabric or Ollama)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from ai_reliability_lab.models import QUESTION

APP = str(Path(__file__).resolve().parents[1] / "app" / "streamlit_app.py")


def start() -> AppTest:
    at = AppTest.from_file(APP, default_timeout=60).run()
    assert not at.exception, at.exception
    return at


def click(at: AppTest, key: str) -> AppTest:
    at.button(key=key).click().run()
    assert not at.exception, at.exception
    return at


def page_text(at: AppTest) -> str:
    parts = (
        [m.value for m in at.markdown] + [e.value for e in at.error] + [c.value for c in at.caption]
    )
    return "\n".join(parts)


def test_app_imports_and_displays_the_question():
    at = start()
    assert at.title[0].value == "AI Reliability Lab"
    assert QUESTION in page_text(at)
    assert "Deterministic — no live LLM" in page_text(at)
    assert "2026-09-26 18:00:00 UTC" in page_text(at)


def test_full_demo_sequence():
    at = start()
    click(at, "btn_reset")
    assert "Broken scenario restored" in "\n".join(s.value for s in at.success)

    click(at, "btn_raw")
    assert "Yes. Ontario beat its August 2026 revenue target" in page_text(at)
    assert "Deterministic conference fallback — no live LLM" in page_text(at)

    click(at, "btn_health")
    assert "BLOCKED" in page_text(at)

    click(at, "btn_governed")
    assert any("I cannot provide a reliable answer" in e.value for e in at.error)

    click(at, "btn_pipeline")
    assert "READY" in page_text(at)

    click(at, "btn_governed")
    text = page_text(at)
    assert "No. Ontario missed its August 2026 target" in text
    assert "Devices was the largest negative contributor" in text
    comparison = next(t.value for t in at.table if "Answer" in t.value.columns)
    assert list(comparison["Answer"]) == ["Beat target", "Refused", "Missed target"]


def test_ollama_fallback_without_a_running_model(monkeypatch):
    monkeypatch.setenv("NARRATOR", "ollama")
    at = start()
    click(at, "btn_reset")
    click(at, "btn_raw")
    text = page_text(at)
    assert "Yes. Ontario beat" in text
    assert "Ollama narration unavailable" in text


@pytest.mark.parametrize("configured", [False, True])
def test_fabric_mode_without_credentials_does_not_crash(monkeypatch, configured):
    monkeypatch.setenv("DEMO_BACKEND", "fabric")
    if configured:  # settings present, but no driver, sign-in or network in CI
        monkeypatch.setenv("FABRIC_SQL_SERVER", "unreachable.invalid")
        monkeypatch.setenv("FABRIC_SQL_DATABASE", "AIPlatform")
        monkeypatch.setenv("FABRIC_USER", "presenter@example.invalid")
    at = start()
    click(at, "btn_raw")
    errors = "\n".join(e.value for e in at.error)
    assert "Fabric" in errors or "pyodbc" in errors
    assert at.button(key="btn_reset").disabled
    assert at.button(key="btn_pipeline").disabled
    click(at, "btn_switch")
    assert not at.button(key="btn_reset").disabled
    click(at, "btn_raw")
    assert "Yes. Ontario beat" in page_text(at)
