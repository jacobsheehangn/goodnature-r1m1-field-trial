"""The rows Save check writes, for the whole input matrix. Shared by the golden-record tests and the freeze script.

For each cell (outcome x carcass x service x camera x trap x the free fields) it builds the Checks, Windows and Follow-up rows that
Save check writes for those inputs, two ways:
  run_inline     exec's the record-building block exactly as it stood inline in the check page on main (20a454a), frozen verbatim in
                 golden/check_save_inline_block_main.txt;
  run_extracted  calls app.build_check_records(), the function the page calls now.
Both run against the same fixture with the clock and the ID generator pinned, so the rows compare byte for byte.

Import this inside a process that has already imported app (app.py routes pages at import time), as tests/journey_seed.py's seeds do.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path

GOLDEN_DIR = Path(__file__).parent / "golden"
INLINE_BLOCK = GOLDEN_DIR / "check_save_inline_block_main.txt"

PINNED_NOW = datetime(2026, 10, 5, 12, 0, 0)
VISIT_ID = "VISIT-GOLDEN"
PHOTO_CHECK_ID = "CHK-GOLDENDETERMINISTIC"
BAG_ID = "MAN-007"
NOTE = "Rain overnight"
REASON = "Bait gone"

FINDINGS = ["Trap still set, no animal", "Dead animal found", "Trap fired, no animal", "Trap disturbed", "Trap missing", "Unable to check"]
NOT_ASSESSABLE = ["Trap missing", "Unable to check"]
SPECIES_RAT = [("Rat", "Norway rat"), ("Rat", "Ship rat"), ("Rat", "Unclear"), ("Mouse", ""), ("Non-target", ""), ("Unknown", "")]
CONDITIONS = ["Dead and apparently normal", "Dead with obvious injury concern", "Alive and trapped", "Alive and maimed", "Unable to assess"]
CAMERA_ISSUES = ["Offline", "Battery low", "Poor view", "Blocked view", "Missing", "Unsure"]
COVERS = ["Yes", "No", "Unsure"]
PHOTO_COUNTS = [0, 1, 3]

# A trap profile is a real trap in the sample data: with or without a camera, at a site with an open trial or without one.
PROFILES = {
    "camera_trial": {"trap": "R1-MAN-001", "site": "MAN", "camera": True},
    "nocamera_trial": {"trap": "R1-MAN-002", "site": "MAN", "camera": False},
    "camera_untracked": {"trap": "R1-KAI-001", "site": "KAI", "camera": True},
    "nocamera_untracked": {"trap": "R1-KAI-002", "site": "KAI", "camera": False},
}
FULL_PRODUCT_PROFILES = ("camera_trial", "nocamera_trial")


# ---------------------------------------------------------------- the matrix
def _camera_answers(has_camera: bool):
    if not has_camera:
        return [("NA", "", "", False)]
    answers = [("Yes", "", "", False), ("Could not assess", "", "", False)]
    answers += [("No", issue, covers, adjusted) for issue in CAMERA_ISSUES for covers in COVERS for adjusted in (False, True)]
    return answers


def _details(has_animal: bool, collected: bool) -> list:
    """(species, rat type, condition, photo count) for a kill; one blank entry for a finding with no animal."""
    if not has_animal:
        return [("", "", "", 0)]
    return [(sp, rat, cond if collected else "", photos if collected else 0)
            for sp, rat in SPECIES_RAT
            for cond in (CONDITIONS if collected else [""])
            for photos in (PHOTO_COUNTS if collected else [0])]


def _cell(profile, finding, carcass, service, reason, camera, issue, covers, adjusted, notes, detail) -> dict:
    species, rat_type, condition, photos = detail
    return {
        "profile": profile, "finding": finding, "carcass": carcass, "service": service, "reason": reason,
        "camera": camera, "issue": issue, "covers": covers, "adjusted": adjusted, "notes": notes,
        "species": species, "rat_type": rat_type, "condition": condition, "photos": photos,
    }


def cells() -> list:
    """Every reachable input combination: only inputs that pass the page's own validation, so every cell is a Save that writes.

    The full product of trap profile x finding x carcass x service x camera answer (incl. every issue x covers x adjusted) x notes.
    The kill details (species, rat type, condition, photo count) change no branch and no other value, so they rotate through that
    product, and a second block takes their full product in a few fixed contexts: every value meets every other in the matrix."""
    out, seen, rotate = [], set(), 0

    def add(cell):
        key = cell_key(cell)
        if key not in seen:
            seen.add(key)
            out.append(cell)

    for profile, prof in PROFILES.items():
        for finding in FINDINGS:
            has_animal = finding == "Dead animal found"
            assessable = finding not in NOT_ASSESSABLE
            for carcass in (["Yes", "No"] if has_animal else [""]):
                details = _details(has_animal, carcass == "Yes")
                services = [("Yes", ""), ("No", REASON)] if assessable else [("NA", "")]
                for service, reason in services:
                    for camera, issue, covers, adjusted in _camera_answers(prof["camera"] and assessable):
                        for notes in ("", NOTE):
                            add(_cell(profile, finding, carcass, service, reason, camera, issue, covers, adjusted, notes, details[rotate % len(details)]))
                            rotate += 1
    for profile in FULL_PRODUCT_PROFILES:
        prof = PROFILES[profile]
        sweep_cameras = [("Yes", "", "", False), ("No", "Offline", "Yes", False)] if prof["camera"] else [("NA", "", "", False)]
        for carcass in ("Yes", "No"):
            for detail in _details(True, carcass == "Yes"):
                for service, reason in (("Yes", ""), ("No", REASON)):
                    for camera, issue, covers, adjusted in sweep_cameras:
                        for notes in ("", NOTE):
                            add(_cell(profile, "Dead animal found", carcass, service, reason, camera, issue, covers, adjusted, notes, detail))
    return out


def camera_issue_required_for(cell: dict) -> bool:
    """The rule a Camera issue task follows, applied to a cell's answers (an independent restatement, for the tests' negative controls)."""
    inp = inputs_for(cell)
    return bool(inp["camera_assigned"] and (inp["camera"] != "Working" or inp["covers"] != "Yes"))


def cell_key(cell: dict) -> str:
    parts = [
        cell["profile"], cell["finding"], f"carcass={cell['carcass'] or '-'}",
        f"service={cell['service']}", f"camera={cell['camera']}",
    ]
    if cell["camera"] == "No":
        parts.append(f"issue={cell['issue']}/covers={cell['covers']}/adjusted={'Y' if cell['adjusted'] else 'N'}")
    if cell["species"]:
        parts.append(f"{cell['species']}{'/' + cell['rat_type'] if cell['rat_type'] else ''}")
    if cell["condition"]:
        parts.append(f"condition={cell['condition']}")
    if cell["finding"] == "Dead animal found" and cell["carcass"] == "Yes":
        parts.append(f"photos={cell['photos']}")
    parts.append("notes" if cell["notes"] else "no-notes")
    return " | ".join(parts)


def is_representative(cell: dict) -> bool:
    """The readable subset stored with full rows: a handful of camera answers, no notes, every other dimension in full. Kill details
    are the plain ones (any species, the ordinary condition, no photos) plus photo counts 1 and 3 on the ordinary kill."""
    camera_ok = cell["camera"] in ("NA", "Yes", "Could not assess") or (cell["issue"], cell["covers"], cell["adjusted"]) in (("Offline", "Yes", False), ("Missing", "No", True))
    plain = cell["condition"] in ("", "Dead and apparently normal") and cell["photos"] == 0
    ordinary_kill = (cell["species"], cell["rat_type"], cell["condition"]) == ("Rat", "Norway rat", "Dead and apparently normal") and cell["photos"] in (1, 3)
    return camera_ok and (plain or ordinary_kill) and not cell["notes"]


def inputs_for(cell: dict) -> dict:
    """The local variables the check page holds at the moment it builds the record, derived from the form answers in the cell."""
    has_animal = cell["finding"] == "Dead animal found"
    collected_animal = has_animal and cell["carcass"] == "Yes"
    no_carcass = has_animal and cell["carcass"] == "No"
    assessable = cell["finding"] not in NOT_ASSESSABLE
    prof = PROFILES[cell["profile"]]
    camera_assigned = prof["camera"]
    camera, covers, adjusted, camera_ready = "No camera", "Not applicable", False, True
    if camera_assigned and assessable:
        if cell["camera"] == "Yes":
            camera, covers, camera_ready = "Working", "Yes", True
        elif cell["camera"] == "No":
            camera, covers, adjusted, camera_ready = cell["issue"], cell["covers"], cell["adjusted"], False
        else:
            camera, covers, camera_ready = "Unsure", "Unsure", False
    photo_gate = {"ready": True, "expected_count": 0, "file_count": 0, "row_count": 0, "photos": []}
    if collected_animal and cell["photos"]:
        photo_gate = {"ready": True, "expected_count": cell["photos"], "file_count": cell["photos"], "row_count": cell["photos"], "photos": [], "check_id": PHOTO_CHECK_ID}
    return {
        "trap_id": prof["trap"], "sid": prof["site"], "vid": VISIT_ID, "check_time": PINNED_NOW,
        "finding": cell["finding"], "collected_animal": collected_animal, "no_carcass": no_carcass, "assessable": assessable,
        "species": cell["species"] if has_animal else "", "rat_type": cell["rat_type"] if has_animal else "",
        "condition": (cell["condition"] if collected_animal else ("Unable to assess" if no_carcass else "")),
        "bag_id": BAG_ID if collected_animal else "", "bag_labelled": collected_animal,
        "service_ready": assessable and cell["service"] == "Yes",
        "service_reason": cell["reason"] if assessable and cell["service"] == "No" else "",
        "camera_assigned": camera_assigned, "camera": camera, "covers": covers, "adjusted": adjusted, "camera_ready": camera_ready,
        "notes": cell["notes"], "photo_gate": photo_gate,
    }


# ---------------------------------------------------------------- the two runners
class Pinned:
    """Pins app.now and app.make_id so the rows are reproducible: the same clock, and IDs numbered in sequence."""

    def __init__(self, app):
        self.app, self.counter = app, 0

    def reset(self, start: int = 1000):
        """Each cell numbers its IDs from 1000, so they never collide with the fixture's (numbered from 1)."""
        self.counter = start

    def __enter__(self):
        self._now, self._make_id = self.app.now, self.app.make_id
        self.app.now = lambda: PINNED_NOW

        def make_id(prefix):
            self.counter += 1
            return f"{prefix}-{self.counter:05d}"

        self.app.make_id = make_id
        return self

    def __exit__(self, *exc):
        self.app.now, self.app.make_id = self._now, self._make_id


