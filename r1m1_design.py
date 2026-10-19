"""Phase 7a (TRIAL_LIFECYCLE_BRIEF.md, "Phase 7"): the visual language as code.

Tokens, self-hosted Lato, the type scale and the component CSS from the design
system (R1M1_DESIGN_SYSTEM_README.md, r1m1_design_tokens.json), plus the icon set
as inline SVG. Nothing here is imported by app.py yet: 7a only proves the
components can be built in the pinned Streamlit 1.60.0 (see phase7a_spike.py).
Each 7b screen PR adopts it.

Rules this module keeps (Phase 7 rules 1-3):
  - CSS and markup only: no write path, no sheet read, no session-state keys.
  - No per-run work: the CSS and every icon are static strings built once at import.
  - Fonts and icons are static files served by Streamlit's static file serving
    (`server.enableStaticServing`, `/app/static/...`). No request to Google.
"""
from __future__ import annotations

import re
from pathlib import Path

STATIC_URL = "/app/static"
_ICON_DIR = Path(__file__).resolve().parent / "static" / "icons"

# ---------------------------------------------------------------- icons -----

def _load_icons() -> dict:
    icons = {}
    if _ICON_DIR.is_dir():
        for path in sorted(_ICON_DIR.glob("*.svg")):
            icons[path.stem] = path.read_text(encoding="utf-8").strip()
    return icons


ICONS = _load_icons()


def icon(name: str, size: int | None = None, css_class: str = "") -> str:
    """Inline SVG for `name` (2px round-cap line icon, colour = the surrounding text
    colour). `size` sets the rendered width and height in px."""
    svg = ICONS[name]
    if size:
        svg = re.sub(r'width="[\d.]+" height="[\d.]+"', f'width="{size}" height="{size}"', svg, count=1)
    if css_class:
        svg = svg.replace("<svg ", f'<svg class="{css_class}" ', 1)
    return svg


# ------------------------------------------------------------------ fonts ---

def _font_face(weight: int, subset: str, unicode_range: str) -> str:
    return (
        "@font-face{font-family:'Lato';font-style:normal;"
        f"font-weight:{weight};font-display:swap;"
        f"src:url({STATIC_URL}/fonts/lato-{weight}-{subset}.woff2) format('woff2');"
        f"unicode-range:{unicode_range};}}"
    )


# Subsets as published by Google Fonts (v25). latin-ext carries the macrons in Maori
# place names (U+0100-017F), so it is not optional.
_LATIN = (
    "U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+0304,U+0308,"
    "U+0329,U+2000-206F,U+20AC,U+2122,U+2191,U+2193,U+2212,U+2215,U+FEFF,U+FFFD"
)
_LATIN_EXT = (
    "U+0100-02BA,U+02BD-02C5,U+02C7-02CC,U+02CE-02D7,U+02DD-02FF,U+0304,U+0308,U+0329,"
    "U+1D00-1DBF,U+1E00-1E9F,U+1EF2-1EFF,U+2020,U+20A0-20AB,U+20AD-20C0,U+2113,"
    "U+2C60-2C7F,U+A720-A7FF"
)
FONT_FACE_CSS = "".join(
    _font_face(w, s, r) for w in (400, 700) for s, r in (("latin-ext", _LATIN_EXT), ("latin", _LATIN))
)

# ----------------------------------------------------------------- tokens ---

TOKENS_CSS = """
:root{
  --page:#ffffff; --ink:#000000; --ink-70:rgba(0,0,0,.70); --ink-50:rgba(0,0,0,.50);
  --ink-10:rgba(0,0,0,.10); --ink-05:rgba(0,0,0,.05);
  --orange:#f37021; --orange-10:rgba(243,112,33,.10); --orange-50:rgba(243,112,33,.50); --orange-ink:#b84808;
  --green:#0da84b; --green-10:rgba(13,168,75,.10); --red:#fe012c; --red-10:rgba(254,1,44,.10);
  --shadow-panel:0 0 100px rgba(0,0,0,.05),0 0 20px rgba(0,0,0,.05),0 0 0 1px rgba(0,0,0,.05);
  --shadow-segment:0 0 0 1px rgba(0,0,0,.05),0 1px 4px rgba(0,0,0,.12);
  --r-card:20px; --r-panel:14px; --r-segment:12px; --r-input:10px; --r-check:8px; --r-pill:999px;
  --font:'Lato',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
"""

# ------------------------------------------------------------- type scale ---
# page title 34/40 bold (48/54 on desktop); card title and section heading 22/30 bold;
# row title 17/22 bold; body 16/22; label 16/22 bold; meta 14/20 in ink-70;
# stat 22 bold, stat label 13/16 in ink-70; button 16 bold (secondary and text 15 bold).
TYPE_CSS = """
.stApp,.stApp div,.stApp p,.stApp span:not([data-testid="stIconMaterial"]),.stApp label,.stApp a,
.stApp button,.stApp input,.stApp textarea,.stApp li,.stApp summary,.stApp h1,.stApp h2,.stApp h3,.stApp h4{
  font-family:var(--font);
}
.stApp{background:var(--page);color:var(--ink);font-size:16px;line-height:22px}
.stApp h1{font-size:34px;line-height:40px;font-weight:700;letter-spacing:0;margin:0;padding:0;color:var(--ink)}
.stApp h2,.stApp h3{font-size:22px;line-height:30px;font-weight:700;letter-spacing:0;margin:0;padding:0;color:var(--ink)}
@media (min-width:701px){.stApp h1{font-size:48px;line-height:54px}}
.stApp [data-testid="stMarkdownContainer"]{margin-bottom:0!important}
.stApp [data-testid="stMarkdownContainer"] p{font-size:16px;line-height:22px;margin:0}
.stApp [data-testid="stWidgetLabel"] p{font-size:16px;line-height:22px;font-weight:700;color:var(--ink)}
.stApp [data-testid="stMainBlockContainer"]{padding:15px 15px 96px;max-width:1220px}
.r1-title{font-size:34px;line-height:40px;font-weight:700}
.r1-card-title{font-size:22px;line-height:30px;font-weight:700}
.r1-row-title{font-size:17px;line-height:22px;font-weight:700}
.r1-meta{font-size:14px;line-height:20px;color:var(--ink-70)}
.r1-stat{font-size:22px;line-height:22px;font-weight:700;text-align:right}
.r1-stat-label{font-size:13px;line-height:16px;color:var(--ink-70);text-align:right}
"""

# ------------------------------------------------------------- components ---

def _mask(name: str) -> str:
    url = f"url({STATIC_URL}/icons/{name}.svg)"
    return f"-webkit-mask:{url} center/contain no-repeat;mask:{url} center/contain no-repeat"


_CHECK_DATA_URI = (
    "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 11 8' fill='none' "
    "stroke='white' stroke-width='2' stroke-linecap='round' stroke-linejoin='round'><path d='M10 1L4 7L1 4'/></svg>\")"
)

_SPECIES_ORDER = ("rat", "mouse", "hedgehog", "question")  # Rat, Mouse, Non-target (hedgehog stands in), Unknown
# The six outcomes of a check, in the order of the page's FINDINGS: still set, dead animal, fired, disturbed, missing, unable to check.
_OUTCOME_ICONS = ("check-circle", "rat", "burst", "warn-circle", "ban", "info-circle")


def _species_icon_rules() -> str:
    return "".join(
        f'[class*="st-key-species"] [data-testid="stRadioGroup"]>label:nth-child({i}){{--icon:url({STATIC_URL}/icons/{name}.svg)}}'
        for i, name in enumerate(_SPECIES_ORDER, start=1)
    )


def _outcome_icon_rules() -> str:
    return "".join(
        f'[class*="st-key-rows_outcome"] [data-testid="stRadioGroup"]>label:nth-child({i}){{--icon:url({STATIC_URL}/icons/{name}.svg)}}'
        for i, name in enumerate(_OUTCOME_ICONS, start=1)
    )


