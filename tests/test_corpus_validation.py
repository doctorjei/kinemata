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

import ast
import shutil
import subprocess
from collections import Counter
from pathlib import Path

import pytest

from kinemata import Entry, scan
from kinemata.baseline import record
from kinemata.contract import BaseRegistry
from kinemata.report import review

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


# -- the ratchet, against the same tree ---------------------------------------
#
# Unit tests pin the fingerprint's boundary with constructed findings. These ask
# the only question that matters for adoption: on a tree that is genuinely
# failing the gate, does recording it go quiet, and does the next real bypass
# still fire? A ratchet that answers no to either is worse than no ratchet.


@pytest.fixture
def scratch(pre_fix_tree, tmp_path):
    """A writable copy of the pre-fix tree; these tests edit the source."""
    target = tmp_path / "src"
    shutil.copytree(pre_fix_tree, target)
    return target


def accepted_findings(tree):
    """Gating findings, tagged with the registry, as the CLI would collect them."""
    report = review(Constants(), tree, strings_only=True)
    return [("constants", hit) for hit in report.strong]


def test_recording_silences_a_tree_that_is_genuinely_failing(scratch, tmp_path):
    """Adoption. This tree holds the nine sites ``42ece129`` names, so the gate
    is red before the baseline and has to be green after it."""
    findings = accepted_findings(scratch)
    assert len(findings) >= 9

    split = record(tmp_path / "b.json", findings).split(accepted_findings(scratch))
    assert not split.new
    assert not split.stale


def test_a_bypass_added_after_the_baseline_still_fires(scratch, tmp_path):
    """The half a baseline is capable of destroying."""
    base = record(tmp_path / "b.json", accepted_findings(scratch))
    (scratch / "kanibako" / "added_later.py").write_text('META = "workset.yaml"\n')

    split = base.split(accepted_findings(scratch))
    assert [hit.path for _, hit in split.new] == ["kanibako/added_later.py"]


def test_shifting_every_accepted_finding_down_its_file_changes_nothing(scratch, tmp_path):
    """Real churn on a real tree: 40 lines inserted at the top of every file
    holding an accepted finding. Line numbers all move; the gate stays quiet."""
    findings = accepted_findings(scratch)
    base = record(tmp_path / "b.json", findings)

    for path in {hit.path for _, hit in findings}:
        source = scratch / path
        source.write_text("\n" * 40 + source.read_text())

    split = base.split(accepted_findings(scratch))
    assert not split.new
    assert not split.stale


def test_moving_an_accepted_bypass_to_another_file_reports_it(scratch, tmp_path):
    """Scope, on real source. The site is not new to the tree, but it is new to
    that file -- and a bypass the baseline follows around the tree would
    reproduce the failure ``42ece129``'s own tripwire made."""
    findings = accepted_findings(scratch)
    base = record(tmp_path / "b.json", findings)

    per_file = Counter(hit.path for _, hit in findings)
    for _, hit in findings:
        if per_file[hit.path] != 1:
            continue
        lines = (scratch / hit.path).read_text().splitlines(keepends=True)
        moved = lines[hit.line - 1].strip()
        try:
            ast.parse(moved)          # it has to be a statement on its own
        except SyntaxError:
            continue
        del lines[hit.line - 1]
        (scratch / hit.path).write_text("".join(lines))
        (scratch / "kanibako" / "moved_here.py").write_text(moved + "\n")
        break
    else:
        pytest.skip("no single-line finding transplants cleanly")

    split = base.split(accepted_findings(scratch))
    assert [hit.path for _, hit in split.new] == ["kanibako/moved_here.py"]
    assert len(split.stale) == 1
