"""Interactive QA against a running Stellaris game.

Runs a full export (``qa_export.run_full_export``), auto-triages obvious breakage,
then walks the user through comparing each extracted value to the matching in-game
panel — recording a report and a paste-ready issue snippet (for #32).

Design: the check plan, auto-triage, and report rendering are pure functions; the
verdict loop takes injectable ``input``/``print`` so it is testable. Only ``main``
touches the real terminal and filesystem.
"""

from __future__ import annotations

from .qa_export import run_full_export


def _g(mapping, *path, default=None):
    """Safe nested lookup: _g(export, 'extraction', 'get_x', 'field')."""
    cur = mapping
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    return default if cur is None else cur


def _check(key, category, label, value, panel):
    return {"key": key, "category": category, "label": label, "value": value, "panel": panel}


def _resolve_meta(export: dict) -> dict:
    """Empire name/date for headers, falling back across export sections.

    The export ``metadata`` block only carries empire_name once the MP-selection
    work (#30) is present; fall back to identity / player_status / get_metadata so
    reports are labelled correctly regardless.
    """
    meta = dict(_g(export, "metadata", default={}))
    name = (
        meta.get("empire_name")
        or _g(export, "extraction", "get_empire_identity", "empire_name")
        or _g(export, "extraction", "get_player_status", "empire_name")
    )
    date = (
        meta.get("date")
        or _g(export, "extraction", "get_metadata", "date")
        or _g(export, "extraction", "get_player_status", "date")
    )
    if name:
        meta["empire_name"] = name
    if date:
        meta["date"] = date
    return meta


def _checks_identity(e):
    ext = ("extraction", "get_empire_identity")
    name = _g(e, "metadata", "empire_name") or _g(e, *ext, "empire_name")
    return [
        _check("empire_name", "identity", "Empire name", name, "Top bar / empire name"),
        _check("authority", "identity", "Authority", _g(e, *ext, "authority"), "Government screen"),
        _check("ethics", "identity", "Ethics", _g(e, *ext, "ethics"), "Government / Ethics"),
        _check("civics", "identity", "Civics", _g(e, *ext, "civics"), "Government / Civics"),
    ]


def _checks_pops(e):
    return [
        _check(
            "total_pops",
            "pops",
            "Total pops",
            _g(e, "extraction", "get_pop_statistics", "total_pops"),
            "Species / Population panel",
        )
    ]


def _checks_colonies(e):
    planets = _g(e, "extraction", "get_planets", "planets", default=[])
    names = (
        [p.get("name") for p in planets if isinstance(p, dict)] if isinstance(planets, list) else []
    )
    return [
        _check(
            "colony_count",
            "colonies",
            "Colony count",
            _g(e, "extraction", "get_planets", "count"),
            "Planets / Outliner colonies",
        ),
        _check("colony_names", "colonies", "Colony names", names, "Planets list"),
    ]


def _checks_military(e):
    ps = ("extraction", "get_player_status")
    return [
        _check(
            "military_fleet_count",
            "military",
            "Military fleets",
            _g(e, *ps, "military_fleet_count"),
            "Fleet manager (military fleets)",
        ),
        _check(
            "military_ships",
            "military",
            "Military ships",
            _g(e, *ps, "military_ships"),
            "Fleet manager (ship count)",
        ),
        _check(
            "military_power",
            "military",
            "Military power",
            _g(e, *ps, "military_power"),
            "Fleet power / top bar",
        ),
        _check(
            "starbase_count",
            "military",
            "Starbases",
            _g(e, *ps, "starbase_count"),
            "Outliner starbases",
        ),
    ]


def _checks_fleet_composition(e):
    return [
        _check(
            "fleet_composition",
            "fleet_composition",
            "Ships by class",
            _g(e, "extraction", "get_fleet_composition", "by_class_total"),
            "Fleet manager (ship types)",
        )
    ]


def _checks_resources(e):
    fields = ("energy", "minerals", "food", "alloys", "consumer_goods")

    def _subset(d):
        return {k: d.get(k) for k in fields if isinstance(d, dict) and k in d}

    return [
        _check(
            "stockpiles",
            "resources",
            "Resource stockpiles",
            _subset(_g(e, "extraction", "get_resources", "stockpiles", default={})),
            "Top bar resource totals",
        ),
        _check(
            "net_monthly",
            "resources",
            "Net monthly income",
            _subset(_g(e, "extraction", "get_resources", "net_monthly", default={})),
            "Top bar (+/- per month)",
        ),
    ]


def _checks_technology(e):
    in_progress = _g(e, "extraction", "get_technology", "in_progress", default=[])
    return [
        _check(
            "completed_count",
            "technology",
            "Technologies researched",
            _g(e, "extraction", "get_technology", "completed_count"),
            "Technology screen (finished)",
        ),
        _check(
            "in_progress",
            "technology",
            "Research in progress",
            len(in_progress) if isinstance(in_progress, list) else in_progress,
            "Research queue",
        ),
    ]


