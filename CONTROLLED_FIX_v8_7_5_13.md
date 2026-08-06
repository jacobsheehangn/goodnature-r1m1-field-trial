# Controlled fix v8.7.5.13 — Page rhythm cleanup

Built directly from v8.7.5.12.

## Removed completely

- retired `show_environment_banner()` component
- FIELD PILOT / Live trial data markup
- all staging-banner CSS
- desktop and mobile spacing that existed to accommodate the retired banner

## Page rhythm

One final authoritative rule now controls authenticated page spacing:

- desktop: 3.25rem top clearance
- mobile: 3.75rem plus device safe-area clearance
- login page retains its own isolated spacing

The Demo data warning is intentionally retained when synthetic records are loaded because it is dataset context, not the retired environment label.

## Unchanged

- closed and open menu controls
- cards
- navigation and workflows
- workbook, checks, photos, windows, history and follow-ups