def build_fixture(app) -> dict:
    """Sample workbook with an open trial at MAN. KAI has none, so a window opened there is left unstamped (T4)."""
    data = app.create_sample_data()
    app.create_trial(data, "MAN", ["R1 · R1 Build 4.3"], PINNED_NOW - timedelta(days=3))
    return data


TOUCHED_SHEETS = ("Checks", "Windows", "Followups")


def _copy(data: dict) -> dict:
    """Copies only the sheets the record writes to; every other sheet is shared, and checked untouched by identity and fingerprint."""
    return {name: (frame.copy(deep=True) if name in TOUCHED_SHEETS else frame) for name, frame in data.items()}


def _fingerprint(data: dict) -> str:
    return hashlib.sha1(json.dumps({n: _rows(f) for n, f in data.items() if n not in TOUCHED_SHEETS}, sort_keys=True).encode()).hexdigest()


def _rows(frame) -> list:
    return frame.fillna("").astype(str).values.tolist()


def _collect(base: dict, staged: dict, trap_id: str, ids) -> dict:
    base_other = base["Windows"][base["Windows"]["Trap ID"] != trap_id]
    staged_other = staged["Windows"][staged["Windows"]["Trap ID"] != trap_id]
    return {
        "ids": list(ids),
        "checks_new": _rows(staged["Checks"].iloc[len(base["Checks"]):]),
        "windows": _rows(staged["Windows"][staged["Windows"]["Trap ID"] == trap_id]),
        "followups_new": _rows(staged["Followups"].iloc[len(base["Followups"]):]),
        "other_windows_unchanged": bool(base_other.equals(staged_other)),
        "other_sheets_unchanged": all(staged[name] is base[name] for name in base if name not in TOUCHED_SHEETS),
    }


