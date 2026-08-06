# Controlled fix v8.7.5.9 — Menu → Traps card component

Built directly from v8.7.5.8.

## Changed

Only the card render block on Menu → Traps.

The old four-column layout has been replaced with the same explicit
`render_compact_card_content()` component already proven on the other corrected surfaces.

## Retained

- existing grey `app_card()` surface
- full-width View action and underlying navigation
- confirmed single drawer chevron
- Trap sites cards
- Administration Trap sites cards
- Administration Builds cards
- all workflow and data logic

## Not changed

- CSS
- menu code
- filters
- trap-detail pages
- workbook structure
- photos, windows, follow-ups, checks or history
