# R1/M1 testing guide

## Required release gate

The required GitHub Actions gate contains:

- static regression checks
- workbook structure and reference checks
- deterministic browser tests against a fresh local Streamlit server
- clean, isolated data for each browser test
- mobile 390 px, mobile 430 px and desktop 1440 px screenshots
- horizontal-overflow check
- initial trap journey and terminology check
- upload-only photo check
- selection-control appearance check

This gate does not depend on Render or its retained workbook.

## Optional deployed smoke test

From GitHub Actions, choose **Run workflow** and enable:

`Also run the optional deployed-app smoke test`

That test is non-blocking. It checks only that the deployed app responds and login works.
It deliberately does not automate sidebar navigation or mutate live staging data.

## Physical device check

Before field use, still confirm on an actual iPhone:

- login
- sidebar opens
- first trap journey
- image picker
- touch targets
- Safari chrome and safe area
- save and confirmation behaviour


## v8.6.56 labels-only release

The navigation test confirms the approved visible labels. Internal routes remain:

- sites
- network
- followups
- results
- setup
- data_management

Selection-control appearance is protected through static CSS-contract checks rather
than a browser assertion tied to Streamlit's internal radio markup.


## Trap detail page

Test at 390 px and 1440 px:

- View opens a dedicated page
- no trap cards remain above the detail
- Back to traps returns to the list
- search and site filter persist
- no horizontal overflow
- grouped event history remains readable


## Mobile menu auto-close

At 390 px:

- open the sidebar
- choose a different main destination
- confirm the destination page renders
- confirm the sidebar closes automatically


## Off-canvas sidebar testing

Do not use Playwright `is_visible()` alone to decide whether the Streamlit sidebar is
open. An off-canvas sidebar can remain visible in the DOM.

Before clicking a mobile menu item, confirm its sidebar geometry intersects the
viewport. Open the collapsed control when it does not.


## Mobile navigation polish

At 390 px:

- confirm the collapsed menu chevron is dark grey against the white header
- open the menu and select another page
- confirm the destination renders once
- confirm the drawer closes once without reopening or flickering

## Pre-render mobile menu close

At 390 px, confirm each main and administrative destination closes the sidebar from
the same tap, renders once, and does not flicker.


## Manual mobile navigation release check

The required CI gate does not automate Streamlit's mobile off-canvas sidebar. Before promotion, manually verify:

- menu chevron is visible
- menu opens
- each destination changes page
- menu closes once
- no close/reopen flicker
- destination appears at the top
