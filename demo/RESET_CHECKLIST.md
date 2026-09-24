# Reset checklist (under 30 seconds locally)

Use between rehearsals and immediately before the talk.

## Local app (DuckDB)

1. Press **Reset Broken Scenario** (≈2 seconds). It recreates `.demo-state/lakehouse.duckdb`
   from the canonical broken extracts, clears run history and resets the fixed demo clock
   (`2026-09-26 18:00:00 UTC`).
2. Confirm the status strip: Scenario state `broken`, Data product status **BLOCKED**.
3. Confirm the Raw and Governed panels show their "Press …" prompts.

If the app is not running, the same reset from a terminal:

```bash
ai-reliability-lab reset
```

A full offline rehearsal that leaves `.demo-state` untouched:

```bash
python scripts/verify_demo.py
```

The committed files in `sample-data/` are never modified by reset or repair. If you suspect
they were edited, run `python scripts/generate_demo_data.py --check` (and `git status`).

## Fabric

1. Run `RefreshEnterpriseData` with `scenario_mode = broken`. **Expected: Failed.**
2. `platform_health.sql` → `BLOCKED`, three blocking reasons.
3. `governed_answer.sql` → no rows.
4. `pipeline_evidence.sql` → exactly one run (BLOCKED).
5. Refresh any open Power BI report so it shows `Data Product Status = BLOCKED`.

## Done when

- [ ] Local status BLOCKED, no answers displayed
- [ ] Fabric health BLOCKED, Gold facts empty
- [ ] Browser tabs open in runbook order, notifications off
