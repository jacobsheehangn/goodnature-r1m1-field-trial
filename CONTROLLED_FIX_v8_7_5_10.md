# Controlled fix v8.7.5.10 — Closed menu control

Built directly from v8.7.5.9.

## Changed

Only the closed-sidebar menu control.

The CSS now explicitly supports both Streamlit DOM forms:

1. `stSidebarCollapsedControl` is the clickable control itself
2. `stSidebarCollapsedControl` contains a nested button

Exactly one app-owned right chevron is drawn in either form.

## Explicitly unchanged

- the confirmed working open-drawer chevron
- all card components and surfaces
- navigation behaviour
- forms and workflows
- workbook, check, photo, window and follow-up logic
- dependency versions

The Streamlit version has not been changed in this controlled fix.
