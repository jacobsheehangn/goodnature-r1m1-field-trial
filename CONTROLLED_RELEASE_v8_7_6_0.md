# v8.7.6.0 — Framework top navigation

Built from the last stable field build, v8.7.5.14.

## Navigation

- removes custom sidebar navigation and all closed-menu injection
- uses Streamlit `st.navigation(..., position="top")`
- primary pages: Trap sites, Traps, Follow-ups, Trial performance
- Administration group: Trial setup, Data & records, Sign out
- retains the existing internal workflow router for site, visit and check screens
- adds an explicit Exit to Trap sites action while inside a field workflow

## Retained

- `Last checked today` site status wording
- existing cards, forms, workflows, workbook and persistent data model
- authentication and refresh persistence
- deliberate navigation scroll-to-top behaviour

## Not included

- follow-up necropsy image upload; recorded in the agreed jobs list for a later feature release
