# R1/M1 Field Trial App — UX Style Guide

## Core principle
Show the current task first, supporting context second, and system detail only when it helps the user make a decision.

## Typography
- Inter Bold (700): page titles, section headings, card headings and primary buttons.
- Inter Regular (400): body copy, guidance details and table content.
- Field labels: Inter Semi Bold (600), never smaller than body text.
- Helper text may be smaller and quieter, but must remain readable.

## Page hierarchy
Each screen follows this order:
1. Page title — the single dominant task or object being worked on.
2. One concise supporting line — only the orientation needed to act.
3. A message area only when the user needs guidance, status, warning or recovery information.
4. Main question or content.
5. Primary action.
6. Secondary actions.

Do not use a large guidance panel when the page title and supporting line already explain where the user is and what to do. A screen should normally have one dominant title, one supporting message and one primary action.

## Information and data presentation
- Show each piece of information once in its clearest location.
- Group information around the user’s decision, not the database structure.
- Use human-readable dates and times; do not show seconds unless analytically necessary.
- Prefer interpreted information over raw values.
- Move IDs and technical detail into panels or technical views unless needed for the current decision.
- On mobile, the title, context, main message and first required question should appear before scrolling.

## Message system
- Guidance (blue): what to do and relevant context.
- Success (green): confirms the action, exact record, time, progress and next action.
- Warning (amber): a decision, exception or possible data-quality issue.
- Error (red): what failed, what was preserved and how to recover.
- Only one high-priority message should dominate at a time.
- Success replaces general guidance until the user begins the next task.

## Forms
- Ask questions in the order the operator performs the work.
- Reveal conditional fields only when relevant.
- Labels describe the decision in plain English.
- Primary button wording states the consequence, e.g. “Save and go to next trap”.
- Confirmation screens explain what will be recorded, closed, started and created.

## Actions and buttons
- One dominant action per screen.
- Secondary actions are quieter and do not compete with the primary path.
- Place an action immediately after, beside or inside the element it affects.
- Use natural content width on desktop. Do not stretch a button across a card, panel or page unless the whole container is one action.
- Use compact buttons for row- and record-level actions such as Open site, Edit trap and Review task.
- Place card and panel actions after the related content, normally at the bottom of the element rather than floating at its top edge.
- Page-level primary actions may be wider, but their scope must be visually obvious.
- On mobile, primary actions may use the full available width and must provide at least a 44 px tap target.
- Keep related primary and secondary actions together at the end of a form or decision.
- Separate destructive or consequential actions from routine save actions and require confirmation where history or results could change.
- Record-level edits use a focused panel on desktop and a full-width form on mobile.
- Multi-step field work uses a full workspace.

## Cards, tables and panels
- Tables provide network or queue context.
- Cards present one site, task or record with its action clearly attached.
- Follow content-first, action-last ordering inside cards and panels.
- A focused panel shows one selected record without losing the list.
- Keep row actions in a consistent final action position.
- If an action affects one record, put it on that record. Never make users select a record in one control and trigger its action somewhere else when a direct row or card action is possible.
- Collection-level actions such as Add trap, Add site and Add build sit above the list; record-level actions such as Edit, Review and View sit inside the relevant row.
- Technical tables may retain IDs; operator tables use plain status and human-readable dates.

## Progress and save feedback
After saving a trap check, show:
- exact Trap ID;
- save time;
- completed count;
- next Trap ID and location;
- one clear next action.

A user should never have to infer whether their work saved.

## Controlled scientific fields
Where a trial field uses agreed categories, use a required controlled selection rather than free text. Animal weight is recorded during necropsy as one of: **0–200 g**, **201–400 g**, or **401+ g**. Display the unit in every option and preserve the selected range in review and export views.

