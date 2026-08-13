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
- ~~Failed save can permanently strand the field operator on that trap~~ — fixed:
  `commit_staged_records_with_photos` now accepts
  `session_state_keys_to_clear_on_failure` and clears them in its `except` block,
  before `st.stop()` — so the save-lock is cleared even when the deeper commit fails,
  not just the three earlier validation paths. Regression-tested in
  `tests/test_save_lock_recovery.py`.
- ~~Every field visit is silently attributed to a hardcoded operator name~~ — fixed:
  added a real "Operator" field to the Administration popover (reachable from every
  page, same as Sign out), bound to `st.session_state.field_operator`. The dead
  `page == "site"` handler's copy still exists but is no longer the only path.
  Regression-tested end-to-end in `tests/test_operator_attribution.py` (sets the name
  via the UI, starts a visit, confirms the saved `Visits.Operator` value).
- ~~My own bulk-activate preview could go stale against what actually commits~~ —
  fixed: the selection checkboxes, individual time overrides, and shared date/time/
  reason inputs are now locked (`disabled=`) once a preview is pending, and the
  confirm step reads from a fully-frozen snapshot (`individual_times` and `reason`
  captured into `bulkact_pending` at preview time) rather than re-reading live widget
  state. Cancel is the only way to change the selection now. Regression-tested in
  `tests/test_bulk_activate_lock.py`.
- ~~Necropsy corrections skipped the consistency rules enforced at first entry~~ —
  fixed: extracted `necropsy_consistency_errors()` (the 4 cross-field rules — e.g. "a
  supportive necropsy must have Final Humane Kill = Yes") into a shared function, now
  called from both the original Necropsy review task and the Necropsy evidence
  correction form. Regression-tested in `tests/test_correction_consistency.py`
  (pure-function coverage of all 4 rules, plus an end-to-end UI test confirming the
  correction form actually blocks an inconsistent save and doesn't persist it).
- ~~Correcting a check's Finding didn't touch the Window it closed~~ — fixed: the
  Field check correction now also updates `Windows.Finding At Close` for the window
  the check closed (via `Checks."Window Closed"`), with its own audit-log row, then
  calls `recalculate_window()` and `refresh_review_status()` — so a corrected Finding
  actually moves the Trial Performance / Kills numbers, and (via the
  `followup_genuinely_warranted()` merge above) can now correctly surface "Needs
  recreation" if the correction newly warrants a review. Regression-tested end-to-end
  in `tests/test_correction_consistency.py`.
- ~~No concurrency check on save~~ — fixed: `save_data()` now rejects a save if the
  on-disk workbook's mtime has moved since this session's data was loaded, instead of
  silently overwriting. Tracked via `st.session_state[DATA_LOADED_MTIME_KEY]`, set
  once right after the app's single top-level `load_data()` call — session-scoped
  (not a module-level global) since Streamlit serves multiple sessions from one
  process. Opt-in: inert for the ~35 other `save_data()` call sites and every existing
  bare-mode test, since the check only fires when session_state carries a tracked
  mtime. On conflict: `st.error(...)` + `st.stop()`, matching this file's existing
  hard-failure pattern, telling the user to reload and retry (a reject, not a
  retry-merge — merging per-field across every sheet was out of scope). Regression-
  tested in `tests/test_save_concurrency.py` (conflict rejected + content preserved,
  normal single-session saves unaffected, untracked/bare-mode saves unaffected).

## High severity — data integrity & security

1. **"Resume checking" restores position, not answers.** After a real session drop,
   the resume dialog reassures the operator their work is safe — but Finding, Species,
   Rat type, Condition, Camera check, Notes live only in ephemeral `session_state` with
   no disk backing (unlike Bag ID/photos, which do persist). Fix direction: persist
   in-progress answers to the same kind of small on-disk transaction record already
   used for photos/bag ID, keyed by the deterministic check ID.

2. **Connectivity resilience covers photos and position, not answers.** Same root
   cause as #1 — the app tells operators to background the browser to use the native
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
