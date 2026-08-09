# v8.7.6.9 — Performance Brief, Phase 2 (fragment pilot traced and skipped; CSS audit)

Phase 2 of `PERFORMANCE_BRIEF_DETAILED.md`, on top of `v8.7.6.8`. Skips
Phase 2a and leaves Phase 2b untouched, both for reasons traced and
confirmed below, not assumed. Completes Phase 2c.

## Phase 2a — fragment pilot on the photo component: traced, then skipped

The brief asked for a pilot: wrap the photo-upload component's
event-handling block (`render_photo_capture_widget`) in `@st.fragment`.
Traced this precisely against the Save-button gating logic before writing
any code, per the brief's own instruction not to assume it "just works."

Finding: `render_photo_capture_widget`'s return value drives the
`disabled=` state of the `Save check`/`Save necropsy review` button, which
renders *outside* the function. A `st.rerun()` inside an `@st.fragment`
only reruns the fragment by default; anything that needs to change outside
it (like that button) requires `st.rerun(scope="app")`, which forces a
full-page rerun — identical cost to today, fragment or not.

Checked every event the component's JS side (`photo_component/index.html`)
actually fires, not just the Python-side action names:
- `upload`, `retry`, `remove` all change `expected_count`/`file_count`/
  `ready` — these must use `scope="app"` for correctness.
- `selection_started` (line 385 of `photo_component/index.html`) carries
  `selections` directly, which triggers `add_expected_photos()` and bumps
  `expected_count` the moment the user picks photos — exactly the signal
  that needs to disable the Save button immediately. Also needs
  `scope="app"`.
- `sync_failures` (line 92) carries `client_failures`, which can flip
  `ready` to `False` via `record_failure()`. Also needs `scope="app"`.

There is no event this component fires that's safe to leave
fragment-scoped without breaking Save-button correctness. Implementing the
pilot as briefed would add `@st.fragment` complexity for a measured
**zero** reduction in full-page reruns. Not implemented — confirmed with
the codebase's owner before skipping.

## Phase 2b — scroll-reset hack: left untouched

The brief's own condition for touching this was "once fragment adoption
reduces how often a full rerun happens." Since 2a didn't land, that
condition was never met — full-rerun frequency during photo interactions
is unchanged from `v8.7.6.8`. No driver to revisit the six-attempt retry
schedule. Confirmed still present at `app.py`'s `scroll_to_top_once()`.

## Phase 2c — CSS fragility audit: real-browser verification + dead-selector removal

**Real-browser verification**, against the live app running Streamlit
1.60, at 1440px (desktop) and 390/430px (mobile), for every element the
brief named:
- Toolbar / top nav: renders correctly, wraps cleanly to two rows on
  mobile, no horizontal overflow at any breakpoint (`document.documentElement.scrollWidth`
  checked directly, not eyeballed).
- Administration dropdown: opens, positions correctly, closes on Escape.
- Card layout (site cards, visit-trap cards): unchanged, verified via
  screenshot at all three breakpoints before and after the removals below.
- Light-theme-forcing script: `getComputedStyle(document.documentElement).colorScheme`
  confirmed `"light only"` at every breakpoint.
- Radio/checkbox controls: confirmed visually unselected (white surface,
  dark outline) and selected (orange fill) states both render correctly —
  the fix from the UI polish work is still intact.
- Full pytest + release-gate suite re-run after the removals below:
  31/31, code/data gate 55/55, browser evidence gate 7/7 — including the
  existing `mobile_checked_state.png` capture of a real "✓ Checked"
  `visit-trap-card`, the exact component whose CSS changed.

**Dead-selector removal.** Not a general specificity clean-up — cross-referenced
every custom class selector in the CSS against actual usage in
Python-generated markup (accounting for dynamically-built class names like
`status-pill-{kind}`, verified by reading the generating code, not just
text-matching). Found 14 selectors with zero references anywhere outside
the CSS itself, all tracing to two superseded iterations plus a few
one-off leftovers:

- `shared-card-status` + its `.is-complete`/`.is-progress`/`.is-warning`
  modifiers, and `site-card-status` — an older status-label styling
  approach, superseded by the `status_pill()` component from the UI
  polish work. Verified `status_pill()`'s own output (`status-pill
  status-pill-{kind}`) is untouched and still renders correctly.
- `visit-trap-id`, `visit-trap-location`, `visit-trap-checkmark` — from an
  earlier 3-column grid layout for the visit-trap card; the current
  implementation uses `visit-trap-line`/`visit-trap-meta`/`visit-trap-status`
  instead (confirmed those three are still live and untouched).
- `site-card-title` — orphaned, no corresponding element anywhere.
- `route-card-current` — a "current route" highlight that nothing in the
  app ever applies.
- `mobile-save-anchor` — remnant of the sticky-CTA feature that
  `tests/release_gate.py` already bans by name (`.element-container:has(.mobile-save-anchor)`);
  this was the class's own now-orphaned definition.
- `.tertiary-action button, button[data-variant="tertiary"]` and
  `.destructive-action button` — button style variants designed but never
  wired to any actual button; `data-variant` doesn't appear anywhere else
  in the app.
- `photo-tile img` — pre-dates the photo grid moving into
  `photo_component/index.html`'s own iframe, which owns its styling now.

`!important` count: 386 → 371 (real reduction, not just fewer lines —
each removed rule typically carried several). `data-testid=` count
unchanged at 211 (none of the removed selectors targeted Streamlit
internals). Confirmed via `ast.parse` that `app.py` still compiles, and
via the full verification pass above that removing these had zero visual
effect at any breakpoint — expected, since none of them matched anything
live to begin with.

## What's still open

- The real-device pass on Phase 1 (`v8.7.6.8`) that the original brief
  wanted before Phase 2's scope was decided — this release went ahead of
  that per an explicit decision, not an oversight.
- Everything Phase 2c intentionally left alone: 211 `data-testid=` selectors
  and 371 `!important` declarations remain, all confirmed live and
  rendering correctly against 1.60 — this pass removed dead code, it did
  not attempt a general specificity reduction, per the brief's own
  instruction not to.
