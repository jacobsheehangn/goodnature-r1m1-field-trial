# v8.7.5.1 — Controlled menu chevron fix

Scope is limited to the shared sidebar controls.

## Fixed

- closed menu chevron visible on desktop and mobile without hover
- open drawer close chevron visible on desktop and mobile without hover
- stable dark-grey contrast on light surfaces
- no dependency on Streamlit's native SVG colour or geometry
- no generic header-button selectors
- no changes to app workflows, data, navigation or forms

## Root cause

The final v8.7.5 CSS layer removed the earlier app-owned pseudo-chevrons and attempted to restore Streamlit's native SVG icons. The rendered native icons were not reliably visible. The final CSS now owns both sidebar icons explicitly.