COMPONENT_CSS = f"""
/* ---- Card: white, radius 20, shadow-panel, padding 15, 10px between cards ---- */
.stApp [class*="st-key-card_"],.stApp [class*="st-key-cardlist_"]{{background:#fff;border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:15px;gap:15px}}
.stApp [class*="st-key-cardlist_"]{{gap:0}}
.stApp [data-testid="stMainBlockContainer"]>div>[data-testid="stVerticalBlock"]{{gap:10px}}

/* A form is just a grouping here, not a second card. */
.stApp [data-testid="stForm"]{{border:0;padding:0;background:transparent}}

/* ---- Buttons ---- */
.stApp div.stButton button,.stApp div.stFormSubmitButton button{{
  border-radius:var(--r-pill);border:0;box-shadow:none;display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:0 24px;transition:none}}
.stApp div.stButton button p{{font-size:15px;line-height:20px;font-weight:700}}
.stApp :is(button[kind="primary"],button[kind="primaryFormSubmit"]){{
  background:var(--orange);color:#fff;min-height:48px;height:48px}}
.stApp :is(button[kind="primary"],button[kind="primaryFormSubmit"]) p{{font-size:16px;color:#fff}}
.stApp :is(button[kind="primary"],button[kind="primaryFormSubmit"]):hover:not(:disabled){{background:#e9621c;color:#fff}}
.stApp :is(button[kind="primary"],button[kind="primaryFormSubmit"]):active:not(:disabled){{background:#cf5515;color:#fff}}
.stApp :is(button[kind="primary"],button[kind="primaryFormSubmit"]):disabled{{background:var(--orange-50);color:#fff;opacity:1;cursor:not-allowed}}
.stApp :is(button[kind="secondary"],button[kind="secondaryFormSubmit"]){{
  background:var(--ink-05);color:var(--orange-ink);min-height:44px;height:44px}}
.stApp :is(button[kind="secondary"],button[kind="secondaryFormSubmit"]) p{{color:var(--orange-ink)}}
.stApp :is(button[kind="secondary"],button[kind="secondaryFormSubmit"]):hover,.stApp :is(button[kind="secondary"],button[kind="secondaryFormSubmit"]):active{{background:var(--ink-10);color:var(--orange-ink)}}
.stApp div.stButton button[kind="tertiary"]{{
  background:transparent;color:var(--orange-ink);min-height:44px;height:44px;padding:0;justify-content:flex-start}}
.stApp button[kind="tertiary"] p{{color:var(--orange-ink)}}
/* Back pill: a secondary button with a 14px left arrow. */
[class*="st-key-back_"] button::before{{content:"";width:14px;height:14px;background:var(--orange-ink);{_mask("arrow-left")}}}
/* Saving: full orange, a spinner, ignores taps. Done: green with a check. Both are disabled
   buttons, restyled so they do not read as disabled. */
.st-key-save_saving button:disabled{{background:var(--orange)!important;opacity:1!important;cursor:progress}}
.st-key-save_saving button::before{{content:"";width:18px;height:18px;background:#fff;{_mask("spinner")};animation:r1spin .9s linear infinite}}
.st-key-save_done button:disabled{{background:var(--green)!important;opacity:1!important;cursor:default}}
.st-key-save_done button::before{{content:"";width:18px;height:18px;background:#fff;{_mask("check")}}}
@keyframes r1spin{{to{{transform:rotate(360deg)}}}}
@media (prefers-reduced-motion:reduce){{.st-key-save_saving button::before{{animation:none}}}}

/* ---- Status: an 8px dot and 14px ink-70 words. Never a coloured pill. ---- */
.r1-status{{display:inline-flex;align-items:center;gap:8px;font-size:14px;line-height:20px;color:var(--ink-70)}}
.r1-status::before{{content:"";width:8px;height:8px;border-radius:50%;background:var(--ink-50)}}
.r1-status.due::before,.r1-status.progress::before{{background:var(--orange)}}
.r1-status.overdue{{color:var(--ink);font-weight:700}}
.r1-status.overdue::before{{background:var(--red)}}
.r1-status.done::before{{background:var(--green)}}

/* Choice widgets fill their card (Streamlit sizes their wrapper to fit-content). */
[class*="st-key-species"],[class*="st-key-rows"],[class*="st-key-seg"]{{width:100%!important}}
[class*="st-key-species"] [data-testid="stRadio"],[class*="st-key-rows"] [data-testid="stRadio"],[class*="st-key-seg"] [data-testid="stButtonGroup"]{{width:100%}}

/* The native radio input stays in the DOM for keyboard and screen readers but is never drawn
   (the legacy sheet unhides it). */
[class*="st-key-species"] [data-testid="stRadioOption"]>span:first-child,[class*="st-key-rows"] [data-testid="stRadioOption"]>span:first-child{{
  position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0);clip-path:inset(50%);opacity:0;pointer-events:none}}
[class*="st-key-species"] [data-testid="stRadioOption"] input,[class*="st-key-rows"] [data-testid="stRadioOption"] input{{opacity:0;position:absolute}}

/* ---- Species tiles (a restyled st.radio, 4 across) ---- */
[class*="st-key-species"] [data-testid="stRadioGroup"]{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}
[class*="st-key-species"] [data-testid="stRadioOption"]{{
  min-height:96px;border-radius:var(--r-card);background:var(--ink-05);display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:6px;padding:12px 2px;margin:0;cursor:pointer;color:var(--ink)}}
[class*="st-key-species"] [data-testid="stRadioOption"]::before{{
  content:"";position:static;left:auto;top:auto;transform:none;border:0;border-radius:0;margin:0;
  width:40px;height:40px;flex:0 0 40px;background:currentColor;
  -webkit-mask:var(--icon) center/contain no-repeat;mask:var(--icon) center/contain no-repeat}}
/* The legacy sheet draws its own radio dot on the label's ::before: the option rows draw their ring on ::after instead. */
[class*="st-key-rows"] [data-testid="stRadioOption"]::before{{display:none}}
[class*="st-key-species"] [data-testid="stRadioOption"]::after{{display:none}}
[class*="st-key-species"] [data-testid="stRadioOption"]>div>div>div:first-child{{display:none}}
[class*="st-key-species"] [data-testid="stRadioOption"] p{{font-size:14px;line-height:20px;text-align:center;white-space:nowrap}}
[class*="st-key-species"] [data-testid="stRadioOption"]:has(input:checked){{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange)}}
[class*="st-key-species"] [data-testid="stRadioOption"]:has(input:checked) p{{font-weight:700}}
{_species_icon_rules()}
@media (max-width:420px){{[class*="st-key-species"] [data-testid="stRadioOption"] p{{font-size:13px}}}}
@media (max-width:380px){{[class*="st-key-species"] [data-testid="stRadioGroup"]{{gap:8px}}}}

/* ---- Option rows (a restyled vertical st.radio) ---- */
[class*="st-key-rows"] [data-testid="stRadioGroup"]{{display:flex;flex-direction:column;gap:8px}}
[class*="st-key-rows"] [data-testid="stRadioOption"]{{
  min-height:56px;border-radius:var(--r-panel);background:var(--ink-05);display:flex;align-items:center;justify-content:space-between;
  padding:0 16px;margin:0;cursor:pointer;color:var(--ink);width:100%}}
[class*="st-key-rows"] [data-testid="stRadioOption"]>div>div>div:first-child{{display:none}}
[class*="st-key-rows"] [data-testid="stRadioOption"] p{{font-size:16px;line-height:22px}}
[class*="st-key-rows"] [data-testid="stRadioOption"]::after{{
  content:"";flex:0 0 24px;width:24px;height:24px;border-radius:50%;box-sizing:border-box;border:2px solid var(--ink-50);background:transparent}}
[class*="st-key-rows"] [data-testid="stRadioOption"]:has(input:checked){{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange)}}
[class*="st-key-rows"] [data-testid="stRadioOption"]:has(input:checked) p{{font-weight:700}}
/* The legacy sheet draws a small orange centre dot for any checked radio, absolutely placed at left:5px !important; the tick of an option row is
   that same pseudo-element, so it is put back in the row's flex layout (at the right) or it sits over the first letter of the label. */
[class*="st-key-rows"] [data-testid="stRadioOption"]:has(input:checked)::after{{
  position:static;left:auto;top:auto;transform:none;border:0;background:var(--orange) {_CHECK_DATA_URI} center/12px no-repeat}}

/* ---- The check form (Phase 6) ---- */
/* The six outcomes: option rows with an icon at the left and the ring at the right. */
[class*="st-key-rows_outcome"] [data-testid="stRadioOption"]{{justify-content:flex-start;gap:12px}}
[class*="st-key-rows_outcome"] [data-testid="stRadioOption"]::before{{
  display:block;content:"";position:static;left:auto;top:auto;transform:none;border:0;border-radius:0;margin:0;
  flex:0 0 24px;width:24px;height:24px;background:var(--ink);-webkit-mask:var(--icon) center/contain no-repeat;mask:var(--icon) center/contain no-repeat}}
[class*="st-key-rows_outcome"] [data-testid="stRadioOption"]>div{{flex:1 1 auto}}
{_outcome_icon_rules()}
/* A field's question, as a heading. */
[class*="st-key-field"] [data-testid="stWidgetLabel"] p{{font-size:16px;line-height:22px;font-weight:700;color:var(--ink)}}
/* A field the Save refused: one red ring round the whole group, and a line under it that says what to do. */
[class*="st-key-fielderr_"] [data-testid="stRadioGroup"],[class*="st-key-fielderr_"] [role="radiogroup"],[class*="st-key-fielderr_"] [data-testid="stTextArea"] textarea,
[class*="st-key-fielderr_"] [data-testid="stCheckbox"] label{{box-shadow:0 0 0 2px var(--red)}}
[class*="st-key-fielderr_"] [class*="st-key-species"] [data-testid="stRadioGroup"]{{padding:6px;border-radius:var(--r-card)}}
[class*="st-key-fielderr_"] [data-baseweb="input"],[class*="st-key-fielderr_"] [data-baseweb="textarea"],[class*="st-key-fielderr_"] [data-baseweb="select"]>div{{box-shadow:0 0 0 2px var(--red)}}
/* ---- Administration (Part B batch 2a): the trap page and its actions ---- */
.r1-status.strong{{color:var(--ink);font-weight:700}}
.r1-happen{{display:flex;gap:10px;align-items:flex-start;font-size:16px;line-height:22px;padding:6px 0;color:var(--ink)}}
.r1-happen svg{{flex:0 0 auto;margin-top:1px;color:var(--ink-70)}}
.r1-blocker{{display:flex;gap:8px;align-items:flex-start;font-size:15px;line-height:20px;color:var(--ink);margin-top:6px}}
.r1-blocker svg{{flex:0 0 auto;margin-top:1px}}
.r1-row-title.blocked{{color:var(--ink-70)}}
[class*="st-key-actrow_"]{{border-bottom:1px solid var(--ink-05);padding:14px 0}}
[class*="st-key-actrow_"] [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;gap:12px}}
[class*="st-key-actrow_"] [data-testid="stColumn"]{{min-width:0!important}}
[class*="st-key-actrow_"] [data-testid="stColumn"]:last-child{{flex:0 0 auto!important;width:auto!important}}
[class*="st-key-actrow_trap_delete"] button p{{color:var(--red)}}
.st-key-danger_button button[kind="primary"]{{background:var(--red)!important}}
.st-key-danger_button button[kind="primary"]:hover:not(:disabled){{background:#c4002f!important}}
.st-key-danger_button button[kind="primary"]:disabled{{background:#f4a3b5!important}}
@media (min-width:701px){{
  .st-key-actions_row{{flex-direction:row!important;align-items:center;gap:12px}}
  .st-key-actions_row>div{{width:auto!important}}
  .stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-trap_side"])>[data-testid="stColumn"]:first-child{{order:2}}
}}
@media (max-width:700px){{
  .stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-trap_side"]){{row-gap:16px}}
}}
[class*="st-key-rows_build"] [data-testid="stRadioOption"] p{{white-space:pre-line;line-height:20px}}
/* ---- Trial setup (Part B batch 2a) ---- */
.stApp [class*="st-key-listrow_trap_"],.stApp [class*="st-key-listrow_site_"],.stApp [class*="st-key-listrow_build_"]{{background:var(--ink-05);border-radius:var(--r-panel);padding:14px 16px;border-bottom:0}}
.stApp [class*="st-key-listrow_"][class*="_sel_"]{{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange)}}
/* A pill button on a grey row, in the card of the trap page's actions and in the panels is white with a hairline, as the boards draw it. */
.stApp :is([class*="st-key-listrow_trap_"],[class*="st-key-listrow_site_"],[class*="st-key-listrow_build_"],[class*="st-key-listrow_net_"],[class*="st-key-listrow_win_"],[class*="st-key-actrow_"],[class*="st-key-card_setup_bulk"]) button[kind="secondary"]{{background:#fff;box-shadow:inset 0 0 0 1px var(--ink-10)}}
.r1-readonly{{background:var(--ink-05);border-radius:var(--r-input);padding:12px 14px;font-size:16px;line-height:22px;color:var(--ink-70);margin:6px 0 10px}}
.st-key-setup_trap_rows,.st-key-setup_trap_rows_review{{gap:12px}}
[class*="st-key-card_setup_bulk"]{{padding:14px 16px}}
[class*="st-key-card_setup_bulk"] [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;gap:12px;align-items:center}}
[class*="st-key-card_setup_bulk"] [data-testid="stColumn"]{{min-width:0!important;flex:1 1 0!important}}
[class*="st-key-card_setup_bulk"] [data-testid="stColumn"]:last-child{{flex:0 0 auto!important;width:auto!important}}
[class*="st-key-tickcard_bulk_"]{{background:var(--ink-05);border-radius:var(--r-panel);padding:14px 16px;gap:8px;box-sizing:border-box}}
[class*="st-key-tickcard_bulk_"]:has([class*="st-key-bsel_"] input:checked){{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange)}}
[class*="st-key-bsel_"]{{width:100%!important}}
[class*="st-key-bsel_"] [data-testid="stCheckbox"] label{{display:flex;align-items:center;gap:12px;min-height:32px;cursor:pointer;position:relative}}
[class*="st-key-bsel_"] [data-testid="stCheckbox"] label::before{{content:"";position:static;left:auto;top:auto;transform:none;flex:0 0 24px;width:24px;height:24px;
  box-sizing:border-box;margin:0;border-radius:8px;border:2px solid var(--ink-50);background:transparent}}
[class*="st-key-bsel_"] [data-testid="stCheckbox"] label::after{{display:none!important}}
[class*="st-key-bsel_"] [data-testid="stCheckbox"] label>div:nth-of-type(1){{display:none}}
[class*="st-key-bsel_"] [data-testid="stCheckbox"] label:has(input:checked)::before{{border-color:var(--orange);background:var(--orange) {_CHECK_DATA_URI} center/14px no-repeat}}
[class*="st-key-bsel_"] [data-testid="stCheckbox"] label p{{font-size:16px;line-height:22px;font-weight:700}}
[class*="st-key-close_trap_setup_panel_top"] button,[class*="st-key-close_site_panel"] button,[class*="st-key-close_build_panel"] button,[class*="st-key-close_window_panel"] button{{min-height:40px;height:40px;width:40px;padding:0;border-radius:50%;background:var(--ink-05)}}
@media (min-width:701px){{[class*="st-key-back_setup_panel_phone"],[class*="st-key-back_close_"],[class*="st-key-back_window_panel_phone"]{{display:none}}}}
@media (max-width:700px){{
  [class*="st-key-close_trap_setup_panel_top"],[class*="st-key-close_site_panel"],[class*="st-key-close_build_panel"],[class*="st-key-close_window_panel"]{{display:none}}
  [class*="st-key-setup_view_panel"] [data-testid="stColumn"]:has([class*="st-key-setup_list"]){{display:none}}
  [class*="st-key-setup_view_panel"] [data-testid="stHorizontalBlock"]{{row-gap:0}}
}}
/* A date field inside a card on a 390px phone is about 125px wide: a day/month/year at 15px with the calendar at its right would clip its last digit. */
@media (max-width:700px){{[class*="st-key-pair_"] [data-testid="stDateInput"] [data-baseweb="input"] input{{font-size:14px;padding-left:11px;padding-right:32px}}}}
/* ---- Traps list and trap history (Part B batch 2b) ---- */
.stApp [class*="st-key-listrow_net_"]{{background:var(--ink-05);border-radius:var(--r-panel);padding:14px 16px;border-bottom:0}}
[class*="st-key-chips_traps_filter"] [role="radiogroup"],[class*="st-key-chips_setup_filter"] [role="radiogroup"],[class*="st-key-chips_perf_by"] [role="radiogroup"],[class*="st-key-chips_export_filter"] [role="radiogroup"],[class*="st-key-chips_audit_filter"] [role="radiogroup"]{{display:flex;flex-wrap:wrap;gap:8px}}
/* ---- Trial performance, lower part (Part B batch 2b, AdmPerfMore) ---- */
.r1-subhead{{font-size:19px;line-height:26px;font-weight:700;margin:20px 0 8px}}
.r1-diag{{display:grid;gap:12px;grid-template-columns:repeat(2,1fr)}}
.r1-diag.cols4{{grid-template-columns:repeat(2,1fr)}}
@media (min-width:701px){{.r1-diag.cols4{{grid-template-columns:repeat(4,1fr)}}}}
.r1-diagcard{{background:var(--ink-05);border-radius:var(--r-panel);padding:16px 18px;display:flex;flex-direction:column;gap:2px;min-width:0}}
.r1-diagcard b{{font-size:34px;line-height:40px;font-weight:700}}
.r1-diagcard span{{font-size:15px;line-height:21px;color:var(--ink-70)}}
@media (max-width:700px){{.r1-diag.cols2{{grid-template-columns:1fr}}}}
[class*="st-key-card_perf_table_"]{{padding:8px;gap:0}}
[class*="st-key-card_perf_calc"]{{gap:6px}}
[class*="st-key-card_perf_calc"] p{{margin:0}}
.stApp [data-testid="stExpander"]{{background:transparent!important;border:0!important;box-shadow:none!important}}
.stApp [data-testid="stExpander"] details{{background:transparent;border:0;border-radius:var(--r-panel)}}
.stApp [data-testid="stExpander"] summary{{background:var(--ink-05);border-radius:var(--r-panel);padding:16px 20px;font-size:17px;line-height:22px}}
.stApp [data-testid="stExpander"] [data-testid="stExpanderDetails"]{{padding:8px 0 4px}}
.r1-stats3{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}
.r1-statcard{{background:var(--ink-05);border-radius:var(--r-panel);padding:14px 16px;display:flex;flex-direction:column;gap:2px}}
.r1-statcard b{{font-size:30px;line-height:36px;font-weight:700;color:var(--ink)}}
.r1-statcard span{{font-size:15px;line-height:20px;color:var(--ink-70)}}
.r1-hist-day{{font-size:15px;line-height:20px;font-weight:700;color:var(--ink-70);padding:18px 0 8px}}
.r1-hist-row{{display:flex;gap:16px;padding:12px 0;border-bottom:1px solid var(--ink-05)}}
.r1-hist-row .t{{flex:0 0 52px;font-size:16px;line-height:22px;color:var(--ink-70)}}
.r1-hist-row .h{{font-size:17px;line-height:22px;font-weight:700;color:var(--ink)}}
.r1-hist-row .d{{font-size:15px;line-height:20px;color:var(--ink-70)}}
.stApp [class*="st-key-listrow_win_"]{{background:var(--ink-05);border-radius:var(--r-panel);padding:14px 16px;border-bottom:0}}
.r1-tag.bad{{background:#ffe1e7;color:var(--red)}}
/* ---- Data & records landing: a row is one tap, with a chevron at its right ---- */
.stApp [class*="st-key-listrow_data_"]{{background:var(--ink-05);border-radius:var(--r-panel);padding:16px 18px;border-bottom:0}}
[class*="st-key-listrow_data_"] [data-testid="stColumn"]:last-child{{flex:0 0 44px!important;width:44px!important}}
.stApp [class*="st-key-listrow_data_"] button[kind="secondary"]{{width:44px;min-width:44px;height:44px;min-height:44px;padding:0!important;background:transparent!important;box-shadow:none!important}}
.stApp [class*="st-key-listrow_data_"] button[kind="secondary"] [data-testid="stMarkdownContainer"] p{{font-size:0!important;line-height:0!important;color:transparent!important;margin:0}}  /* the name stays for screen readers and tests; the chevron is drawn */
.stApp [class*="st-key-listrow_data_"] button[kind="secondary"]::after{{content:"";width:22px;height:22px;background:var(--ink);{_mask("chevron-down")};transform:rotate(-90deg)}}
.stApp [class*="st-key-card_followup_"],.stApp [class*="st-key-card_recovery"]{{gap:12px}}
[class*="st-key-card_audit_table"]{{padding:8px}}
/* A date and a time side by side (the task forms): one field look at 48px, with a calendar and a clock at the right, as the boards draw them. */
[class*="st-key-pair_"] [data-testid="stDateInput"] [data-baseweb="input"],[class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"]>div{{
  box-sizing:border-box;min-height:48px;height:48px;border:1px solid var(--ink-10);border-radius:var(--r-input);background:#fff;box-shadow:none;position:relative}}
[class*="st-key-pair_"] [data-testid="stDateInput"] [data-baseweb="input"]::after,[class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"]>div::after{{
  content:"";position:absolute;z-index:2;right:14px;top:50%;margin-top:-10px;width:20px;height:20px;background:var(--ink);pointer-events:none}}
[class*="st-key-pair_"] [data-testid="stDateInput"] [data-baseweb="input"]::after{{{_mask("calendar")}}}
[class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"]>div::after{{{_mask("clock")}}}
[class*="st-key-pair_"] [data-testid="stTimeInput"] svg[data-baseweb="icon"]{{display:none}}
[class*="st-key-pair_"] [data-testid="stDateInput"] input{{font-size:15px;padding-right:38px}}
[class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"] div{{font-size:15px}}
[class*="st-key-pair_"] [data-testid="stDateInput"] input::placeholder{{color:var(--ink-50);opacity:1}}
/* The time's "HH:mm" hint sits under the field's own (white) input and lost its first letter; the input is made see-through. */
[class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"] input,[class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"] div:has(>input){{background:transparent!important}}
/* A date or time the Save refused: the same red ring as every other field (this rule is as specific as the pair's own, and comes after it). */
[class*="st-key-fielderr_"] [class*="st-key-pair_"] [data-testid="stDateInput"] [data-baseweb="input"],
[class*="st-key-fielderr_"] [class*="st-key-pair_"] [data-testid="stTimeInput"] [data-baseweb="select"]>div{{box-shadow:0 0 0 2px var(--red)}}
[class*="st-key-pair_"] [data-testid="stDateInput"] [data-baseweb="base-input"]{{background:transparent;border-radius:var(--r-input)}}
.r1-msg.info.ok svg{{color:var(--green)}}
/* The task forms' option rows: regular weight until chosen, as the boards draw them. */
[class*="st-key-rows_cam_"] [data-testid="stRadioOption"] p,[class*="st-key-rows_issue_"] [data-testid="stRadioOption"] p{{font-weight:400}}
[class*="st-key-rows_cam_"] [data-testid="stRadioOption"]:has(input:checked) p,[class*="st-key-rows_issue_"] [data-testid="stRadioOption"]:has(input:checked) p{{font-weight:700}}
.r1-fielderr{{display:flex;gap:8px;align-items:center;font-size:14px;line-height:20px;font-weight:700;color:var(--ink);margin-top:6px}}
.r1-fielderr svg{{flex:0 0 auto;color:var(--red)}}
/* Ticks and switches fill their row (Streamlit sizes their wrapper to fit-content). */
[class*="st-key-tick_"],[class*="st-key-sw_"]{{width:100%!important}}
[class*="st-key-tick_"] [data-testid="stCheckbox"],[class*="st-key-sw_"] [data-testid="stCheckbox"],[class*="st-key-sw_"] [data-testid="stElementContainer"]{{width:100%!important}}
/* A tick that is a whole row: "Bag labelled", "Camera adjusted". The box is the board's: 24px, rounded, inside the row with 14px of padding (the
   legacy sheet draws an 18px square hanging on the row's left edge; it is moved into the row's flow and redrawn). */
[class*="st-key-tick_"] [data-testid="stCheckbox"] label{{display:flex;align-items:center;gap:12px;min-height:56px;width:100%;box-sizing:border-box;
  border-radius:var(--r-panel);background:var(--ink-05);padding:0 14px;cursor:pointer;position:relative}}
[class*="st-key-tick_"] [data-testid="stCheckbox"] label::before{{content:"";position:static;left:auto;top:auto;transform:none;flex:0 0 24px;width:24px;height:24px;
  box-sizing:border-box;margin:0;border-radius:8px;border:2px solid var(--ink-50);background:transparent}}
[class*="st-key-tick_"] [data-testid="stCheckbox"] label::after{{display:none!important}}
[class*="st-key-tick_"] [data-testid="stCheckbox"] label>div:nth-of-type(1){{display:none}}
[class*="st-key-tick_"] [data-testid="stCheckbox"] label:has(input:checked){{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange)}}
[class*="st-key-tick_"] [data-testid="stCheckbox"] label:has(input:checked)::before{{border-color:var(--orange);background:var(--orange) {_CHECK_DATA_URI} center/14px no-repeat}}
[class*="st-key-tick_"] [data-testid="stCheckbox"] label p{{font-size:16px;line-height:22px}}
/* The found-outcome card: its row keeps the text and the Change button side by side, with no rule under it. */
[class*="st-key-card_check_found"] [class*="st-key-listrow_"]{{border-bottom:0;padding:0}}
/* A switch row: the label at the left, the switch at the right ("Change check time"). */
[class*="st-key-sw_"] [data-testid="stCheckbox"] label{{display:flex;flex-direction:row-reverse;justify-content:space-between;align-items:center;gap:12px;width:100%;min-height:44px;padding:0;cursor:pointer}}
[class*="st-key-sw_"] [data-testid="stCheckbox"] label>div:nth-of-type(1){{position:relative;flex:0 0 52px;width:52px;height:32px;box-sizing:border-box;padding:0;margin:0;
  border:0!important;border-radius:16px;background:rgba(0,0,0,.2)!important;box-shadow:none}}
[class*="st-key-sw_"] [data-testid="stCheckbox"] label::before,[class*="st-key-sw_"] [data-testid="stCheckbox"] label::after,
[class*="st-key-sw_"] [data-testid="stCheckbox"] label>div:nth-of-type(1)::before,[class*="st-key-sw_"] [data-testid="stCheckbox"] label>div:nth-of-type(1)::after{{display:none!important}}
[class*="st-key-sw_"] [data-testid="stCheckbox"] label>div:nth-of-type(1)>div{{position:absolute;top:3px;left:3px;width:26px;height:26px;border-radius:50%;background:#fff!important;
  box-shadow:0 1px 3px rgba(0,0,0,.3);transform:none!important;border:0}}
[class*="st-key-sw_"] [data-testid="stCheckbox"] label:has(input:checked)>div:nth-of-type(1){{background:var(--orange)!important}}
[class*="st-key-sw_"] [data-testid="stCheckbox"] label:has(input:checked)>div:nth-of-type(1)>div{{left:23px}}
[class*="st-key-sw_"] [data-testid="stCheckbox"] label p{{font-size:16px;line-height:22px}}
/* An expander as a quiet grey row with its chevron at the right ("Anything else to record?"). */
[class*="st-key-more_"] [data-testid="stExpander"],[class*="st-key-more_"] [data-testid="stExpander"] details{{border:0!important;border-radius:var(--r-panel);background:var(--ink-05)!important;overflow:hidden;box-shadow:none}}
[class*="st-key-more_"] [data-testid="stExpander"] summary{{background:transparent!important}}
[class*="st-key-more_"] [data-testid="stExpander"] summary{{min-height:48px;padding:0 16px}}
[class*="st-key-more_"] [data-testid="stExpander"] summary>span{{display:flex;flex-direction:row-reverse;justify-content:space-between;align-items:center;width:100%}}
[class*="st-key-more_"] [data-testid="stExpander"] summary p{{font-size:16px;line-height:22px}}
[class*="st-key-more_"] [data-testid="stExpander"] [data-testid="stExpanderDetails"]{{padding:0 16px 16px}}
/* The Save button while it works: the spinner state of the Save board. */
.st-key-save_saving button:disabled p{{color:#fff}}

/* ---- Final-result rows: the same option rows, two across ---- */
[class*="st-key-rows2"] [data-testid="stRadioGroup"]{{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}}

/* ---- Chips (st.pills): wrapping, one tap, no dropdown. For the nine-range rat weight scale. ---- */
[class*="st-key-chips"]{{width:100%!important}}
[class*="st-key-chips"] [role="radiogroup"]{{display:flex;flex-wrap:wrap;gap:8px;width:100%!important}}
[class*="st-key-chips"] button[role="radio"]{{
  min-height:44px;border-radius:var(--r-pill);border:0;background:var(--ink-05);color:var(--ink);padding:0 16px;box-shadow:none}}
[class*="st-key-chips"] button[role="radio"] p{{font-size:15px;line-height:20px;font-weight:400;color:inherit}}
[class*="st-key-chips"] button[role="radio"][aria-checked="true"]{{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange)}}
[class*="st-key-chips"] button[role="radio"][aria-checked="true"] p{{font-weight:700}}

/* ---- Segmented control (st.segmented_control). Only when every label is about 12 characters or fewer. ---- */
[class*="st-key-seg"] [role="radiogroup"]{{display:flex;width:100%!important;max-width:none!important;gap:0;background:var(--ink-05);border-radius:var(--r-segment);padding:2px}}
/* The filter on Follow-ups sits in its own container, so its element wrappers are widened to the column. */
[class*="st-key-seg_followup"] [data-testid="stElementContainer"],[class*="st-key-seg_followup"] [data-testid="stButtonGroup"]{{width:100%!important}}
@media (min-width:701px){{[class*="st-key-seg_followup"]{{max-width:480px}}}}
[class*="st-key-seg"] button[role="radio"]{{
  flex:1 1 0;min-width:0;min-height:44px;border:0;border-radius:var(--r-input);background:transparent;color:var(--ink-70);box-shadow:none}}
[class*="st-key-seg"] button[role="radio"] p{{font-size:15px;line-height:20px;font-weight:400;color:inherit}}
[class*="st-key-seg"] button[role="radio"][aria-checked="true"]{{background:#fff;color:var(--ink);box-shadow:var(--shadow-segment)}}
[class*="st-key-seg"] button[role="radio"][aria-checked="true"] p{{font-weight:700}}
/* Needs-a-choice: a 2px orange ring AND (written by the page) the words "Choose a build". */
[class*="st-key-seg_choose"] [role="radiogroup"]:not(:has(button[aria-checked="true"])){{box-shadow:inset 0 0 0 2px var(--orange)}}
.r1-need{{color:var(--orange-ink);font-weight:700;font-size:14px;line-height:20px}}
/* Inside a form the words cannot be written by the page (nothing re-runs until submit), so CSS shows them
   until a segment is chosen. */
[class*="st-key-seg_choosef"] [data-testid="stButtonGroup"]:not(:has(button[aria-checked="true"]))::after{{
  content:"Choose a build";display:block;color:var(--orange-ink);font-weight:700;font-size:14px;line-height:20px;margin-top:6px}}
/* A build row on Set up step 1: a white card holding the checkbox. */
[class*="st-key-card_build"]{{padding:14px 15px}}
/* A site card on Trap sites: a button and a text button under it. On a phone both are the width of the card (the Main board);
   on desktop they keep their natural width, like every other 7a screen (see the 700px block below). */
.stApp [class*="st-key-card_site_"]{{gap:8px}}
.stApp [class*="st-key-card_site_"] .r1-msg{{margin:2px 0 4px}}
.stApp [class*="st-key-acts_site_"]{{gap:8px}}
/* A status and, beside it on the same line, the "Not tracked" tag. */
.r1-statusrow{{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-top:2px}}
.r1-tag{{display:inline-flex;align-items:center;min-height:26px;padding:0 12px;border-radius:var(--r-pill);background:var(--orange-10);color:var(--orange-ink);font-size:13px;line-height:18px;font-weight:700}}
@media (min-width:701px){{
  /* Trap sites on desktop: two columns, top-aligned, 16px apart; each card's two actions side by side, 20px apart. */
  [class*="st-key-grid_sites"]{{display:grid!important;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px!important;align-items:start}}
  /* the number is top-aligned with the name on desktop (the phone keeps it where it is) */
  [class*="st-key-card_site_"] .r1-titlerow{{align-items:flex-start}}
  .stApp [class*="st-key-acts_site_"]{{flex-direction:row!important;align-items:center;gap:20px}}
  .stApp [class*="st-key-acts_site_"] [data-testid="stElementContainer"]{{width:auto!important}}
}}
.r1-label{{font-size:16px;line-height:22px;font-weight:700;margin:6px 0 2px}}
.r1-card-title{{font-size:22px;line-height:30px;font-weight:700;margin-bottom:4px}}
@media (max-width:700px){{
  /* Primary buttons fill the phone. The element container around a button is itself fit-content, so it has to widen too. */
  .stApp [data-testid="stElementContainer"]:has(button[kind="primary"]),
  .stApp [data-testid="stElementContainer"]:has(button[kind="primaryFormSubmit"]),
  .stApp [data-testid="stElementContainer"]:has(button[kind="primaryFormSubmit"]) > div{{width:100%}}
  .stApp div.stButton:has(button[kind="primary"]),.stApp div.stFormSubmitButton:has(button[kind="primaryFormSubmit"]){{width:100%}}
  .stApp div.stButton button[kind="primary"],.stApp div.stFormSubmitButton button[kind="primaryFormSubmit"]{{width:100%}}
  /* A Trap sites card: its button (primary, or the secondary of a site checked today) and its text button, full width, centred. */
  .stApp [class*="st-key-card_site_"] [data-testid="stElementContainer"]:has(:is(button[kind="primary"],button[kind="secondary"],button[kind="tertiary"])),
  .stApp [class*="st-key-card_site_"] div.stButton:has(:is(button[kind="primary"],button[kind="secondary"],button[kind="tertiary"])){{width:100%}}
  .stApp [class*="st-key-card_site_"] :is(button[kind="primary"],button[kind="secondary"],button[kind="tertiary"]){{width:100%;justify-content:center}}
  /* The hub's two columns stack on a phone; st.columns(gap="large") would leave 64px between the cards. */
  .stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-card_hub_visits"]),.stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-nec_left"]){{row-gap:16px}}
  /* End trial… sits under the Visits card on desktop. On a phone it stays where it always was, after the Evidence card: the left column's
     children join the stacked row so the block can be ordered after the right column, and a rule above it stands in for the old divider. */
  .stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-card_hub_visits"])>[data-testid="stColumn"]:first-child,
  .stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-card_hub_visits"])>[data-testid="stColumn"]:first-child>[data-testid="stVerticalBlock"]{{display:contents}}
  .stApp [data-testid="stHorizontalBlock"]:has([class*="st-key-card_hub_visits"])>[data-testid="stColumn"]:last-child{{order:1}}
  .stApp [data-testid="stLayoutWrapper"]:has(>[class*="st-key-hub_end_block"]){{order:2;flex:0 0 100%}}
  .stApp [class*="st-key-hub_end_block"]{{border-top:1px solid var(--ink-10);padding-top:16px;margin-top:4px}}
}}
[class*="st-key-pair_"] [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;gap:12px}}
[class*="st-key-pair_"] [data-testid="stColumn"]{{min-width:0!important;width:auto!important;flex:1 1 0!important}}
.r1-titlerow{{display:flex;justify-content:space-between;align-items:flex-end;gap:12px}}
.r1-title{{font-size:34px;line-height:40px;font-weight:700}}
@media (min-width:701px){{.r1-title{{font-size:48px;line-height:54px}}}}
.r1-chips{{display:flex;gap:10px;flex-wrap:wrap}}
.r1-chip{{flex:1 1 140px;background:var(--ink-05);border-radius:var(--r-panel);padding:10px 14px}}
.r1-chip b{{display:block;font-size:17px;line-height:22px}} .r1-chip span{{font-size:14px;line-height:20px;color:var(--ink-70)}}
.r1-kv{{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--ink-05);font-size:16px;line-height:22px}}
.r1-kv:last-child{{border-bottom:0}} .r1-kv .k{{color:var(--ink-70)}} .r1-kv .v{{font-weight:700;text-align:right}}
.r1-rowicon{{flex:0 0 44px;width:44px;height:44px;border-radius:var(--r-input);background:var(--ink-05);display:flex;align-items:center;justify-content:center}}

/* ---- List row: text left, action right, one line even on a phone ---- */
.stApp [class*="st-key-listrow_"]{{border-bottom:1px solid var(--ink-05);padding:12px 0;gap:0}}
[class*="st-key-listrow_"] [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;align-items:center;gap:12px}}
[class*="st-key-listrow_"] [data-testid="stColumn"]{{min-width:0!important;width:auto!important;flex:1 1 0!important}}
[class*="st-key-listrow_"] [data-testid="stColumn"]:last-child{{flex:0 0 auto!important}}
.stApp [class*="st-key-listrow_next"]{{background:var(--orange-10);border-radius:var(--r-panel);padding:12px;border-bottom:0}}
/* Follow-ups: the highlight reaches 7px into the card so its icon and Review button line up with the other rows' (they sat 12px off). */
.stApp [class*="st-key-listrow_next_followup_"]{{margin-left:-7px;margin-right:-7px;width:calc(100% + 14px)!important;max-width:none;box-sizing:border-box;padding:12px 7px}}
.r1-donerow{{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--ink-05)}}
.r1-donebox{{flex:0 0 44px;width:44px;height:44px;border-radius:var(--r-input);background:var(--green-10);color:var(--green);display:flex;align-items:center;justify-content:center}}
.stApp [class*="st-key-listrow_"][class*="end_visit_"],.stApp [class*="st-key-listrow_"][class*="end_followup_"],.r1-donerow.is-last{{border-bottom:0}}
/* The trap list's filter toggle is a rarely used extra, so it reads as quiet text, not as a heading. */
.stApp [class*="st-key-visit_filter_expanded_"] label p{{font-size:15px;line-height:20px;font-weight:400;color:var(--ink-70)}}
/* ...but still a 44px tap target: the whole label is the button. */
.stApp [class*="st-key-visit_filter_expanded_"] label{{min-height:44px;display:flex;align-items:center;cursor:pointer}}
/* Big numbers on a summary card (Trial performance), and a heading between cards. */
.r1-stats2{{display:flex;gap:36px;align-items:flex-end;margin:4px 0 8px}}
.r1-bigstat{{font-size:36px;line-height:40px;font-weight:700}}
.r1-bigstat-label{{font-size:14px;line-height:20px;color:var(--ink-70)}}
.r1-section{{font-size:22px;line-height:30px;font-weight:700;margin:24px 0 4px}}
/* In a narrow summary card the value stays on one line ("12 of 13") and the label wraps instead. */
[class*="st-key-card_perf_"] .r1-kv .v{{white-space:nowrap}}
.r1-donerow.is-just-saved{{background:var(--green-10);border-radius:var(--r-panel);padding:12px;border-bottom:0}}
.r1-donerow.is-just-saved .r1-donebox{{background:#fff}}
/* A progress bar: a thin ink-05 track with an orange fill. */
.r1-bar{{height:8px;border-radius:4px;background:var(--ink-05);overflow:hidden;margin:4px 0 12px}}
.r1-bar span{{display:block;height:100%;background:var(--orange);border-radius:4px}}

/* ---- Message panel: radius 14, padding 14; warn / error / success / info ---- */
.r1-msg{{border-radius:var(--r-panel);padding:14px;display:flex;gap:12px;align-items:flex-start;color:var(--ink)}}
.r1-msg .t{{font-size:17px;line-height:22px;font-weight:700}}
.r1-msg .d{{font-size:15px;line-height:20px}}
.r1-msg.warn{{background:var(--orange-10)}} .r1-msg.error{{background:var(--red-10)}}
.r1-msg.success{{background:var(--green-10)}} .r1-msg.info{{background:var(--ink-05)}}
.r1-msg svg{{flex:0 0 auto;margin-top:2px}} .r1-msg.warn svg{{color:var(--orange)}} .r1-msg.error svg{{color:var(--red)}} .r1-msg.success svg{{color:var(--green)}}

/* ---- Stepper: 26px discs, 2px joins ---- */
.r1-stepper{{display:flex;align-items:center;gap:8px;font-size:14px;line-height:20px}}
.r1-stepper .s{{display:inline-flex;align-items:center;gap:8px;white-space:nowrap;color:var(--ink-70)}}
.r1-stepper .d{{width:26px;height:26px;border-radius:50%;background:var(--ink-05);color:var(--ink-70);display:inline-flex;align-items:center;justify-content:center;font-weight:700;font-size:13px}}
.r1-stepper .s.now{{color:var(--ink);font-weight:700}} .r1-stepper .s.now .d{{background:var(--orange);color:#fff}}
.r1-stepper .s.done{{color:var(--ink)}} .r1-stepper .s.done .d{{background:var(--green);color:#fff}}
.r1-stepper .j{{flex:1 1 12px;height:2px;background:var(--ink-05);min-width:12px}} .r1-stepper .j.done{{background:var(--green)}}
@media (max-width:340px){{.r1-stepper{{flex-wrap:wrap;row-gap:8px}}.r1-stepper .j{{display:none}}}}  /* three labelled steps do not fit one row at 320px */
"""

