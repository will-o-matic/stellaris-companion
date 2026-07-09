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
    _canonical,
    _json_safe,
    baseline_payload,
    collect_extraction,
    compare_baselines,
    evaluate_smell,
    run_full_export,
    write_baselines,
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


def test_json_safe_sorts_sets_for_determinism():
    # Sets have no stable iteration order; the export must serialise them
    # deterministically or regression baselines drift run-to-run.
    assert _json_safe({"x": {"b", "a", "c"}}) == {"x": ["a", "b", "c"]}
    assert _json_safe({"x": {3, 1, 2}}) == {"x": [1, 2, 3]}


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


# --- regression baselines (tier 3) ---


def _fake_export():
    return {
        "metadata": {
            "save_path": "x.sav",
            "exported_at": "2026-01-01T00:00:00",
            "tool_version": "1",
        },
        "extraction": {"get_fleets": {"fleets": [1, 2]}, "get_wars": {"wars": []}},
        "raw_counts": {"fleet": 2, "war": 0},
        "audit": {"smell": [], "validation": {"pass_rate": 90}},
    }


def test_baseline_payload_has_per_method_files_and_excludes_volatile_metadata():
    payload = baseline_payload(_fake_export())

    assert "get_fleets.json" in payload
    assert "get_wars.json" in payload
    assert "_raw_counts.json" in payload
    assert "_smell.json" in payload
    # Volatile metadata (exported_at, tool_version, save_path) must not be baselined.
    assert not any("metadata" in name for name in payload)


def test_write_and_compare_baselines_roundtrip(tmp_path):
    export = _fake_export()
    write_baselines(export, str(tmp_path))

    assert compare_baselines(export, str(tmp_path)) == []


def test_compare_baselines_detects_drift(tmp_path):
    export = _fake_export()
    write_baselines(export, str(tmp_path))

    drifted = _fake_export()
    drifted["extraction"]["get_fleets"]["fleets"] = [1, 2, 3]

    assert "get_fleets.json" in compare_baselines(drifted, str(tmp_path))


def test_canonical_strips_volatile_fields():
    # get_metadata embeds file_path (relative vs absolute) and modified (mtime);
    # these must not cause baseline drift across machines/paths.
    a = {"file_path": "/abs/path/test_save.sav", "modified": "2026-01-01T00:00:00", "date": "2242"}
    b = {"file_path": "test_save.sav", "modified": "2026-07-09T10:42:15", "date": "2242"}

    assert _canonical(a) == _canonical(b)


def test_compare_baselines_is_order_insensitive(tmp_path):
    # The extractor builds some lists by iterating sets, so element order can vary
    # across processes (hash seed). Regression comparison must ignore list order.
    export = _fake_export()
    write_baselines(export, str(tmp_path))

    reordered = _fake_export()
    reordered["extraction"]["get_fleets"]["fleets"] = [2, 1]  # same items, swapped

    assert compare_baselines(reordered, str(tmp_path)) == []


def test_compare_baselines_reports_missing_baseline(tmp_path):
    # Empty baseline dir -> every payload file is "missing".
    mismatches = compare_baselines(_fake_export(), str(tmp_path))
    assert "get_fleets.json" in mismatches


def test_main_update_baselines_writes_files(tmp_path, monkeypatch):
    import stellaris_save_extractor.qa_export as qa

    monkeypatch.setattr(qa, "run_full_export", lambda save_path, **kw: _fake_export())

    rc = qa.main(["some.sav", "--update-baselines", str(tmp_path)])

    assert rc == 0
    assert (tmp_path / "get_fleets.json").exists()
    assert (tmp_path / "_raw_counts.json").exists()
