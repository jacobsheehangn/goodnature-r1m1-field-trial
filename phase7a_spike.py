"""Phase 7a spike (TRIAL_LIFECYCLE_BRIEF.md): can the Phase 7 components be built in the
pinned Streamlit 1.60.0? A scratch app, NOT part of the product: Render runs app.py,
this file is never reachable there. Run it beside the app with

    streamlit run phase7a_spike.py

(it lives at the repo root so Streamlit's static file serving finds ./static).
Every name, count and ID on these pages is illustrative.

(a) species tiles   (b) segmented control   (c) option rows   (d) list rows
(e) primary button saving / done            (f) navigation: phone, desktop, current state, count
"""
import streamlit as st

import r1m1_design as d

st.set_page_config(page_title="R1/M1 · Phase 7a spike", layout="wide", initial_sidebar_state="collapsed")

FOLLOWUPS_OPEN = 3
DATA_QUALITY_FLAGGED = 4


def sites_page():
    render("sites")
    st.title("Trap sites")
    spike_components()


def stub(title):
    def page():
        render(KEY_BY_TITLE[title])
        st.title(title)
        st.markdown('<div class="r1-meta">Stub page for the navigation states.</div>', unsafe_allow_html=True)
    page.__name__ = "stub_" + title.lower().replace(" ", "_").replace("&", "and")
    return page


PAGES = {
    "sites": st.Page(sites_page, title="Trap sites", default=True),
    "followups": st.Page(stub("Follow-ups"), title="Follow-ups", url_path="follow-ups"),
    "performance": st.Page(stub("Trial performance"), title="Trial performance", url_path="trial-performance"),
    "traps": st.Page(stub("Traps"), title="Traps", url_path="traps"),
    "setup": st.Page(stub("Trial setup"), title="Trial setup", url_path="trial-setup"),
    "records": st.Page(stub("Data & records"), title="Data & records", url_path="data-records"),
    "quality": st.Page(stub("Data quality"), title="Data quality", url_path="data-quality"),
}
KEY_BY_TITLE = {p.title: k for k, p in PAGES.items()}
ADMIN = ("traps", "setup", "records", "quality")


def link(key, current):
    st.page_link(PAGES[key], label=PAGES[key].title, disabled=(key == current))


def render(current):
    """Navigation: the style sheet, then both layouts (CSS shows one at 700px)."""
    extra = d.count_badge_css("follow-ups", FOLLOWUPS_OPEN) + d.count_badge_css("data-quality", DATA_QUALITY_FLAGGED)
    st.markdown(d.design_css(extra), unsafe_allow_html=True)
    with st.container(key="app_nav"):
        # Desktop (over 700px): Trap sites, Follow-ups (count), Trial performance, Administration.
        with st.container(horizontal=True, key="nav_desktop"):
            link("sites", current)
            link("followups", current)
            link("performance", current)
            with st.container(key="navmore_on_desktop" if current in ADMIN else "navmore_off_desktop"):
                with st.popover("Administration"):
                    for k in ADMIN:
                        link(k, current)
                    st.button("Sign out", key="signout_desktop")
        # Phone (700px and under): Trap sites, Follow-ups (count), More.
        with st.container(horizontal=True, key="nav_phone"):
            link("sites", current)
            link("followups", current)
            with st.container(key="navmore_on_phone" if current == "performance" or current in ADMIN else "navmore_off_phone"):
                with st.popover("More"):
                    link("performance", current)
                    st.markdown('<div class="r1-menu-group">Administration</div>', unsafe_allow_html=True)
                    for k in ADMIN:
                        link(k, current)
                    st.button("Sign out", key="signout_phone")


def note(text):
    st.markdown(f'<div class="r1-meta" style="margin-top:6px">{text}</div>', unsafe_allow_html=True)