# ------------------------------------------------------------- navigation ---
# One row on a phone (700px and under): Trap sites, Follow-ups (count), More.
# Four items on desktop: Trap sites, Follow-ups (count), Trial performance, Administration.
# Both are drawn and CSS shows one, so the switch at 700px costs no round trip.
# The current section's page_link is `disabled` (kept from the shipped app): that is the
# "you are here" state, restyled here.

NAV_CSS = """
.st-key-app_nav{margin-bottom:5px}
/* The pills are drawn outside the screen container, so they take the app font here (they were Streamlit's own Source Sans). */
.st-key-app_nav,.st-key-app_nav *:not([data-testid="stIconMaterial"]){font-family:var(--font)}
.st-key-nav_phone,.st-key-nav_desktop{gap:8px!important;flex-wrap:nowrap!important;align-items:center}
@media (max-width:340px){.st-key-nav_phone{flex-wrap:wrap!important}}  /* a 320px phone cannot fit three pills on one row */
@media (min-width:701px){.st-key-nav_phone{display:none!important}}
@media (max-width:700px){.st-key-nav_desktop{display:none!important}}
.st-key-app_nav [data-testid="stPageLink"] a{
  min-height:44px;display:inline-flex;align-items:center;gap:8px;border-radius:var(--r-pill);background:var(--ink-05);
  color:var(--ink-70);padding:0 16px;text-decoration:none;box-sizing:border-box;white-space:nowrap}
.st-key-app_nav [data-testid="stPageLink"] a p{font-size:15px;line-height:20px;font-weight:400;color:inherit}
.st-key-app_nav [data-testid="stPageLink"] a[aria-disabled="true"],.st-key-app_nav [data-testid="stPageLink"] a[disabled]{
  background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange);color:var(--ink);opacity:1;cursor:default}
.st-key-app_nav [data-testid="stPageLink"] a[aria-disabled="true"] p,.st-key-app_nav [data-testid="stPageLink"] a[disabled] p{font-weight:700;color:var(--ink)}
.stApp .st-key-app_nav [data-testid="stPopoverButton"]{
  min-height:44px;height:44px;border-radius:var(--r-pill);background:var(--ink-05);border:0;box-shadow:none;color:var(--ink-70);padding:0 14px 0 16px;gap:6px}
.stApp .st-key-app_nav [data-testid="stPopoverButton"] p{font-size:15px;line-height:20px;font-weight:400;color:inherit}
.st-key-app_nav [data-testid="stPopoverButton"]>div{width:auto;justify-content:center;gap:8px}
.st-key-app_nav [data-testid="stPopoverButton"] [data-testid="stIconMaterial"]{display:none}
.st-key-app_nav [data-testid="stPopoverButton"]::after{content:"";width:10px;height:6px;background:currentColor;
  -webkit-mask:url(/app/static/icons/chevron-down.svg) center/contain no-repeat;mask:url(/app/static/icons/chevron-down.svg) center/contain no-repeat}
.stApp [class*="st-key-navmore_on"] [data-testid="stPopoverButton"]{background:var(--orange-10);box-shadow:inset 0 0 0 2px var(--orange);color:var(--ink)}
.stApp [class*="st-key-navmore_on"] [data-testid="stPopoverButton"] p{font-weight:700}
/* open / hover state of the pill: keep the label ink, never the secondary-button orange */
.stApp .st-key-app_nav [data-testid="stPopoverButton"]:is(:hover,:focus,:active,[aria-expanded="true"]){background:var(--ink-10);color:var(--ink-70);outline:0}
.stApp [class*="st-key-navmore_on"] [data-testid="stPopoverButton"]:is(:hover,:focus,:active,[aria-expanded="true"]){background:var(--orange-10);color:var(--ink)}
/* the menu: Streamlit renders it in a portal outside .stApp, so these rules carry no .stApp prefix */
body [data-testid="stPopoverBody"],body [data-testid="stPopoverBody"] *:not([data-testid="stIconMaterial"]){font-family:var(--font)}
body [data-testid="stPopoverBody"]{border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:8px 0;border:0;width:min(320px,calc(100vw - 30px));min-width:min(300px,calc(100vw - 30px))}
body [data-testid="stPopoverBody"] [data-testid="stVerticalBlock"]{gap:0}
body [data-testid="stPopoverBody"] [data-testid="stElementContainer"],body [data-testid="stPopoverBody"] [data-testid="stPageLink"],
body [data-testid="stPopoverBody"] [data-testid="stPageLink"]>div,body [data-testid="stPopoverBody"] div.stButton{width:100%!important}
body [data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"]{margin-bottom:0!important}
/* Streamlit gives each element a margin that made the 48px rows overlap by 12px (a visible 40px pitch): rows sit edge to edge. */
body [data-testid="stPopoverBody"] [data-testid="stElementContainer"],body [data-testid="stPopoverBody"] [data-testid="stPageLink"]{margin:0!important}
body [data-testid="stPopoverBody"] [data-testid="stElementContainer"]:has([data-testid="stPageLink"]),body [data-testid="stPopoverBody"] [data-testid="stPageLink"]{height:48px;padding:0}
body [data-testid="stPopoverBody"] [data-testid="stPageLink"] a,body [data-testid="stPopoverBody"] div.stButton button{
  min-height:48px;height:auto;width:100%;display:flex;align-items:center;justify-content:space-between;background:transparent;border-radius:0;border:0;
  border-bottom:1px solid var(--ink-05);outline:0;box-shadow:none;padding:0 16px;color:var(--ink);text-decoration:none;box-sizing:border-box}
body [data-testid="stPopoverBody"] div.stButton button{justify-content:flex-start;border-bottom:0;text-align:left}
body [data-testid="stPopoverBody"] div.stButton button>div{width:100%;justify-content:flex-start}
body [data-testid="stPopoverBody"] [data-testid="stPageLink"] a p,body [data-testid="stPopoverBody"] div.stButton button p{font-size:16px;line-height:22px;font-weight:400;color:var(--ink)}
body [data-testid="stPopoverBody"] [data-testid="stPageLink"] a:is([aria-disabled="true"],[disabled]) p{font-weight:700}
body .r1-menu-group{font-size:13px;line-height:16px;font-weight:700;color:var(--ink-70);padding:16px 16px 6px}
/* the help under the Operator field is a visible line, not a tooltip, and carries the divider above Sign out */
body .r1-menu-help{font-size:13px;line-height:18px;color:var(--ink-70);padding:0 16px 12px;border-bottom:1px solid var(--ink-05)}
/* the Operator name sits in the menu like any other row: same side padding, a 44px field */
body [data-testid="stPopoverBody"] [data-testid="stTextInput"]{padding:0 16px 8px}
body [data-testid="stPopoverBody"] [data-testid="stTextInput"] label p{font-size:13px;line-height:16px;font-weight:700;color:var(--ink-70)}
body [data-testid="stPopoverBody"] [data-testid="stTextInput"] input{min-height:44px;font-size:16px}
"""


