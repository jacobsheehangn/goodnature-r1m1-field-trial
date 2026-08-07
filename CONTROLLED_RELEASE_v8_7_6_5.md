# v8.7.6.5 — Minimal Streamlit toolbar

Built directly from v8.7.6.4.

## Only change

Adds the supported Streamlit configuration:

```toml
[client]
toolbarMode = "minimal"
```

This removes the local development toolbar and Deploy control from normal app use without hiding framework elements through CSS.

## Unchanged

- navigation architecture and layout
- page routing
- field workflows
- cards
- authentication
- workbook and field data
