"""Writes constraints.txt: every package the app needs at runtime, pinned to the version installed in the TESTED environment (the virtualenv the suite runs on).

    .venv/bin/python tools/make_constraints.py

The runtime set is found by walking the dependencies of requirements.txt (as `pip install -r requirements.txt` would, markers evaluated for this
environment), so test-only packages (pytest, Playwright, ...) are left out. To upgrade anything: change requirements.txt, rebuild a fresh virtualenv from it,
run the full suite and the release gate on that virtualenv, run this script, and commit both files together."""
from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]
HEADER = """# The runtime packages, pinned to the versions the full suite and the release gate run on (written by tools/make_constraints.py; do not edit by hand).
# requirements.txt includes this file (-c), so `pip install -r requirements.txt` installs exactly these and nothing newer.
# To upgrade: change requirements.txt, rebuild a fresh virtualenv, run the suite and the gate on it, run tools/make_constraints.py, commit both.
"""


def normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def requirement_names(path: Path) -> list:
    """The package names named in a requirements file (its -c / -r option lines and comments are skipped)."""
    names = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("-"):
            names.append(Requirement(line).name)
    return names


def runtime_closure(roots: list) -> dict:
    """{normalised name: installed version} for the roots and everything they need at runtime in this environment."""
    seen: dict = {}

    def walk(name: str) -> None:
        key = normalise(name)
        if key in seen:
            return
        try:
            dist = metadata.distribution(key)
        except metadata.PackageNotFoundError:
            raise SystemExit(f"{name} is needed at runtime but is not installed in this environment; build the environment from requirements.txt first")
        seen[key] = dist.version
        for text in dist.requires or []:
            req = Requirement(text)
            if req.marker is None or req.marker.evaluate({"extra": ""}):
                walk(req.name)

    for root in roots:
        walk(root)
    return seen


def build() -> str:
    """The text constraints.txt should have, for the packages installed in this environment."""
    closure = runtime_closure(requirement_names(ROOT / "requirements.txt"))
    return HEADER + "".join(f"{name}=={version}\n" for name, version in sorted(closure.items()))


def main() -> int:
    text = build()
    (ROOT / "constraints.txt").write_text(text)
    print(f"constraints.txt: {text.count('==')} packages")
    return 0


if __name__ == "__main__":
    sys.exit(main())
