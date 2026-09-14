"""What ``exclude`` removes, and whether it removed what its author named.

**The incident.** An adopter wrote ``exclude = ["tests/"]`` to skip their test
trees. The fragment is matched as an unanchored substring after its trailing
slash is stripped, so it also removed
``docs/plans/2026-03-07-smoke-tests-design.md`` and a sibling -- two
documentation claims and one external link, silently. The general shape is worse
than the loss: a project cannot say *this directory* as distinct from *this
substring*, so a denylist cannot be used for scoping at all. ``exclude =
["docs/"]`` would also remove ``api-docs/``, the tree such a config would exist
to cover.

Two answers here, and deliberately not a third. The anchored spelling is **new**
rather than a repair of the old one: redefining a trailing slash would silently
change what every config already written removes, which is the class of defect
being fixed. And the audit reports what a fragment did, so a project that keeps
the spelling it has still finds out.
"""

from __future__ import annotations

import pytest

from kinemata.exclusion import (
    Removed,
    anchored_form,
    anchors,
    audit,
    excluded,
    matches,
)

TREE = (
    "tests/test_thing.py",
    "tests/support/files.py",
    "docs/plans/2026-03-07-smoke-tests-design.md",
    "docs/index.md",
    "api-docs/generated.md",
    "src/kinemata/config.py",
)


# -- the substring rule, unchanged -------------------------------------------


def test_a_bare_fragment_still_matches_anywhere(tmp_path):
    """The historical behavior, pinned so the anchored form cannot alter it."""
    assert matches("docs/plans/2026-03-07-smoke-tests-design.md", "tests")
    assert matches("api-docs/generated.md", "docs/")
    assert excluded("tests/test_thing.py", ("tests",))


def test_the_adopter_s_loss_is_reproduced(tmp_path):
    """Named because a regression here is a silent one."""
    removed = [rel for rel in TREE if excluded(rel, ("tests",))]
    assert "docs/plans/2026-03-07-smoke-tests-design.md" in removed


# -- the anchored spelling ---------------------------------------------------


def test_a_leading_slash_anchors_at_the_root():
    assert matches("docs/index.md", "/docs/")
    assert not matches("api-docs/generated.md", "/docs/")


def test_an_anchored_fragment_matches_the_path_itself():
    assert matches("docs", "/docs")
    assert matches("docs/index.md", "/docs")


def test_an_anchored_fragment_does_not_match_a_sibling_prefix():
    """`/docs` must not take `docs-old/`, which a `startswith` alone would."""
    assert not matches("docs-old/index.md", "/docs")


def test_a_bare_slash_removes_nothing():
    """An empty stem would otherwise match every path in the tree."""
    assert not matches("docs/index.md", "/")
    assert not matches("docs/index.md", "//")


def test_the_scoping_case_the_adopter_abandoned():
    """"Scan only this directory" as *exclude everything else* now works."""
    kept = [rel for rel in TREE if not excluded(rel, ("/docs/",))]
    assert "api-docs/generated.md" in kept
    assert "docs/index.md" not in kept


# -- the audit ---------------------------------------------------------------


def test_a_fragment_that_removed_nothing_is_reported():
    report = audit(TREE, ("deliverables/",))
    assert report.inert and report.inert[0].fragment == "deliverables/"
    assert "removed 0 files" in report.lines()[0]


def test_a_substring_only_removal_is_reported_with_the_fix():
    """Matched inside a name, where anchoring IS the right advice."""
    report = audit(TREE, ("tests/",))
    assert report.incidental
    line = report.lines()[0]
    assert "inside a name rather than a directory" in line
    assert "docs/plans/2026-03-07-smoke-tests-design.md" in line
    assert "'/tests/'" in line


#: The adopter's tree, reduced to the shape that made the old remedy false: a
#: fragment naming real directories that are not at the root.
DEEP = (
    "tests/test_core.py",
    "docs/plans/2026-03-07-smoke-tests-design.md",
    "packages/agent-claude/tests/test_credentials.py",
    "packages/agent-codex/tests/test_auth.py",
)


