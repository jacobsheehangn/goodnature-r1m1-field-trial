# v8.7.6.10 — Card System, Phase 1 (shell, hierarchy, content — not the schedule/urgency pill)

Phase 1 of `CARD_SYSTEM_BRIEF.md`, on top of `v8.7.6.9`. Phase 2 (the site
card's schedule split and urgency pill) is deliberately not part of this
release — new relative-date logic with real boundary conditions needs its
own verification pass, not a shared one with this mechanical/CSS-only work.

## What changed

**Shell — every card and every primary button:**
- Card radius `14px → 20px`, new three-layer soft ambient shadow
  (`0 0 0 1px / 0 0 20px / 0 0 100px`, all `rgba(0,0,0,.05)`), reversing
  `STYLE_GUIDE.md`'s earlier "flat cards, no shadow" principle —
  deliberately, per the brief.
- This shell was duplicated across **8 separate rule blocks** in `app.py`
  (an artifact of this file's iterative-patch history — confirmed by
  reading every `<style>` block in full, not just grepping for one match).
  All 8 updated consistently, including the `.visit-trap-card` checked
  state, which had its own direct rule outside the marker-based system.
- Button radius `9px → 999px` (pill) — applied at the single shared base
  rule every button variant inherits from, not just Primary. Real-device
  testing found square Secondary buttons (Check/Edit/Review/View/Pause)
  sitting inside the new 20px-rounded cards read as visibly unfinished;
  the brief had only specified Primary, but the coherence problem was real
  once actually looked at on a phone, so Secondary was brought in too.
- Card title `1rem/1.05rem → 22px` bold (`.shared-card-heading strong`,
  `.site-card-heading`), including removing a mobile-specific downsize
  that would have fought the new flat 22px.
- Card padding and inter-element gap consolidated to one literal `15px`
  value at every breakpoint, replacing `.32rem`/`.4rem`/`.28rem` and
  several breakpoint-specific overrides (including two "extra breathing
  room" rules that are now redundant once the base gap is a full 15px).
- Administration popover (`stPopoverBody`): border removed, `10px` radius
  + the same shadow; page-link/button rows brought to a `40px`/`15px`
  rhythm.

**Per-card-type content:**
- Site card: dropped the duplicate trap count ("9 active traps" *and*
  "0 of 9 traps checked" together) — shows the fraction while a visit is
  in progress, the plain count before one starts, never both.
- Trap management + Traps list cards: label:value reformatting
  (`Build:`, `Camera:`, `Route:`, `Last kill:`), stripping the redundant
  `{Product} Build ` prefix from the Build Version value.
- Build management card: `First active: … · Source: …` (was bare text),
  stripping a `Built from ` prefix from Notes when present, falling back
  to the raw note text otherwise.
- Follow-up card: `Bag: … · Reason: …` on one line, `Created: …` on the
  next; the follow-up **type** (Camera review / Necropsy review) now
  renders as a new neutral grey tag (`status-pill-neutral`) instead of
  bare text, so it can never be mistaken for one of the four real status
  colours. Priority is still shown plainly, unchanged — an explicit
  decision this time (not a re-punt): no extra visual weight for High in
  this release.
- Tertiary button tier added: necropsy review's "← Back to task list"
  only, scoped to that one button via its own Streamlit `key` (not a
  shared class/type) after checking that the app's 7 other "Back" buttons
  don't share a selector that would have swept them in too. Padding
  bumped past Figma's ~34–40px spec to a 44px minimum tap target
  (`STYLE_GUIDE.md`'s "field clarity first").

**`STYLE_GUIDE.md`** updated for all of the above: card radius/shadow/
padding/gap tokens, Primary button radius, card title scale, and the
Tertiary tier's full spec (it already had a one-line stub — expanded
in place rather than treated as new, since the brief's assumption that it
"doesn't exist in the guide at all" didn't hold up once checked).

## Verified

- Real browser, both breakpoints (1440 desktop / 390 & 430 mobile):
  shell renders correctly on Trap sites, Traps list, Follow-ups (including
  a freshly generated necropsy follow-up, since the demo seed had none
  open), and the Administration popover.
- **One real bug caught and fixed during verification, not before:** the
  Tertiary button's background/color initially failed to apply — traced to
  a CSS cascade-order conflict (tied specificity with later
  `button[kind="secondary"]` redeclarations elsewhere in the file, which
  won by being later in document order) and a Streamlit-rendered child
  span carrying its own color override. Fixed by moving the rule to the
  file's last `<style>` block and adding an explicit `button *` selector
  for the child span. Confirmed via direct `getComputedStyle` inspection
  before and after, not just a visual re-check.
- Login page confirmed unaffected: its own card/form styling is scoped
  separately and untouched; its Sign-in button uses Streamlit's distinct
  `primaryFormSubmit` kind, which the Primary-button pill rule doesn't
  match (confirmed via `getComputedStyle`, not assumed).
- Nav pills confirmed unchanged (`box-shadow: none`, `999px` radius,
  same as before) — visually diffed, not just "wasn't in the diff."
- Full local suite: 31/31. Code/data gate: 55/55. Browser evidence gate:
  7/7 — including the existing `mobile_checked_state.png` capture, which
  now shows the new shell on a real `visit-trap-card` in its checked
  state.

## Real-device pass — done, and it found three real bugs no browser test caught

Tested against a physical phone on the same Wi-Fi as the dev machine
(local server bound to `0.0.0.0`, reached at the Mac's LAN IP — a genuine
physical device, not a simulator). All three findings below were
confirmed with direct DOM/CSS inspection, not just re-styled on
appearance, and all three are now covered by the full suite passing
afterward.

1. **Secondary buttons stayed square.** See the button-radius entry above
   — the brief only specified Primary; real-device viewing showed the
   contrast against the new rounded cards read as unfinished, not
   deliberate. Fixed at the shared base rule.

2. **A whole class of buttons silently lost their intended padding/height.**
   Any button with Streamlit's `help=` tooltip parameter (`Finish site
   check`, the trap-editor `×` close button, at least two others) gets
   wrapped by Streamlit in extra `stTooltipHoverTarget`/`stTooltipIcon`
   `<span>` elements between `div.stButton` and the actual `<button>`.
   Every button-sizing rule in this file used a `div.stButton > button`
   *direct-child* selector, which silently stopped matching the moment a
   tooltip wrapper was present — the button still picked up radius (from
   a separate, non-child-restricted rule) but fell back to Streamlit's raw
   `4px 12px` padding / `40px` min-height underneath. Confirmed via
   `getComputedStyle` and a full ancestor-chain dump before concluding
   this, not guessed from appearance. Fixed by changing every such
   selector in the file from direct-child (`>`) to descendant matching,
   closing the whole bug class rather than patching the one button that
   happened to get noticed.

3. **Photo picker had a large empty gap below it — both on the check form
   and the necropsy review form.** Traced via devtools on the real device
   to the photo-upload iframe (`photo_component/index.html`) being stuck
   at a leftover `height="501"` while its actual content (`summary`/`grid`,
   both empty pre-upload) needed a fraction of that. Root cause: the
   component only ever called Streamlit's `setFrameHeight` **once**, at
   initial script load, with nothing to correct it afterward if that one
   measurement landed wrong or content changed later — a fragile pattern
   that a fast local Chromium run doesn't reliably expose but a real
   device under real timing conditions does. Fixed with a `ResizeObserver`
   on the component's own body plus redundant re-triggers (`load`, a short
   `setTimeout`, and on every `streamlit:render` message), so the reported
   height stays continuously correct instead of being a single guess.
   This is the photo-integrity module's *display* layer only — none of
   the upload/store/verify logic was touched, and the full
   `test_photo_store.py` / `test_photo_component.py` suite plus the
   3-photo-kill browser test all still pass unchanged.

## What's still open

- Phase 2 (site card schedule split + urgency pill) — not started,
  correctly gated behind this checkpoint per the brief's own sequencing.