def _checks_leaders(e):
    return [
        _check(
            "leader_count",
            "leaders",
            "Leader count",
            _g(e, "extraction", "get_leaders", "count"),
            "Leaders screen",
        )
    ]


def _checks_wars(e):
    return [
        _check(
            "active_war_count",
            "wars",
            "Active wars",
            _g(e, "extraction", "get_wars", "active_war_count"),
            "Diplomacy / War status",
        )
    ]


def _checks_diplomacy(e):
    return [
        _check(
            "relation_count",
            "diplomacy",
            "Known empires (relations)",
            _g(e, "extraction", "get_diplomacy", "relation_count"),
            "Contacts / Diplomacy",
        )
    ]


# Ordered registry: (category_key, label, builder). "Pick each run" selects from here.
CATEGORIES = [
    ("identity", "Empire identity", _checks_identity),
    ("pops", "Population", _checks_pops),
    ("colonies", "Colonies", _checks_colonies),
    ("military", "Military", _checks_military),
    ("fleet_composition", "Fleet composition", _checks_fleet_composition),
    ("resources", "Resources", _checks_resources),
    ("technology", "Technology", _checks_technology),
    ("leaders", "Leaders", _checks_leaders),
    ("wars", "Wars", _checks_wars),
    ("diplomacy", "Diplomacy", _checks_diplomacy),
]


def build_checks(export: dict, categories=None) -> list[dict]:
    """Build the flat list of checks for the selected categories (all if None)."""
    selected = set(categories) if categories is not None else {c[0] for c in CATEGORIES}
    checks: list[dict] = []
    for key, _label, builder in CATEGORIES:
        if key in selected:
            checks.extend(builder(export))
    return checks


def auto_triage(export: dict) -> list[dict]:
    """Surface obvious breakage before any human comparison.

    Catches crashed extractor methods, smell flags, validator issues, and key
    metrics that are suspiciously zero/blank for an established empire.
    """
    issues: list[dict] = []

    for method, result in _g(export, "extraction", default={}).items():
        if isinstance(result, dict) and "__error__" in result:
            issues.append(
                {
                    "severity": "error",
                    "category": method,
                    "message": f"{method} crashed during extraction: {result['__error__']}",
                }
            )

    for flag in _g(export, "audit", "smell", default=[]):
        issues.append(
            {
                "severity": "error",
                "category": flag.get("name", "smell"),
                "message": flag.get("message", ""),
            }
        )

    for issue in _g(export, "audit", "validation", "issues", default=[]):
        issues.append(
            {
                "severity": "warning",
                "category": issue.get("check", "validation"),
                "message": issue.get("message", ""),
            }
        )

    # Suspicious zeros/blanks — these are essentially never legitimately empty for
    # a mid/late-game empire, so a zero here usually means a broken extractor.
    if not (_resolve_meta(export).get("empire_name") or "").strip():
        issues.append(
            {"severity": "warning", "category": "identity", "message": "Empire name is blank."}
        )
    if _g(export, "extraction", "get_pop_statistics", "total_pops") == 0:
        issues.append({"severity": "warning", "category": "pops", "message": "Total pops is 0."})
    if _g(export, "extraction", "get_planets", "count") == 0:
        issues.append(
            {"severity": "warning", "category": "colonies", "message": "Colony count is 0."}
        )
    if _g(export, "extraction", "get_leaders", "count") == 0:
        issues.append(
            {"severity": "warning", "category": "leaders", "message": "Leader count is 0."}
        )

    return issues


_VERDICT_MARK = {"match": "✓", "mismatch": "✗", "skip": "–"}


def render_report(session: dict) -> str:
    """Render a markdown QA report for a completed session."""
    meta = session.get("meta", {})
    checks = session.get("checks", [])
    auto = session.get("auto_issues", [])
    counts = {
        v: sum(1 for c in checks if c.get("verdict") == v) for v in ("match", "mismatch", "skip")
    }

    lines = [
        f"# QA check — {meta.get('empire_name', 'Unknown empire')}",
        "",
        f"- Date (in-game): {meta.get('date', 'n/a')}",
        f"- Verdicts: {counts['match']} match, {counts['mismatch']} mismatch, {counts['skip']} skipped",
        "",
        "## Automatic issues",
        "",
    ]
    if auto:
        for issue in auto:
            lines.append(f"- **[{issue['severity']}]** {issue['category']}: {issue['message']}")
    else:
        lines.append("- None detected.")
    lines += [
        "",
        "## Checks",
        "",
        "| Result | Metric | Extracted | Note |",
        "| --- | --- | --- | --- |",
    ]
    for c in checks:
        mark = _VERDICT_MARK.get(c.get("verdict"), "?")
        lines.append(f"| {mark} | {c['label']} | {_fmt_value(c['value'])} | {c.get('note', '')} |")
    lines.append("")
    return "\n".join(lines)