_INLINE_CODE = None


def _inline_code():
    global _INLINE_CODE
    if _INLINE_CODE is None:
        _INLINE_CODE = compile(INLINE_BLOCK.read_text(encoding="utf-8"), str(INLINE_BLOCK), "exec")
    return _INLINE_CODE


def build_extracted(app, base: dict, cell: dict, photo_gate=None):
    """Builds the record by calling the function the page calls. Returns (staged, (check_id, old window, new window))."""
    inp = inputs_for(cell)
    if photo_gate is not None:
        inp["photo_gate"] = photo_gate
    staged = _copy(base)
    expected_photo_count = int(inp["photo_gate"].get("expected_count", 0)) if inp["collected_animal"] else 0
    record = app.build_check_records(
        staged, visit_id=inp["vid"], site_id=inp["sid"], trap_id=inp["trap_id"], check_time=inp["check_time"], finding=inp["finding"],
        collected_animal=inp["collected_animal"], no_carcass=inp["no_carcass"], assessable=inp["assessable"],
        species=inp["species"], rat_type=inp["rat_type"], condition=inp["condition"], bag_id=inp["bag_id"], bag_labelled=inp["bag_labelled"],
        service_ready=inp["service_ready"], service_reason=inp["service_reason"],
        camera_assigned=inp["camera_assigned"], camera=inp["camera"], covers=inp["covers"], adjusted=inp["adjusted"], camera_ready=inp["camera_ready"],
        notes=inp["notes"], photo_check_id=inp["photo_gate"].get("check_id"), expected_photo_count=expected_photo_count,
    )
    return staged, (record["check_id"], record["old_window_id"], record["new_window_id"])


