"""AI Reliability Lab: the conference demo application.

Run with:  streamlit run app/streamlit_app.py

The UI only displays results computed by the data paths; it performs no business calculation.
Works fully offline with the default DuckDB backend and deterministic narrator.
"""

from __future__ import annotations

import altair as alt
import streamlit as st
import yaml

from ai_reliability_lab.backends.base import Backend, BackendUnavailable
from ai_reliability_lab.backends.duckdb import DuckDBBackend
from ai_reliability_lab.backends.fabric import FabricBackend
from ai_reliability_lab.clock import DEMO_CLOCK_UTC, format_utc
from ai_reliability_lab.config import CONTRACTS_DIR, NARRATORS, get_settings
from ai_reliability_lab.governed_path import ask_governed, read_health
from ai_reliability_lab.models import QUESTION, GovernedAnswer, HealthReport, RawAnswer, Refusal
from ai_reliability_lab.narration import OllamaNarrator, cad, narrate, pct
from ai_reliability_lab.observability import list_runs, quality_results, quarantined_rows
from ai_reliability_lab.pipeline import (
    PipelineFailed,
    reset_broken_scenario,
    run_governed_pipeline,
)
from ai_reliability_lab.queries import load_query
from ai_reliability_lab.raw_path import ask_raw

SESSION_TITLE = "Why AI Projects Fail: Data Platform Lessons Every Architect Should Know"
EVENT_LINE = (
    "Day of Data Toronto 2026 · Saturday, 26 September 2026 · 3:00–3:50 PM EDT · Room B · "
    "Daniele Mario Areddu"
)
DISCLAIMER = (
    "A synthetic, production-inspired architecture scenario. "
    "It does not represent a real customer deployment."
)
STATUS_COLOURS = {
    "READY": "#0a6b2d",
    "BLOCKED": "#b00020",
    "FAILED": "#6b0000",
    "RUNNING": "#8a5a00",
    "UNKNOWN": "#4a4a4a",
}

st.set_page_config(page_title="AI Reliability Lab", layout="wide")
st.markdown(
    """
<style>
html, body, [class*="st-"] { font-size: 19px; }
.arl-question { font-size: 1.55rem; font-weight: 700; line-height: 1.35;
  border-left: 8px solid #0b5cad; background: #eef3fa; color: #111;
  padding: 0.7rem 1.1rem; margin: 0.4rem 0 0.8rem 0; }
.arl-badge { display: inline-block; color: #fff; font-weight: 700;
  padding: 0.1rem 0.6rem; border-radius: 0.3rem; }
.arl-answer { font-size: 1.3rem; line-height: 1.45; }
</style>
""",
    unsafe_allow_html=True,
)

settings = get_settings()
state = st.session_state
state.setdefault("backend_name", settings.backend)
state.setdefault("narrator", settings.narrator)
state.setdefault("raw", None)
state.setdefault("raw_narration", None)
state.setdefault("governed", [])  # list of (label, result, narration)
state.setdefault("health_inspected", False)
state.setdefault("notice", None)


def badge(status: str) -> str:
    colour = STATUS_COLOURS.get(status, STATUS_COLOURS["UNKNOWN"])
    return f'<span class="arl-badge" style="background:{colour}">{status}</span>'


def variance_text(amount, percent) -> str:
    return f"{cad(amount, signed=True)} ({pct(percent)})"


def category_text(category) -> str:
    if category is None:
        return "none"
    return f"{category.category_name} ({cad(category.variance_cad, signed=True)})"


def get_backend() -> Backend:
    if state.backend_name == "fabric":
        if "fabric_backend" not in state:
            state.fabric_backend = FabricBackend(
                settings.fabric_server,
                settings.fabric_database,
                settings.fabric_user,
                settings.fabric_odbc_driver,
            )
        return state.fabric_backend
    backend = DuckDBBackend(settings.duckdb_path)
    if not backend.exists():
        reset_broken_scenario(backend)
    return backend


def ollama() -> OllamaNarrator | None:
    if state.narrator != "ollama":
        return None
    return OllamaNarrator(settings.ollama_url, settings.ollama_model)


def clear_answers() -> None:
    state.raw, state.raw_narration, state.governed = None, None, []


def switch_to_duckdb() -> None:
    """Button callback: runs before the rerun, so it may change the radio's state."""
    state.backend_name = "duckdb"
    state.notice = None
    clear_answers()


def safe_health(backend: Backend) -> HealthReport | None:
    try:
        return read_health(backend)
    except BackendUnavailable as exc:
        state.notice = ("error", str(exc))
        return None


