# v8.7.6.4 — Responsive navigation layout

Built from v8.7.6.3.

## Layout correction

- All five navigation controls share one horizontal wrapping container.
- Administration now wraps with the page links instead of sitting in a separate block.
- All five controls use the same pill shape, height, border, padding and type.
- The container uses the full available width.
- Desktop remains on one line whenever the available width permits.
- Mobile wraps naturally based on the real viewport.

## Architecture unchanged

- `st.navigation(position="hidden")` remains the router.
- `st.page_link` remains the page-navigation control.
- Administration remains a Streamlit popover.
- No JavaScript, DOM injection, sidebar opening or browser-specific routing logic.
