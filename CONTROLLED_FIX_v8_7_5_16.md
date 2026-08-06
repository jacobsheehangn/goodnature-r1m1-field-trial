# v8.7.5.16 — Mobile sidebar control

Built directly from v8.7.5.15 diagnostic evidence.

## Diagnostic result

On iPhone Safari:
- parent app DOM was accessible
- sidebar existed off-screen
- Streamlit did not render any collapsed-menu control
- no native button existed to click

## Fix

- removes temporary diagnostics
- adds one app-owned mobile menu button
- directly reveals the existing Streamlit sidebar
- adds a tap-outside overlay
- supports Escape close
- keeps desktop behaviour unchanged
- no dependency on Streamlit's missing Safari collapsed control

## Unchanged

- open-drawer control styling
- site status wording
- cards, forms, workflows and data
