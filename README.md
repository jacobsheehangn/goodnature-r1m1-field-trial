# R1/M1 Field Trial App — v8.6.39 Compact Staging Banner

## Deployment requirement

Set `R1M1_DATA_DIR` to a persistent, writable mounted folder before field use. The workbook, evidence photos and automatic backups are stored there. If unset, the app folder is used.

## Critical fixes

- Atomic workbook replacement with timestamped backups; latest 20 backups retained.
- Phone photos are orientation-corrected, resized to 1600 px maximum and compressed to JPEG under 2 MB.
- A raw capture above 20 MB or an unreadable image is rejected before the check saves.
- Photo files are rolled back if the linked workbook save fails.
- Photo paths are stored relative to the configured data folder.
- Startup checks verify that the data folder is writable and warn when it appears temporary.
- Sidebar version label corrected.

# R1/M1 Field Trial App — v8.6.27 System Quality Pass

This release applies the agreed first-principles and style-system audit at shared-system level. Key changes include evidence provenance, central derived-field recalculation, structured camera-issue resolution, shared workflow components, natural duration formatting, read-only exports, demo-data warning and white-on-orange primary actions.

# R1/M1 Field Trial App — v8.6.25 Trap Finding Heading

- Restores the explicit **What did you find?** heading at the start of each trap check.
- Removes raw HTML from the bag-label instruction.

# R1/M1 Field Trial App — v8.6.24 Shared Review UX

This build fixes immediate conditional rendering in camera review, standardises follow-up task hierarchy, and restores the three-group trap-check confirmation. The included efficacy data is synthetic demonstration data.

# R1/M1 Field Trial App — v8.6.22 Evidence Task Flow

## Synthetic completed-evidence demo

This package contains **synthetic demonstration data**, not real efficacy evidence. It includes 20 completed R1 kills, five completed no-kill camera reviews, no open follow-up tasks, and one active window per trap.

# R1/M1 Field Trial App — v8.6.22

This build completes the evidence-task workflow update.

## Main changes

- Separate camera-review forms for confirmed kills and no-kill windows.
- Confirmed-kill reviews imply activation and kill, and ask only for the evidence needed to calculate attraction, interaction-to-kill speed and video assessment.
- Camera event timestamps begin blank, preventing accidental zero-duration performance records.
- Camera, necropsy and data-correction tasks share one UX pattern: what is being recorded, what the app will update, save, then a clear success state and next action.
- Planned site checks are fixed at a three-day interval for the current trial method.
- Actual test-window timestamps remain unchanged and continue to control evidence validation and calculations.

Run `START_APP.command` on macOS, or install the requirements and run:

```bash
streamlit run app.py
```


Synthetic median first-interaction-to-kill time: **32 hours**.


## v8.6.24

Confirmed-kill camera reviews no longer ask whether the animal entered the strike area. This is implied by the confirmed kill and remains stored as Yes for reporting consistency. The field remains available in no-kill reviews.


## v8.6.27 focused Performance view

- Top line now shows good vs bad kills, performance against the under-24-hour interaction-to-kill target, and evidence completeness.
- One diagnostic breakdown is shown at a time: rodent weight, build, site or trap.
- Attraction, conversion, timing diagnostics and raw records are retained under More detail.


## v8.6.30 camera-sampled performance
- Camera review tasks are created for every assessable closed window on camera-equipped traps, including no-kill checks.
- Non-camera traps skip all camera questions and still support field checks, necropsy and humane-outcome reporting.
- Performance shows camera coverage and a stepped interaction-to-humane-kill funnel.
- Rat weight bands now use 50 g increments through 400+ g.
- Rat kills capture Norway rat, Ship rat or Unclear.
- Site activation requires confirmed mobile coverage.


## v8.6.30 camera logic and Performance integrity

- One shared camera-issue predicate prevents non-camera traps creating camera tasks.
- Camera assignment is recorded on each test window so historical reporting does not depend on the trap's current camera setup.
- Whole-trial humane outcomes use physical kills, including non-camera kills and kills with unusable footage.
- Timing uses only physical kills with usable camera evidence and valid event times.
- No-kill evidence follows interaction → meaningful entry → activation and blocks contradictory states.
- Funnel language refers to reviewed camera windows, not unique rats.


## v8.6.30 photos and flow

- Trap-check confirmation and success transitions return to the top of the page.
- Dead-animal checks support mobile camera capture, preview, removal and multiple photos.
- Image files are saved under `evidence/<site>/<bag-or-trap>/`; workbook metadata is stored in the `Photos` sheet.
- Check next trap now uses a navigation callback and advances on the first tap.


## v8.6.32 controlled site-code rename

Site codes can now be renamed from **Setup → Trap sites → Edit → Rename site code**.

The rename:

- validates the new code and checks it is unique
- updates linked Site ID references in Sites, Traps, Visits, Windows, Followups and Photos
- uses the existing atomic save and automatic backup process
- adds an Audit Log entry with the reason and affected record counts
- leaves trap IDs, bag IDs and existing record IDs unchanged


## v8.6.33 rename integrity

- Site-code rename previews affected traps, visits, windows, follow-ups and photos.
- Existing evidence files move from the old site folder to the new site folder.
- Linked photo file paths update at the same time.
- File moves roll back if the atomic workbook save fails.
- Destination collisions block the rename before anything is moved.
- Backup filenames use microseconds and a short UUID to prevent rapid-save collisions.


## v8.6.34 site data

The seeded site records now use:

- HUT — Hutt River
- NAE — Naenae
- TAW — Tawa

All linked Site ID references were updated across traps, visits, windows, follow-ups and photos.


## v8.6.35 linked ID cleanup

All seeded identifiers now use the real site prefixes:

- HUT — Hutt River
- NAE — Naenae
- TAW — Tawa

This includes trap IDs, camera IDs, visit IDs, window IDs, linked check fields, follow-up links, bag IDs, evidence links and photo metadata.


## v8.6.36 deployment release

Added:

- fail-closed shared-password login
- sign-out action
- staging/production environment banner
- Render Blueprint with a paid web service and 1 GB persistent disk
- `/var/data` live-data configuration
- clean launch seed containing sites, builds, traps and one open window per trap
- no visits, checks, follow-ups, photos or audit history in the clean seed
- GitHub `.gitignore`
- deployment, security and operations guides

Render uses `R1M1_SEED_MODE=clean`. Local use remains on the demo seed unless configured otherwise.


## v8.6.37 forced light theme

The app now uses a fixed light theme across desktop, iPhone and Android.

- Goodnature orange remains the primary action colour.
- Text, labels, inputs, borders and cards use explicit light-theme colours.
- iOS and Android dark-mode preferences no longer switch the app into a dark palette.
- Primary and secondary buttons have explicit contrast-safe colours.


## v8.6.38 global surface pass

Changed only the agreed global UI items:

- restored borders and light surface backgrounds for cards, forms and grouped sections
- fixed sidebar button text contrast
- made the active sidebar item solid Goodnature orange with white text
- reduced the mobile Streamlit header height and forced it light
- added iPhone/Safari bottom safe-area spacing

Unchanged:

- typography
- sidebar width
- staging banner
- site-card content and density


## v8.6.39 compact staging banner

- Mobile now shows one line: **STAGING — Setup and testing only**
- Desktop shows: **STAGING — Setup and testing only. Do not record real field results.**
- No other layout, card, navigation or typography changes.
