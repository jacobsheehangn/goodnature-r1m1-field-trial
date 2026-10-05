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


def _species_icon_rules() -> str:
    return "".join(
        f'[class*="st-key-species"] [data-testid="stRadioGroup"]>label:nth-child({i}){{--icon:url({STATIC_URL}/icons/{name}.svg)}}'
        for i, name in enumerate(_SPECIES_ORDER, start=1)
    )


COMPONENT_CSS = f"""
/* ---- Card: white, radius 20, shadow-panel, padding 15, 10px between cards ---- */
.stApp [class*="st-key-card_"],.stApp [class*="st-key-cardlist_"]{{background:#fff;border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:15px;gap:15px}}
.stApp [class*="st-key-cardlist_"]{{gap:0}}
.stApp [data-testid="stMainBlockContainer"]>div>[data-testid="stVerticalBlock"]{{gap:10px}}

/* ---- Buttons ---- */
.stApp div.stButton button,.stApp div.stFormSubmitButton button{{
  border-radius:var(--r-pill);border:0;box-shadow:none;display:inline-flex;align-items:center;justify-content:center;gap:8px;
  padding:0 24px;transition:none}}
.stApp div.stButton button p{{font-size:15px;line-height:20px;font-weight:700}}
.stApp button[kind="primary"],.stApp [data-testid="stBaseButton-primary"]{{
  background:var(--orange);color:#fff;min-height:48px;height:48px}}
.stApp button[kind="primary"] p,.stApp [data-testid="stBaseButton-primary"] p{{font-size:16px;color:#fff}}
.stApp button[kind="primary"]:hover:not(:disabled){{background:#e9621c;color:#fff}}
.stApp button[kind="primary"]:active:not(:disabled){{background:#cf5515;color:#fff}}
.stApp button[kind="primary"]:disabled{{background:var(--orange-50);color:#fff;opacity:1;cursor:not-allowed}}
.stApp button[kind="secondary"],.stApp [data-testid="stBaseButton-secondary"]{{
  background:var(--ink-05);color:var(--orange-ink);min-height:44px;height:44px}}
.stApp button[kind="secondary"] p,.stApp [data-testid="stBaseButton-secondary"] p{{color:var(--orange-ink)}}
.stApp button[kind="secondary"]:hover,.stApp button[kind="secondary"]:active{{background:var(--ink-10);color:var(--orange-ink)}}
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

/* ---- Species tiles (a restyled st.radio, 4 across) ---- */
[class*="st-key-species"] [data-testid="stRadioGroup"]{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px}}
[class*="st-key-species"] [data-testid="stRadioOption"]{{
  min-height:96px;border-radius:var(--r-card);background:var(--ink-05);display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:6px;padding:12px 2px;margin:0;cursor:pointer;color:var(--ink)}}
[class*="st-key-species"] [data-testid="stRadioOption"]::before{{
  content:"";width:40px;height:40px;flex:0 0 40px;background:currentColor;
  -webkit-mask:var(--icon) center/contain no-repeat;mask:var(--icon) center/contain no-repeat}}
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
[class*="st-key-rows"] [data-testid="stRadioOption"]:has(input:checked)::after{{
  border:0;background:var(--orange) {_CHECK_DATA_URI} center/12px no-repeat}}

/* ---- Segmented control (st.segmented_control). Only when every label is about 12 characters or fewer. ---- */
[class*="st-key-seg"] [role="radiogroup"]{{display:flex;width:100%!important;max-width:none!important;gap:0;background:var(--ink-05);border-radius:var(--r-segment);padding:2px}}
[class*="st-key-seg"] button[role="radio"]{{
  flex:1 1 0;min-width:0;min-height:44px;border:0;border-radius:var(--r-input);background:transparent;color:var(--ink-70);box-shadow:none}}
[class*="st-key-seg"] button[role="radio"] p{{font-size:15px;line-height:20px;font-weight:400;color:inherit}}
[class*="st-key-seg"] button[role="radio"][aria-checked="true"]{{background:#fff;color:var(--ink);box-shadow:var(--shadow-segment)}}
[class*="st-key-seg"] button[role="radio"][aria-checked="true"] p{{font-weight:700}}
/* Needs-a-choice: a 2px orange ring AND (written by the page) the words "Choose a build". */
[class*="st-key-seg_choose"] [role="radiogroup"]:not(:has(button[aria-checked="true"])){{box-shadow:inset 0 0 0 2px var(--orange)}}
.r1-need{{color:var(--orange-ink);font-weight:700;font-size:14px;line-height:20px}}

/* ---- List row: text left, action right, one line even on a phone ---- */
.stApp [class*="st-key-listrow_"]{{border-bottom:1px solid var(--ink-05);padding:12px 0;gap:0}}
[class*="st-key-listrow_"] [data-testid="stHorizontalBlock"]{{flex-wrap:nowrap!important;align-items:center;gap:12px}}
[class*="st-key-listrow_"] [data-testid="stColumn"]{{min-width:0!important;width:auto!important;flex:1 1 0!important}}
[class*="st-key-listrow_"] [data-testid="stColumn"]:last-child{{flex:0 0 auto!important}}
.stApp [class*="st-key-listrow_next"]{{background:var(--orange-10);border-radius:var(--r-panel);padding:12px;border-bottom:0}}
.r1-donerow{{display:flex;align-items:center;gap:12px;padding:12px 0;border-bottom:1px solid var(--ink-05)}}
.r1-donebox{{flex:0 0 44px;width:44px;height:44px;border-radius:var(--r-input);background:var(--green-10);color:var(--green);display:flex;align-items:center;justify-content:center}}

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
body [data-testid="stPopoverBody"]{border-radius:var(--r-card);box-shadow:var(--shadow-panel);padding:8px 0;border:0;min-width:min(300px,calc(100vw - 30px))}
body [data-testid="stPopoverBody"] [data-testid="stVerticalBlock"]{gap:0}
body [data-testid="stPopoverBody"] [data-testid="stElementContainer"],body [data-testid="stPopoverBody"] [data-testid="stPageLink"],
body [data-testid="stPopoverBody"] [data-testid="stPageLink"]>div,body [data-testid="stPopoverBody"] div.stButton{width:100%!important}
body [data-testid="stPopoverBody"] [data-testid="stMarkdownContainer"]{margin-bottom:0!important}
body [data-testid="stPopoverBody"] [data-testid="stPageLink"] a,body [data-testid="stPopoverBody"] div.stButton button{
  min-height:48px;height:auto;width:100%;display:flex;align-items:center;justify-content:space-between;background:transparent;border-radius:0;border:0;
  border-bottom:1px solid var(--ink-05);outline:0;box-shadow:none;padding:0 20px;color:var(--ink);text-decoration:none;box-sizing:border-box}
body [data-testid="stPopoverBody"] div.stButton button{justify-content:flex-start;border-bottom:0;text-align:left}
body [data-testid="stPopoverBody"] div.stButton button>div{width:100%;justify-content:flex-start}
body [data-testid="stPopoverBody"] [data-testid="stPageLink"] a p,body [data-testid="stPopoverBody"] div.stButton button p{font-size:16px;line-height:22px;font-weight:400;color:var(--ink)}
body [data-testid="stPopoverBody"] [data-testid="stPageLink"] a:is([aria-disabled="true"],[disabled]) p{font-weight:700}
.r1-menu-group{font-size:13px;line-height:16px;font-weight:700;color:var(--ink-70);padding:16px 20px 6px}
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