def count_badge_css(href_suffix: str, count: int, scope: str = ".st-key-app_nav") -> str:
    """A right-hand count on a page_link pill, shown only when above zero. The count is
    drawn with CSS because a page_link label cannot hold markup; the caller passes a
    number it already has (no extra scan). 22px pill, 13px bold orange-ink on orange-10,
    white when its pill is the current page."""
    if count <= 0:
        return ""
    return (
        f'{scope} a[href$="{href_suffix}"]::after,[data-testid="stPopoverBody"] a[href$="{href_suffix}"]::after{{'
        f'content:"{int(count)}";min-width:22px;height:22px;border-radius:999px;background:var(--orange-10);color:var(--orange-ink);'
        f'font-size:13px;line-height:22px;font-weight:700;text-align:center;padding:0 6px;box-sizing:border-box}}'
        f'{scope} a[href$="{href_suffix}"]:is([aria-disabled="true"],[disabled])::after{{background:#fff;color:var(--orange-ink)}}'
    )


def design_css(extra: str = "") -> str:
    """Everything, as one <style> block (static string; nothing computed per run)."""
    return "<style>" + FONT_FACE_CSS + TOKENS_CSS + TYPE_CSS + COMPONENT_CSS + NAV_CSS + extra + "</style>"


# ---------------------------------------------------------------- scoping ---
# The journey screens (Phases 2, 6) are built in these components while the rest of the
# app still wears the old look until each 7b PR. So their CSS is scoped to one container
# (`st.container(key="r1_screen")`): nothing outside it changes.

