"""Fabric-asset checks: valid notebook, identical shared logic, no fabricated IDs or secrets."""

from __future__ import annotations

import ast
import importlib.util
import inspect
import json
import re
from pathlib import Path

import pytest

from ai_reliability_lab import medallion, quality

ROOT = Path(__file__).resolve().parents[1]
FABRIC = ROOT / "fabric"
NOTEBOOK = FABRIC / "notebooks" / "BuildTrustedLayer.ipynb"
NOTEBOOK_SOURCE = FABRIC / "notebooks" / "BuildTrustedLayer.py"

SHARED_CONSTANTS = {
    medallion: [
        "BRONZE_SOURCES",
        "SILVER_TRANSFORMS",
        "GOLD_DIMENSION_TRANSFORMS",
        "GOLD_FACT_TRANSFORMS",
        "OBSERVABILITY_SCHEMAS",
    ],
    quality: ["LATEST_INGESTION_SQL", "QUALITY_CHECK_SQL"],
}
SHARED_FUNCTIONS = [
    "format_sql",
    "freshness_minutes",
    "describe_check",
    "evaluate_check",
    "run_quality_checks",
    "summarise_health",
]
REQUIRED_MEASURES = [
    "Gross Revenue CAD",
    "Returns CAD",
    "Net Revenue CAD",
    "Revenue Target CAD",
    "Variance to Target CAD",
    "Variance to Target %",
    "Largest Negative Category",
    "Latest Refresh UTC",
    "Data Product Status",
    "Data Is Trusted",
]
GUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I)
SECRET_PATTERNS = [
    re.compile(p, re.I)
    for p in (
        r"password\s*=",
        r"\bpwd\s*=",
        r"accountkey\s*=",
        r"sharedaccesssignature",
        r"client_secret",
        r"bearer\s+[a-z0-9\-_.]{20,}",
        r"\bsk-[a-z0-9]{20,}",
        r"\bgh[pousr]_[a-z0-9]{20,}",
    )
]


def notebook_tree() -> ast.Module:
    return ast.parse(NOTEBOOK_SOURCE.read_text(encoding="utf-8"))


def load_builder():
    spec = importlib.util.spec_from_file_location(
        "builder", ROOT / "scripts" / "build_fabric_notebook.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_notebook_is_valid_json_and_generated_from_source():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    assert notebook["nbformat"] == 4
    assert notebook["metadata"]["kernelspec"]["name"] == "synapse_pyspark"
    assert NOTEBOOK.read_text(encoding="utf-8") == load_builder().render()


def test_notebook_has_the_required_cells():
    notebook = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
    code = ["".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "code"]
    parameters = [c for c in notebook["cells"] if "parameters" in c["metadata"].get("tags", [])]
    assert len(parameters) == 1
    params = "".join(parameters[0]["source"])
    assert 'scenario_mode = "broken"' in params and "demo_clock_utc" in params
    everything = "\n".join(code)
    for marker in (
        'spark.conf.set("spark.sql.session.timeZone", "UTC")',
        "def load_bronze",
        "def build_silver_and_dimensions",
        "def evaluate_quality",
        "def publish_gold",
        'f"{data_root}/{relative}"',
        "summarise_health(results)",
        "write_health(",
        "RAW_ANSWER_SQL",
        "GOVERNED_ANSWER_SQL",
        'if health["status"] != "READY" and fail_on_blocked',
    ):
        assert marker in everything, marker
    assert 'data_root = "Files/data"' in params


def test_notebook_shared_constants_match_the_package():
    assigned = {
        node.targets[0].id: node.value
        for node in notebook_tree().body
        if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name)
    }
    for module, names in SHARED_CONSTANTS.items():
        for name in names:
            assert ast.literal_eval(assigned[name]) == getattr(module, name), name


def test_notebook_shared_functions_match_the_package():
    notebook_functions = {
        node.name: ast.dump(node)
        for node in notebook_tree().body
        if isinstance(node, ast.FunctionDef)
    }
    for name in SHARED_FUNCTIONS:
        package_node = ast.parse(inspect.getsource(getattr(quality, name))).body[0]
        assert notebook_functions[name] == ast.dump(package_node), name


@pytest.mark.parametrize("name", ["raw_answer", "governed_answer", "category_variance"])
def test_notebook_inline_sql_matches_the_sql_files(name):
    assigned = {
        node.targets[0].id: ast.literal_eval(node.value)
        for node in notebook_tree().body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    inline = assigned[f"{name.upper()}_SQL"].strip()
    file_sql = (FABRIC / "sql" / f"{name}.sql").read_text(encoding="utf-8").strip().rstrip(";")
    assert inline == file_sql


def test_required_sql_files_exist():
    for name in (
        "raw_answer",
        "governed_answer",
        "platform_health",
        "category_variance",
        "pipeline_evidence",
        "quality_results",
        "source_lineage",
    ):
        text = (FABRIC / "sql" / f"{name}.sql").read_text(encoding="utf-8")
        assert text.lstrip().startswith("--"), f"{name}.sql should explain itself on screen"


def test_required_dax_measures_are_documented():
    dax = (FABRIC / "semantic-model" / "measures.dax").read_text(encoding="utf-8")
    defined = set(re.findall(r"^([A-Z][A-Za-z %()]+?) =\s*$", dax, re.M))
    for measure in REQUIRED_MEASURES:
        assert measure in defined, measure
    assert "gold_fact_sales[net_revenue_cad]" in dax
    setup = (FABRIC / "semantic-model" / "setup.md").read_text(encoding="utf-8")
    assert "TrustedBusinessMetrics" in setup


def test_pipeline_guide_names_the_pipeline_and_parameter():
    guide = (FABRIC / "pipeline" / "manual-setup.md").read_text(encoding="utf-8")
    assert "RefreshEnterpriseData" in guide
    assert "@pipeline().parameters.scenario_mode" in guide


def fabric_files():
    return [p for p in FABRIC.rglob("*") if p.is_file()]


def test_no_fabricated_fabric_identifiers():
    assert not [p for p in FABRIC.rglob(".platform")]
    for path in fabric_files():
        text = path.read_text(encoding="utf-8")
        assert not GUID.search(text), path
        for key in ('"logicalId"', '"workspaceId"', '"artifactId"', '"default_lakehouse"'):
            assert key not in text, (path, key)


def test_no_credentials_in_fabric_assets_or_sample_data():
    paths = fabric_files() + [p for p in (ROOT / "sample-data").rglob("*") if p.is_file()]
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for pattern in SECRET_PATTERNS:
            assert not pattern.search(text), (path, pattern.pattern)
