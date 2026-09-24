# Failure fallback

Rule: **never debug on stage.** Every fallback below keeps the story intact, because the local
DuckDB replica runs the same logic offline.

| Symptom | Immediate action | What to say |
| --- | --- | --- |
| No internet / Fabric sign-in fails | Stay in the local app (DuckDB is the default). Skip the Fabric tabs. | "Everything you are about to see runs the same SQL that runs in Fabric. Here it is running on my laptop." |
| Fabric Spark session slow to start | Press **Run Governed Pipeline** locally and continue; come back to Monitor at the end if it finished. | "Trial capacity is warming up; the logic is identical locally." |
| Fabric pipeline fails in repaired mode | Continue locally. Afterwards check `Files/data` uploads and the parameters cell. | "Good: the platform refused to publish. We'll finish on the local replica." |
| App was started in Fabric mode and cannot connect | Press **Switch to DuckDB** (or pick DuckDB in the sidebar). | none needed |
| Ollama slow or not running | Switch Narration to *Deterministic*. The app falls back automatically anyway. | "The words change; the numbers do not. The model never calculates." |
| Streamlit page errors or freezes | Terminal: `Ctrl+C`, then `streamlit run app/streamlit_app.py`, then **Reset Broken Scenario** (under 30 s). | "Let me reset the scenario." |
| Browser unusable | Terminal: `ai-reliability-lab demo` prints all three acts. | "Same demo, command-line edition." |
| Laptop unusable | Slides with the three acts' screenshots (and the backup video, if one was recorded). | Tell the story from the slides. |

## Pre-talk sanity check (1 minute)

```bash
python scripts/verify_demo.py
```

All checks must say `[ok]`. If one does not, use the deterministic, DuckDB-only flow and
report the failing check after the session.