# ---------------------------------------------------------------- sidebar
with st.sidebar:
    st.header("Demo settings")
    st.radio(
        "Backend",
        ["duckdb", "fabric"],
        key="backend_name",
        on_change=clear_answers,
        format_func=lambda b: "DuckDB (offline replica)" if b == "duckdb" else "Fabric (read-only)",
    )
    st.radio(
        "Narration",
        list(NARRATORS),
        key="narrator",
        format_func=lambda n: (
            "Deterministic (no LLM)" if n == "deterministic" else "Ollama (local)"
        ),
    )
    st.divider()
    st.caption(DISCLAIMER)
    st.caption(
        "Sources are synthetic CSV extracts representing an Azure SQL orders system and an "
        "on-premises SQL Server returns system. No live database is queried in DuckDB mode."
    )
    st.caption(
        "Narrators only restate computed facts. Figures, health checks and refusals are "
        "produced by data-access code, never by a model."
    )

# ---------------------------------------------------------------- header
st.title("AI Reliability Lab")
st.markdown(f"**{SESSION_TITLE}**  \n{EVENT_LINE}")
st.markdown(f'<div class="arl-question">{QUESTION}</div>', unsafe_allow_html=True)
status_area = st.container()

# ---------------------------------------------------------------- controls
is_local = state.backend_name == "duckdb"
local_only = None if is_local else "Read-only backend: run RefreshEnterpriseData in Fabric."
c1, c2, c3, c4, c5 = st.columns(5)
clicked_reset = c1.button(
    "Reset Broken Scenario", key="btn_reset", disabled=not is_local, help=local_only
)
clicked_raw = c2.button("Ask Raw System", key="btn_raw", type="primary")
clicked_health = c3.button("Inspect Platform Health", key="btn_health")
clicked_pipeline = c4.button(
    "Run Governed Pipeline", key="btn_pipeline", disabled=not is_local, help=local_only
)
clicked_governed = c5.button("Ask Governed System", key="btn_governed", type="primary")

try:
    backend = get_backend()
    if clicked_reset:
        result = reset_broken_scenario(backend)
        state.raw, state.raw_narration, state.governed = None, None, []
        state.health_inspected = False
        state.notice = ("success", f"Broken scenario restored ({result.run.pipeline_run_id}).")
    if clicked_raw:
        state.raw = ask_raw(backend)
        state.raw_narration = narrate(state.raw, state.narrator, ollama())
    if clicked_health:
        state.health_inspected = True
    if clicked_pipeline:
        with st.status("Running RefreshEnterpriseData (local replica)…", expanded=True) as box:
            st.write("Ingesting repaired extracts into Bronze…")
            result = run_governed_pipeline(backend)
            st.write("Silver: deduplication, FX conversion, returns reconciliation, quarantine")
            st.write(f"Quality gates evaluated: {len(result.quality_results)} checks")
            st.write(f"Gold published: {result.run.status == 'READY'}")
            box.update(label=f"Pipeline finished: {result.run.status}", state="complete")
        state.health_inspected = True
    if clicked_governed:
        answer = ask_governed(backend)
        stage = "after repair" if isinstance(answer, GovernedAnswer) else "while unhealthy"
        state.governed.append(
            (f"Governed ({stage})", answer, narrate(answer, state.narrator, ollama()))
        )
except (BackendUnavailable, PipelineFailed, FileNotFoundError, LookupError) as exc:
    state.notice = ("error", str(exc))
    backend = None

health = safe_health(backend) if backend is not None else None

with status_area:
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.markdown(f"**Backend**  \n{'DuckDB local replica' if is_local else 'Fabric SQL endpoint'}")
    narration_text = (
        "Deterministic — no live LLM"
        if state.narrator == "deterministic"
        else (f"Ollama ({settings.ollama_model}), local")
    )
    s2.markdown(f"**Narration**  \n{narration_text}")
    s3.markdown(f"**Demo as-of (fixed clock)**  \n{format_utc(DEMO_CLOCK_UTC)}")
    scenario = health.scenario_mode if health else "unknown"
    s4.markdown(f"**Scenario state**  \n{scenario}")
    status = health.status if health else "UNKNOWN"
    s5.markdown(f"**Data product status**  \n{badge(status)}", unsafe_allow_html=True)

if state.notice:
    kind, message = state.notice
    (st.error if kind == "error" else st.success)(message)
    if kind == "error" and not is_local:
        st.button("Switch to DuckDB", key="btn_switch", on_click=switch_to_duckdb)
    state.notice = None

