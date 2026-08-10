# v8.7.6.11 — Card System, Phase 2 (site card schedule split + urgency pill)

Phase 2 of `CARD_SYSTEM_BRIEF.md`, on top of `v8.7.6.10`'s Phase 1 shell/
content/real-device-fix release. New logic with real date-boundary
conditions, not just CSS/markup — given its own test coverage and
real-device pass, not a shared one with Phase 1.

## A brief-vs-code discrepancy found before writing any code

The brief describes the destination as "the site page reached via
Resume/Start checking ... that page already exists — 'Select the trap you
are standing at'". Checked directly: `Start checking`/`Resume checking`
both navigate straight to the `"visit"` page (`go("visit", ...)`), whose
header *is* "Select the trap you are standing at" — confirming that's the
real target. There is a separate, literal `"site"` page in `app.py` with a
similar name, but nothing in the app navigates to it any more (grepped for
`go("site"` — zero matches). It's dead code from an earlier navigation
structure. Left untouched — removing dead code wasn't this brief's ask —
and the schedule block was added to `"visit"`, the page actually reached.

## What changed

- **Schedule split**: the Trap sites list card no longer shows an absolute
  `Last … · Next …` date line. That line moved to the top of the `"visit"`
  page (right under "Select the trap you are standing at"), computed the
  same way it always was, just relocated.
- **Urgency pill**: for a site with no visit in progress, a new
  `site_urgency_pill()` function computes `Overdue by N days` (red/error),
  `Due today` (amber/warning), or nothing at all (quiet) if it isn't due
  soon — pure calendar-date arithmetic, no lookahead window defined by the
  brief, so anything due tomorrow or later stays quiet. Sites with an
  active visit keep their existing `In progress`/`Ready to finish` pill in
  the same slot, unchanged — the two pill types are mutually exclusive by
  construction (one `if/else` branch decides which is computed at all).
- **A real gap this exposed**: `status_pill()` had success/guidance/warning
  variants but no `error`/red one, even though the red tokens
  (`--red-bg`/`--red-text`) were already defined and used elsewhere
  (message panels). Added `.status-pill-error`, reusing those existing
  tokens rather than inventing a new red.
- **"Last checked today" pill removed as a side effect, deliberately**:
  the brief's final card shape is exhaustive — "title, one pill (urgency
  or progress-state), trap count, button" — with no third category for a
  freshly-completed site. A site completed today is, by the urgency
  function's own logic, simply not due again soon, so it now shows no
  pill (the pale-green card background from `site-complete-marker` is
  untouched and still signals "just done" on its own).
- **`STYLE_GUIDE.md`**: documented the `error` pill variant and the
  urgency pill as its first real usage; confirmed the four semantic
  colours were already token-documented (just not all wired into
  `status_pill()`) rather than assuming they were missing entirely.

## Verified

- **Real boundary-condition tests**, not eyeballed — `site_urgency_pill`
  is a pure function with no Streamlit dependency, extracted from `app.py`
  via `ast` (the file can't be imported directly — it runs the whole app
  at module level) and exec'd in isolation so the tests exercise the
  actual implementation, not a re-typed copy. 9 tests: far future, due
  tomorrow (still quiet — not "due soon"), exactly due today, one day
  overdue (singular "day"), multiple/far overdue (plural "days"), and a
  parametrized sweep of the three states immediately around the boundary
  so a future off-by-one can't hide between widely-spaced test cases.
- Full local suite: 40/40 (31 existing + 9 new). Code/data gate: 55/55.
  Browser evidence gate: 7/7.
- Real device (physical phone over LAN, confirmed working): site cards
  show the urgency pill correctly (demo data's sites all happen to be
  overdue, confirmed as red pills reading "Overdue by N days"), and the
  visit page correctly shows the relocated `Last … · Next …` line.

## What's still open

- None from this brief — `CARD_SYSTEM_BRIEF.md` Phase 1 and Phase 2 are
  both complete and real-device verified.