SCREEN_KEY = "r1_screen"
SCREEN_SCOPE = f".st-key-{SCREEN_KEY}"


def _split_top_level(text: str, sep: str = ",") -> list:
    parts, depth, current = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == sep and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += ch
    parts.append(current)
    return parts


def _split_declarations(body: str) -> list:
    """Split `a:b;c:url(x;y);d:e` on top-level semicolons (not inside parens or quotes)."""
    parts, depth, quote, current = [], 0, "", ""
    for ch in body:
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ";" and depth == 0 and not quote:
            parts.append(current)
            current = ""
        else:
            current += ch
    if current.strip():
        parts.append(current)
    return parts


def _important(body: str) -> str:
    out = []
    for decl in _split_declarations(body):
        decl = decl.strip()
        if not decl:
            continue
        name = decl.split(":", 1)[0].strip()
        out.append(decl if "!important" in decl or name.startswith("--") or name == "content" else f"{decl}!important")
    return ";".join(out)


def scope_css(css: str, scope: str, important: bool = False) -> str:
    """Prefix every selector in `css` with `scope`. `.stApp` becomes the scope itself,
    `:root`, `@font-face`, `@keyframes` and portal rules (`body …`, the popover menu) are
    left alone, and `@media` blocks are scoped inside."""
    out, i, n = [], 0, len(css)
    while i < n:
        brace = css.find("{", i)
        if brace == -1:
            out.append(css[i:])
            break
        prelude = css[i:brace].strip()
        depth, j = 1, brace + 1
        while j < n and depth:
            depth += {"{": 1, "}": -1}.get(css[j], 0)
            j += 1
        body = css[brace + 1:j - 1]
        i = j
        if prelude.startswith("/*"):  # a comment glued to the next rule
            end = prelude.find("*/")
            prelude = prelude[end + 2:].strip() if end != -1 else prelude
        if prelude.startswith("@media") or prelude.startswith("@supports"):
            out.append(f"{prelude}{{{scope_css(body, scope, important)}}}")
        elif prelude.startswith("@") or prelude.startswith(":root"):
            out.append(f"{prelude}{{{body}}}")
        else:
            selectors = []
            for sel in _split_top_level(prelude):
                sel = sel.strip()
                if not sel:
                    continue
                if sel.startswith("body ") or "stPopoverBody" in sel:
                    selectors.append(sel)
                elif sel.startswith(".stApp"):
                    selectors.append(scope + sel[len(".stApp"):])
                else:
                    selectors.append(f"{scope} {sel}")
            if selectors:
                out.append(f"{','.join(selectors)}{{{_important(body) if important else body}}}")
    return "".join(out)


