"""Validation against a real, documented duplication incident.

kanibako-cli commit ``42ece129`` -- "Give the tier filenames and box_data one
carrier each, and guard it" -- names its own eight sites in its message, plus a
ninth (``import_reconcile._STANDALONE_BOX_DIR``). That message is the ground
truth: a human/agent pair found those sites by hand and wrote down where they
were. This test asks whether the mechanism finds the same ones.

It reconstructs the tree at ``42ece129^`` -- the state *before* the fix -- so the
sites are present to be found. Skipped when the corpus is not cloned.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from registry import Entry, scan
from registry.contract import BaseRegistry

CORPUS = Path(__file__).resolve().parents[1] / "corpus" / "kanibako-cli"
COMMIT = "42ece129"

pytestmark = pytest.mark.skipif(
    not CORPUS.exists() or shutil.which("git") is None,
    reason="kanibako-cli corpus not cloned",
)

#: The sites commit 42ece129 names in its own message.
NAMED_SITES = {
    ("kanibako/project/names.py", 198),
    ("kanibako/project/names.py", 279),
    ("kanibako/launch/box_resolve.py", 84),
    ("kanibako/launch/box_resolve.py", 126),
    ("kanibako/commands/box/_lifecycle.py", 969),
    ("kanibako/commands/box/_lifecycle.py", 970),
    ("kanibako/commands/box/_lifecycle.py", 1210),
    ("kanibako/settings/settings_launch.py", 243),
    ("kanibako/project/import_reconcile.py", 53),
}

#: The constants that existed at the time, and the literal that bypasses each.
CONSTANTS = {
    "WORKSET_META_FILE": (r"workset\.yaml", "settings/config.py"),
    "BOX_META_FILE": (r"box\.yaml", "settings/config.py"),
    "AGENT_META_FILE": (r"agent\.yaml", "settings/config.py"),
    "STANDALONE_META_DIR": (r"box_data", "settings/paths_defaults.py"),
}


class Constants(BaseRegistry):
    name = "constants"

    def entries(self):
        for cid, (literal, home) in CONSTANTS.items():
            yield Entry(id=cid, antipatterns=(literal,), home=(home,))


@pytest.fixture(scope="module")
def pre_fix_tree(tmp_path_factory):
    """The source tree immediately before ``42ece129`` landed."""
    work = tmp_path_factory.mktemp("prefix")
    subprocess.run(
        ["git", "clone", "-q", "--no-checkout", "--shared", str(CORPUS), str(work / "t")],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(work / "t"), "checkout", "-q", f"{COMMIT}^"], check=True
    )
    return work / "t" / "src"


def test_finds_every_site_the_commit_names(pre_fix_tree):
    found = {(h.path, h.line) for h in scan(Constants(), pre_fix_tree, strings_only=True)}
    missed = NAMED_SITES - found
    assert not missed, f"failed to find documented bypasses: {sorted(missed)}"


def test_the_filters_are_what_make_it_usable(pre_fix_tree):
    """Precision, measured. Unfiltered output is unusable; filtered is not.

    Both flags are passed explicitly here. Left unset they resolve from the
    registry's own ``match_mode``, which is the right default everywhere except
    a test that exists to compare the modes.
    """
    raw = len(scan(Constants(), pre_fix_tree, code_only=False, strings_only=False))
    code = len(scan(Constants(), pre_fix_tree, code_only=True, strings_only=False))
    strings = len(scan(Constants(), pre_fix_tree, strings_only=True))

    assert raw > 100          # prose swamps the signal
    assert code < raw / 3     # dropping comments/docstrings is most of the win
    assert strings < code     # dropping identifiers is the rest
    assert strings < 25       # small enough for a human to read


def test_it_finds_a_bypass_the_manual_fix_missed(pre_fix_tree):
    """The mechanism's value over a careful human pass.

    ``targets/__init__.py`` spells ``"box_data"`` in a path expression while
    ``STANDALONE_META_DIR`` exists. 42ece129 did not fix it, and it is still
    present on ``main`` months later -- so this is not a stale finding.
    """
    found = {(h.path, h.line) for h in scan(Constants(), pre_fix_tree, strings_only=True)}
    assert ("kanibako/targets/__init__.py", 192) in found
    assert ("kanibako/targets/__init__.py", 192) not in NAMED_SITES

    still_there = (CORPUS / "src/kanibako/targets/__init__.py").read_text()
    assert '"box_data"' in still_there
