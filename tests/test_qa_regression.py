"""Golden-master regression tests for the QA full export across a save corpus.

For each committed baseline set under ``tests/qa_baselines/<id>/`` whose matching
save is present locally, the full export is regenerated and diffed against the
baselines. This catches extraction drift when a new Stellaris version or DLC lands.

Saves live in ``tests/saves/<id>.sav`` (gitignored) or the project-root
``test_save.sav``; baselines are committed. Regenerate after an *intended* change:

    python scripts/qa_export.py <save> --update-baselines tests/qa_baselines/<id>

New game version / DLC workflow: drop the save in ``tests/saves/``, run the export,
eyeball the smell report, then ``--update-baselines`` and commit the baseline JSON
(never the ``.sav`` itself). Until baselines are committed, this test skips.
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from stellaris_save_extractor.qa_export import compare_baselines, run_full_export

ROOT = Path(__file__).parent.parent
SAVES_DIR = ROOT / "tests" / "saves"
BASELINE_ROOT = ROOT / "tests" / "qa_baselines"


def _resolve_save(stem: str) -> Path | None:
    """Find the .sav for a baseline id in the project root or tests/saves/."""
    for candidate in (ROOT / f"{stem}.sav", SAVES_DIR / f"{stem}.sav"):
        if candidate.exists():
            return candidate
    return None


def _baseline_cases() -> list[str]:
    """Baseline ids that have committed baseline files."""
    if not BASELINE_ROOT.exists():
        return []
    return sorted(p.name for p in BASELINE_ROOT.iterdir() if p.is_dir() and any(p.glob("*.json")))


@pytest.mark.parametrize(
    "stem",
    _baseline_cases()
    or [pytest.param("", marks=pytest.mark.skip(reason="no QA baselines committed yet"))],
)
def test_export_matches_committed_baselines(stem):
    save = _resolve_save(stem)
    if save is None:
        pytest.skip(f"save {stem}.sav not present locally")

    export = run_full_export(str(save))
    mismatches = compare_baselines(export, str(BASELINE_ROOT / stem))

    assert mismatches == [], f"QA baseline drift for {stem}: {mismatches}"