def spike_components():
    st.markdown('<div class="r1-meta">Spike annotations are in grey above each card. Names and counts are illustrative.</div>', unsafe_allow_html=True)

    note("(a) Species tiles: a restyled st.radio, four across")
    with st.container(key="card_a"):
        st.radio("What was it?", ["Rat", "Mouse", "Non-target", "Unknown"], horizontal=True, key="species_a", index=0)

    note("(b) Segmented control: st.segmented_control; second one needs a choice")
    with st.container(key="card_b"):
        st.segmented_control("Rat type", ["Norway rat", "Ship rat", "Unclear"], key="seg_a", default="Norway rat", selection_mode="single")
        build = st.segmented_control("Build for this trap", ["Build 18", "Build 19"], key="seg_choose_b", selection_mode="single")
        if build is None:
            st.markdown('<div class="r1-need">Choose a build</div>', unsafe_allow_html=True)

    note("(c) Option rows: a restyled vertical st.radio")
    with st.container(key="card_c"):
        st.radio("Camera working and covering the trap?", ["Yes", "No", "Could not assess"], key="rows_c", index=0)

    note("(d) List rows: text left, button right, one line on a phone")
    with st.container(key="cardlist_d"):
        rows = [("R16-10", "Build 19", True), ("R16-11", "Build 18", False), ("R16-12", "Build 19", False)]
        for n, (trap, build_name, is_next) in enumerate(rows):
            with st.container(key=f"listrow_next_{n}" if is_next else f"listrow_{n}"):
                left, right = st.columns([3, 1], vertical_alignment="center")
                left.markdown(f'<div class="r1-row-title">{trap}</div><div class="r1-meta">{build_name}</div>', unsafe_allow_html=True)
                right.button("Check", key=f"check_{n}", type="primary" if is_next else "secondary")
        st.markdown(
            f'<div class="r1-donerow"><div class="r1-donebox">{d.icon("check", 14)}</div><div><div class="r1-row-title">R16-09</div>'
            '<div class="r1-meta">Checked 8:55 · Still set, no animal</div></div></div>'
            f'<div class="r1-donerow"><div class="r1-donebox">{d.icon("rat", 34)}</div><div><div class="r1-row-title">R16-08</div>'
            '<div class="r1-meta">Checked 8:49 · Dead animal found · Rat</div></div></div>',
            unsafe_allow_html=True,
        )

    note("(e) Buttons: ready, saving (disabled, ignores taps), done; secondary, text and back pill")
    with st.container(key="card_e"):
        st.button("Save check", type="primary", key="save_ready", width="stretch")
        st.button("Saving check…", type="primary", key="save_saving", disabled=True, width="stretch")
        st.markdown('<div class="r1-meta">Keep this screen open until it finishes.</div>', unsafe_allow_html=True)
        st.button("Saved", type="primary", key="save_done", disabled=True, width="stretch")
        st.button("Finish site check", type="primary", key="finish_disabled", disabled=True, width="stretch")
        st.markdown('<div class="r1-meta">5 traps still to check.</div>', unsafe_allow_html=True)
        st.button("Exit to Trap sites", key="back_exit")
        st.button("Trial overview", key="text_btn", type="tertiary")

    note("Status dots, message panels, stepper (static markup)")
    with st.container(key="card_f"):
        st.markdown(
            '<div style="display:flex;flex-direction:column;gap:10px">'
            '<span class="r1-status due">Due today</span><span class="r1-status progress">In progress</span>'
            '<span class="r1-status overdue">Overdue by 8 days</span><span class="r1-status done">All 9 traps checked</span>'
            '<span class="r1-status">No trial running</span></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            f'<div class="r1-msg warn">{d.icon("warn-circle", 22)}<div><div class="t">Record why the trap is not ready.</div>'
            '<div class="d">Add a reason in the box above, then save again.</div></div></div>'
            f'<div class="r1-msg success" style="margin-top:8px">{d.icon("check-circle", 22)}<div><div class="t">R16-10 saved</div>'
            '<div class="d">Dead animal found · Rat · 1 photo.</div></div></div>',
            unsafe_allow_html=True,
        )
        st.markdown(
            '<div class="r1-stepper"><span class="s done"><span class="d">✓</span>Set up</span><span class="j done"></span>'
            '<span class="s now"><span class="d">2</span>Checking</span><span class="j"></span>'
            '<span class="s"><span class="d">3</span>End trial</span></div>',
            unsafe_allow_html=True,
        )


pg = st.navigation(list(PAGES.values()), position="hidden")
pg.run()
