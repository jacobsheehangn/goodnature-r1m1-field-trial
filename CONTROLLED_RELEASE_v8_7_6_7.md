# v8.7.6.7 — Photo Integrity Corrections

Built from the unreleased `v8_7_6_7_WIP_Photo_Integrity_Corrections` working tree
handed over on 7 August 2026, on top of the trusted `v8.7.6.5` baseline.
Supersedes the withdrawn `v8.7.6.6` (never deployed).

## Why

Three real field checks at Moa Point (`M15-8 / MOA-002`, `M15-7 / MOA-003`,
`M15-9 / MOA-004`) saved successfully but silently lost their selected
photos — no error, no evidence rows. `v8.7.6.6` attempted a fix but was
withdrawn after review found seven concrete defects in its retry, failure
classification, durability and rollback behaviour (see `HANDOVER_TO_CLAUDE.md`
§12). This release re-examines and completes that corrective work.

## What changed

- Photo transaction/storage logic extracted into `photo_integrity.py`: durable
  per-check `manifest.json`, SHA-256 verification, permanent-vs-transient
  failure classification, atomic writes, removed-photo tombstones, and
  hash-matched final-copy rollback.
- Browser component (`photo_component/index.html`) rewritten: each selected
  photo prepares and uploads independently (no longer waits for a batch),
  exactly three automatic retries at ~1s/2s/4s, manual retry only after
  those are exhausted, fixed-footprint cards (3-col desktop / 2-col mobile)
  so a photo changing state doesn't reflow its neighbours.
- `Save check` is disabled while any selected photo is unresolved and
  re-verifies against the durable manifest — not session state — both when
  the button becomes enabled and again at the moment of commit.
- Check/follow-up/Photos rows commit together; on any failure after the
  workbook write, the workbook is restored from a checksum-verified copy and
  any final photo copies already made are rolled back. If rollback can't be
  confirmed, the UI says so explicitly rather than claiming success.
- Fixed `tests/release_gate.py`: it never read `photo_integrity.py`, so the
  checks for the new storage functions could not pass regardless of code
  quality, and three checks still matched literal strings from the withdrawn
  `v8.7.6.6` build. Both are corrected; no application behaviour changed.
- `toolbarMode = "minimal"` and all navigation/card/workflow code are
  unchanged from `v8.7.6.5`.

## Verified so far (this review, 7 Aug 2026)

- `photo_integrity.py` — 8 existing focused tests plus 5 additional tests
  written this review (missing-file, hash-tampering, malformed photo ID,
  duplicate-ID dedup, unexpected-row detection) all pass, run directly
  without pytest since this module has no Streamlit dependency.
- `tests/release_gate.py` — 55/55 checks pass after the fix above.
- `app.py` and `photo_integrity.py` both compile cleanly (`py_compile`);
  the `photo_integrity` import aliases in `app.py` were checked by hand
  against the actual exported names.
- Manual trace of the full save/commit/rollback path in `app.py` against
  every invariant in `HANDOVER_TO_CLAUDE.md` §14, including the
  deterministic-Check-ID collision question: the UI removes the "Check"
  button once a trap has a recorded check for the current visit, so the
  deterministic ID (only used when photos are expected) cannot be reissued
  for a second attempt at the same trap within the same visit. There is no
  check-deletion feature in the app, so that path doesn't reopen the risk.
- Diffed against `v8.7.6.5`: all ten changed hunks are photo/save-path
  related or the `MAX_PHOTO_DIMENSION` 1600→1800 constant; navigation,
  cards, and `.streamlit/config.toml` are byte-identical to baseline.

## NOT yet verified — required before deploy

This review ran in a sandboxed environment with no network access and
neither Streamlit nor Playwright installed, so none of the following has
been exercised, only read:

- `tests/test_photo_component.py`, `tests/test_local_app.py`,
  `tests/test_live_smoke.py` — all need a running Streamlit server plus a
  real browser (Playwright/Chromium).
- Real iPhone Safari testing: HEIC input, portrait/landscape orientation,
  actual ~5MB photo compression behaviour, no-cropping confirmation.
- Actual automatic-retry request timing/count over a real network (only
  the JS scheduling logic was read, not observed firing).
- Multi-operator concurrent access to the same Visit ID — the workbook has
  no locking beyond `save_data()`'s existing semantics, and two operators
  racing on the same untouched trap could merge their photo selections
  into one check. This looks like a pre-existing, low-probability edge
  case given the one-operator-per-visit field process, not something
  introduced by this release, but it is not covered by any test.
- Deployed Render environment / persistent `/var/data` behaviour.

Run before release:

```bash
python -m pytest -q tests/
bash run_release_gate.sh
```

then the real-device pass from `HANDOVER_TO_CLAUDE.md` §15 ("Real
iPhone / Safari" and "Field-issue reproduction" sections) against a
deployed instance, before this replaces `v8.7.6.5` on Render.

Not field-proven until that device/browser pass is complete.