def render_issue_snippet(session: dict) -> str:
    """Render a paste-ready findings block for filing against #32.

    Includes auto-detected errors and any human-confirmed mismatches; excludes
    matches and skips (they are not findings).
    """
    meta = session.get("meta", {})
    findings = []
    for issue in session.get("auto_issues", []):
        if issue.get("severity") == "error":
            findings.append(f"- (auto) {issue['category']}: {issue['message']}")
    for c in session.get("checks", []):
        if c.get("verdict") == "mismatch":
            findings.append(
                f"- {c['label']}: extracted `{_fmt_value(c['value'])}`, "
                f"game shows `{c.get('note') or '?'}` (panel: {c['panel']})"
            )

    if not findings:
        return "No mismatches found — extraction matches the game for the checked metrics."

    header = (
        f"Extraction mismatches for **{meta.get('empire_name', 'empire')}** "
        f"(in-game date {meta.get('date', 'n/a')}), likely instances of the #32 "
        f"4.x failure modes:"
    )
    return "\n".join([header, ""] + findings)


def _fmt_value(value) -> str:
    """Render a check value compactly for the terminal."""
    if value is None:
        return "(missing)"
    if isinstance(value, float):
        return f"{value:,.0f}"
    if isinstance(value, list):
        if not value:
            return "(none)"
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        if not value:
            return "(none)"
        return ", ".join(f"{k}={v}" for k, v in value.items())
    return str(value)


def _prompt_categories(input_fn, output_fn) -> list[str]:
    """Ask which categories to walk this session (Enter/'all' = everything)."""
    output_fn("Which areas do you want to check? (comma-separated numbers, or Enter for all)")
    for i, (_key, label, _fn) in enumerate(CATEGORIES, start=1):
        output_fn(f"  {i}. {label}")
    raw = (input_fn("Selection: ") or "").strip().lower()
    if raw in ("", "all", "a"):
        return [c[0] for c in CATEGORIES]
    picked: list[str] = []
    for token in raw.replace(",", " ").split():
        if token.isdigit():
            idx = int(token) - 1
            if 0 <= idx < len(CATEGORIES):
                picked.append(CATEGORIES[idx][0])
    return picked or [c[0] for c in CATEGORIES]


def run_interactive(export, *, input_fn=input, output_fn=print, categories=None) -> dict:
    """Walk the user through comparing each extracted value to the game."""
    if categories is None:
        categories = _prompt_categories(input_fn, output_fn)

    auto = auto_triage(export)
    if auto:
        output_fn(f"\n[!] {len(auto)} issue(s) found automatically (before checking the game):")
        for issue in auto:
            output_fn(f"  [{issue['severity']}] {issue['category']}: {issue['message']}")
    else:
        output_fn("\nNo automatic issues detected. Now comparing against the game...")

    checks = build_checks(export, categories)
    results: list[dict] = []
    for check in checks:
        output_fn(f"\n{check['label']}: {_fmt_value(check['value'])}")
        output_fn(f"  In-game: {check['panel']}")
        answer = (input_fn("  [m]atch / [x] mismatch / [s]kip: ") or "").strip().lower()
        if answer in ("m", "y"):
            verdict = "match"
        elif answer in ("x", "n"):
            verdict = "mismatch"
        else:
            verdict = "skip"
        note = ""
        if verdict == "mismatch":
            note = (input_fn("  What does the game show? ") or "").strip()
        results.append({**check, "verdict": verdict, "note": note})

    return {
        "meta": _resolve_meta(export),
        "auto_issues": auto,
        "checks": results,
    }


def main(argv=None, *, input_fn=input, output_fn=print) -> int:
    """Interactive QA session: export the save, then walk the checks."""
    import argparse
    import sys

    # Save data can contain characters the terminal's encoding (e.g. Windows
    # cp1252) can't represent; degrade gracefully instead of crashing.
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001 - best-effort console hardening
        pass

    parser = argparse.ArgumentParser(
        prog="stellaris-qa-check",
        description="Interactively QA a Stellaris save's extraction against the running game.",
    )
    parser.add_argument("save_path", nargs="?", help="Path to a .sav (default: most recent save).")
    parser.add_argument(
        "--categories",
        help="Comma-separated category keys to check (default: ask interactively). "
        "Available: " + ", ".join(c[0] for c in CATEGORIES),
    )
    parser.add_argument("--report", help="Write the markdown report here (default: alongside cwd).")
    args = parser.parse_args(argv)

    save_path = args.save_path
    if not save_path:
        from stellaris_companion.save_loader import find_most_recent_save

        save_path = find_most_recent_save()
        if not save_path:
            output_fn("No save file found.")
            return 2

    output_fn(f"Exporting {save_path} ...")
    export = run_full_export(str(save_path))

    categories = None
    if args.categories:
        categories = [c.strip() for c in args.categories.split(",") if c.strip()]

    session = run_interactive(export, input_fn=input_fn, output_fn=output_fn, categories=categories)

    report = render_report(session)
    report_path = args.report or "stellaris-qa-report.md"
    from pathlib import Path

    Path(report_path).write_text(report, encoding="utf-8")

    output_fn("\n" + "=" * 60)
    output_fn(f"Report written to {report_path}")
    output_fn("\n--- paste-ready findings (for issue #32) ---\n")
    output_fn(render_issue_snippet(session))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
