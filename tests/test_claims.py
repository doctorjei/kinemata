"""Documentation claims, and the two ways a checker of prose goes wrong.

Over-reporting kills adoption; under-reporting kills the check while it still
says "clean". Both happened to the prototype this replaces, so both have tests.
"""

from __future__ import annotations

import subprocess
import textwrap
from datetime import date

from kinemata.claims import CLAIM_KINDS, Promise, verify


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


#: A promise with room left on it, for tests about something other than dates.
LATER = Promise(path="out/report.json", until=date(2027, 1, 1))


def broken(result):
    return {(claim.kind, claim.text) for claim in result.broken}


# -- the claims themselves ---------------------------------------------------


def test_a_path_that_does_not_exist_is_reported(tmp_path):
    write(tmp_path, "doc.md", "See `src/app.py` and `src/gone.py`.\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    assert broken(verify(tmp_path)) == {("path", "src/gone.py")}


def test_a_path_anchored_differently_still_resolves(tmp_path):
    """Documents anchor honestly in more than one way.

    A checker that demands one spelling reports correct prose, which is the
    fastest way to be ignored.
    """
    write(tmp_path, "src/pkgname/cli.py", "x = 1\n")
    write(tmp_path, "doc.md", "`src/pkgname/cli.py`, `pkgname/cli.py`, `cli.py`\n")
    assert verify(tmp_path).broken == []


def test_a_directory_resolves(tmp_path):
    write(tmp_path, "docs/thing.md", "x\n")
    write(tmp_path, "doc.md", "Everything lives in `docs/`.\n")
    assert verify(tmp_path).broken == []


def test_a_dead_relative_link_is_reported(tmp_path):
    write(tmp_path, "doc.md", "[here](./real.md) and [gone](./missing.md)\n")
    write(tmp_path, "real.md", "x\n")
    assert broken(verify(tmp_path)) == {("link", "./missing.md")}


def test_an_external_link_is_not_ours_to_falsify(tmp_path):
    write(tmp_path, "doc.md", "[spec](https://example.org/a.md) and [anchor](#section)\n")
    assert verify(tmp_path).broken == []


# -- over-reporting: what is discussed rather than asserted ------------------


def test_a_negated_path_is_discussed_not_claimed(tmp_path):
    write(tmp_path, "doc.md", "There is no `src/ssh_key.py` in this tree.\n")
    assert verify(tmp_path).broken == []


def test_negation_does_not_disable_the_rest_of_the_line(tmp_path):
    """The under-reporting bug, which is the dangerous direction.

    An earlier version skipped any line containing a negation word, so a line
    that also made a real claim went unchecked and the tool reported clean
    while checking less than it said.
    """
    write(
        tmp_path,
        "doc.md",
        "There is no `src/ssh_key.py`, but the loader is `src/really_gone.py`.\n",
    )
    assert broken(verify(tmp_path)) == {("path", "src/really_gone.py")}


def test_a_placeholder_is_teaching_a_shape(tmp_path):
    write(tmp_path, "doc.md", "Point it at `src/pkg/constants.py` in your project.\n")
    assert verify(tmp_path).broken == []


def test_a_glob_is_not_a_file(tmp_path):
    write(tmp_path, "doc.md", "Scans `src/**` and `tests/**`.\n")
    assert verify(tmp_path).broken == []


def test_code_in_backticks_is_not_a_path(tmp_path):
    write(tmp_path, "doc.md", "Call `entries()`; set `closed`; read `config.data`.\n")
    result = verify(tmp_path)
    assert result.broken == []
    assert result.checked == 0


def test_a_superseded_record_is_not_stale(tmp_path):
    """An archive cites what was true when it was written."""
    write(tmp_path, "archives/old.md", "The loader is `src/removed.py`.\n")
    assert verify(tmp_path, historical=["archives/"]).broken == []
    assert broken(verify(tmp_path)) == {("path", "src/removed.py")}


# -- commits, and refusing to check silently ---------------------------------


def test_a_commit_that_is_not_in_the_tree_is_reported(tmp_path):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.email", "t@example.org"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    write(tmp_path, "a.txt", "x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "first"], check=True)
    real = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--short=8", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    write(tmp_path, "doc.md", f"Real `{real}`, dead `deadbee1`.\n")
    assert broken(verify(tmp_path)) == {("commit", "deadbee1")}


def test_an_uncheckable_kind_is_named_not_dropped(tmp_path):
    """A checker that quietly stops checking is worse than no checker."""
    write(tmp_path, "doc.md", "Commit `abc1234` did it.\n")
    result = verify(tmp_path)  # not a git repository
    assert result.broken == []
    assert result.unavailable == ["commit hashes (not a git repository)"]


