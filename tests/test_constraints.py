"""The dependency constraints (20 Oct 2026): a fresh Render build must install the versions the suite ran on.

Until then only Streamlit (and, after the sign-in logo and the fonts came back HTTP 500, Starlette) was pinned; the other 40 runtime packages were whatever was
newest at build time, 17 of them already newer than the tested environment. `constraints.txt` pins all of them, `requirements.txt` includes it (-c), and these
tests fail if the tested environment, the file and the requirements ever disagree."""
from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import make_constraints as mc  # noqa: E402


def pins(path: Path) -> dict:
    found = {}
    for line in path.read_text().splitlines():
        match = re.match(r"^\s*([A-Za-z0-9_.-]+)==([^\s#]+)", line)
        if match:
            assert mc.normalise(match.group(1)) not in found, f"{match.group(1)} is pinned twice in {path.name}"
            found[mc.normalise(match.group(1))] = match.group(2)
    return found


def test_the_constraints_file_is_exact_pins_only() -> None:
    for line in (ROOT / "constraints.txt").read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            assert re.fullmatch(r"[a-z0-9-]+==[A-Za-z0-9.!+_-]+", line.strip()), f"not an exact pin: {line!r}"
    assert len(pins(ROOT / "constraints.txt")) >= 40


def test_the_tested_environment_is_the_locked_one() -> None:
    wrong = {name: (version, metadata.version(name)) for name, version in pins(ROOT / "constraints.txt").items() if metadata.version(name) != version}
    assert not wrong, f"installed here but pinned differently (pinned, installed): {wrong}"


def test_every_runtime_package_is_pinned_and_no_pin_is_stale() -> None:
    closure = mc.runtime_closure(mc.requirement_names(ROOT / "requirements.txt"))
    pinned = pins(ROOT / "constraints.txt")
    assert set(closure) - set(pinned) == set(), f"needed at runtime but not pinned: {sorted(set(closure) - set(pinned))}"
    assert set(pinned) - set(closure) == set(), f"pinned but no longer needed: {sorted(set(pinned) - set(closure))}"


def test_the_committed_file_is_what_the_generator_writes() -> None:
    assert (ROOT / "constraints.txt").read_text() == mc.build(), "constraints.txt was edited by hand or is out of date: run tools/make_constraints.py"


def test_requirements_include_the_constraints_and_agree_with_them() -> None:
    text = (ROOT / "requirements.txt").read_text()
    assert re.search(r"^-c constraints\.txt\s*$", text, re.M), "requirements.txt must include -c constraints.txt, so any pip install of it honours the pins"
    constrained = pins(ROOT / "constraints.txt")
    for name, version in pins(ROOT / "requirements.txt").items():
        assert constrained.get(name) == version, f"{name}=={version} in requirements.txt but {constrained.get(name)} in constraints.txt"


def test_the_render_build_installs_requirements_txt() -> None:
    render = (ROOT / "render.yaml").read_text()
    assert re.search(r"buildCommand:\s*pip install -r requirements\.txt", render), "Render must install requirements.txt (which includes the constraints)"
