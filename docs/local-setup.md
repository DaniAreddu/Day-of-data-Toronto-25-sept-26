# Local setup

Runs completely offline after installation. No Fabric, Azure, OpenAI, Anthropic or Ollama
account is needed.

## Requirements

* Python 3.12 (3.13 also works; CI uses 3.12)
* Git

## Install

Windows PowerShell:

```powershell
git clone https://github.com/DaniAreddu/Day-of-data-Toronto-25-sept-26.git
cd Day-of-data-Toronto-25-sept-26
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

Bash:

```bash
git clone https://github.com/DaniAreddu/Day-of-data-Toronto-25-sept-26.git
cd Day-of-data-Toronto-25-sept-26
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

If PowerShell blocks activation, run
`Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` in that window, or call
`.\.venv\Scripts\python.exe` directly.

(The repository name contains "25-sept-26"; the session itself is on Saturday, 26 September 2026.)

## Verify

```bash
python scripts/generate_demo_data.py --check   # committed data reproduces byte for byte
python scripts/verify_demo.py                  # the three acts, offline
pytest
```

## Run

```bash
streamlit run app/streamlit_app.py
```

The app opens at <http://localhost:8501>. Usage statistics are disabled in
`.streamlit/config.toml`, and nothing is loaded from the internet. Runtime state lives in
`.demo-state/` (gitignored); **Reset Broken Scenario** recreates it in about two seconds.

CLI rehearsal without a browser:

```bash
ai-reliability-lab demo
```

## Regenerate the synthetic data

```bash
python scripts/generate_demo_data.py
```

Seed `20260926`, fixed demo clock `2026-09-26T18:00:00Z`. Generation fails if the narrative
invariants (`naive raw > target > governed`, Devices largest negative, one duplicate, stale
returns, FX gap, one orphan return) do not hold.

## Optional: Ollama narration

1. Install Ollama locally and pull a small model, for example `ollama pull llama3.2:3b`.
2. Set `NARRATOR=ollama` (and optionally `OLLAMA_MODEL`, `OLLAMA_URL`) or pick it in the sidebar.
3. The model only rewords the computed facts; any number not present in the facts causes a
   fallback to deterministic text. Refusals never go to the model. If Ollama is not running,
   the app falls back automatically and says so.

## Optional: Fabric SQL endpoint (read-only)

See [fabric-setup.md](fabric-setup.md#optional-read-fabric-from-the-local-app). Requires the
Microsoft ODBC Driver 18 and `pip install -e ".[fabric]"`.