def _component_css_only() -> str:
    # `important`: the legacy sheet restyles buttons, radios and labels with !important, so the
    # journey screens' components must outrank it (inside their own scope only).
    return FONT_FACE_CSS + TOKENS_CSS + scope_css(TYPE_CSS + COMPONENT_CSS, SCREEN_SCOPE, important=True)


# The navigation is on nearly every page, including the existing ones, so it carries what it needs itself: the font, the tokens
# and its own rules, forced above the legacy sheet (which restyles links and buttons with !important). One static string, built once.
NAV_APP_CSS = "<style>" + FONT_FACE_CSS + TOKENS_CSS + scope_css(NAV_CSS, ".stApp", important=True) + "</style>"

# One static string, built once at import (no per-run work).
SCREEN_CSS = "<style>" + _component_css_only() + "</style>"

# The journey screens that follow the Set up / End trial pattern show no top navigation, and read as a
# single column (a form is not stretched across a desktop).
HIDE_TOP_NAV_CSS = "<style>.st-key-app_top_navigation,.st-key-app_nav{display:none!important}</style>"
NARROW_CSS = f"<style>{SCREEN_SCOPE}{{max-width:760px}}</style>"



def stepper_html(current: int, done_through: int = 0) -> str:
    """Set up · Checking · End trial. `current` is 1-3; steps before it are done (a check),
    the current one is orange, later ones are grey. Appears only on the four trial-level
    screens, never on the visit or check pages."""
    names = ("Set up", "Checking", "End trial")
    parts = []
    for idx, name in enumerate(names, start=1):
        if idx < current:
            parts.append(f'<span class="s done"><span class="d">{icon("check", 11)}</span>{name}</span>')
        elif idx == current:
            parts.append(f'<span class="s now"><span class="d">{idx}</span>{name}</span>')
        else:
            parts.append(f'<span class="s"><span class="d">{idx}</span>{name}</span>')
        if idx < len(names):
            parts.append(f'<span class="j{" done" if idx < current else ""}"></span>')
    return f'<div class="r1-stepper">{"".join(parts)}</div>'


