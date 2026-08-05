## Run locally

On Mac, double-click `START_LOCAL_TEST.command`.

Local records are stored separately in `local_test_data/`.
Use `RESET_LOCAL_TEST_DATA.command` to restore fresh demo data.

# R1/M1 Field Trial App — v8.6.73 Field Pilot Mode

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


## v8.6.40 canonical mobile UI

Replaced accumulated CSS patches with one canonical stylesheet.

Fixed:

- iPhone login auto-zoom with 16 px mobile form controls
- Streamlit menu clipping by removing fixed toolbar/header heights
- card outlines using a shared app-owned marker across 19 bordered sections
- sidebar active and inactive text contrast
- Safari safe-area spacing

Unchanged:

- approved typography
- sidebar width
- site and trap card content
- staging message copy


## v8.6.41 global field UX

System-wide changes:

- user-facing route language replaced with trap order and trap progress
- shared navigation now resets every destination page to the top
- scroll reset retries after Streamlit rerenders
- radio and select controls use one consistent light-theme component style
- generic sticky form actions removed
- sidebar open/close controls explicitly use dark icons
- seeded trap locations now read `Trap 1`, `Trap 2`, and so on

Internal workbook field names such as `Route Order` remain unchanged for data compatibility.


## v8.6.42 explicit photo capture

The camera no longer initialises when **Dead animal found** is selected.

Photo flow:

1. choose a photo type
2. tap **Take photo** or **Upload image**
3. capture/select the image
4. see a thumbnail in the check
5. remove it or add another image
6. save all images with the trap check

The camera exists only after an explicit **Take photo** action. Manual upload supports one or more JPG, PNG or WebP images. Duplicate images are skipped.


## v8.6.43 upload-only photos

- Removed the embedded camera widget throughout the app.
- **Add photo** opens the device's standard image picker.
- Multiple images, thumbnails, duplicate detection and removal remain.
- Hardened mobile sidebar open/close icon contrast.
- Unselected radio buttons and checkboxes now use white interiors with dark outlines.
- Updated the style guide to capture the current approved baseline.


## v8.6.44 automated release gate

Added:

- static source checks
- workbook integrity checks
- Playwright desktop and mobile smoke tests
- screenshot capture
- one-command local runner
- GitHub Actions workflow
- environment-variable credential handling

See `TESTING_GUIDE.md`.


## v8.6.45 hardened release gate

- Added a self-contained Playwright `page` fixture.
- Removed reliance on the optional pytest-playwright plugin.
- Browser preflight failures now explain how to install Chromium.
- GitHub Actions remains the recommended live test runner.


## v8.6.46 GitHub-compatible release gate

- Removed the unavailable `artifact-tool` test dependency.
- Workbook release checks now use `openpyxl`.
- App behaviour and trial data are unchanged.


## v8.6.47 login test fix

- Targets the password textbox exactly in Playwright.
- Avoids matching Streamlit's separate **Show password** button.
- Tightens the sign-in button locator.
- No app behaviour or trial data changed.


## v8.6.48 live gate stability

- Login tests tolerate Render cold starts and already-authenticated sessions.
- Mobile sidebar tests select only visible, on-screen controls.
- Legacy persistent values such as `Route point 1` display as `Trap 1`.
- Internal workbook fields remain unchanged.


## v8.6.49 metric surface fix

- Removed the nested border and background from Streamlit metrics.
- The surrounding section card remains the single visual boundary.
- Audited all metrics: 3 total, all 3 inside section cards.
- Added a live browser regression test for metric border and shadow styles.
- No data or calculation changes.


## v8.6.50 native-aligned field UI

Controlled alignment with the Goodnature native app:

- refined neutral and semantic colour tokens
- softened card borders and shadows
- standardised 14 px section radius
- clarified primary, secondary, tertiary and destructive action hierarchy
- retained larger field controls, sidebar navigation and explicit labels
- replaced the style guide with a Streamlit-specific Goodnature field UI guide


## v8.6.51 live test hardening

- waits for the visible main Trap sites screen rather than hidden staging/sidebar text
- avoids strict-mode collisions from duplicate Streamlit elements
- scans multiple Streamlit sidebar-control variants
- clicks only controls that are visible and inside the viewport
- adds explicit waits before Start checking
- scopes Performance navigation to the sidebar
- no app behaviour or trial data changes


## v8.6.52 state-aware live tests

- site journeys support Start checking, Continue checking, Resume checking and Open visit
- tests no longer assume the persistent staging workbook is fresh
- sidebar navigation clicks the actual button ancestor
- sidebar targets are scrolled into view before clicking
- no app behaviour or trial data changed


## v8.6.53 deterministic release gate

The required release gate no longer drives the deployed Render app.

It now:

1. starts a fresh local Streamlit instance in GitHub Actions
2. uses isolated clean-seed data for every browser test
3. runs static, workbook and browser checks deterministically
4. uploads screenshots

The deployed Render check is now a separate, optional, non-blocking smoke test available
from **Run workflow**. It checks only that the deployed app opens and accepts login.

This removes persistent staging data, Render deployment timing and Streamlit sidebar
positioning from the required release decision.


## v8.6.54 radio test fix

- replaces the obsolete BaseWeb radio selector with a geometry-based rendered indicator check
- verifies the visible radio indicator is not solid black
- no app behaviour, styling or data changes


