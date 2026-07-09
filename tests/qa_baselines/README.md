# QA export regression baselines

Committed golden-master baselines for the QA full export, consumed by
`tests/test_qa_regression.py`. One subdirectory per corpus save (baseline id =
save file stem), each containing one `<method>.json` per extracted section plus
`_raw_counts.json` and `_smell.json`.

Baselines are stored canonicalised (sorted, with volatile fields like `file_path`
and `modified` stripped) so they compare stably across machines. Comparison is
order-insensitive (some sections build lists from sets).

## Regenerating after an intended extraction change

```
python scripts/qa_export.py <save> --update-baselines tests/qa_baselines/<id>
```

Review the diff before committing — an unexpected change here is exactly the
extraction regression the harness exists to catch. Saves live in `tests/saves/`
(gitignored) or the project-root `test_save.sav`.
