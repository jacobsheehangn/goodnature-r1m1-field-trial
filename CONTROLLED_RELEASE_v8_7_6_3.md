# v8.7.6.3 — Native wrapping page links

Built from v8.7.6.2.

## Root cause fixed

The stateful `st.pills` value was reset to the current routed page before the new selection could trigger navigation. The controls therefore rendered and reacted visually but did not change pages.

## Navigation

- `st.navigation(position="hidden")` remains the supported router.
- Main destinations now use native `st.page_link` controls.
- Links sit inside `st.container(horizontal=True)`, which wraps to another line when space is limited.
- Administration remains a native Streamlit popover and now uses native page links.
- Current main destination is disabled to show location and prevent redundant reruns.
- No JavaScript, DOM injection, sidebar control, pills state, callback routing or browser-specific code.

## Unchanged

- authentication
- trap-check workflows
- cards
- follow-up logic
- workbook and field data
- Python 3.12 local launcher