def test_a_path_names_a_sibling_tree_and_still_resolves(tmp_path):
    """Notes beside a repository describe it, and call it by name."""
    (tmp_path / "notes").mkdir()
    write(tmp_path, "loader/src/app.py", "x = 1\n")
    write(tmp_path, "notes/doc.md", "The loader is `loader/src/app.py`.\n")
    assert verify(tmp_path / "notes").broken  # nothing to resolve against
    assert verify(tmp_path / "notes", resolve_in=["../loader"]).broken == []


def test_negation_may_follow_the_claim(tmp_path):
    write(tmp_path, "doc.md", "The file `src/old.py` is gone.\n")
    assert verify(tmp_path).broken == []


def test_a_claim_does_not_negate_itself(tmp_path):
    """The lookahead starts after the claim.

    Starting at it let `src/gone.py` match "gone" against its own text and
    report itself exempt -- an exemption the check hands out to exactly the
    paths most likely to be dead.
    """
    write(tmp_path, "doc.md", "The loader is `src/gone.py` today.\n")
    assert broken(verify(tmp_path)) == {("path", "src/gone.py")}


def test_a_count_is_settled_by_the_command_that_knows(tmp_path):
    from kinemata.claims import Counted

    write(tmp_path, "doc.md", "The suite has **4 tests**.\n")
    spec = Counted(
        pattern=r"\*\*(\d+) tests\*\*",
        command=("{python}", "-c", "print('7 tests collected')"),
        extract=r"(\d+) tests collected",
        label="test count",
    )
    result = verify(tmp_path, counts=[spec])
    assert [claim.kind for claim in result.broken] == ["test count"]
    assert "actually 7" in result.broken[0].text


def test_a_declared_oracle_that_cannot_run_is_a_failure(tmp_path):
    """Not a note. In CI, "printed a warning and exited 0" is a pass."""
    from kinemata.claims import Counted

    write(tmp_path, "doc.md", "The suite has **4 tests**.\n")
    spec = Counted(
        pattern=r"\*\*(\d+) tests\*\*",
        command=("definitely-not-a-command-here",),
        extract=r"(\d+)",
    )
    result = verify(tmp_path, counts=[spec])
    assert result.broken == []
    assert result.blocked and result.failed


def test_a_count_pattern_may_use_alternation(tmp_path):
    """The first *matching* group, not group 1.

    "103 tests pass" and "**103 tests**" are one claim written two ways, and
    reading group 1 blindly crashes on the second phrasing.
    """
    from kinemata.claims import Counted

    write(tmp_path, "doc.md", "The suite has 7 tests pass here.\n")
    spec = Counted(
        pattern=r"\*\*(\d+) tests\*\*|\b(\d+) tests pass\b",
        command=("{python}", "-c", "print('7 tests collected')"),
        extract=r"(\d+) tests collected",
    )
    assert verify(tmp_path, counts=[spec]).broken == []


def test_kinds_are_a_table_not_a_hardcoded_sequence():
    """Adding a kind is a row, and the loop never learns their names."""
    assert {kind.name for kind in CLAIM_KINDS} == {"path", "link", "commit"}
    (commit,) = [kind for kind in CLAIM_KINDS if kind.needs_git]
    assert commit.when_unavailable


def test_a_document_behind_a_symlink_is_read(tmp_path):
    """The silent half of the walk defect, and the one that matters here.

    ``_walk`` skipped a symlinked directory entirely, so documents living
    behind one were never read and every claim in them passed by not being
    looked at. A checker reporting "all resolve" about files it never opened is
    the inert signal this project exists to catch.
    """
    write(tmp_path, "real/doc.md", "See `src/gone.py`.\n")
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "linked").symlink_to(tmp_path / "real")

    assert broken(verify(tmp_path / "tree")) == {("path", "src/gone.py")}


def test_a_path_behind_a_symlink_resolves_however_it_is_anchored(tmp_path):
    """The index has the same defect with the opposite symptom: loud.

    A path claim is checked against the filesystem first, so a root-anchored
    one resolved anyway. One anchored from inside -- the ordinary way to cite a
    module -- falls through to the index, which was built on ``rglob`` and so
    did not contain anything behind a link. Correct prose, reported dead.
    """
    write(tmp_path, "real/internal/handler.py", "x = 1\n")
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "linked").symlink_to(tmp_path / "real")
    write(tmp_path, "tree/doc.md", "See `internal/handler.py`.\n")

    result = verify(tmp_path / "tree")
    assert result.checked == 1  # a claim nobody extracted proves nothing
    assert result.broken == []


