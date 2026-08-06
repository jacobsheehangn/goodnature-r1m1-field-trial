# Controlled fix v8.7.5.14 — Safari menu and site status

Built directly from v8.7.5.13.

## Site card

When there is no open visit and the latest completed visit ended today:
- status now reads `Last checked today`
- `Start checking` remains available

No lifecycle or repeat-visit behaviour changed.

## Closed-menu control

The closed-menu trigger no longer depends on CSS pseudo-elements rendered by Chrome or Safari.

It now:
- creates one app-owned browser button
- shows only while the sidebar is closed
- invokes Streamlit's real collapsed-sidebar control
- works against either a direct control or nested button DOM
- hides Streamlit's native closed control visually
- updates after rerenders, resize and orientation changes

## Explicitly unchanged

- working open-drawer control
- cards and page layouts
- navigation targets and workflows
- workbook, checks, photos, windows, history and follow-ups