## Consistency rules
- Use no more than one orientation sentence below a page title. Do not restate the same instruction in a guidance panel.
- Use a blue guidance panel only when the user needs information that changes how they complete the current task. Selection prompts and empty-panel instructions use quiet helper text instead.
- Every saved edit or completed review must produce a persistent success message after the page reruns. The message names the affected record and confirms what changed.
- Add actions are section-level actions and may be primary. Edit, inspect and review actions are record-level actions and remain visually secondary until a record is selected.
- Full-width buttons are reserved for mobile layouts and sidebar navigation. Their width reflects the available navigation surface rather than action scope.
- Back navigation sits consistently before the page title and uses the same wording pattern: “← All sites”, “← Back to site”, or the relevant parent destination.
- Operator-facing screens use interpreted labels and human-readable dates. Technical IDs and raw values remain available only in evidence, setup and export views.


## List and edit-panel layout

- Default list state uses the full available content width.
- Do not reserve blank space for an inactive edit panel.
- Open the focused right-hand panel only after a record-level Add or Edit action.
- When the panel closes, restore the list to full width and preserve the user's section and filter context.


## List control alignment
- Place filters and view controls on the left.
- Place collection-level actions such as Review next task or Export filtered on the right.
- Keep row-level actions inside the final column of the record row.
- Do not invent a right-side action where the page has no meaningful collection-level action.


## Operational readiness confirmations
- Confirm the end state that matters for the next test window rather than forcing an action that is not part of the trial method.
- For trap checks, record **Trap condition after check** as: Still set and ready, Fired and reset, Not ready / could not reset, or Not assessed.
- Do not require firing a trap simply because lure was added.
- Start a new test window only when the trap is ready, trap function is confirmed, fresh lure is present, and the camera is working and covering the trap.
- When a required end state is not met, require a plain-language reason and do not start a new window.

## Goodnature brand layer
- Use the approved horizontal Goodnature wordmark once in persistent application chrome, normally at the top of the sidebar.
- Preserve the logo's proportions and clear space. Do not repeat it in page content or resize it so heavily that it competes with the current page title.
- Recommended width: **150–180 px on desktop** and **120–145 px on mobile**.
- Use Goodnature orange (`#F36C21`) for primary actions, active navigation, selected controls and accessible focus states.
- Use a darker orange (`#DF5E18`) for hover/pressed states and a pale orange surface (`#FFF3EB`) for restrained active-navigation treatment.
- Primary buttons use dark text on the standard orange surface for stronger contrast. A hover state may use white text only with the darker orange.
- Keep body text, headings, surfaces and borders neutral. Do not colour ordinary headings orange or use orange as a large page background.
- Brand colour never replaces semantic status colour: blue remains guidance, green success, amber warning and red error/destructive action.
- The app is an operational field tool. Brand should improve recognition and trust without adding noise, duplicating hierarchy or weakening task clarity.


## Primary button interaction states

- Default: Goodnature orange background with white text.
- Hover: white text remains unchanged; the orange becomes slightly lighter through reduced background opacity.
- Pressed: use a slightly deeper orange while retaining white text.
- Never fade the whole button, because that would reduce text contrast.
- Disabled buttons use a neutral treatment and must not resemble an active primary action.

### Follow-up queue layout
- The follow-up queue uses the full content width until a task is selected.
- The review panel appears only after the operator chooses **Review** or **Review next task**.
- Row actions remain on one line and do not reduce the readable width of the queue while no task is open.
## Site-card outer balance

Site-card content remains left-aligned and keeps its existing internal spacing. The bordered card controls the outer whitespace:

- remove the default top margin from the first `h3`
- apply 24 px top padding and 24 px bottom padding to the card
- do not vertically centre the content with flexbox
- do not change horizontal alignment or spacing between the individual elements

This gives the first and last elements equal clearance from the card edges.



## Results-page hierarchy

Results pages answer the decision question before showing the underlying records.

