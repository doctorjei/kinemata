"""What ``exclude`` removes: whole path segments, one reading, every check.

**The incident.** An adopter wrote ``exclude = ["tests/"]`` to skip their test
trees. It was matched as an unanchored substring, and the documentation checks
stripped its trailing slash first while the scans did not -- so it also removed
``docs/plans/2026-03-07-smoke-tests-design.md`` from ``claims`` and left it in
``check``: two documentation claims and one external link, lost silently, by one
line meaning two things.

**The rule since 2026-09-24** (user: *"a consistent, always-runs-the-same
solution - not a hack"*): a fragment names whole segments at any depth, a leading
slash anchors, and nothing is a substring. The cases below pin it from the
incident outward, and pin that every consumer reads it the same way.
"""

from __future__ import annotations

import pytest

from kinemata.exclusion import Removed, audit, excluded, matches

TREE = (
    "tests/test_thing.py",
    "tests/support/files.py",
    "packages/agent-claude/tests/test_credentials.py",
    "mytests/helper.py",
    "docs/plans/2026-03-07-smoke-tests-design.md",
    "docs/index.md",
    "api-docs/generated.md",
    "LICENSE.md",
    "vendor/lib/LICENSE.md",
    "src/kinemata/config.py",
)


def removed(*fragments):
    return [rel for rel in TREE if excluded(rel, fragments)]


# -- the rule -----------------------------------------------------------------


def test_the_adopter_s_loss_does_not_happen():
    """``tests/`` names the directory, never ``smoke-tests`` inside a name."""
    assert "docs/plans/2026-03-07-smoke-tests-design.md" not in removed("tests/")


def test_a_directory_is_removed_at_any_depth():
    """The case an anchored remedy once got wrong: plugin test trees below the root."""
    assert removed("tests/") == [
        "tests/test_thing.py",
        "tests/support/files.py",
        "packages/agent-claude/tests/test_credentials.py",
    ]


def test_a_name_is_never_matched_inside_another_name():
    assert not matches("mytests/helper.py", "tests/")
    assert not matches("api-docs/generated.md", "docs/")
    assert not matches("docs/plans/2026-03-07-smoke-tests-design.md", "tests")


def test_a_trailing_slash_changes_nothing():
    """One reading. The old split was a slash stripped on one side only."""
    assert removed("tests/") == removed("tests")
    assert removed("docs/") == removed("docs")


def test_a_file_name_is_removed_wherever_it_is():
    assert removed("LICENSE.md") == ["LICENSE.md", "vendor/lib/LICENSE.md"]


def test_a_multi_segment_fragment_needs_every_segment_in_order():
    assert matches("packages/agent-claude/tests/x.py", "agent-claude/tests")
    assert not matches("packages/agent-claude/tests/x.py", "claude/tests")
    assert not matches("tests/agent-claude/x.py", "agent-claude/tests")


# -- the anchored spelling ---------------------------------------------------


def test_a_leading_slash_anchors_at_the_root():
    assert removed("/tests/") == ["tests/test_thing.py", "tests/support/files.py"]
    assert removed("/LICENSE.md") == ["LICENSE.md"]


def test_an_anchored_fragment_matches_the_path_itself():
    assert matches("docs", "/docs")
    assert matches("docs/index.md", "/docs")


def test_an_anchored_fragment_does_not_match_a_sibling_prefix():
    """`/docs` must not take `docs-old/`, which a `startswith` alone would."""
    assert not matches("docs-old/index.md", "/docs")


@pytest.mark.parametrize("fragment", ["", "/", "//"])
def test_a_fragment_with_no_segments_removes_nothing(fragment):
    """An empty stem would otherwise match every path in the tree."""
    assert not matches("docs/index.md", fragment)


def test_the_scoping_case_the_adopter_abandoned():
    """"Scan only this directory" as *exclude everything else* works."""
    kept = [rel for rel in TREE if not excluded(rel, ("/docs/",))]
    assert "api-docs/generated.md" in kept
    assert "docs/index.md" not in kept


# -- every consumer reads it the same way -------------------------------------


def test_claims_and_check_agree_on_what_tests_slash_removes(tmp_path):
    """The split itself, end to end: one design doc, both commands reading it.

    Before, ``claims`` skipped the document and ``check`` read it. The document
    makes one false path claim, so ``claims`` now reports it -- which is the
    claim the adopter lost.
    """
    from kinemata.cli import main

    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_x.py").write_text("X = 1\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "smoke-tests-design.md").write_text(
        "The runner lives in `src/runner.py`.\n"
    )
    (tmp_path / "kinemata.toml").write_text(
        '[project]\nroot = "."\nexclude = ["tests/"]\n\n[claims]\n'
    )
    assert main(["claims", "--config", str(tmp_path / "kinemata.toml")]) == 1


# -- the audit ---------------------------------------------------------------


def test_a_fragment_that_removed_nothing_is_reported():
    report = audit(TREE, ("deliverables/",))
    assert report.inert and report.inert[0].fragment == "deliverables/"
    assert "removed 0 files" in report.lines()[0]


def test_a_fragment_written_for_part_of_a_name_is_reported_as_removing_nothing():
    """What a config relying on the old substring reading sees: never silence."""
    report = audit(TREE, ("egg-info", "smoke-tests"))
    assert [item.fragment for item in report.inert] == ["egg-info", "smoke-tests"]
    assert all("never part of a name" in line for line in report.lines())


def test_a_clean_run_says_nothing():
    """A report that speaks when nothing is wrong is one readers learn to skip."""
    assert audit(TREE, ("/docs/", "tests/")).lines() == ()


def test_a_pruned_directory_is_not_called_inert():
    """`.venv/` removes nothing because the walk never descends into it.

    Reporting that as "nothing matches it" is false in the way that matters --
    the directory is there. Measured on this repository's own config, where the
    first draft of the report said exactly that.
    """
    report = audit(TREE, (".venv/",), pruned=(".venv", "__pycache__"))
    assert report.removed == ()
    assert report.lines() == ()


def test_removed_reports_its_own_shape():
    item = Removed(fragment="/x/", paths=("x/a",))
    assert item.anchored and not item.inert
