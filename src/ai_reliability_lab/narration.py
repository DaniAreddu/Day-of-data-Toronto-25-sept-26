"""Turn already-computed, validated facts into sentences.

Narrators never calculate, query, or decide. Two modes exist:

* ``deterministic`` (default): string templates over the computed facts. No model is involved,
  and the UI labels it exactly that way.
* ``ollama`` (optional): a local model rewrites the structured JSON facts. Its output is
  rejected if it contains any number that is not present in the facts; the deterministic text
  is used instead. The model is never consulted for a refusal.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from decimal import Decimal

from .clock import format_utc
from .models import QUESTION, GovernedAnswer, RawAnswer, Refusal, to_facts

DETERMINISTIC_LABEL = "Deterministic conference fallback — no live LLM"
REFUSAL_LABEL = "Deterministic refusal — enforced in data-access code; no model consulted"
MINUS = "−"


@dataclass(frozen=True)
class Narration:
    text: str
    label: str
    mode: str
    fallback_reason: str | None = None


class NarrationRejected(ValueError):
    """The model output could not be trusted to restate the facts."""


def cad(value: Decimal, *, signed: bool = False) -> str:
    text = f"CAD {abs(value):,.2f}"
    if not signed:
        return text if value >= 0 else f"{MINUS}{text}"
    return f"+{text}" if value >= 0 else f"{MINUS}{text}"


def pct(value: Decimal) -> str:
    return f"+{value:.2f}%" if value >= 0 else f"{MINUS}{abs(value):.2f}%"


def deterministic_raw(raw: RawAnswer) -> str:
    verdict = "Yes. Ontario beat" if raw.beat_target else "No. Ontario missed"
    return (
        f"{verdict} its August 2026 revenue target: revenue was {cad(raw.revenue)} against a "
        f"target of {cad(raw.target)}, a variance of {cad(raw.variance, signed=True)} "
        f"({pct(raw.variance_pct)}). {raw.driver.category_name} drove the result, finishing "
        f"{cad(raw.driver.variance_cad, signed=True)} versus its category target."
    )


def deterministic_governed(answer: GovernedAnswer) -> str:
    verdict = "Yes. Ontario beat" if answer.beat_target else "No. Ontario missed"
    text = (
        f"{verdict} its August 2026 target. {answer.metric_display_name} was "
        f"{cad(answer.net_revenue)} against a target of {cad(answer.target)}, a variance of "
        f"{cad(answer.variance, signed=True)} ({pct(answer.variance_pct)}). "
    )
    if answer.largest_negative is not None:
        worst = answer.largest_negative
        text += (
            f"{worst.category_name} was the largest negative contributor at "
            f"{cad(worst.variance_cad, signed=True)} versus its category target. "
        )
    else:
        text += "No category finished below its target. "
    text += (
        f"Evidence: pipeline run {answer.pipeline_run_id}, refreshed "
        f"{format_utc(answer.refresh_utc)}, data contract {answer.data_contract_version}, "
        f"status {answer.quality_status}."
    )
    return text


_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _allowed_numbers(facts: dict) -> set[str]:
    allowed = set()
    for token in _NUMBER.findall(json.dumps(facts) + QUESTION):
        plain = token.replace(",", "")
        allowed.add(plain)
        if "." in plain:
            allowed.add(plain.rstrip("0").rstrip("."))
            allowed.add(plain.split(".")[0])
    return allowed


def check_numbers(text: str, facts: dict) -> None:
    allowed = _allowed_numbers(facts)
    unknown = [t for t in _NUMBER.findall(text) if t.replace(",", "").rstrip(".") not in allowed]
    if unknown:
        raise NarrationRejected(f"model output contains numbers not in the facts: {unknown[:5]}")


class OllamaNarrator:
    def __init__(self, url: str, model: str, timeout: float = 45.0) -> None:
        self.url = url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def _post(self, path: str, payload: dict, timeout: float) -> dict:
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    def available(self) -> bool:
        try:
            with urllib.request.urlopen(self.url + "/api/tags", timeout=1.5) as response:
                return response.status == 200
        except (OSError, ValueError):
            return False

    def narrate(self, facts: dict) -> str:
        prompt = (
            "You narrate results for a data platform demonstration. Rewrite the JSON facts as "
            "two or three plain English sentences that answer the question. Use only facts "
            "present in the JSON and copy every number exactly as written. Do not calculate, "
            "round, estimate or add any number or claim.\n\n"
            f"Question: {QUESTION}\n\nFacts (JSON):\n{json.dumps(facts, indent=2)}\n"
        )
        body = self._post(
            "/api/generate",
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0},
            },
            self.timeout,
        )
        text = str(body.get("response", "")).strip()
        if not text:
            raise NarrationRejected("model returned an empty response")
        check_numbers(text, facts)
        return text


def _facts(result: RawAnswer | GovernedAnswer) -> dict:
    facts = to_facts(result)
    facts["answer_path"] = "raw_ungoverned" if isinstance(result, RawAnswer) else "governed"
    facts.pop("governance", None)
    return facts


def narrate(
    result: RawAnswer | GovernedAnswer | Refusal,
    mode: str = "deterministic",
    ollama: OllamaNarrator | None = None,
) -> Narration:
    if isinstance(result, Refusal):
        return Narration(result.message, REFUSAL_LABEL, "deterministic")

    fallback = deterministic_raw(result) if isinstance(result, RawAnswer) else None
    if fallback is None:
        fallback = deterministic_governed(result)
    if mode != "ollama" or ollama is None:
        return Narration(fallback, DETERMINISTIC_LABEL, "deterministic")

    try:
        text = ollama.narrate(_facts(result))
    except (OSError, urllib.error.URLError, ValueError) as exc:
        return Narration(
            fallback,
            DETERMINISTIC_LABEL,
            "deterministic",
            fallback_reason=f"Ollama narration unavailable ({exc}); used deterministic text.",
        )
    return Narration(
        text,
        f"Local LLM via Ollama ({ollama.model}) — narrating validated JSON facts only",
        "ollama",
    )
