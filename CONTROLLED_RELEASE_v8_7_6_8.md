# v8.7.6.8 — Performance Brief, Phase 1 (load_data caching + font loading)

Phase 1 of `PERFORMANCE_BRIEF_DETAILED.md`, on top of `v8.7.6.7`. Phase 2
(fragment pilot, scroll-reset hack, CSS audit) is deliberately not part of
this release — the brief's checkpoint requires reporting back on Phase 1's
measured effect before Phase 2's scope is decided.

## Why

`load_data()` re-parsed the entire workbook — nine separate
`pd.read_excel()` calls — on every single script rerun, with no caching.
Since every interaction triggers a full rerun (no `@st.fragment` usage
anywhere in the app), this cost was paid on every click, tap, and
keystroke, not just page loads. Separately, the Google Fonts stylesheet
was loaded via a blocking CSS `@import`, delaying first paint.

## What changed

- `load_data()`'s actual file-parsing moved into a new
  `_load_data_cached(mtime)`, decorated with `@st.cache_data`, keyed on
  `DATA_FILE.stat().st_mtime`. The seed/create-sample-data logic stays in
  the outer, uncached `load_data()` — only the parse itself is cached.
  Read pattern also changed from nine separate `pd.read_excel(...)` calls
  to a single `pd.ExcelFile(DATA_FILE)` opened once and `.parse()`'d per
  sheet.
- Google Fonts: replaced the blocking `@import` inside the main `<style>`
  block with `<link rel="preconnect">` (googleapis.com and gstatic.com)
  plus a separate `<link rel="stylesheet">`, injected via its own
  `st.markdown(unsafe_allow_html=True)` call immediately before the CSS
  block.

## Verified so far

- **Read-pattern speed** (`pd.read_excel` loop vs `pd.ExcelFile` + `.parse`,
  same real seed workbook, 5 runs each): 131.4ms mean → 44.4ms mean, a 3.0x
  speedup on the parse itself, independent of caching.
- **Caching semantics, tested directly** (not inferred from reading the
  code): decorated the real `_load_data_cached` function, instrumented
  with a read-counter, against a real workbook file.
  - 1 call → 1 real read.
  - 2 more calls with the file unchanged → still 1 real read (cache hit
    confirmed, not a re-read).
  - File then saved exactly the way `save_data()` does it (write to a
    temp file, `os.replace()` over the original) → next call produces a
    2nd real read (cache correctly invalidated), and the returned data
    reflects the new content, not a stale copy.
- Full local suite: 31/31 passing (`pytest tests/ --ignore=tests/test_live_smoke.py`) —
  this is a read-path change only, no existing test needed updating.
- `app.py` compiles cleanly (`ast.parse`).

## NOT yet verified — required before this is considered field-proven

- **Real device / real browser, not just this environment.** The brief
  asked for a re-measurement of how the app *feels* on a real device
  after 1a+1b — that hasn't been done. The numbers above are pure Python
  timing of the read functions in isolation, not an in-browser
  page-load/interaction-latency measurement.
- **Single-session "save then reload" UI check** — covered indirectly by
  the existing `test_local_app.py` browser suite (which saves a check and
  asserts the very next render shows it, and passed), but not re-confirmed
  as a fresh manual pass specifically after this change.
- **Font-loading first-paint improvement** — the `<link>` swap is
  structurally correct (verified via `grep`, and the app still renders in
  Inter in the browser test screenshots), but no before/after first-paint
  timing was measured; the brief only asked this render correctly, which
  it does.
- Deployed Render environment behaviour under this caching change with
  real concurrent traffic.

## Checkpoint — reporting back per the brief's ground rule

Phase 1a is real (3x on the parse itself, plus the cache now removing
essentially all of that cost on unchanged-file reruns — every interaction
in an unchanged session no longer touches the filesystem at all). Phase 1b
is a small, low-risk, standalone fix with no measurable downside found.

Whether Phase 2's full scope is warranted, or just the fragment pilot
(2a), should be decided after a real-device pass on this Phase 1 build —
not fixed in advance.