# -- promises: a design describes what does not exist yet ---------------------


def test_a_promised_path_is_held_open_rather_than_reported(tmp_path):
    """A design document is a registry of claims about work not yet done.

    Without this, gating one leaves two bad options: a permanently red gate,
    which teaches its reader to skim, or a stub that satisfies the check by
    letter. Measured on a real design set at 6 failures in 52 claims, every one
    of that class.
    """
    write(tmp_path, "design.md", "It writes `out/report.json` when it runs.\n")
    assert broken(verify(tmp_path)) == {("path", "out/report.json")}

    result = verify(tmp_path, promised=[LATER], today=date(2026, 9, 8))
    assert result.broken == []
    assert [claim.text for claim in result.deferred] == ["out/report.json"]
    assert result.checked == 1  # deferred, not dropped from the count


def test_a_promise_the_tree_has_kept_fails(tmp_path):
    """The only failure here that fires on something going right.

    An exemption list nobody prunes is an allowlist with a good story, so the
    declaration going stale is the thing that gates -- and it costs one line to
    fix, in the file where somebody chose it.
    """
    write(tmp_path, "design.md", "It writes `out/report.json` when it runs.\n")
    write(tmp_path, "out/report.json", "{}\n")

    result = verify(tmp_path, promised=[LATER], today=date(2026, 9, 8))
    assert result.kept == ["out/report.json"]
    assert result.failed
    assert "remove it from `promised`" in result.text()


def test_a_promise_does_not_silence_a_path_it_did_not_name(tmp_path):
    """Matched by exact spelling. A promise that also covered every other
    `report.json` in the tree would suppress claims nobody chose to defer, and
    suppression that reads clean is the failure this package exists to catch."""
    write(
        tmp_path, "design.md",
        "Writes `out/report.json`, reads `vendor/report.json`.\n",
    )
    result = verify(tmp_path, promised=[LATER], today=date(2026, 9, 8))
    assert broken(result) == {("path", "vendor/report.json")}


def test_a_commit_cannot_be_promised(tmp_path):
    """A file can be intended and absent; a hash cannot. Allowing it would only
    buy a way to defer a citation that is simply wrong."""
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.email", "t@example.org"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    write(tmp_path, "a.txt", "x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "first"], check=True)

    write(tmp_path, "doc.md", "Fixed in `deadbee1`.\n")
    result = verify(tmp_path, promised=[Promise("deadbee1", date(2027, 1, 1))],
                    today=date(2026, 9, 8))
    assert broken(result) == {("commit", "deadbee1")}
    assert result.deferred == []


def test_a_promise_past_its_date_fails(tmp_path):
    """A promise otherwise expires **only by being kept**. If the work is
    cancelled or never starts, the document goes on citing a file nobody will
    build and nothing is ever red again -- the document still cites the path, so
    coverage cannot tell. A date is the only signal available for that case."""
    write(tmp_path, "design.md", "It writes `out/report.json` when it runs.\n")
    promise = Promise(path="out/report.json", until=date(2026, 8, 1))

    early = verify(tmp_path, promised=[promise], today=date(2026, 7, 31))
    assert early.overdue == []
    assert not early.failed

    late = verify(tmp_path, promised=[promise], today=date(2026, 8, 2))
    assert late.overdue == ["out/report.json (deferred until 2026-08-01)"]
    assert late.failed


def test_a_promise_no_document_cites_fails(tmp_path):
    """The rename case. The new name fails loudly as a dead claim while the old
    entry silently protects nothing -- and a list half full of names nobody will
    ever create cannot be read by the next person."""
    write(tmp_path, "design.md", "It writes `out/report.v2.json` when it runs.\n")
    result = verify(tmp_path, promised=[LATER], today=date(2026, 9, 8))

    assert result.uncovered == ["out/report.json"]
    assert broken(result) == {("path", "out/report.v2.json")}
    assert result.failed


def test_every_promise_lapses_eventually(tmp_path):
    """There is no value meaning never, deliberately. A deferral that cannot
    lapse is an ignore list with a better name: if the work is canceled or never
    starts, the document goes on naming a file nobody will build and nothing is
    ever red again."""
    write(tmp_path, "design.md", "It writes `out/report.json` when it runs.\n")
    result = verify(tmp_path, promised=[LATER], today=date(2099, 1, 1))
    assert result.overdue == ["out/report.json (deferred until 2027-01-01)"]
    assert result.failed
