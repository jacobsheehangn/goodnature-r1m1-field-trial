# Controlled fix v8.7.5.8 — Explicit card components

Built directly from v8.7.5.6, the confirmed single-chevron build.

## Changed

Only:
- trap cards inside Trap sites
- Administration → Trap sites cards
- Administration → Builds cards

## Implementation

- one reusable `render_compact_card_content()` renderer
- each surface uses the already-proven `app_card()` outer surface
- existing columns on the two Administration surfaces were removed
- no new CSS selectors
- no `:has()` additions
- no wrapper detection
- no menu code changes

## Retained

- confirmed single drawer chevron
- standalone Traps page card styling
- all workflow, data, photo, history, window and follow-up behaviour