def test_a_directory_below_the_root_is_not_told_to_anchor_at_the_root():
    """🛑 The reported defect: the remedy reached none of the paths beside it.

    An adopter was told to write ``/tests/`` for paths three directories down.
    Anchoring is root-relative, so taking it would have stopped excluding three
    plugin test trees while ``check`` went on exiting 0. They reproduced it
    against this module and did not take the advice.
    """
    line = next(
        line for line in audit(DEEP, ("tests/",)).lines()
        if "below the root" in line
    )
    assert "packages/agent-claude/tests/test_credentials.py" in line
    assert "ROOT-relative" in line
    assert "'/packages/agent-claude/tests/'" in line
    assert "'/packages/agent-codex/tests/'" in line


def test_the_suggested_spelling_actually_removes_the_paths_it_is_printed_beside():
    """The property the old message violated, asserted directly.

    Deriving the advice from the fragment is what produced advice that matched
    nothing it listed; this is the test that would have caught it.
    """
    for item in audit(DEEP, ("tests/",)).incidental:
        for form in item.anchored_forms:
            assert any(matches(rel, form) for rel in item.deeper), form
        for rel in item.deeper:
            assert any(matches(rel, form) for form in item.anchored_forms), rel


def test_the_two_kinds_of_incidental_match_are_told_apart():
    """One is probably meant and one probably is not; they got one remedy."""
    item = audit(DEEP, ("tests/",)).incidental[0]
    assert item.within_a_name == ("docs/plans/2026-03-07-smoke-tests-design.md",)
    assert item.deeper == (
        "packages/agent-claude/tests/test_credentials.py",
        "packages/agent-codex/tests/test_auth.py",
    )


def test_a_fragment_is_matched_segment_wise_when_deriving_a_spelling():
    """``tests`` names the directory and never ``smoke-tests``."""
    assert anchored_form("packages/x/tests/a.py", "tests/") == "/packages/x/tests/"
    assert anchored_form("docs/smoke-tests-design.md", "tests/") == ""
    assert anchored_form("a/b/c.py", "") == ""


def test_a_multi_segment_fragment_derives_its_whole_path():
    assert anchored_form(
        "packages/agent-claude/tests/support/x.py", "agent-claude/tests"
    ) == "/packages/agent-claude/tests/"


def test_a_fragment_matching_only_part_of_a_segment_has_no_anchored_form():
    """And so is told the other thing, correctly.

    ``claude/tests`` removes :shown:`packages/agent-claude/tests/x.py` as a
    substring of ``agent-claude``, and no anchored spelling reaches it --
    ``/claude/tests/`` needs a literal ``claude`` segment. Reporting an
    anchored form here would be the original defect in a new place.
    """
    assert anchored_form("packages/agent-claude/tests/x.py", "claude/tests") == ""


def test_a_clean_run_says_nothing():
    """A report that speaks when nothing is wrong is one readers learn to skip."""
    assert audit(TREE, ("/docs/", "/tests/")).lines() == ()


def test_a_pruned_directory_is_not_called_inert():
    """`.venv/` removes nothing because the walk never descends into it.

    Reporting that as "nothing matches it" is false in the way that matters --
    the directory is there. Measured on this repository's own config, where the
    first draft of the report said exactly that.
    """
    report = audit(TREE, (".venv/",), pruned=(".venv", "__pycache__"))
    assert report.removed == ()
    assert report.lines() == ()


def test_an_over_broad_match_nothing_else_would_keep_is_not_reported():
    """`tests/` took 511 paths on this repository and `corpus/` had them all.

    An over-broad fragment that changes no outcome is noise. Only the paths no
    other fragment removes are worth a line.
    """
    report = audit(TREE, ("tests/", "docs/"))
    item = next(one for one in report.removed if one.fragment == "tests/")
    assert not item.incidental


def test_an_anchored_fragment_is_never_called_incidental():
    report = audit(TREE, ("/tests/",))
    assert not report.incidental
    assert report.lines() == ()


@pytest.mark.parametrize(
    "rel, fragment, expected",
    [
        ("tests/a.py", "tests", True),
        ("docs/smoke-tests-design.md", "tests", False),
        ("tests", "tests", True),
    ],
)
def test_anchors_is_the_discriminator_the_report_uses(rel, fragment, expected):
    assert anchors(rel, fragment) is expected


def test_removed_reports_its_own_shape():
    item = Removed(fragment="/x/", paths=("x/a",))
    assert item.anchored and not item.inert