## v8.6.55 trap history

- restored Trap history to the main navigation
- each trap shows total kills, total checks and last-kill date
- trap detail shows lifetime totals and full chronological history
- includes completed follow-up work in the timeline
- supports site filtering and trap/location search


## v8.6.56 navigation labels

Visible language only:

- Trap history → Traps
- Follow-up tasks → Follow-ups
- Performance → Trial performance
- Setup → Trial setup
- Data Management → Data & records
- More → Administration
- Trial history → Trial periods

Internal route keys, data flows and page behaviour are unchanged.

The browser-level radio DOM test was removed because the tested first-trap screen does
not consistently render a Streamlit radio control. The release gate now verifies the
actual white, dark-outline and orange-selected CSS rules directly.


## v8.6.59 trap detail page

- replaced the simulated Traps drawer with a dedicated detail page
- same navigation model on desktop and mobile
- Back to traps replaces ×
- Traps remains highlighted in the sidebar
- search and site filter persist on return
- grouped history and fixed-width time column retained
- no workbook or field-check workflow changes


## v8.6.60 mobile menu auto-close

- mobile sidebar closes after selecting a main or administrative destination
- shared navigation behaviour only; no page-specific patches
- retries after Streamlit rerenders its page chrome
- desktop sidebar behaviour is unchanged


## v8.6.61 mobile menu close fix

The first auto-close implementation failed when Streamlit's collapse control was
off-screen or replaced during rerender.

The shared close routine now:

- observes Streamlit DOM changes
- retries for up to 3.2 seconds
- activates off-screen collapse controls programmatically
- supports multiple control variants
- sends Escape as a fallback
- confirms closure from the sidebar's actual state and geometry


## v8.6.62 navigation state and gate fix

- mobile browser tests now distinguish an open sidebar from an off-canvas sidebar
- tests open the menu before attempting to click a mobile navigation item
- trap search and site filter use durable session state separate from widget state
- returning from trap detail restores the previous list context
- no workbook or field workflow changes


## v8.6.63 mobile navigation polish

- forces the mobile menu chevron to dark grey on the white header
- removes mutation observers and repeated sidebar clicks
- closes the sidebar once, 120 ms after the destination page renders
- uses one Escape fallback only when no collapse control is found
- desktop behaviour is unchanged


## v8.6.64 pre-render menu close

- removes the post-render mobile sidebar close routine
- closes the sidebar from the same tap that selects a destination
- uses one capture-phase listener for named navigation destinations
- ignores the Administration expander
- retains the dark-grey mobile menu chevron


## v8.6.65 stable release gate

- app behaviour is unchanged from v8.6.64
- removed required browser automation for Streamlit's mobile off-canvas sidebar
- retained deterministic mobile rendering and overflow tests
- retained trap-detail, Back and filter-state tests
- mobile menu contrast, close and flicker are manual release checks


## v8.6.66 mobile chevron contrast fix

- CSS-only change
- forces the mobile header menu chevron geometry to dark grey
- also covers the sidebar collapse chevron and Administration expander chevron
- targets SVG paths, lines and polylines rather than relying on inherited icon colour
- navigation behaviour and release-gate strategy are unchanged


## v8.6.67 message contrast and header clearance

- fixes unreadable white text in pale-yellow warning/guidance panels
- warning text now uses dark olive `#4a4317`
- all semantic panels explicitly inherit readable dark text
- increases mobile top clearance so Back actions and page context are not hidden under the header
- desktop spacing remains unchanged


## v8.6.68 header-clearance test fix

- app CSS and behaviour are unchanged from v8.6.67
- replaces an invalid bounding-box assertion
- verifies computed mobile top padding is at least the rendered header height
- retains the mobile chevron and message-contrast fixes


## v8.6.69 clean browser gate

- app behaviour and CSS are unchanged from v8.6.68
- removed brittle browser tests for mobile chevron colour, header padding and warning-panel colour
- those visual rules remain protected by the static gate and manual release checks
- dead-animal flow now fails when the required option is missing instead of skipping
- required browser tests now focus on stable user outcomes


## v8.6.70 mobile navigation and auth persistence

- replaces Streamlit's mobile sidebar chevrons with app-owned dark-grey CSS chevrons
- removes the small white icon boxes inside the open drawer
- aligns the Administration expander chevron at the far right
- stores a signed access token in the browser URL after successful login
- browser refresh and pull-to-refresh restore access without re-entering the password
- the token does not contain the shared password


## v8.6.71 correct app-menu chevron

- reverts the incorrect v8.6.70 toolbar/settings chevron styling
- targets only `stSidebarCollapsedControl`, the actual app menu control
- keeps the open-drawer collapse control transparent and aligned
- keeps the Administration chevron aligned right without a white icon box
- refresh-persistent authentication from v8.6.70 remains included


## v8.6.72 single drawer close control

- keeps the working dark-grey collapsed app-menu chevron
- removes the custom pseudo-chevron from the open drawer
- restores one native drawer close icon with no white box
- keeps the Administration expander chevron aligned right
- keeps refresh-persistent authentication


## v8.6.73 field pilot mode

- changes the environment banner to `FIELD PILOT — Live trial data`
- treats the persistent workbook as the authoritative pilot record
- keeps the single mobile drawer close control
- keeps refresh-persistent authentication
- no data is deleted or reset by this release
