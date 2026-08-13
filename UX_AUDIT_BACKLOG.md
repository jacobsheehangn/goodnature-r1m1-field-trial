# UX audit backlog

From a full-app UX audit run 2026-08-13 (five parallel reviews covering the core
field-check flow, follow-up/review workflows, corrections & performance dashboards,
trial-setup/administration, and cross-cutting concerns — perf, session state, mobile,
connectivity, auth). Findings below are what's still outstanding after the first pass
of fixes. Line numbers are as of the audit commit and will drift as the file changes —
treat them as a starting point, not gospel.

**Working agreement:** whenever a release is pushed, resurface this list and ask what
to tackle next, rather than letting it go stale in a closed conversation.

## Done

- ~~Follow-up removal can silently mislabel a real kill as "review not required"~~ —
  merged the existing unmerged fix (`a2fd9d2`, branch `claude/missing-followup-recovery-34fc4d`)
  into main. `followup_genuinely_warranted()` / `missing_followup_windows()` /
  `recreate_followup()`.
- ~~"Sign out" doesn't actually sign out~~ — fixed: sign-out now also clears the
  `access` URL query param, not just session state. Regression-tested in
  `tests/test_auth.py` (confirmed it fails against the pre-fix code, not just that it
  passes now).

## High severity — data integrity & security

1. **Failed save can permanently strand the field operator on that trap.**
   `app.py` — `commit_staged_records_with_photos` calls `st.stop()` on failure without
   resetting the per-trap saving-lock; next rerun the Save button stays disabled forever.
   Fix direction: reset the lock in the failure path too, not just the three earlier
   validation-failure paths.

2. **"Resume checking" restores position, not answers.** After a real session drop,
   the resume dialog reassures the operator their work is safe — but Finding, Species,
   Rat type, Condition, Camera check, Notes live only in ephemeral `session_state` with
   no disk backing (unlike Bag ID/photos, which do persist). Fix direction: persist
   in-progress answers to the same kind of small on-disk transaction record already
   used for photos/bag ID, keyed by the deterministic check ID.

3. **Every field visit is silently attributed to a hardcoded operator name.**
   `field_operator` defaults to `"Jake"`; the only Operator input field lives in the
   dead `page == "site"` handler (confirmed unreachable). Fix direction: either add a
   real operator-name entry point to the live flow, or resurrect/repair the dead one.

4. **Necropsy corrections skip the consistency rules enforced at first entry.** The
   original necropsy review enforces cross-field rules (e.g. "a supportive necropsy
   must have Final Humane Kill = Yes"); the Corrections version of the same form has
   none of them. Fix direction: factor those rules into a shared validator called from
   both paths.

5. **Correcting a check's Finding doesn't touch the Window it closed.** The Field-check
   correction tool only writes `Checks`, never `Windows.Finding At Close`, and doesn't
   recalculate anything — so "Correction saved" doesn't actually move the numbers on
   Trial Performance for exactly the kind of mistake this tool exists to fix.

6. **My own bulk-activate preview can go stale against what actually commits** (Trial
   setup → Traps → Bulk activate traps). Clicking "Preview activation" freezes the
   selected trap list and shared date/time into session state, but the checkboxes and
   date/time widgets above stay live underneath the preview — and per-trap individual
   time overrides are read live, not frozen. Editing a selection after previewing can
   silently commit something different from what the preview showed. Fix direction:
   lock the inputs once a preview is pending, or drop the freeze and compute the
   confirm from live state at click time.

7. **No concurrency check on save.** Every save is an unconditional full-workbook
   overwrite with no check that the on-disk file is still the version this rerun
   loaded — two operators saving around the same time can silently clobber each
   other's work. Fix direction: compare file mtime/checksum immediately before the
   final write and reject/retry-merge on mismatch.

8. **Connectivity resilience covers photos and position, not answers.** Same root
   cause as #2 — the app tells operators to background the browser to use the native
   camera, which is exactly the kind of real session loss that leaves the
   questionnaire unrecoverable.

## Medium severity — workflow friction & scale readiness

- No double-submit lock on the 3 follow-up review save buttons (camera/necropsy/
  camera-issue) — the check page got this fix explicitly; reviews didn't.
- Necropsy review has no notes field — can't record why an assessment was ambiguous
  or contradicts camera evidence.
- "Evidence unusable" doesn't require an explanation despite the UI text implying it
  should — inconsistent with the camera-issue path one branch down.
- Camera evidence is a free-text URL field, not the hardened/checksummed photo
  pipeline necropsy gets.
- Trap detail hides open follow-ups, showing only completed ones.
- Window detail has no link into its own review task.
- The only place to correct a window's physical finding is filed under "Camera
  evidence" — misleading for camera-less traps.
- Window start-time correction is hardcoded to R1 only; M1 has the same underlying
  bug with no fix path.
- "Results needing attention" lists bad kills/windows with a plain Window ID, no link
  into Corrections to actually fix them.
- Same action, different validation: Activate/Deactivate require a non-empty reason;
  Move trap and Change build (same page, same card shape) don't.
- No chronological guardrail on effective times across activate/deactivate/move/
  change-build — can silently create negative-duration windows.
- Traps list has no search or status filter, only site — a real gap heading toward
  50+ traps.
- Every save is a full-workbook rewrite, cost scaling with total historical data —
  fine now, won't scale gracefully over months.
- Single shared password, no per-operator identity or session timeout.

## Low severity — polish

- Validation errors are generic bundled lists, not tied to the specific offending
  field (camera review, necropsy, corrections forms).
- No pending-count badge on the Follow-ups nav link.
- Audit Log has no search/filter.
- Move trap uses `st.toggle` where its three siblings use `st.expander`.
- Per-check `session_state` widget keys aren't cleaned up after save.
- The dead `page == "site"` handler and a second dead trap-edit drawer panel — the
  latter happens to be the only place `delete_unused_trap` is wired up, so there is
  currently **no way to delete a mistakenly-added trap** at all. Worth reviving that
  one function even if the rest of the dead panel is deleted.

## What's already solid (don't re-litigate)

Photo integrity pipeline (checksummed, transactional, rollback-safe), `load_data()`
caching, mobile tap targets/breakpoints, the site-removal/rename tool's guardrails
(type-to-confirm, reason, linked-record preview — a good pattern the weaker tools
above should copy), the window start-time bulk-correction tool's preview/partial-
failure handling, and the demo-data warning banner were all checked and found to
already meet a high bar.
