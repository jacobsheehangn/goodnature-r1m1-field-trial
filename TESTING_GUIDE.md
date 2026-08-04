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