# ---------------------------------------------------------------- answers
left, right = st.columns(2, gap="large")
with left:
    st.subheader("Raw Answer")
    raw: RawAnswer | None = state.raw
    if raw is None:
        st.info("Press **Ask Raw System** (Act 1).")
    else:
        st.markdown(badge("UNGOVERNED"), unsafe_allow_html=True)
        st.caption(state.raw_narration.label)
        if state.raw_narration.fallback_reason:
            st.caption(state.raw_narration.fallback_reason)
        st.markdown(
            f'<div class="arl-answer">{state.raw_narration.text}</div>', unsafe_allow_html=True
        )
        m1, m2, m3 = st.columns(3)
        m1.metric('"Revenue" (raw)', cad(raw.revenue))
        m2.metric("Target", cad(raw.target))
        m3.metric("Variance", cad(raw.variance, signed=True), pct(raw.variance_pct))
        st.markdown(
            f"**Driver:** {raw.driver.category_name} "
            f"({cad(raw.driver.variance_cad, signed=True)} vs category target)  \n"
            f"**Source freshness:** orders extract ingested "
            f"{format_utc(raw.latest_orders_ingested_at_utc)}; returns not consulted; "
            "no freshness SLA evaluated  \n"
            f"**Rows summed:** {raw.rows_scanned} raw rows, currencies "
            f"{', '.join(raw.currencies_summed)} added together"
        )
        st.markdown("**Governance indicators**")
        st.table([{"Control": k, "Raw path": f"✗ {v}"} for k, v in raw.governance.items()])

with right:
    st.subheader("Governed Answer")
    if not state.governed:
        st.info("Press **Ask Governed System** (Acts 2 and 3).")
    else:
        label, answer, narration = state.governed[-1]
        if isinstance(answer, Refusal):
            st.markdown(badge("REFUSED"), unsafe_allow_html=True)
            st.caption(narration.label)
            st.error(answer.message)
            st.markdown("**Blocking reasons**")
            for reason in answer.reasons:
                st.markdown(f"- {reason}")
        else:
            st.markdown(badge("TRUSTED"), unsafe_allow_html=True)
            st.caption(narration.label)
            if narration.fallback_reason:
                st.caption(narration.fallback_reason)
            st.markdown(f'<div class="arl-answer">{narration.text}</div>', unsafe_allow_html=True)
            g1, g2, g3 = st.columns(3)
            g1.metric(answer.metric_display_name, cad(answer.net_revenue))
            g2.metric("Target", cad(answer.target))
            g3.metric("Variance", cad(answer.variance, signed=True), pct(answer.variance_pct))
            st.markdown(
                f"**Largest negative category:** {category_text(answer.largest_negative)}  \n"
                f"**Semantic metric:** `{answer.metric_name}` v{answer.metric_version}  \n"
                f"**Definition:** {answer.metric_definition}  \n"
                f"**Refreshed:** {format_utc(answer.refresh_utc)} · "
                f"**Run:** `{answer.pipeline_run_id}`  \n"
                f"**Quality status:** {answer.quality_status} · "
                f"**Contract:** {answer.data_contract_version}  \n"
                f"**Lineage:** {' → '.join(answer.source_lineage)} → Gold → {answer.metric_name}"
            )

# ---------------------------------------------------------------- chart and comparison
trusted = next((a for _, a, _ in reversed(state.governed) if isinstance(a, GovernedAnswer)), None)
if state.raw is not None:
    st.subheader("Raw vs Target vs Governed")
    bars = [
        {"Measure": "Naive raw revenue", "CAD": float(state.raw.revenue), "Kind": "raw"},
        {"Measure": "Target", "CAD": float(state.raw.target), "Kind": "target"},
    ]
    if trusted is not None:
        bars.append(
            {
                "Measure": "Governed net revenue",
                "CAD": float(trusted.net_revenue),
                "Kind": "governed",
            }
        )
    else:
        st.caption("Governed net revenue is withheld until the data product is READY.")
    chart = (
        alt.Chart(alt.Data(values=bars))
        .mark_bar(size=46)
        .encode(
            y=alt.Y("Measure:N", sort=None, title=None, axis=alt.Axis(labelFontSize=16)),
            x=alt.X("CAD:Q", title="CAD", scale=alt.Scale(zero=False, nice=True)),
            color=alt.Color(
                "Kind:N",
                scale=alt.Scale(
                    domain=["raw", "target", "governed"], range=["#c0392b", "#6b6b6b", "#0b5cad"]
                ),
                legend=None,
            ),
            tooltip=["Measure:N", alt.Tooltip("CAD:Q", format=",.2f")],
        )
        .properties(height=60 * len(bars) + 30)
    )
    labels = chart.mark_text(align="left", dx=6, fontSize=16).encode(
        text=alt.Text("CAD:Q", format=",.2f"), color=alt.value("#111")
    )
    st.altair_chart(chart + labels, width="stretch")