def build_inline(app, base: dict, cell: dict, photo_gate=None):
    """Builds the record by running the frozen inline block, with the page's local variables set from the cell."""
    inp = inputs_for(cell)
    if photo_gate is not None:
        inp["photo_gate"] = photo_gate
    staged = _copy(base)
    namespace = dict(vars(app))
    namespace.update(inp)
    namespace["staged"] = staged
    exec(_inline_code(), namespace)
    return staged, (namespace["check_id"], namespace["old_id"], namespace["new_id"])


BUILDERS = {"extracted": build_extracted, "inline": build_inline}


def run_extracted(app, pin: Pinned, base: dict, cell: dict) -> dict:
    pin.reset()
    staged, ids = build_extracted(app, base, cell)
    return _collect(base, staged, PROFILES[cell["profile"]]["trap"], ids)


def run_inline(app, pin: Pinned, base: dict, cell: dict) -> dict:
    pin.reset()
    staged, ids = build_inline(app, base, cell)
    return _collect(base, staged, PROFILES[cell["profile"]]["trap"], ids)


def digest(output: dict) -> str:
    return hashlib.sha1(json.dumps(output, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()[:12]


def compute(app, runner: str = "extracted", keep_rows_for=None) -> dict:
    """{cell key: digest} for the whole matrix, plus full outputs for the cells keep_rows_for(cell) accepts."""
    run = {"extracted": run_extracted, "inline": run_inline}[runner]
    digests, rows, flags_failed = {}, {}, []
    with Pinned(app) as pin:
        pin.reset(0)
        base = build_fixture(app)
        before = _fingerprint(base)
        for cell in cells():
            key = cell_key(cell)
            output = run(app, pin, base, cell)
            assert key not in digests, f"duplicate cell key: {key}"
            digests[key] = digest(output)
            if not (output["other_windows_unchanged"] and output["other_sheets_unchanged"]):
                flags_failed.append(key)
            if keep_rows_for and keep_rows_for(cell):
                rows[key] = output
        assert _fingerprint(base) == before, "a sheet the record must not touch was changed in place"
    return {"digests": digests, "rows": rows, "touched_something_else": flags_failed}


# ---------------------------------------------------------------- the photo chain
# The builder alone cannot show what happens to photos: they are finalised and written by commit_staged_records_with_photos, from the
# pending folder on disk. These cases run the whole chain (stage photos, build the record, commit, reload) in a throwaway data dir.
PHOTO_CASES = {
    "collected_0_photos": ("camera_trial", "Dead animal found", "Yes", 0),
    "collected_1_photo": ("camera_trial", "Dead animal found", "Yes", 1),
    "collected_3_photos": ("camera_trial", "Dead animal found", "Yes", 3),
    "collected_nocamera_1_photo": ("nocamera_trial", "Dead animal found", "Yes", 1),
    "collected_nocamera_3_photos": ("nocamera_trial", "Dead animal found", "Yes", 3),
    "staged_2_then_no_carcass": ("camera_trial", "Dead animal found", "No", 2),
    "staged_2_then_trap_fired": ("camera_trial", "Trap fired, no animal", "", 2),
}


def _staged_photo_payloads(count: int) -> list:
    import base64
    from io import BytesIO
    from PIL import Image
    payloads = []
    for i in range(count):
        buffer = BytesIO()
        Image.new("RGB", (64, 48), (40 + i * 30, 90, 140)).save(buffer, "JPEG", quality=80)
        raw = buffer.getvalue()
        payloads.append({
            "photo_id": f"PHOTO-GOLDEN-{i:04d}", "name": f"photo_{i}.jpg", "width": 64, "height": 48,
            "original_size": len(raw), "attempt": 1, "captured_time": f"2026-10-05T11:5{i}:00Z",
            "data_url": "data:image/jpeg;base64," + base64.b64encode(raw).decode("ascii"),
        })
    return payloads


def _files_under(root: Path, sub: str) -> list:
    base = root / sub
    return sorted(str(p.relative_to(root)) for p in base.rglob("*") if p.is_file()) if base.exists() else []


def run_photo_chain(app, pin: Pinned, case: str, runner: str = "extracted") -> dict:
    import shutil
    import photo_integrity as pi
    profile, finding, carcass, staged_count = PHOTO_CASES[case]
    root = Path(app.DATA_ROOT)
    for sub in (".pending_photos", "evidence"):
        shutil.rmtree(root / sub, ignore_errors=True)
    pin.reset(0)
    app.save_data(build_fixture(app))
    base = app.load_data()  # what the page works with: the workbook as read from disk
    prof = PROFILES[profile]
    trap_id, site_id = prof["trap"], prof["site"]
    has_animal, collected = finding == "Dead animal found", finding == "Dead animal found" and carcass == "Yes"
    window_id = str(app.open_window(base, trap_id)["Window ID"])
    context = {
        "check_id": pi.deterministic_check_id(VISIT_ID, trap_id), "visit_id": VISIT_ID, "trap_id": trap_id,
        "site_id": site_id, "bag_id": BAG_ID if collected else "", "window_id": window_id,
    }
    if staged_count and not collected:
        context["bag_id"] = BAG_ID  # photos staged while the kill was still a collected one, then the outcome changed
    for payload in _staged_photo_payloads(staged_count):
        pi.store_photo(root, context, payload, app.MAX_SAVED_PHOTO_BYTES)
    cell = _cell(
        profile, finding, carcass, "Yes" if finding not in NOT_ASSESSABLE else "NA", "",
        "Yes" if prof["camera"] and finding not in NOT_ASSESSABLE else "NA", "", "", False, "",
        ("Rat", "Norway rat", "Dead and apparently normal" if collected else "", staged_count if collected else 0) if has_animal else ("", "", "", 0),
    )
    gate = {"ready": True, "expected_count": 0, "file_count": 0, "row_count": 0, "photos": []}
    if collected:  # the page draws the uploader, and takes its gate from the pending manifest, only for a collected kill
        gate = {**app.verify_pending_photo_transaction(root, context, app.MAX_SAVED_PHOTO_BYTES), "context": context, "check_id": context["check_id"]}
    pin.reset()
    staged, ids = BUILDERS[runner](app, base, cell, photo_gate=gate)
    data = _all_copy(base)
    original = _all_copy(base)
    returned = app.commit_staged_records_with_photos(
        data=data, staged=staged, original_data=original, photo_gate=gate,
        expected_photo_count=int(gate.get("expected_count", 0)) if collected else 0,
        record_id=ids[0], photos_id_column="Check ID", verify_persisted=lambda reloaded: {},
        log_prefix="check", log_fields={}, record_noun="check", record_description="check, follow-up or photo record",
    )
    reloaded = app.load_data()
    return {
        "ids": list(ids), "photo_count_returned": int(returned),
        "checks_new": _rows(reloaded["Checks"].iloc[len(base["Checks"]):]),
        "windows": _rows(reloaded["Windows"][reloaded["Windows"]["Trap ID"] == trap_id]),
        "followups_new": _rows(reloaded["Followups"].iloc[len(base["Followups"]):]),
        "photos": _rows(reloaded["Photos"]),
        "final_files": _files_under(root, "evidence"),
        "pending_files_after": _files_under(root, ".pending_photos"),
    }


def _all_copy(data: dict) -> dict:
    return {name: frame.copy(deep=True) for name, frame in data.items()}


def compute_photo_chain(app, runner: str = "extracted") -> dict:
    out = {}
    with Pinned(app) as pin:
        for case in PHOTO_CASES:
            out[case] = run_photo_chain(app, pin, case, runner)
    return out
