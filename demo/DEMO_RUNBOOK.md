# Demo runbook: AI Reliability Lab (10 minutes)

Session: *Why AI Projects Fail: Data Platform Lessons Every Architect Should Know*.
Day of Data Toronto 2026, Saturday, 26 September 2026, 3:00–3:50 PM EDT, Room B.
The demo slot is minutes 28–38 of the talk (see [SPEAKER_SCRIPT.md](SPEAKER_SCRIPT.md)).

*A synthetic, production-inspired architecture scenario. It does not represent a real customer
deployment.* Say this once, out loud, before Act 1.

## Before going on stage (T-30 minutes)

- [ ] **Reset the local scenario:** `python scripts/verify_demo.py` (all checks pass), then start
      the app and press **Reset Broken Scenario**.
- [ ] **Verify the DuckDB fallback:** sidebar Backend = *DuckDB (offline replica)*, Narration =
      *Deterministic (no LLM)*. Turn Wi-Fi off once and click through Acts 1–3; turn it back on.
- [ ] **Verify Fabric login:** open the `DayOfDataToronto-Dev` workspace in the browser and sign in.
- [ ] **Verify the Fabric pipeline:** run `RefreshEnterpriseData` with `scenario_mode = broken`
      (expected: **Failed**) so Fabric is in the broken state.
- [ ] **Verify the SQL endpoint:** `platform_health.sql` shows `BLOCKED`; `governed_answer.sql`
      returns no rows.
- [ ] **Screen scaling:** projector at 1920×1080; browser zoom 125–150% so the question and
      answers are readable from the back row. Hide the bookmarks bar.
- [ ] **Disable notifications:** Windows Focus / Do Not Disturb, close chat and mail clients.
- [ ] **Open browser tabs, in order:** (1) AI Reliability Lab (`localhost:8501`),
      (2) Fabric pipeline `RefreshEnterpriseData`, (3) SQL analytics endpoint with the four
      queries in separate tabs, (4) Monitor hub.
- [ ] **Start Streamlit:** `streamlit run app/streamlit_app.py`; leave the terminal minimised.
- [ ] **Optional: start Ollama** (`ollama serve`) and switch Narration to *Ollama* only if it
      was rehearsed today. Otherwise stay deterministic.
- [ ] **Keep offline mode ready:** DuckDB is the default; nothing in Acts 1–3 needs internet.
- [ ] **Backup video (optional):** if screen-recording tooling is available, record one clean
      run-through the day before. It is a nice-to-have, not a requirement.

## Live sequence

### Minute 0–2: Raw answer (Act 1)

1. Point at the question banner and read it aloud:
   > Did Ontario beat its August 2026 revenue target, and which product category drove the result?
2. Press **Ask Raw System**.
3. Show the confident answer, the three metrics and "Devices drove the result".

Say:

> The answer looks precise, the SQL ran successfully, and nothing crashed.

### Minute 2–4: Reveal the platform

1. Open the **SQL Evidence** tab → *raw_answer.sql*. Point at `FROM bronze_orders` and
   `SUM(o.gross_amount) AS revenue`.
2. Back in the Raw Answer panel, walk down the **Governance indicators**: no metric definition,
   non-CAD rows summed as CAD, no deduplication, returns not consulted, no freshness check.
3. Press **Inspect Platform Health** and open the **Platform Health** tab:
   returns feed 3,600 minutes old against a 240-minute SLA, missing FX, orphan return, and one
   duplicate order event.

Say:

> The model did not hallucinate. The platform gave it the wrong truth.

### Minute 4–6: Fail closed (Act 2)

1. Press **Ask Governed System**.
2. Show the red refusal and its three blocking reasons. Point at the label: *deterministic
   refusal, enforced in data-access code; no model consulted*.
3. Optional (Fabric tab): run `governed_answer.sql` on the SQL endpoint: no rows. The same gate
   holds in SQL.

Say:

> A production-grade AI system must be able to say: I cannot answer from unhealthy data.

> In production, refusing to answer is a feature, not a failure.

### Minute 6–8: Repair

1. Fabric tab: run `RefreshEnterpriseData` with `scenario_mode = repaired`. While Spark starts,
   come back to the app.
2. App: press **Run Governed Pipeline** (local replica of the same notebook logic).
3. Show the status box, then the **Data Quality** tab (all blocking checks PASS, warnings for the
   resolved duplicate and the quarantined test order) and the **Observability** tab (BLOCKED run,
   then READY run with row counts and duration).
4. The status strip turns **READY**. If the Fabric run has finished, show it succeeding in the
   Monitor hub.

### Minute 8–10: Trusted answer (Act 3)

1. Press **Ask Governed System** again: the same question.
2. Show: Ontario **missed** the target; Devices is the largest negative contributor.
3. Point at the semantic metric and definition, refresh timestamp, run id, quality status and
   lineage. Open the **Lineage** tab.
4. Scroll to **Raw vs Target vs Governed** and **Compare outcomes**.

Say:

> Same question. Same presentation layer. Different data contract.

Close with:

> Production AI does not begin with a prompt. It begins with a trustworthy data contract.

## If something goes wrong

See [FAILURE_FALLBACK.md](FAILURE_FALLBACK.md). The rule is simple: **never debug on stage**.
Switch to the local DuckDB flow and keep telling the story.