if state.raw is not None or state.governed:
    st.subheader("Compare outcomes")
    rows = []
    if state.raw is not None:
        rows.append(
            {
                "Path": "Raw system (Act 1)",
                "Answer": "Beat target" if state.raw.beat_target else "Missed target",
                "Figure": cad(state.raw.revenue),
                "Variance": variance_text(state.raw.variance, state.raw.variance_pct),
                "Category": f"{state.raw.driver.category_name} (driver)",
                "Evidence": "none",
            }
        )
    for label, answer, _ in state.governed:
        if isinstance(answer, Refusal):
            rows.append(
                {
                    "Path": label,
                    "Answer": "Refused",
                    "Figure": "withheld",
                    "Variance": "withheld",
                    "Category": "withheld",
                    "Evidence": f"{answer.health.status} · {answer.health.pipeline_run_id}",
                }
            )
        else:
            worst = answer.largest_negative
            rows.append(
                {
                    "Path": label,
                    "Answer": "Beat target" if answer.beat_target else "Missed target",
                    "Figure": cad(answer.net_revenue),
                    "Variance": f"{cad(answer.variance, signed=True)} ({pct(answer.variance_pct)})",
                    "Category": f"{worst.category_name} (largest negative)" if worst else "none",
                    "Evidence": f"{answer.quality_status} · {answer.pipeline_run_id}",
                }
            )
    st.table(rows)

# ---------------------------------------------------------------- evidence tabs
tabs = st.tabs(
    [
        "Platform Health",
        "Data Quality",
        "Observability",
        "Semantic Contract",
        "SQL Evidence",
        "Lineage",
    ]
)


def show_health(report: HealthReport | None) -> None:
    if report is None:
        st.warning("No health record available.")
        return
    st.markdown(
        f"Data product `{report.data_product}` {badge(report.status)}", unsafe_allow_html=True
    )
    h1, h2, h3, h4 = st.columns(4)
    h1.metric(
        "Returns freshness",
        f"{report.returns_freshness_minutes:,} min"
        if report.returns_freshness_minutes is not None
        else "n/a",
        f"SLA {report.freshness_sla_minutes} min",
        delta_color="off",
    )
    h2.metric("Duplicates detected", report.duplicate_count)
    h3.metric("Missing FX", report.missing_fx_count)
    h4.metric("Orphan returns", report.orphan_return_count)
    h5, h6, h7, h8 = st.columns(4)
    h5.metric(
        "Orders freshness",
        f"{report.orders_freshness_minutes:,} min"
        if report.orders_freshness_minutes is not None
        else "n/a",
    )
    h6.metric("Quarantined rows", report.quarantined_rows)
    h7.metric("Unsupported currency", report.unsupported_currency_count)
    h8.metric("Contract version", report.data_contract_version)
    st.markdown(
        f"**Pipeline run:** `{report.pipeline_run_id}`  \n"
        f"**Last successful refresh:** {format_utc(report.last_successful_refresh_utc)}  \n"
        f"**Evaluated at (wall clock):** {format_utc(report.evaluated_at_utc)} · "
        f"**Scenario as-of:** {format_utc(report.as_of_utc)}"
    )
    if report.blocking_reasons:
        st.markdown("**Blocking quality gates**")
        for reason in report.blocking_reasons:
            st.markdown(f"- 🛑 {reason}")
    if report.warning_reasons:
        st.markdown("**Warnings (non-blocking)**")
        for reason in report.warning_reasons:
            st.markdown(f"- ⚠️ {reason}")


with tabs[0]:
    if not state.health_inspected and not state.governed:
        st.info("Press **Inspect Platform Health** to reveal the data-product health record.")
    else:
        show_health(health)

if backend is not None:
    try:
        with tabs[1]:
            st.markdown("**Quality gate results (current run)**")
            st.dataframe(quality_results(backend), hide_index=True, width="stretch")
            st.markdown("**Quarantined rows**")
            st.dataframe(quarantined_rows(backend), hide_index=True, width="stretch")
        with tabs[2]:
            runs = list_runs(backend)
            st.markdown("**gold_pipeline_runs** (newest first)")
            st.dataframe(
                [
                    {
                        "run id": r.pipeline_run_id,
                        "mode": r.scenario_mode,
                        "status": r.status,
                        "started (UTC)": format_utc(r.started_at_utc),
                        "completed (UTC)": format_utc(r.completed_at_utc),
                        "duration ms": r.duration_ms,
                        "bronze orders": r.bronze_order_rows,
                        "bronze returns": r.bronze_return_rows,
                        "silver sales": r.silver_sales_rows,
                        "quarantined": r.quarantined_rows,
                        "duplicates": r.duplicate_count,
                        "missing FX": r.missing_fx_count,
                        "orphans": r.orphan_return_count,
                        "freshness min": r.freshness_minutes,
                        "contract": r.data_contract_version,
                        "failure reasons": " | ".join(r.failure_reasons),
                    }
                    for r in runs
                ],
                hide_index=True,
                width="stretch",
            )
            st.caption(
                "The same fields are written by the Fabric notebook. In production they would feed "
                "enterprise monitoring and alerting (see architecture/trusted-platform.md)."
            )
    except BackendUnavailable as exc:
        st.error(str(exc))

