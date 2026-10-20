"""What a Camera review save writes, for every reachable input: the Windows row it fills and the Follow-up it completes (Batch 1, 14 Oct 2026).

Run inside a process that has imported app. run_inline exec's the save block exactly as it stood inline in the follow-up task page on main
(`golden/camera_review_inline_block_main.txt`); run_extracted calls app.apply_camera_review(), the function the page calls once the block is moved.
The clock and the ID generator are pinned (as in check_save_matrix), so the rows compare byte for byte."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

from check_save_matrix import Pinned, PINNED_NOW

GOLDEN_DIR = Path(__file__).parent / "golden"
INLINE_BLOCK = GOLDEN_DIR / "camera_review_inline_block_main.txt"
T0 = PINNED_NOW - timedelta(hours=6)              # the closed window started 6 h before the pinned now ...
WINDOW_END = PINNED_NOW - timedelta(hours=3)      # ... and the check closed it 3 h before
FIRST, TRIGGER, KILL = T0 + timedelta(minutes=10), T0 + timedelta(minutes=20), T0 + timedelta(minutes=30)
LEVELS = ["Single interaction", "Repeated interaction", "Heavy / repeated interaction"]
ASSESSMENTS = ["Humane", "Not humane", "Unclear", "No usable video"]
EXTRAS = [("", ""), ("n", ""), ("", "https://example.test/video"), ("n", "https://example.test/video")]   # (notes, link)


def cells() -> list:
    """Every reachable answer set: only what the page lets through its own validation."""
    out = []
    def add(**c):
        c.setdefault("interaction_level", "Unclear"); c.setdefault("strike_area", "Unclear"); c.setdefault("activated", "Unclear")
        c.setdefault("assessment", "Not applicable"); c.setdefault("first", False); c.setdefault("trigger", False); c.setdefault("kill", False)
        for notes, link in EXTRAS:
            out.append({**c, "notes": notes, "link": link})
    # a kill review (the window's finding is Dead animal found)
    add(kill=False, is_kill=True, usable="No", target="Unclear")
    for level in LEVELS:
        for assessment in ASSESSMENTS:
            add(is_kill=True, usable="Yes", target="Yes", interaction_level=level, strike_area="Yes", activated="Yes", assessment=assessment, first=True, kill=True)
    # a review of something other than a kill
    add(is_kill=False, usable="No", target="Unclear")
    add(is_kill=False, usable="Yes", target="No", interaction_level="Not applicable", strike_area="Not applicable", activated="No")
    add(is_kill=False, usable="Yes", target="Unclear")
    for level in LEVELS:
        base = dict(is_kill=False, usable="Yes", target="Yes", interaction_level=level, first=True)
        add(**base, strike_area="Yes", activated="Yes", trigger=True)
        add(**base, strike_area="Yes", activated="No")
        add(**base, strike_area="Yes", activated="Unclear")
        add(**base, strike_area="No", activated="No")
        add(**base, strike_area="Unclear", activated="Unclear")
    return out


def cell_key(c: dict) -> str:
    parts = ["kill" if c["is_kill"] else "other", f"usable={c['usable']}", f"target={c['target']}", c["interaction_level"], f"strike={c['strike_area']}",
             f"activated={c['activated']}", f"video={c['assessment']}"]
    parts += [f"first={'Y' if c['first'] else 'N'}", f"trigger={'Y' if c['trigger'] else 'N'}", f"kill={'Y' if c['kill'] else 'N'}"]
    parts += ["notes" if c["notes"] else "no-notes", "link" if c["link"] else "no-link"]
    return " | ".join(parts)


def build_fixture(app, is_kill: bool) -> dict:
    data = app.create_sample_data()
    idx = data["Windows"].index[data["Windows"]["Trap ID"] == "R1-MAN-001"][0]
    for k, v in {"Start Time": app.dtstr(T0), "End Time": app.dtstr(WINDOW_END), "Status": "Closed", "End Reason": "Scheduled line check and relure",
                 "Finding At Close": "Dead animal found" if is_kill else "Trap fired, no animal", "Bag ID": "MAN-007" if is_kill else "", "Review Status": "Open"}.items():
        data["Windows"].at[idx, k] = v
    window_id = data["Windows"].at[idx, "Window ID"]
    app.add_followup(data, "Camera review", "MAN", "R1-MAN-001", "VISIT-GOLDEN", window_id, "MAN-007" if is_kill else "", "Dead animal found" if is_kill else "Trap fired, no animal",
                     "Confirm target interaction, activation, kill and video evidence", "Normal")
    return data


def _copy(data):
    return {n: f.copy(deep=True) for n, f in data.items()}


def _inputs(c: dict) -> dict:
    return {
        "is_kill_review": c["is_kill"], "evidence_usable": c["usable"], "target": c["target"], "interaction_level": c["interaction_level"],
        "strike_area": c["strike_area"], "activated": c["activated"], "assessment": c["assessment"],
        "first_dt": FIRST if c["first"] else None, "trigger_dt": TRIGGER if c["trigger"] else None, "kill_dt": KILL if c["kill"] else None,
        "link": c["link"], "notes": c["notes"],
    }


def _setup(data):
    wid = data["Followups"].iloc[-1]["Window ID"]
    idxs = data["Windows"].index[data["Windows"]["Window ID"] == wid].tolist()
    item = data["Followups"].iloc[-1]
    return idxs, item, str(item["Follow-up ID"])


_INLINE = None


def run_inline(app, base, c):
    global _INLINE
    if _INLINE is None:
        _INLINE = compile(INLINE_BLOCK.read_text(encoding="utf-8"), str(INLINE_BLOCK), "exec")
    data = _copy(base)
    idxs, item, fid = _setup(data)
    ns = dict(vars(app)); ns.update(_inputs(c)); ns.update(data=data, idxs=idxs, item=item, fid=fid)
    exec(_INLINE, ns)
    return _collect(data, idxs[0], fid)


def run_extracted(app, base, c):
    data = _copy(base)
    idxs, item, fid = _setup(data)
    app.apply_camera_review(data, item, idx=idxs[0], **_inputs(c))
    return _collect(data, idxs[0], fid)


def _collect(data, idx, fid):
    w = data["Windows"].loc[idx]
    f = data["Followups"][data["Followups"]["Follow-up ID"] == fid].iloc[0]
    return {"window": [str(w[k]) for k in data["Windows"].columns], "followup": [str(f[k]) for k in data["Followups"].columns]}


def digest(o):
    return hashlib.sha1(json.dumps(o, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:12]


def compute(app, runner="extracted", keep_rows=None):
    run = {"inline": run_inline, "extracted": run_extracted}[runner]
    digests, rows = {}, {}
    with Pinned(app) as pin:
        pin.reset(0)
        bases = {True: build_fixture(app, True), False: build_fixture(app, False)}
        for c in cells():
            pin.reset()
            out = run(app, bases[c["is_kill"]], c)
            key = cell_key(c)
            assert key not in digests, key
            digests[key] = digest(out)
            if keep_rows and keep_rows(c):
                rows[key] = out
    return {"digests": digests, "rows": rows}
