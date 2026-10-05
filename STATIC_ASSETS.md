# static/ (assets served at /app/static)

Served by Streamlit's static file serving (`server.enableStaticServing = true` in
`.streamlit/config.toml`) at `/app/static/<path>`. Public, unauthenticated, cached by
the browser: only put files here that are safe to publish.

- `fonts/` - Lato 400 and 700, latin and latin-ext (latin-ext carries the macrons in
  Māori place names), woff2, from Google Fonts v25. Licence: `fonts/OFL.txt` (SIL Open
  Font License 1.1). Self-hosted so no request goes to Google: the operators have weak signal.
- `icons/` - 2px round-cap line icons as inline-able SVG (`stroke="currentColor"`).
  Species (mouse, rat, hedgehog, stoat, squirrel, cat) and check-circle, check, arrow-left,
  plus, info-circle, warn-circle are the vectors from the designer's Figma file (nodes
  `2497:12298` and `2196:9075`), centred in their boxes. `chevron-down` is the Figma
  "Down" arrow's geometry. `question`, `camera`, `bag` and `spinner` are not in the Figma
  file and are drawn here in the same style.