with tabs[3]:
    metric = yaml.safe_load((CONTRACTS_DIR / "net_revenue.metric.yml").read_text(encoding="utf-8"))
    st.markdown(
        f"**{metric['display_name']}** "
        f"(`{metric['metric']}` v{metric['version']}, {metric['status']})  \n"
        f"**Owner:** {metric['owner_role']} · **Grain:** {metric['grain']}  \n"
        f"**Definition:** {metric['definition']}  \n"
        f"**Formula:** `{metric['formula']}`  \n"
        f"**Accepted currencies:** {', '.join(metric['accepted_currencies'])} · "
        f"**Freshness SLA:** returns {metric['freshness_sla_minutes']['returns']} min · "
        f"**Classification:** {metric['security_classification']}"
    )
    with st.expander("contracts/net_revenue.metric.yml"):
        st.code(
            (CONTRACTS_DIR / "net_revenue.metric.yml").read_text(encoding="utf-8"), language="yaml"
        )
    st.caption("The definition lives in a governed contract and in Gold, not in a prompt.")

with tabs[4]:
    with st.expander("Raw path: raw_answer.sql", expanded=state.raw is not None):
        st.code(load_query("raw_answer"), language="sql")
        if state.raw is not None:
            st.table(
                [
                    {
                        "category": c.category_name,
                        '"revenue"': f"{c.actual_cad:,.2f}",
                        "target": f"{c.target_cad:,.2f}",
                        "variance": f"{c.variance_cad:+,.2f}",
                    }
                    for c in state.raw.categories
                ]
            )
    with st.expander("Health gate: platform_health.sql"):
        st.code(load_query("platform_health"), language="sql")
    with st.expander("Governed path: governed_answer.sql"):
        st.code(load_query("governed_answer"), language="sql")
    with st.expander("Governed path: category_variance.sql", expanded=trusted is not None):
        st.code(load_query("category_variance"), language="sql")
        if trusted is not None:
            st.table(
                [
                    {
                        "category": c.category_name,
                        "net revenue CAD": f"{c.actual_cad:,.2f}",
                        "target": f"{c.target_cad:,.2f}",
                        "variance": f"{c.variance_cad:+,.2f}",
                    }
                    for c in trusted.categories
                ]
            )
    with st.expander("Pipeline evidence: pipeline_evidence.sql"):
        st.code(load_query("pipeline_evidence"), language="sql")

with tabs[5]:
    gate_status = health.status if health else "UNKNOWN"
    gold_colour = {"READY": "#d8f0df", "BLOCKED": "#f8d7da"}.get(
        health.status if health else "", "#eeeeee"
    )
    st.graphviz_chart(
        f"""
digraph lineage {{
  rankdir=LR;
  node [shape=box, style="rounded,filled", fillcolor="#ffffff", fontname="Helvetica"];
  orders [label="Azure SQL\\nOrders (synthetic extract)"];
  returns [label="SQL Server\\nReturns (synthetic extract)"];
  fx [label="Treasury\\nFX reference"];
  bronze [label="Bronze\\nas received"];
  silver [label="Silver\\ndedup · FX · reconcile · quarantine"];
  gates [label="Quality gates\\n{gate_status}", fillcolor="{gold_colour}"];
  gold [label="Gold\\nstar schema", fillcolor="{gold_colour}"];
  semantic [label="Semantic contract\\nNet Revenue CAD"];
  app [label="AI application\\n(answers or refuses)"];
  orders -> bronze; returns -> bronze; fx -> bronze;
  bronze -> silver -> gates -> gold -> semantic -> app;
}}
""",
        width="stretch",
    )
    st.caption(
        "Every Gold row carries its order event id, source systems and pipeline run id "
        "(see architecture/lineage.md)."
    )

st.divider()
st.caption(f"{DISCLAIMER} All timestamps are UTC. Session date: Saturday, 26 September 2026.")
