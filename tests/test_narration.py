"""Narration: deterministic by default, Ollama optional, never trusted with numbers."""

from __future__ import annotations

import json

import pytest

from ai_reliability_lab.governed_path import ask_governed
from ai_reliability_lab.narration import (
    DETERMINISTIC_LABEL,
    REFUSAL_LABEL,
    NarrationRejected,
    OllamaNarrator,
    check_numbers,
    narrate,
)
from ai_reliability_lab.raw_path import ask_raw


def test_deterministic_raw_narration_is_labelled_and_uses_computed_facts(broken_db):
    raw = ask_raw(broken_db)
    narration = narrate(raw)
    assert (
        narration.label == DETERMINISTIC_LABEL == "Deterministic conference fallback — no live LLM"
    )
    assert narration.text.startswith("Yes. Ontario beat")
    assert f"{raw.revenue:,.2f}" in narration.text
    assert raw.driver.category_name in narration.text


def test_deterministic_governed_narration(repaired_db):
    answer = ask_governed(repaired_db)
    narration = narrate(answer)
    assert narration.text.startswith("No. Ontario missed")
    assert f"{answer.net_revenue:,.2f}" in narration.text
    assert "Devices was the largest negative contributor" in narration.text
    assert answer.pipeline_run_id in narration.text


def test_refusal_never_consults_a_model(broken_db):
    class Forbidden(OllamaNarrator):
        def narrate(self, facts):
            raise AssertionError("the model must not be consulted for a refusal")

    refusal = ask_governed(broken_db)
    narration = narrate(refusal, "ollama", Forbidden("http://unused", "none"))
    assert narration.label == REFUSAL_LABEL
    assert narration.text == refusal.message


def test_unavailable_ollama_falls_back_to_deterministic(broken_db):
    offline = OllamaNarrator("http://127.0.0.1:9", "llama3.2:3b", timeout=1)
    assert not offline.available()
    narration = narrate(ask_raw(broken_db), "ollama", offline)
    assert narration.mode == "deterministic"
    assert narration.label == DETERMINISTIC_LABEL
    assert "Ollama narration unavailable" in narration.fallback_reason


class ScriptedOllama(OllamaNarrator):
    def __init__(self, reply: str):
        super().__init__("http://scripted", "scripted-model")
        self.reply = reply
        self.prompts = []

    def _post(self, path, payload, timeout):
        self.prompts.append(payload["prompt"])
        return {"response": self.reply}


def test_ollama_output_is_accepted_only_with_known_numbers(repaired_db):
    answer = ask_governed(repaired_db)
    faithful = ScriptedOllama(
        f"Ontario missed its target: net revenue was CAD {answer.net_revenue:,.2f} "
        f"versus CAD {answer.target:,.2f}."
    )
    narration = narrate(answer, "ollama", faithful)
    assert narration.mode == "ollama"
    assert "Ollama (scripted-model)" in narration.label
    facts = json.loads(faithful.prompts[0].split("Facts (JSON):\n", 1)[1])
    assert facts["net_revenue"] == str(answer.net_revenue)  # structured facts, not a free query

    inventive = ScriptedOllama("Ontario missed by CAD 12,345.67 because of the weather.")
    narration = narrate(answer, "ollama", inventive)
    assert narration.mode == "deterministic"
    assert "numbers not in the facts" in narration.fallback_reason


def test_number_guard():
    facts = {"net_revenue": "320475.66", "variance_pct": "-2.29"}
    check_numbers("Net revenue CAD 320,475.66 (-2.29%) for August 2026.", facts)
    with pytest.raises(NarrationRejected):
        check_numbers("Net revenue CAD 330,000.00", facts)
