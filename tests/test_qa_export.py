"""Tests for the QA full-export tooling (stellaris_save_extractor.qa_export).

The QA export runs every "full" extractor method, dumps raw gamestate sections for
ground truth, and audits extraction health with a "silent-failure" smell check
(extracted collection empty while the raw section clearly has data). These are the
Stellaris 4.x failure modes tracked in issue #32.
"""

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellaris_save_extractor.qa_export import (
    EXPORT_METHODS,
    RAW_SECTIONS,
    collect_extraction,
    evaluate_smell,
    run_full_export,
)

TEST_SAVE = Path(__file__).parent.parent / "test_save.sav"


@pytest.fixture(scope="module")
def save_path():
    if not TEST_SAVE.exists():
        pytest.skip(f"test_save.sav not found at {TEST_SAVE}")
    return str(TEST_SAVE)


class _FakeExtractor:
    """Minimal extractor double exposing a couple of get_* methods."""

    def get_alpha(self):
        return {"count": 3}

    def get_boom(self):
        raise ValueError("kaboom")

    def get_with_kwargs(self, limit=5):
        return {"limit": limit}


def test_collect_extraction_captures_results_and_errors():
    methods = [("get_alpha", {}), ("get_boom", {}), ("get_with_kwargs", {"limit": 99})]
    result = collect_extraction(_FakeExtractor(), methods)

    assert result["get_alpha"] == {"count": 3}
    assert result["get_with_kwargs"] == {"limit": 99}
    # A crashing extractor method is a finding, not a crash of the whole export.
    assert "__error__" in result["get_boom"]
    assert "kaboom" in result["get_boom"]["__error__"]


# --- silent-failure smell check ---

_FLEET_RULE = [{"name": "fleets", "extracted": ("get_fleets", "fleets"), "raw_section": "fleet"}]


def test_smell_flags_empty_extraction_when_raw_has_data():
    extraction = {"get_fleets": {"fleets": []}}
    raw = {"fleet": {"1": {}, "2": {}}}

    flags = evaluate_smell(extraction, raw, _FLEET_RULE)

    assert len(flags) == 1
    assert flags[0]["name"] == "fleets"
    assert flags[0]["extracted_count"] == 0
    assert flags[0]["raw_count"] == 2


def test_smell_no_flag_when_extraction_present():
    extraction = {"get_fleets": {"fleets": [{"id": 1}]}}
    raw = {"fleet": {"1": {}, "2": {}}}

    assert evaluate_smell(extraction, raw, _FLEET_RULE) == []


def test_smell_no_flag_when_raw_also_empty():
    extraction = {"get_fleets": {"fleets": []}}
    raw = {"fleet": {}}

    assert evaluate_smell(extraction, raw, _FLEET_RULE) == []


def test_smell_accepts_raw_counts_as_ints():
    # run_full_export feeds smell a {section: count} mapping, not full raw dumps.
    extraction = {"get_fleets": {"fleets": []}}
    raw_counts = {"fleet": 5}

    flags = evaluate_smell(extraction, raw_counts, _FLEET_RULE)

    assert len(flags) == 1
    assert flags[0]["raw_count"] == 5


# --- full export orchestration (integration; needs test_save.sav) ---


def test_run_full_export_has_core_sections(save_path):
    export = run_full_export(save_path)
    assert {"metadata", "extraction", "raw_counts", "audit"} <= set(export)


def test_run_full_export_runs_every_registered_method(save_path):
    export = run_full_export(save_path)
    for name, _kwargs in EXPORT_METHODS:
        assert name in export["extraction"], f"missing extraction section: {name}"


def test_run_full_export_is_json_serializable(save_path):
    export = run_full_export(save_path)
    # The whole point is a clean JSON dump — must not raise.
    json.dumps(export)


def test_run_full_export_includes_raw_sections_when_requested(save_path):
    export = run_full_export(save_path, include_raw=True)
    assert "raw_sections" in export


def test_run_full_export_metadata_records_save_path(save_path):
    export = run_full_export(save_path)
    assert export["metadata"]["save_path"]


def test_run_full_export_raw_counts_only_requested_sections(save_path):
    # The Rust bridge envelope adds keys like game/schema_version/tool_version;
    # raw_counts must contain only the sections we asked for.
    export = run_full_export(save_path)
    assert set(export["raw_counts"]).issubset(set(RAW_SECTIONS))


# --- CLI entry point (unit; run_full_export stubbed) ---


def test_main_writes_json_output_file(tmp_path, monkeypatch):
    import stellaris_save_extractor.qa_export as qa

    monkeypatch.setattr(
        qa, "run_full_export", lambda save_path, **kw: {"stub": True, "save": str(save_path)}
    )
    out = tmp_path / "export.json"

    rc = qa.main(["some_empire.sav", "-o", str(out)])

    assert rc == 0
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data == {"stub": True, "save": "some_empire.sav"}


def test_main_defaults_to_most_recent_save(tmp_path, monkeypatch):
    import stellaris_save_extractor.qa_export as qa

    monkeypatch.setattr(
        "stellaris_companion.save_loader.find_most_recent_save", lambda: "auto_found.sav"
    )
    captured = {}

    def _fake_export(save_path, **kw):
        captured["save_path"] = save_path
        return {"ok": True}

    monkeypatch.setattr(qa, "run_full_export", _fake_export)

    rc = qa.main(["-o", str(tmp_path / "e.json")])

    assert rc == 0
    assert captured["save_path"] == "auto_found.sav"
