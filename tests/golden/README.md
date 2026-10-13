# Golden record for Save check

What the check page writes to the workbook, frozen from `main` (`20a454a`) before the record-building code was moved out of the page
into `app.build_check_records()` (Phase 6, S3).

| File | What it is |
|---|---|
| `check_save_inline_block_main.txt` | The record-building block exactly as it stood inline in the check page on `main` (`old_id = close_window(...)` to `refresh_review_status(...)`), dedented. The tests run it, so the old behaviour can be reproduced at any time. |
| `check_save_golden_digests.tsv` | One digest of the written rows for every cell of the matrix (2,704 cells): trap with/without a camera and with/without an open trial, all six findings, carcass collected Yes/No, species and rat type, condition, photo counts 0/1/3, service ready or not (with a reason), every camera answer (Yes, Could not assess, No with every issue x covers x adjusted), notes or none. |
| `check_save_golden_rows.json` | The full rows for the readable subset (168 cells), so a failure can be read, not just detected. |
| `check_save_golden_photos.json` | The whole photo chain (stage, build, commit, reload) for photo counts 0, 1 and 3 and for photos staged before the outcome changed: Photos rows, final files, files left in the pending folder. |
| `freeze_check_save.py` | How the golden is made. It runs the frozen inline block, never the new function. |
| `check_save_golden_changes.json`, `record_deliberate_changes.py` | Deliberate changes laid over the frozen golden: the cells that moved, their new digest and full new rows, and the reason. The frozen golden itself is not edited. Today: the 8 cells of S4 (13 Oct 2026): at a camera trap, Unable to check and Trap missing record Camera Condition and Camera Covers Trap as "Not assessed" and raise no Camera issue task. |

`tests/check_save_matrix.py` is the matrix and the runner. `tests/test_check_save_golden.py` holds the function the page calls (and the
frozen block) to the golden; `tests/test_check_save_golden_ui.py` answers the real form for ten cells and holds what is written to the golden.

**The golden is never edited to make a test pass.** A deliberate change in what Save check writes (S4 is the first) is recorded with
`record_deliberate_changes.py --reason "<why>"`, in a reviewed change that lists the cells that moved; the test also names the cells that are
allowed to move, so an unexpected move still fails.
