"""Tests for the interactive QA check tool (stellaris_save_extractor.qa_check).

The tool runs a full export, auto-triages obvious breakage, then walks the user
through comparing extracted values to in-game panels. The pure pieces (check plan,
auto-triage, report/snippet rendering, verdict loop with injected I/O) are tested
here; only the raw input()/print() wrapper is untested glue.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellaris_save_extractor.qa_check import (
    CATEGORIES,
    auto_triage,
    build_checks,
    render_issue_snippet,
    render_report,
    run_interactive,
)


def _export(**overrides):
    """A minimal but realistically-shaped export for check building."""
    export = {
        "metadata": {"empire_name": "Great Coffee Nation", "date": "2242.11.22", "player_id": 0},
        "extraction": {
            "get_empire_identity": {
                "empire_name": "Great Coffee Nation",
                "authority": "auth_democratic",
                "ethics": ["ethic_egalitarian"],
                "civics": ["civic_meritocracy"],
            },
            "get_pop_statistics": {"total_pops": 7913},
            "get_planets": {"count": 6, "planets": [{"name": "Coffee Prime"}]},
            "get_player_status": {
                "military_fleet_count": 2,
                "military_ships": 93,
                "military_power": 6487.9,
                "starbase_count": 19,
            },
            "get_fleet_composition": {"by_class_total": {"corvette": 23}},
            "get_resources": {"stockpiles": {"energy": 1000}, "net_monthly": {"alloys": 50}},
            "get_technology": {"completed_count": 120, "in_progress": []},
            "get_leaders": {"count": 22},
            "get_wars": {"active_war_count": 1, "count": 1},
            "get_diplomacy": {"relation_count": 13, "allies": [], "rivals": []},
        },
        "audit": {"smell": [], "validation": {"issues": []}},
    }
    export["extraction"].update(overrides)
    return export


def test_categories_are_registered():
    keys = [c[0] for c in CATEGORIES]
    assert "pops" in keys and "military" in keys and "colonies" in keys


def test_build_checks_selects_requested_categories_and_reads_values():
    checks = build_checks(_export(), ["pops"])
    assert len(checks) >= 1
    pop_check = next(c for c in checks if c["category"] == "pops")
    assert pop_check["value"] == 7913
    # No other category leaked in.
    assert all(c["category"] == "pops" for c in checks)


def test_build_checks_military_yields_multiple_checks():
    checks = build_checks(_export(), ["military"])
    values = {c["key"]: c["value"] for c in checks}
    assert values["military_ships"] == 93
    assert values["military_fleet_count"] == 2


def test_build_checks_all_categories_no_crash_on_sparse_export():
    sparse = {"metadata": {}, "extraction": {}, "audit": {}}
    checks = build_checks(sparse)  # all categories, mostly missing data
    assert len(checks) >= len(CATEGORIES)  # at least one check per category
    # Every check has the required display fields.
    for c in checks:
        assert {"key", "category", "label", "value", "panel"} <= set(c)


# --- auto-triage ---


def test_auto_triage_flags_extraction_errors_and_smell():
    export = _export(get_wars={"__error__": "ValueError('boom')"})
    export["audit"]["smell"] = [{"name": "fleets", "message": "fleets empty but raw has 40"}]

    issues = auto_triage(export)

    assert any(i["severity"] == "error" and "get_wars" in i["category"] for i in issues)
    assert any(i["category"] == "fleets" for i in issues)


def test_auto_triage_flags_suspicious_zeros():
    export = _export(
        get_pop_statistics={"total_pops": 0},
        get_planets={"count": 0, "planets": []},
        get_leaders={"count": 0},
        get_empire_identity={},  # truly nameless (no metadata or identity fallback)
    )
    export["metadata"]["empire_name"] = ""

    issues = auto_triage(export)
    blob = " ".join(i["message"].lower() for i in issues)

    assert "pop" in blob
    assert "colon" in blob
    assert "name" in blob


def test_auto_triage_clean_export_has_no_issues():
    assert auto_triage(_export()) == []


def test_auto_triage_uses_identity_name_when_metadata_lacks_it():
    # Pre-#30 exports have no empire_name in the metadata block, but identity does.
    export = _export()
    export["metadata"].pop("empire_name")

    issues = auto_triage(export)

    assert not any("name is blank" in i["message"].lower() for i in issues)


# --- interactive verdict loop (injected I/O) ---


def _scripted(responses):
    it = iter(responses)
    return lambda *a, **k: next(it)


def test_run_interactive_records_verdicts_and_notes():
    # military = 4 checks: fleet_count, ships, power, starbase (in that order).
    responses = ["m", "x", "game says 23", "s", "m"]
    session = run_interactive(
        _export(),
        input_fn=_scripted(responses),
        output_fn=lambda *a, **k: None,
        categories=["military"],
    )

    verdicts = [c["verdict"] for c in session["checks"]]
    assert verdicts == ["match", "mismatch", "skip", "match"]
    assert session["checks"][1]["note"] == "game says 23"


def test_run_interactive_prompts_for_categories_when_none():
    # Category #2 in the registry is "pops"; then "m" for its single check.
    session = run_interactive(
        _export(),
        input_fn=_scripted(["2", "m"]),
        output_fn=lambda *a, **k: None,
        categories=None,
    )
    assert session["checks"]
    assert all(c["category"] == "pops" for c in session["checks"])


# --- report + issue snippet ---


def _session():
    return {
        "meta": {"empire_name": "Great Coffee Nation", "date": "2242.11.22"},
        "auto_issues": [
            {"severity": "error", "category": "fleets", "message": "fleets empty but raw 40"}
        ],
        "checks": [
            {
                "key": "total_pops",
                "category": "pops",
                "label": "Total pops",
                "value": 7913,
                "panel": "Species",
                "verdict": "match",
                "note": "",
            },
            {
                "key": "military_ships",
                "category": "military",
                "label": "Military ships",
                "value": 93,
                "panel": "Fleet manager",
                "verdict": "mismatch",
                "note": "game says 23",
            },
        ],
    }


def test_render_report_contains_meta_checks_and_auto_issues():
    md = render_report(_session())
    assert "Great Coffee Nation" in md
    assert "Total pops" in md
    assert "game says 23" in md
    assert "fleets empty but raw 40" in md


def test_render_issue_snippet_lists_mismatches_and_refs_32():
    snippet = render_issue_snippet(_session())
    assert "Military ships" in snippet
    assert "game says 23" in snippet
    assert "#32" in snippet
    # A matching check is not a finding — it should not appear.
    assert "Total pops" not in snippet


# --- CLI orchestration ---


def test_main_runs_export_and_writes_report(tmp_path, monkeypatch):
    import stellaris_save_extractor.qa_check as qc

    monkeypatch.setattr(qc, "run_full_export", lambda save_path, **k: _export())
    report = tmp_path / "qa-report.md"

    rc = qc.main(
        ["some_empire.sav", "--categories", "pops", "--report", str(report)],
        input_fn=_scripted(["m"]),
        output_fn=lambda *a, **k: None,
    )

    assert rc == 0
    assert report.exists()
    assert "QA check" in report.read_text(encoding="utf-8")
