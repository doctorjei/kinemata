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

from kinemata.exclusion import Removed, anchors, audit, excluded, matches

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
    report = audit(TREE, ("tests/",))
    assert report.incidental
    line = report.lines()[0]
    assert "by substring rather than by directory" in line
    assert "docs/plans/2026-03-07-smoke-tests-design.md" in line
    assert "'/tests/'" in line


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
