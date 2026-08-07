# v8.7.6.2 — Wrapping top navigation

Built from v8.7.6.1.

## Navigation architecture

- Streamlit `st.navigation` remains the router.
- Router position is now `hidden`, so Streamlit does not render its mobile overflow drawer.
- Four main destinations use Streamlit `st.pills`.
- Pills wrap naturally at narrow widths rather than collapsing into a menu.
- Administration uses a Streamlit popover.
- Destinations use `st.switch_page`, preserving framework URLs, routing and browser history.
- No JavaScript, DOM injection, sidebar opening, overlay, chevron or browser-specific code.

## Destinations

Primary:
- Trap sites
- Traps
- Follow-ups
- Trial performance

Administration:
- Trial setup
- Data & records
- Sign out

## Unchanged

- authentication
- trap-check workflows
- cards
- follow-up logic
- workbook and field data
- local Python 3.12 launcher fix
