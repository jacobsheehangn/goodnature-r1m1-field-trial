# v8.7.5.15 — Menu diagnostics

Built directly from v8.7.5.14.

## Purpose

This is a diagnostic staging build, not a final menu fix.

It removes the failed app-owned closed-menu injection and exposes Streamlit's native
closed control again. A temporary Menu diagnostics panel reports:

- Safari/Chrome user agent
- viewport
- whether the component can access the parent app DOM
- whether the native closed-menu control exists
- direct button, nested button, or wrapper-only DOM form
- control size and computed visibility
- sidebar geometry and open/closed result
- whether a programmatic click was attempted and whether it opened the drawer

## Test

On the failing iPhone Safari session:

1. Sign in.
2. Leave the sidebar closed.
3. Open `Menu diagnostics — temporary`.
4. Screenshot the initial JSON.
5. Tap `Test native menu`.
6. Wait one second.
7. Screenshot the updated JSON and the page/drawer state.

Also repeat once after:
- browser refresh
- opening and closing the drawer manually, if the native control is visible
- rotating the phone, optional

## Unchanged

- open-drawer control
- site status wording (`Last checked today`)
- cards, forms, workflows and data
