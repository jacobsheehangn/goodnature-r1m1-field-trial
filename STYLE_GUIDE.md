# R1/M1 Field Trial App Style Guide

## Design position

The field app uses the Goodnature native app’s visual language—colour, typography,
rounded surfaces, status treatment and action hierarchy—adapted for a browser-based
field workflow.

It intentionally keeps stronger grouping, larger tap targets and more explicit labels
than the native consumer app.

## Core principles

1. **Field clarity first**
   - Prefer explicit text over icon-only actions.
   - Keep tap targets large.
   - Use one clear task per screen.
   - Avoid hidden or gesture-only interactions.

2. **One section, one boundary**
   - A meaningful section may have one outer card.
   - Content inside that section must not introduce another card border unless it is
     a genuinely separate task or warning.
   - Metrics inside cards are borderless.

3. **Native alignment without imitation**
   - Reuse the Goodnature colour, radius, status and action hierarchy.
   - Do not copy native bottom navigation, bottom sheets or icon-heavy density into
     Streamlit where those patterns are fragile or unclear.

## Tokens

### Brand and text

- Primary orange: `#F36C21`
- Orange hover: `#E9621C`
- Orange pressed: `#CF5515`
- Primary text: `#25262D`
- Muted text: `#6F7178`

### Surfaces and borders

- Page: `#FFFFFF`
- Standard grouped surface: `#F7F7F5`
- Standard border: `#D7D9DD`
- Standard radius: `14px`
- Form-control radius: `10px–12px`

### Semantic status colours

- Guidance: pale blue `#EDF4FB`
- Success: pale green `#EAF7EF`
- Warning/waiting: pale yellow `#FFF3D9`
- Error/fault: pale peach `#FFF0EA`

## Typography

- Inter is the standard family.
- Preserve the current field-app scale.
- Use one dominant page title.
- Avoid multiple large headings competing in one viewport.
- Labels remain explicit and medium-to-bold for outdoor readability.
- Do not reduce type simply to match native-app density.

## Surfaces

- Use borders for meaningful groups, not every block.
- Prefer spacing and pale background contrast before adding another outline.
- Use subtle shadow only on the outer section card.
- Selected or active sections may use orange emphasis.
- Do not nest `st.metric`, alerts or ordinary content as bordered cards inside a card.

## Actions

### Primary

- Filled Goodnature orange.
- One primary action per section where possible.
- White text.

### Secondary

- Pale neutral-grey surface.
- Dark text.
- No orange fill.

### Tertiary

- Orange text on transparent background.
- Use for low-risk actions such as Cancel, Back or View details.

### Destructive

- Pale peach/red treatment.
- Must not look identical to the ordinary primary action.

## Status pattern

Use the native-app state pattern:

- one icon where helpful
- short status title
- one supporting sentence
- pale semantic background
- optional action

Apply this to:

- check saved
- trap not ready
- follow-up required
- save failure
- incomplete evidence
- staging
- unable to check

## Navigation

- Keep the Streamlit sidebar.
- Do not replace it with native bottom tabs.
- Sidebar open and close controls must remain visible on mobile.
- Streamlit’s three-dot menu is secondary system chrome.

## Forms and controls

- Mobile inputs render at least `16px`.
- Unselected radios and checkboxes: white interior, dark outline.
- Selected radios and checkboxes: Goodnature orange.
- Select fields: full border and consistent rounded corners.
- Do not use solid black selection controls.
- Keep user zoom enabled.

## Photos

- No embedded browser camera stream.
- Add photos using the device’s standard image picker.
- Support multiple images, thumbnails and removal before save.
- Save images against the check, window, trap, site and bag ID.

## Streamlit constraints

### Strong alignment

- colour tokens
- typography
- cards and grouped surfaces
- button hierarchy
- semantic status panels

### Adapted alignment

- radios, checkboxes and selects
- responsive cards
- sidebar navigation
- confirmation and success pages

### Do not force

- native bottom sheets
- bottom tab navigation
- icon-only actions
- native camera flows
- pixel-perfect native modal behaviour
- animation-heavy transitions

## Release checks

Every release should confirm:

- one boundary per section
- no nested metric borders
- correct primary/secondary action hierarchy
- mobile sidebar controls visible
- controls are not solid black when unselected
- no horizontal overflow
- safe-area spacing remains
- photo upload remains upload-only
- old route wording does not return


## Trap history

- Operational trap history is separate from aggregate Performance.
- The list must show lifetime kill and check counts without opening each trap.
- A trap detail view shows full chronological history.
- Use plain field language: kills, checks, last kill and full history.


## List-to-detail navigation

Use a dedicated detail page when a record includes substantial content such as summary
metrics, long history, related records or management actions.

Do not simulate a responsive drawer with Streamlit columns. On narrow screens, columns
stack in document order and can place the detail below the full list.

Required pattern:

- List page → View → Detail page
- Detail page starts with **Back to [list]**
- Preserve search and filters when returning
- Keep the matching main-navigation item active
- Do not use breadcrumbs for a single list-to-detail level
- Use × only for genuine overlays, dialogs or drawers
- Use Back for full-page navigation
- Desktop and mobile use the same information architecture

For event history:

- group events under day headings
- newest day first
- fixed-width time column
- flexible content column
- wrapping must remain in the content column


## Mobile navigation completion

Selecting a destination from the mobile main menu must:

1. navigate to the chosen page
2. close the sidebar
3. reveal the new page at its top

The menu must not remain open after navigation. This rule applies to primary and
administrative destinations because both use the shared navigation helper.


## Mobile sidebar implementation note

The Streamlit sidebar close control may be replaced during rerender and may sit outside
the visible viewport. Mobile auto-close must not depend on a control being visibly
positioned on screen.

The shared close routine must:

- confirm the sidebar is open
- observe Streamlit DOM replacement
- support multiple close-control variants
- retry after rerender
- allow programmatic activation of an off-screen collapse control
- use Escape as a fallback
- stop only once the sidebar geometry or state confirms it is closed


## Mobile sidebar motion

Closing the mobile menu after navigation must use one deliberate close action after the
destination page renders.

Do not use mutation observers or repeated click attempts for sidebar closure. Repeated
activation can make the menu close and reopen while Streamlit replaces its DOM.

The collapsed menu control must maintain dark-grey contrast against the white mobile
header.

## Mobile navigation timing

Close the mobile sidebar in the same user interaction that selects a destination,
before Streamlit starts rerendering. Do not schedule sidebar closure after render.


## Semantic panel contrast

Semantic background colours must never rely on inherited white text. Panel title,
body and action text must meet readable contrast against the panel background.

Warning and waiting panels use dark text on pale yellow.

## Mobile header clearance

Page-level Back actions, titles and context must begin below the persistent Streamlit
mobile header and safe area. Do not position page content underneath system chrome.


## Mobile navigation icons

Do not depend on Streamlit's native sidebar SVG colour or alignment. On mobile, hide
the native SVG and render one app-owned dark-grey chevron within the existing control.

Drawer expander chevrons sit at the far right without a separate white icon box.

## Refresh-persistent staging access

Staging access may persist across browser refresh using a signed token derived from
the configured shared password. Never place the password itself in browser storage or
the URL.


## Mobile drawer convention

For a left-aligned mobile drawer:

- the closed-state menu control sits at the top left of the app header
- the open-state close control sits at the top right inside the drawer
- only one drawer close control is shown
- section expanders remain separate controls

## Release reasoning standard

A requested UI change is not just a selector or CSS instruction. Before implementation,
define the full interaction across closed, open, mobile and desktop states, preserve
unrelated behaviour, and use established interface conventions unless the product
requires otherwise.