def message_html(kind: str, title: str, detail: str = "", icon_name: str = "") -> str:
    """Message panel: warn / error / success / info, icon + bold title + 15px detail. `icon_name` replaces the kind's own icon."""
    icon_name = icon_name or {"warn": "warn-circle", "error": "warn-circle", "success": "check-circle", "info": "info-circle"}[kind]
    body = f'<div class="d">{detail}</div>' if detail else ""
    heading = f'<div class="t">{title}</div>' if title else ""
    return f'<div class="r1-msg {kind}">{icon(icon_name, 22)}<div>{heading}{body}</div></div>'

# ---------------------------------------------------------------- Visit complete (Phase 7b, 6 of 8) -----
# The summary shown once, in place of the old one-line "site check completed" message, on the page Finish site check lands on. Its rules are
# rooted at .r1-vc (not at the screen container) because it is drawn above whichever page that is; it uses only the :root tokens.
VISIT_COMPLETE_CSS = """<style>
.r1-vc{display:flex;flex-direction:column;align-items:center;gap:12px;max-width:560px;margin:8px auto 24px;text-align:center;color:var(--ink)}
.r1-vc-badge{width:92px;height:92px;border-radius:50%;background:var(--green-10);display:flex;align-items:center;justify-content:center;margin-top:4px}
.r1-vc-badge span{width:64px;height:64px;border-radius:50%;background:var(--green);color:#fff;display:flex;align-items:center;justify-content:center}
.r1-vc-title{font-size:34px;line-height:40px;font-weight:700}
.r1-vc-site{font-size:17px;line-height:22px;color:var(--ink-70);margin-top:-6px}
.r1-vc-stats{width:100%;box-sizing:border-box;display:flex;justify-content:space-around;gap:12px;background:#fff;border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:18px 12px;margin-top:4px}
.r1-vc-stats b{display:block;font-size:30px;line-height:36px;font-weight:700}
.r1-vc-stats span{display:block;font-size:14px;line-height:20px;color:var(--ink-70)}
.r1-vc-needs{width:100%;text-align:left}
.r1-vc-needs h3{font-size:17px;line-height:22px;font-weight:700;margin:8px 0 8px;padding:0}
.r1-vc-list{background:#fff;border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:4px 16px}
.r1-vc-row{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--ink-05)}
.r1-vc-row:last-child{border-bottom:0}
.r1-vc-row .tile{flex:0 0 44px;width:44px;height:44px;border-radius:var(--r-input);background:var(--ink-05);display:flex;align-items:center;justify-content:center}
.r1-vc-row .t{font-size:17px;line-height:22px;font-weight:700}
.r1-vc-row .d{font-size:14px;line-height:20px;color:var(--ink-70)}
.r1-vc-next{font-size:15px;line-height:20px;color:var(--ink-70)}
.r1-vc-site .dk{display:none}
@media (min-width:701px){
  /* Desktop: one compact success card across the top: the tick, the title and "site · next visit due" on the left, the counts on the right. */
  .r1-vc{display:grid;grid-template-columns:auto 1fr auto;grid-template-areas:"badge title stats" "badge site stats" "needs needs needs";align-items:center;
    column-gap:20px;row-gap:0;max-width:none;margin:0 0 16px;text-align:left;background:#fff;border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:18px 24px}
  .r1-vc-badge{grid-area:badge;margin:0;width:72px;height:72px}
  .r1-vc-badge span{width:48px;height:48px}
  .r1-vc-title{grid-area:title;font-size:30px;line-height:36px;align-self:end}
  .r1-vc-site{grid-area:site;margin-top:0;align-self:start}
  .r1-vc-site .dk{display:inline}
  .r1-vc-stats{grid-area:stats;width:auto;background:transparent;box-shadow:none;padding:0;margin:0;gap:28px;justify-content:flex-end}
  .r1-vc-needs{grid-area:needs;margin-top:14px}
  .r1-vc-next{display:none}
}
</style>"""