1. Show the primary performance result first.
2. Show sample size, evidence completeness and failures next.
3. Show comparisons only when deliberately selected.
4. Keep individual records and calculation notes available on demand rather than permanently expanded.
5. Do not imply a pass/fail decision unless an approved target is configured.
6. Pending evidence must remain visible and must not be silently removed from the story.

## Analytical results

- A Results page leads with the answer, then confidence in that answer, then exceptions, then detailed records.
- Use one dominant result value per selected context. Supporting counts must be visibly subordinate.
- Always show the denominator or sample basis beside the primary result.
- Related evidence counts should read as one compact group rather than competing headline cards.
- Use plain-language sections: **Performance**, **Evidence**, **Results needing review**, and **Detail**.
- Results include completed test windows only. Active field deployments remain in Test Windows and never appear as pending result records.
- A pending result must have a linked open follow-up task. Surface any mismatch as a data issue rather than silently displaying it.
- Tables, calculation definitions and individual records stay available on demand.
- Colour supports meaning but never carries the conclusion alone.
- Do not call a result passing, failing, positive or negative without an approved target.

## Test-window views

- Use **Active** in the interface for a current open field deployment. Reserve **Open** for internal stored status where needed.
- Test Windows defaults to **Closed**, because completed windows are the normal review task.
- Active windows are clearly described as current deployments, not pending evidence or results.
- Lists use the full available width until a row is selected. The detail panel appears only after selection.


## Field sample IDs
- Show a short, writable bag ID immediately after **Dead animal found** is selected, before the animal is bagged.
- Use a site-based three-letter prefix and a three-digit sequence, for example **MAN-014**.
- Keep technical record IDs in the data layer; never ask field operators to copy them onto samples.
- Require confirmation that the animal has been bagged and labelled before the check can proceed.

## Camera interaction evidence
- Every assessable closed window requires a camera interaction review, including windows with no animal found.
- Record whether meaningful target interaction occurred, not every interaction event.
- Use the controlled interaction levels: Single interaction, Repeated interaction, Heavy / repeated interaction, Not applicable, or Unclear.
- Capture the first target interaction time, strike-area entry, activation and kill only where supported by usable evidence.
- Reject contradictory evidence and timestamps outside the test window or in an impossible order.
- A closed window must be assessed, awaiting a linked evidence task, or explicitly not assessable. It must never remain ambiguously pending.

## Effectiveness results
- Present effectiveness as a chain: **Attracted → Activated → Killed → Humane**.
- Keep attraction, conversion, speed and humane outcome separate so one strong measure cannot hide a weak one.
- Attraction reporting uses windows with confirmed target interaction and traps with interaction; do not require event counting.
- Surface repeated or heavy interaction without a kill as a priority result.
- Use medians for deployment-to-first-interaction, interaction-to-activation and interaction-to-kill because field timings are often skewed.
- Always show the sample basis beside each rate or timing result.


## Evidence time entry

- Evidence timestamps describe when events occurred during the test window, not when footage was reviewed.
- Always show the linked test-window start and end above timestamp fields.
- Default evidence inputs to a valid time within that period.
- Prevent dates outside the test-window period and validate event order.
- Group related validation failures into one actionable error message.

## Data corrections

- Corrections are separate from normal field and review workflows.
- Require a reason for every saved correction.
- Preserve record type, record ID, field, previous value, new value and change time.
- Do not silently overwrite or delete operational records.
- Use Data Management for corrections, audit history, exports and backups.


## Navigation language

Use labels that describe the user’s job rather than the underlying data model.

- **Trap sites** — start or resume field visits.
- **Follow-up tasks** — complete camera and necropsy evidence work.
- **Performance** — understand attraction, conversion, speed and humane outcomes.
- **Setup** — manage trap sites, traps and builds.
- **Data Management** — corrections, trial history, audit log, export and backup.

Do not expose **Trap Network** or **Test Windows** as primary navigation labels. Traps belong in Setup; test-window records are presented as Trial history under Data Management.


