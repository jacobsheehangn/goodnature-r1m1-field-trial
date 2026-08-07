# v8.7.6.6 Critical Photo Integrity

## Scope
A tightly contained photo-integrity release built on v8.7.6.5.

- Keeps navigation, cards, workflow and workbook structure unchanged.
- Replaces only the dead-animal photo uploader internals with browser-side preparation.
- Resizes to a maximum 1800 px long edge and exports JPEG at 82% quality before transfer.
- Stores each prepared photo immediately against a stable pending Check ID.
- Uses stable Photo IDs and idempotent file paths.
- Retries transient file writes automatically after 1, 2 and 4 seconds.
- Shows per-photo preparing, uploading, saved, retrying and failed states.
- Retries only failed photos and never rewrites an already verified identical file.
- Uses a fixed 3-column desktop / 2-column mobile grid with reserved status and action space.
- Blocks Save check only when one or more selected photos are unresolved.
- Allows normal saving when no photos were selected.
- Re-verifies file count and pending photo-row count before enabling and during final save.
- Commits the check, follow-ups and Photos rows in the existing single workbook save.
- Reloads the workbook after save and verifies the persisted Photos rows.

## Browser claim
Browser-side preparation is implemented but must be tested on deployed mobile Safari before the release is described as field-proven.