def visit_complete_html(site: str, stats, needs, next_due: str = "") -> str:
    """The Visit complete summary: a green check, the title and site, a card of numbers, what needs doing next, when the next visit is due.
    `stats` is [(value, label)]; `needs` is [(icon name, title, caption)]; every string is already escaped by the caller."""
    stat_html = "".join(f"<div><b>{value}</b><span>{label}</span></div>" for value, label in stats)
    needs_html = ""
    if needs:
        rows = "".join(
            f'<div class="r1-vc-row"><div class="tile">{icon(name, 22)}</div><div><div class="t">{title}</div><div class="d">{caption}</div></div></div>'
            for name, title, caption in needs
        )
        needs_html = f'<div class="r1-vc-needs"><h3>Needs doing next</h3><div class="r1-vc-list">{rows}</div></div>'
    next_html = f'<div class="r1-vc-next">Next visit due {next_due}.</div>' if next_due else ""
    dk = f'<span class="dk"> · next visit due {next_due}</span>' if next_due else ""  # desktop only: the compact card says it on the site line
    return (
        f'<div class="r1-vc" role="status">'
        f'<div class="r1-vc-badge"><span>{icon("check", 36)}</span></div>'
        f'<div class="r1-vc-title" role="heading" aria-level="1">Visit complete</div><div class="r1-vc-site">{site}{dk}</div>'
        f'<div class="r1-vc-stats">{stat_html}</div>{needs_html}{next_html}</div>'
    )
