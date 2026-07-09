# QA regression save corpus

Drop Stellaris `.sav` files here to add them to the QA export regression corpus
(`tests/test_qa_regression.py`). The `.sav` files themselves are **gitignored**
(`*.sav`) — only baselines are committed (see `tests/qa_baselines/`).

Naming: the file stem is the baseline id. `tests/saves/pegasus_4_4.sav` pairs with
baselines under `tests/qa_baselines/pegasus_4_4/`. The project-root `test_save.sav`
is also picked up automatically (baseline id `test_save`).

## Adding a save (e.g. a new game version or DLC)

1. Copy the save here: `tests/saves/<id>.sav`.
2. Run the export and eyeball the smell report for silent breakage:
   `python scripts/qa_export.py tests/saves/<id>.sav`
3. When the extraction looks correct, snapshot baselines:
   `python scripts/qa_export.py tests/saves/<id>.sav --update-baselines tests/qa_baselines/<id>`
4. Commit the baseline JSON under `tests/qa_baselines/<id>/` (never the `.sav`).

The regression test then diffs future exports of that save against the baselines,
catching extraction drift when the extractor or the game data model changes.
