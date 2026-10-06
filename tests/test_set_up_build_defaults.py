"""QA brief F1: on Set up step 2 a trap's build control is never filled by a silent default.
The only allowed source is the trap's own stored build, and only when that build is one of the trial's declared
builds; otherwise nothing is selected (the needs-a-choice ring and the words "Choose a build")."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

from playwright.sync_api import Page, expect

sys.path.insert(0, str(Path(__file__).parent))
from journey_seed import JOURNEY_SEED  # noqa: E402
from test_trial_model_ui import _serve  # noqa: E402
from test_trial_screens import _open_set_up, _tick  # noqa: E402

DECLARED = ["R1 · R1 Build 4.3", "R1 · R1 Build 4.2"]

# New trap 1 is stored on Build 4.2 (declared); new trap 2 on Build 4.1 (not declared). The relocated KAI traps
# are stored on 4.2 and 4.1 the same way, so every group is covered.
STORED_BUILDS_SEED = JOURNEY_SEED.replace("    app.save_data(data)\n", """    def store(trap_id, build):
        data["Traps"].loc[data["Traps"]["Trap ID"] == trap_id, "Build Version"] = build
    store("R1-MAN-NEW1", "R1 Build 4.2"); store("R1-MAN-NEW2", "R1 Build 4.1")
    relocatable = [t for t in data["Traps"][(data["Traps"]["Status"] == "Inactive") & (data["Traps"]["Site ID"] != "MAN") & (data["Traps"]["Product"] == "R1")]["Trap ID"]]
    store(relocatable[0], "R1 Build 4.2"); store(relocatable[1], "R1 Build 4.1")
    app.save_data(data)
""")


def test_the_default_comes_from_the_traps_own_declared_build_and_never_from_the_first_option() -> None:
    script = f"""
        import json, app
        declared = {DECLARED!r}
        trap = lambda product, build: {{"Product": product, "Build Version": build}}
        print(json.dumps([
            app.set_up_default_build(trap("R1", "R1 Build 4.2"), declared),
            app.set_up_default_build(trap("R1", "R1 Build 4.1"), declared),
            app.set_up_default_build(trap("R1", ""), declared),
            app.set_up_default_build(trap("M1", "M1 Build 1.5"), declared),
            app.set_up_default_build(trap("R1", "R1 Build 4.2"), []),
        ]))
    """
    env = dict(os.environ, R1M1_ENVIRONMENT="local", R1M1_ALLOW_NO_AUTH="true", R1M1_SEED_MODE="clean", R1M1_DATA_DIR=tempfile.mkdtemp())
    result = subprocess.run([sys.executable, "-c", textwrap.dedent(script)], cwd=Path(__file__).resolve().parents[1], env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr[-2000:]
    stored_declared, stored_undeclared, no_build, other_product, nothing_declared = json.loads(result.stdout.strip().splitlines()[-1])
    assert stored_declared == "R1 · R1 Build 4.2", "a declared stored build is the default"
    assert stored_undeclared == "" and no_build == "" and other_product == "" and nothing_declared == "", "anything else gives no default"


def _selected(page: Page, trap_id: str) -> list[str]:
    """Labels of the segments selected in a trap's build control (empty = nothing chosen)."""
    return page.locator(f'[class*="st-key-seg_choosef_{trap_id}"] button[role="radio"][aria-checked="true"]').all_inner_texts()


def _build_control_trap_ids(page: Page) -> list[str]:
    return page.evaluate("""() => [...document.querySelectorAll('[class*="st-key-seg_choosef_"]')]
        .map(el => (el.className.match(/st-key-seg_choosef_(\\S+)/) || [])[1]).filter(Boolean)""")


def test_new_and_relocated_traps_show_their_own_declared_build_or_nothing(page: Page, tmp_path: Path) -> None:
    data_dir = tmp_path / "d"; data_dir.mkdir()
    with _serve(data_dir, STORED_BUILDS_SEED) as url:
        _open_set_up(page, url)
        _tick(page, "Build 4.2")
        page.get_by_role("button", name="Next: choose traps").click()
        expect(page.get_by_text("Set all unassigned to", exact=True)).to_be_visible(timeout=20_000)
        page.wait_for_timeout(800)

        # A new trap stored on 4.2 shows 4.2; a new trap stored on 4.1 (not declared) shows nothing.
        assert _selected(page, "R1-MAN-NEW1") == ["Build 4.2"]
        assert _selected(page, "R1-MAN-NEW2") == []
        # The line under each trap says where its pre-selection came from, and says when there is none.
        expect(page.get_by_text("New trap · added as Build 4.2", exact=True)).to_be_visible()
        expect(page.get_by_text("New trap · added as Build 4.1 — not in this trial", exact=True)).to_be_visible()
        # The same rule for the relocated traps (those that are not MAN's own).
        relocated = [t for t in _build_control_trap_ids(page) if "-MAN-" not in t]
        assert len(relocated) >= 2, relocated
        shown = {t: _selected(page, t) for t in relocated}
        assert ["Build 4.2"] in shown.values() and [] in shown.values(), shown
        assert all(len(v) <= 1 for v in shown.values()), shown

        # Submitting leaves the undeclared one undecided: it is named, and the trap on a declared build is not.
        page.get_by_role("button", name="Preview activation").click()
        message = page.get_by_text("need a build before you can continue", exact=False)
        expect(message).to_be_visible(timeout=20_000)
        assert "R1-MAN-NEW2" in message.inner_text()
        assert "R1-MAN-NEW1" not in message.inner_text(), "a trap on a declared build is not asked again"
