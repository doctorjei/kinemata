"""The version floor: a declared fact, checked against the source that claims it.

`requires-python` is a promise to everyone who installs this. It was asserted and
never exercised -- CI pinned one interpreter, and the box it was written on had
no other -- so the floor was true by inspection and nothing more. kanibako asked
whether it held before adopting, because their gate interpreter is the floor by
deliberate choice, and the honest answer at the time was "probably".

This settles the syntax half locally, at any interpreter. The library half needs
a real 3.11 and lives in the CI matrix; see `test_the_floor_is_exercised_in_ci`.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCES = sorted((ROOT / "src").rglob("*.py"))


def declared_floor() -> tuple[int, int]:
    """The floor, read from the one place that declares it.

    Restating "3.11" in this file would make the test pass while the package
    promised something else -- the exact re-derivation this project reports in
    other people's code.
    """
    spec = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["requires-python"]
    match = re.fullmatch(r">=\s*(\d+)\.(\d+)", spec.strip())
    if not match:
        raise AssertionError(
            f"cannot read a floor from requires-python = {spec!r}. Teach this test the "
            "new spelling rather than letting it pass on a spec it does not understand."
        )
    return int(match[1]), int(match[2])


def test_every_source_file_parses_at_the_declared_floor():
    floor = declared_floor()
    assert SOURCES, "no sources found; this test would pass by scanning nothing"

    broken = []
    for path in SOURCES:
        try:
            ast.parse(path.read_text(), filename=str(path), feature_version=floor)
        except SyntaxError as exc:
            broken.append(f"{path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")

    assert not broken, (
        f"source uses syntax newer than the declared floor {floor[0]}.{floor[1]}:\n  "
        + "\n  ".join(broken)
    )


def test_the_floor_check_can_actually_fail():
    """Mutation check: without this, the test above passes on an inert parser.

    `feature_version` is silently ignored for some constructs, so a check built
    on it can look like it is enforcing a floor while enforcing nothing. This
    pins a construct it does reject, and will start failing if the floor ever
    rises past 3.12 -- at which point the control needs a newer construct, which
    is the correct thing to be told.
    """
    floor = declared_floor()
    if floor >= (3, 12):
        pytest.skip("positive control is a 3.12 construct; the floor has passed it")

    newer = "type Alias = int\n"          # PEP 695, 3.12+
    with pytest.raises(SyntaxError):
        ast.parse(newer, feature_version=floor)

    # ...and is fine one version up -- but only where the *running* interpreter
    # can parse it at all. `feature_version` makes the parser stricter, never
    # newer, so on 3.11 this line raises whatever is passed to it, and the
    # control fails for the one reason it is not testing.
    #
    # ⚠ **This is why the floor job was red from the day it was added.** The
    # matrix went in on 2026-09-09 to catch a 3.12-only stdlib call, and instead
    # failed here on every run for four days -- so the signal it exists to give
    # was never once delivered. A check that has been red since it landed is not
    # a check, and this file is where that was finally read.
    if sys.version_info >= (3, 12):
        ast.parse(newer, feature_version=(3, 12))


def test_the_floor_is_exercised_in_ci():
    """The syntax check above cannot see a 3.12-only stdlib call.

    `itertools.batched`, `Path.walk`, `typing.override` all parse cleanly at 3.11
    and fail at run time. Only running the suite on the floor catches those, so
    the workflow has to name it -- and a matrix that quietly drops the floor
    would leave this file asserting something nothing performs.

    ⚠ **Skips when the workflow is absent**, which is the case inside a source
    distribution: ``MANIFEST.in`` prunes ``.github``, because CI configuration is
    not part of what a consumer builds. Found by building an sdist and running
    the tests it ships -- this was the one failure, and the package had been
    sending a test somewhere it could not pass. Same convention as the corpus
    skips.
    """
    floor = declared_floor()
    checks = ROOT / ".github/workflows/checks.yml"
    if not checks.is_file():
        pytest.skip("no workflow here -- a source distribution prunes .github")
    workflow = checks.read_text()
    spelled = f'"{floor[0]}.{floor[1]}"'
    assert spelled in workflow, (
        f"{spelled} does not appear in checks.yml, so the declared floor is never run. "
        "Add it to the test matrix or lower the claim in pyproject.toml."
    )