### Site-card implementation note
Use a dedicated site-card heading class with `margin-top: 0`. Do not rely on parent `:has()` selectors to override Streamlit heading margins, as the generated DOM can change between versions. The card container should retain its normal equal outer padding.


## Conditional field-work steps
- Keep one task flow inside one visual container.
- Number only the steps currently visible to the operator.
- When a conditional step is hidden, renumber later steps rather than leaving a gap.
- Place contextual warnings, such as bag-labelling instructions, immediately after the answer that triggered them.

## Mobile field mode

The field workflow is designed for a phone before desktop.

- Starting work should feel like **Start checking**, not creating an administrative session. The visit record is created in the background.
- Keep trap ID, location and route progress visible while the check scrolls.
- Capture routine timestamps automatically. Put manual date/time changes behind an exception control.
- Do not preselect the physical finding. Require an explicit observation.
- Use contextual readiness questions rather than exposing internal condition fields.
- Ask one primary camera-readiness question and reveal issue detail only when needed.
- Use vertical route cards on mobile; do not make a wide table the main field interface.
- Keep one primary action at the end of the current task and make it full width on mobile.
- Preserve entered widget values when validation fails and show one compact error summary.
- After save, state what was saved, current progress and the next physical trap.


## Confirmation and success states

- Before saving, confirm only observations and physical actions completed by the user.
- Keep technical record changes out of the main confirmation unless they change the user's decision.
- After saving, confirm that the action succeeded, summarize important system-created tasks or records, and make the next action dominant.
- Do not repeat the same progress count immediately outside a success message.
- Use **Check trap** for the first trap and **Check next trap** only after route progress has begun.
- On mobile, selecting a navigation destination should render the page and collapse the sidebar.

## Mobile safety pass — v8.6.21

- Do not preselect observations or physical actions that become trial evidence.
- Require an explicit Yes/No response for reluring.
- Record how the trap was actually left; do not assume one relure method:
  - Still set and ready
  - Fired and reset
  - Not ready / could not reset
  - Could not assess
- A trap may begin a new window after either "Still set and ready" or "Fired and reset", provided fresh lure was added and the camera is ready.
- Do not infer that a trap was function-tested merely because it remained set and ready.
- Species, animal condition, lure condition, site condition, camera issue and camera coverage begin unselected.
- Show route progress once and keep the full route collapsed until requested.
- Confirmation pages use one title and one confirmation heading; do not repeat guidance in multiple blocks.
- Sticky mobile actions must attach to the actual action button rather than to a decorative marker.
- Responsive rules must not globally force every column in every app area to stack.

## Evidence task flow

- Follow-up forms use the same sequence: **What you are recording**, **What the app will update**, then one save action.
- A successful save confirms what changed and presents one clear next action.
- Kill camera reviews imply activation and kill. They ask for first interaction time and kill time, without asking the reviewer to reconfirm whether a kill occurred.
- No-kill camera reviews ask whether target interaction and activation occurred so attraction and conversion failures remain distinguishable.
- Evidence timestamps start blank. Important performance timings must never be created from shared default values.
- Event timestamps must fall within the linked test window and follow a valid sequence.
- The current trial method uses a fixed three-day planned check interval. Actual timestamps remain the source of truth for evidence and performance calculations.


## Evidence task hierarchy

- Show **Task context** first: trap, site, build, bag ID, reason and evidence period.
- Show **Complete this review** second, with only fields relevant to the selected answers.
- Conditional evidence fields must appear immediately; do not hide them inside a form that waits for submission.
- Show **Saving this will update** immediately before one clear save action.
- After save, confirm what changed and direct the user to the next open task.

## Trap-check confirmation

Use three groups: **You recorded**, **After saving, the app will**, and **Next**. Use Markdown, not literal HTML tags, for emphasis.


## Locked decision — primary buttons

All Goodnature-orange primary buttons use **white text** in default, hover, focus and pressed states. This is the single app-wide rule.
