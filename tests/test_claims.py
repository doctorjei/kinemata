"""Documentation claims, and the two ways a checker of prose goes wrong.

Over-reporting kills adoption; under-reporting kills the check while it still
says "clean". Both happened to the prototype this replaces, so both have tests.
"""

from __future__ import annotations

import subprocess
import textwrap
import threading
from datetime import date
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from kinemata.claims import CLAIM_KINDS, ClaimsError, Promise, verify
from kinemata.config import ConfigError, load


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


def test_a_citation_stamp_is_never_link_text(tmp_path):
    """The residual `docs/citations.md` states, closed.

    A stamp is a bracket group, so `[0TMQDKB-Ty](see below)` parsed as a link
    and `see` was reported as a dead path. A space between the two prevented it
    and was rejected as the fix: whitespace is invisible, survives editing
    poorly, and a rule that holds only while nobody deletes a character is not
    a rule. Both spellings are asserted here, because the point is that the
    behavior no longer depends on which one was written.
    """
    write(tmp_path, "doc.md",
          "[0TMQDKB-Ty](see below)\n\n[0TMQDKB-Ty] (see below)\n")
    assert verify(tmp_path).broken == []


def test_a_stamp_beside_a_real_link_does_not_disturb_it(tmp_path):
    """The other half: taught not to over-report, still reporting.

    A filter that suppressed the whole line, or the following group, would pass
    the test above and quietly stop checking every link a stamp sits next to.
    """
    write(tmp_path, "doc.md",
          "[the design](./real.md) [0TMQDKB-Ty] and [gone](./missing.md)\n")
    write(tmp_path, "real.md", "x\n")
    assert broken(verify(tmp_path)) == {("link", "./missing.md")}


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


#: The four branches this project's own config carries. Kept here so a change to
#: how the claimed value is picked out of a multi-branch match is caught against
#: the real shape rather than a two-branch simplification of it.
TEST_COUNT_PATTERN = (
    r"\*\*(\d+) tests?\*\*|\b(\d+) tests? pass\b"
    r"|\*\*Tests:\*\* (\d+) pass\b|\b(\d+) tests? collected\b"
)


def test_the_numeric_form_is_unchanged_by_settling_values(tmp_path):
    """A number is a value, and generalizing must not move the numeric case.

    Both directions, against the live four-branch pattern: agreement is silent
    and disagreement carries the true number in the finding.
    """
    from kinemata.claims import Counted

    oracle = ("{python}", "-c", "print('7 tests collected')")
    spec = Counted(
        pattern=TEST_COUNT_PATTERN,
        command=oracle,
        extract=r"(\d+) tests collected",
        label="test count",
    )
    write(tmp_path, "doc.md", "**Tests:** 7 pass, and 7 tests collected.\n")
    assert verify(tmp_path, counts=[spec]).broken == []

    write(tmp_path, "doc.md", "**Tests:** 4 pass\n")
    result = verify(tmp_path, counts=[spec])
    assert [claim.kind for claim in result.broken] == ["test count"]
    assert "actually 7" in result.broken[0].text


def test_a_value_that_is_not_a_number_is_settled(tmp_path):
    """The whole point of the generalization, and the polarity it adds.

    An adopting project could not express 291 of 326 conformance checks against
    this tool, and the largest structural reason was that every mechanism here
    is negative: a registry reports a *second* spelling of a declared value and
    says nothing when the document and the code disagree. 125 of those checks
    assert the opposite shape -- a documented row equals what the code produces.
    """
    from kinemata.claims import Counted

    write(tmp_path, "doc.md", "The default mode is `strict`.\n")
    spec = Counted(
        pattern=r"default mode is `(\w+)`",
        command=("{python}", "-c", "print('mode=lenient')"),
        extract=r"mode=(\w+)",
        label="default mode",
    )
    result = verify(tmp_path, counts=[spec])
    assert [claim.kind for claim in result.broken] == ["default mode"]
    assert "actually lenient" in result.broken[0].text


def test_a_value_that_agrees_is_silent(tmp_path):
    """Agreement passes. Under the negative mechanism this rides beside, a
    document spelling a declared value is itself the finding -- which is the
    inversion that made a whole class of conformance check inexpressible."""
    from kinemata.claims import Counted

    write(tmp_path, "doc.md", "The default mode is `strict`.\n")
    spec = Counted(
        pattern=r"default mode is `(\w+)`",
        command=("{python}", "-c", "print('mode=strict')"),
        extract=r"mode=(\w+)",
        label="default mode",
    )
    assert verify(tmp_path, counts=[spec]).broken == []


def test_a_value_is_compared_exactly_and_never_converted(tmp_path):
    """The documented limit, pinned so nobody "fixes" it into a normalizer.

    "16 KB" and the byte count are different spellings of one budget, and this
    settles the spelling it was given. Reporting the mismatch is the safe
    direction: the alternative is a unit conversion that, when wrong, passes.
    """
    from kinemata.claims import Counted

    write(tmp_path, "doc.md", "Projections get a 16 KB budget.\n")
    spec = Counted(
        pattern=r"a (\d+ KB) budget",
        command=("{python}", "-c", "print('budget=16384')"),
        extract=r"budget=(\S+)",
        label="budget",
    )
    result = verify(tmp_path, counts=[spec])
    assert [claim.kind for claim in result.broken] == ["budget"]
    assert "actually 16384" in result.broken[0].text


def test_edge_whitespace_does_not_decide_a_comparison(tmp_path):
    """Stripped on both sides, and only there.

    A command's output ends in a newline and a pattern written to swallow one
    would otherwise fail a comparison that agrees -- silent wrongness inside the
    check that exists to refuse it. Interior spacing is left alone: the value
    below carries a space and is settled as written.
    """
    from kinemata.claims import Counted

    write(
        tmp_path,
        "doc.md",
        """
        | key | value |
        |---|---|
        | stamp | sealed copy |
        """,
    )
    spec = Counted(
        # A table cell arrives padded, which is formatting rather than anything
        # the document asserts -- and the oracle's output ends in a newline.
        pattern=r"\| stamp \|([^|]+)\|",
        command=("{python}", "-c", "print('sealed copy')"),
        extract=r"^(.*)$",
        label="stamp",
    )
    assert verify(tmp_path, counts=[spec]).broken == []


def test_kinds_are_a_table_not_a_hardcoded_sequence():
    """Adding a kind is a row, and the loop never learns their names."""
    assert {kind.name for kind in CLAIM_KINDS} == {"path", "link", "commit", "url"}
    (commit,) = [kind for kind in CLAIM_KINDS if kind.needs_git]
    assert commit.when_unavailable
    # The capability fields are what let a kind say it cannot run here, and a
    # kind needing both would need neither field tested to slip through.
    (url,) = [kind for kind in CLAIM_KINDS if kind.needs_network]
    assert not url.needs_git


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
    assert "remove the promise" in result.text()


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
    result = verify(tmp_path,
                    promised=[Promise(path="deadbee1", until=date(2027, 1, 1))],
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


# -- external links: the one claim nothing here could falsify -----------------


class _Answers(BaseHTTPRequestHandler):
    """Serves a status chosen by the path, so a test can name what it wants."""

    def do_HEAD(self):  # http.server's spelling, not ours
        code = 405 if "headless" in self.path else self._code()
        self.send_response(code)
        self.end_headers()

    def do_GET(self):
        self.send_response(self._code())
        self.end_headers()

    def _code(self):
        return int(self.path.strip("/").split("-")[-1] or 200)

    def log_message(self, *args):
        pass  # the suite is not a web server log


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), _Answers)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()
    httpd.server_close()


def test_a_dead_external_link_is_reported(tmp_path, server):
    """The gap this closes. A URL that 404s was invisible to every check here.

    Found 2026-09-08 when a dead OpenFastTrace link sat in `CONVENTIONS.md` and
    was caught by a person reading it rather than by a gate.
    """
    write(tmp_path, "doc.md", f"See [the guide]({server}/gone-404).\n")
    result = verify(tmp_path, external=True)
    assert ("url", f"{server}/gone-404") in broken(result)
    assert result.failed


def test_a_live_external_link_is_not_a_finding(tmp_path, server):
    write(tmp_path, "doc.md", f"See [the guide]({server}/here-200).\n")
    result = verify(tmp_path, external=True)
    assert not result.broken


def test_a_bare_url_in_prose_is_checked_too(tmp_path, server):
    """Not restricted to markdown link targets: the link that motivated this
    kind was a bare URL in a list, which a target-only reader walks past."""
    write(tmp_path, "doc.md", f"Repo: {server}/gone-404\n")
    result = verify(tmp_path, external=True)
    assert ("url", f"{server}/gone-404") in broken(result)


def test_an_unanswerable_address_is_reported_and_never_fails(tmp_path, server):
    """Three outcomes, because two would be a lie.

    A 403 cannot distinguish a deleted page from a reader the site refuses, and
    a gate that goes red on a bot-hostile host is a gate its reader learns to
    skim. Reported by name -- the reader may want to open it themselves.
    """
    write(tmp_path, "doc.md", f"See {server}/refused-403 and {server}/broken-500.\n")
    result = verify(tmp_path, external=True)
    assert not result.broken
    assert not result.failed
    assert [line for line in result.unavailable if "refused-403" in line]
    assert [line for line in result.unavailable if "broken-500" in line]


def test_external_links_are_counted_when_the_check_is_off(tmp_path, server):
    """Off is a decision; off and invisible is a blind spot."""
    write(tmp_path, "doc.md", f"See {server}/gone-404 and {server}/other-404.\n")
    result = verify(tmp_path)
    assert not result.broken
    assert ("2 external link(s) (network checks not enabled; "
            "set external = true under [claims])") in result.unavailable


def test_an_address_that_answered_nothing_is_not_a_confirmation(tmp_path, server):
    """Resolving is the gate's answer, and it is not always the writer's.

    A 403 resolves here on purpose -- nothing said the page is gone -- and that
    reading was the whole of what this module recorded, so a run could report
    every claim resolving while none of its addresses had been reached.
    ``unavailable`` named the address; nothing named the *claims* resting on it,
    which is what a writer deciding whether to date a document has to ask.
    """
    write(tmp_path, "doc.md", f"See {server}/refused-403.\n")
    result = verify(tmp_path, external=True)
    assert not result.broken and not result.failed
    assert [claim.text for claim in result.unsettled] == [f"{server}/refused-403"]


def test_a_live_address_is_settled_and_not_merely_unfalsified(tmp_path, server):
    """The positive control: a yes is a yes, and stays out of this bucket."""
    write(tmp_path, "doc.md", f"See {server}/here-200.\n")
    assert verify(tmp_path, external=True).unsettled == []


def test_an_address_nobody_asked_about_is_unsettled(tmp_path, server):
    """With the network check off, every address resolves and none is confirmed."""
    write(tmp_path, "doc.md", f"See {server}/here-200.\n")
    assert len(verify(tmp_path).unsettled) == 1


def test_a_commit_outside_a_repository_is_unsettled(tmp_path):
    """The same shape one oracle over: no history to ask means no confirmation.

    ``unavailable`` already says the tree is not a repository. This says how
    many citations were riding on the answer it could not give.
    """
    write(tmp_path, "doc.md", "Fixed in `abcdef12`.\n")
    result = verify(tmp_path)
    assert not result.broken
    assert [claim.text for claim in result.unsettled] == ["abcdef12"]


def test_a_dead_url_in_an_archive_is_still_dead(tmp_path, server):
    """`historical` exempts claims about the *tree*, and a URL is not one.

    An archive citing a path that has since been deleted was right when it was
    written, so checking it reports the archive for being an archive. There is
    no equivalent for an address: the reader who follows a dead link out of a
    changelog gets the same nothing they would get anywhere else, and "it worked
    when this was written" does not help them.

    Measured on an adopting project 2026-09-09, whose two historical fragments
    took 17 of its 36 URLs out of the check -- including both of the genuine
    404s it had. The exemption was removing exactly the findings it exists to
    keep.
    """
    write(tmp_path, "archives/old.md", f"We used {server}/gone-404 at the time.\n")
    result = verify(tmp_path, external=True, historical=["archives/"])
    assert ("url", f"{server}/gone-404") in broken(result)


def test_an_archive_is_still_exempt_from_claims_about_the_tree(tmp_path, server):
    """The other half of the same edit, asserted so it cannot be lost.

    Turning the URL kind's `current_only` off must not turn it off for the kinds
    that report the tree's present state -- the skip is per kind, and one line
    in the same table would have made the exemption vanish for all of them.
    """
    write(
        tmp_path,
        "archives/old.md",
        f"The loader is `src/removed.py`, see {server}/gone-404.\n",
    )
    assert ("path", "src/removed.py") in broken(verify(tmp_path))

    result = verify(tmp_path, external=True, historical=["archives/"])
    assert broken(result) == {("url", f"{server}/gone-404")}


def test_a_server_refusing_head_is_asked_again_with_get(tmp_path, server):
    """The refusal is of the method, not the resource.

    A link check has no use for a body, so it asks with ``HEAD`` -- and enough
    servers answer 405 to that alone. Treating those as unanswerable would put a
    working link on the unchecked list, where nobody looks.
    """
    write(tmp_path, "doc.md", f"See {server}/headless-200\n")
    result = verify(tmp_path, external=True)
    assert not result.broken
    assert not [line for line in result.unavailable if "headless" in line]


# -- shapes a foreign project reported, and this tree never had ---------------


def test_a_windows_environment_path_is_not_a_claim(tmp_path):
    """Found on httpie, whose documentation says where its config lives.

    `%` joined the external prefixes and a backslash disqualifies a token
    outright: neither spelling can be resolved against this tree, so both are
    cases of *cannot settle* rather than cases of a broken claim.
    """
    write(
        tmp_path,
        "doc.md",
        "On Windows, the config file is at `%APPDATA%\\httpie\\config.json`.\n",
    )
    assert not verify(tmp_path).broken


def test_an_environment_variable_path_with_forward_slashes_is_not_a_claim(tmp_path):
    """`%` earns its place in the prefix list separately from the backslash rule.

    The corpus case had backslashes and both rules caught it, so removing `%`
    changed no test -- an untested rule, which is the thing this project reports
    in other people's code. This is the spelling only `%` catches.
    """
    write(tmp_path, "doc.md", "The config lives at `%APPDATA%/httpie/config.json`.\n")
    assert not verify(tmp_path).broken


def test_a_token_with_a_backslash_is_not_a_claim(tmp_path):
    """`\\o/` sat in requests' changelog and was reported as a dead path."""
    write(tmp_path, "doc.md", "-   Enhanced status codes experience `\\o/`\n")
    assert not verify(tmp_path).broken


def test_a_document_relative_path_resolves_against_the_tree(tmp_path):
    """httpie's packaging README names `./get_release_artifacts.sh` and the
    file sits beside it. The `./` survived into every lookup, so a correct
    reference read as a dead one."""
    write(tmp_path, "extras/README.md", "### `./get_release_artifacts.sh`\n")
    write(tmp_path, "extras/get_release_artifacts.sh", "#!/bin/sh\n")
    assert not verify(tmp_path).broken


def test_a_capitalized_attribute_is_not_read_as_a_file(tmp_path):
    """`Response.json` is an attribute in requests' changelog, read as a file
    because `.json` is a known suffix.

    The boundary is asserted in every direction, because the rule shipped with a
    cost and then had it narrowed away: a capitalized *document* name is a
    spelling projects actually use, while an attribute called `md` is one nobody
    writes. The collision is real only where the tail is also a plausible method
    name.
    """
    write(tmp_path, "doc.md", "-   New `Response.json` property.\n")
    assert not verify(tmp_path).broken
    write(tmp_path, "other.md", "See `README.md` and `Introduction.md` for the rest.\n")
    assert broken(verify(tmp_path)) == {
        ("path", "README.md"), ("path", "Introduction.md"),
    }


# -- what an adopting project measured, 2026-09-09 ----------------------------


def test_a_url_elided_in_prose_is_not_an_address(tmp_path):
    """Nothing invents a claim, least of all one that then gets a request.

    Prose writes a scheme and an ellipsis to mean "an address goes here". The
    strip that removes sentence punctuation from a real address reduced that to
    a bare scheme, which was asked over the network and reported. The filter is
    on the empty authority rather than on the ellipsis: anything the strip can
    reduce to a scheme has the same defect, and matching the symptom leaves the
    next spelling of it to be found the same way.
    """
    write(tmp_path, "doc.md", "Write it as http://... in the config.\n")
    result = verify(tmp_path, external=True)
    assert not result.broken
    assert result.checked == 0


def test_a_scheme_with_no_host_is_never_asked(tmp_path, server):
    """The general case, stated separately from the ellipsis that found it."""
    write(tmp_path, "doc.md", f"Compare https:// with {server}/here-200\n")
    result = verify(tmp_path, external=True)
    assert result.checked == 1
    assert not result.broken


def test_neither_and_nor_read_as_the_denial_they_are(tmp_path):
    """Their example, and the document was right.

    A sentence reporting that a cited test file and its test name have both
    stopped existing is a report about an absence. The word list had `formerly`
    and not the bare `former`, `missing` and not `dead`, `no` and not `neither`
    -- which is the shape a hand-written vocabulary fails in.
    """
    write(
        tmp_path,
        "doc.md",
        "The note cited `tests/test_prefs.py`, and neither that path nor that "
        "test name exists in the tree.\n",
    )
    assert verify(tmp_path).broken == []


def test_dead_and_former_negate_a_path(tmp_path):
    write(tmp_path, "one.md", "The dead `src/old_loader.py` is worth deleting.\n")
    write(tmp_path, "two.md", "Its former home, `src/attic.py`, is empty now.\n")
    assert verify(tmp_path).broken == []


def test_a_generic_stand_in_filename_is_not_a_claim(tmp_path):
    """`file.py` is the most generic name a document can write.

    A one-letter stem was already read as an example; the word *file* itself was
    not, and produced findings on prose teaching a shape.
    """
    write(tmp_path, "doc.md", "Run it as `kinemata check file.py` to see.\n")
    assert verify(tmp_path).broken == []


def test_a_digit_stand_in_is_not_a_claim(tmp_path):
    """A requirement identifier written with n's for its digits names a form.

    There is no document called that, and reporting it teaches readers that the
    check does not understand the convention they are writing in.
    """
    write(tmp_path, "doc.md", "Each requirement gets its own `Rnnn.md`.\n")
    assert verify(tmp_path).broken == []
    write(tmp_path, "real.md", "The first one is `R001.md`.\n")
    assert broken(verify(tmp_path)) == {("path", "R001.md")}


def test_an_all_digit_number_is_not_a_commit_hash(tmp_path):
    """Hex is a superset of decimal, so every backticked number was a hash.

    An eleven-digit byte count in an adopter's notes was reported as a dead
    commit. Git does not mint all-decimal short hashes often enough for that
    catch to be worth the class of finding it produces, and a number in
    backticks is the commonest token in prose there is.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    for key, value in (("user.email", "t@example.org"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(tmp_path), "config", key, value], check=True)
    write(tmp_path, "a.txt", "x\n")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "first"], check=True)

    write(tmp_path, "doc.md", "The corpus weighs `31130589017` bytes; see `deadbee1`.\n")
    assert broken(verify(tmp_path)) == {("commit", "deadbee1")}


# -- the allowlist a project can extend ---------------------------------------


def test_a_project_may_declare_the_suffixes_that_name_its_files(tmp_path):
    """Fourteen extensions chosen here are wrong for most repositories.

    On one adopter's tree the only two content files -- a container definition
    carrying a dotted project name, and a terminal configuration ending in
    `.conf` -- were cited five times in backticks and seen zero times. The scan
    came back four of twenty-seven and looked nearly green while being
    structurally unable to see what the repository is about.
    """
    write(tmp_path, "doc.md", "Built from `Containerfile.kanibako`, and `tmux.conf`.\n")
    assert verify(tmp_path).broken == []  # invisible, which is the defect

    result = verify(tmp_path, file_suffixes=[".conf", ".kanibako"])
    assert broken(result) == {
        ("path", "Containerfile.kanibako"), ("path", "tmux.conf"),
    }


def test_declared_suffixes_add_to_the_built_in_set(tmp_path):
    """Extension, not replacement. A knob that replaced the default would let
    one added suffix silently switch off the other fourteen, which is the same
    failure -- a check quietly narrowing -- in the fix for it."""
    write(tmp_path, "doc.md", "See `src/ghost.py` and `tmux.conf`.\n")
    assert broken(verify(tmp_path, file_suffixes=[".conf"])) == {
        ("path", "src/ghost.py"), ("path", "tmux.conf"),
    }


def test_a_file_suffix_without_its_dot_is_refused(tmp_path):
    """It would match nothing, and match nothing quietly."""
    (tmp_path / "kinemata.toml").write_text(
        '[claims]\nfile_suffixes = ["conf"]\n'
    )
    with pytest.raises(ConfigError, match="would match nothing"):
        load(tmp_path / "kinemata.toml")


def test_declared_file_suffixes_reach_the_settings(tmp_path):
    (tmp_path / "kinemata.toml").write_text(
        '[claims]\nfile_suffixes = [".conf", ".kanibako"]\n'
    )
    assert load(tmp_path / "kinemata.toml").claim_file_suffixes == (
        ".conf", ".kanibako",
    )


# -- declarations that were present and doing nothing -------------------------


def test_a_suffix_that_yields_no_claims_says_so(tmp_path):
    """The trap, and the one worth naming loudest.

    Every extractor here reads markdown syntax. An adopter added a YAML suffix
    and got byte-identical output -- no extra claims, no note, and a green run
    that meant less than the one before it. A warning rather than a failure,
    because a suffix may honestly match nothing; silence is what is not
    allowed.
    """
    write(tmp_path, "doc.md", "See `src/app.py`.\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    write(tmp_path, "compose.yml", "services:\n  app:\n    image: x\n")

    result = verify(tmp_path, suffixes=[".md", ".yml"])
    assert [line for line in result.warnings if ".yml" in line and "yielded no" in line]
    assert not [line for line in result.warnings if ".md" in line]
    assert not result.failed  # a warning, deliberately


def test_a_suffix_that_matches_nothing_is_a_different_message(tmp_path):
    """Two mistakes with two fixes: a typo or a tree without those documents,
    against documents that were read and could not be seen into."""
    write(tmp_path, "doc.md", "See `src/app.py`.\n")
    write(tmp_path, "src/app.py", "x = 1\n")

    result = verify(tmp_path, suffixes=[".md", ".rst"])
    assert [line for line in result.warnings if ".rst" in line and "no files" in line]


def test_a_warning_reaches_stderr(tmp_path, capsys):
    """Kept on the result *and* printed. A caller that never reads the result
    object is the one this was invisible to."""
    write(tmp_path, "doc.md", "See `src/app.py`.\n")
    write(tmp_path, "src/app.py", "x = 1\n")

    verify(tmp_path, suffixes=[".md", ".rst"])
    assert ".rst" in capsys.readouterr().err


def test_a_resolve_in_tree_that_is_not_there_refuses(tmp_path):
    """It failed open, and open was invisible.

    An adopter compared a run declaring a missing sibling tree against a run
    declaring nothing: identical bytes, same findings, same exit code, no note
    on stderr. In CI, where the sibling is usually not checked out, that is
    every claim it was meant to settle going unchecked while the run reads
    clean. A warning was considered and rejected -- the steady state it would
    have to tolerate is "the tree I resolve against is often absent", and a
    project in that state is asking for a check it is not getting.
    """
    write(tmp_path, "doc.md", "The loader is `loader/src/app.py`.\n")
    with pytest.raises(ClaimsError, match="not a directory"):
        verify(tmp_path, resolve_in=["../loader"])


def test_external_on_with_nothing_to_reach_says_so(tmp_path, capsys):
    """Declared and reaching nothing reads exactly like declared and working.

    Found on this project's own tree: excluding two documents it carries but did
    not author took the address population from five to none -- and all five had
    been somebody else's, so the network check had been settling no link of this
    project's while looking every inch like a network gate.
    """
    write(tmp_path, "doc.md", "See `src/app.py`.\n")
    write(tmp_path, "src/app.py", "x = 1\n")

    result = verify(tmp_path, external=True)
    assert result.broken == []
    assert any("settles nothing" in note for note in result.warnings)
    assert "external is on" in capsys.readouterr().err


def test_external_on_with_something_to_reach_is_silent(tmp_path, capsys):
    """The negative control: the note is about an empty population, not about
    the flag being set. Without this the assertion above passes on any tree."""
    write(tmp_path, "doc.md", "See <https://example.invalid/x>.\n")

    result = verify(tmp_path, external=True, timeout=0.01)
    assert not any("settles nothing" in note for note in result.warnings)


def _repository(path):
    """A tiny git repository, returning the short hash of its one commit.

    Two hazards, both met the hard way, both deterministic once named.

    The file carries the directory's name because two repositories built here
    in the same second, from the same content and the same identity, get the
    *same* commit hash -- and a test whose two trees share a hash proves nothing
    about which one settled it.

    The commit is re-made until its short hash is not all digits, because
    ``_commit_claims`` skips those on purpose: hex is a superset of decimal, so
    an all-decimal run in backticks is a number in prose far more often than it
    is a hash. Roughly one short hash in forty is all digits, which is a flake
    rate high enough to be seen and low enough to be blamed on something else.
    """
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    for key, value in (("user.email", "t@example.org"), ("user.name", "T")):
        subprocess.run(["git", "-C", str(path), "config", key, value], check=True)
    for attempt in range(20):
        (path / "a.txt").write_text(f"{path.name} {attempt}\n")
        subprocess.run(["git", "-C", str(path), "add", "-A"], check=True)
        subprocess.run(
            ["git", "-C", str(path), "commit", "-q", "--allow-empty",
             "-m", f"first {attempt}"],
            check=True,
        )
        short = subprocess.run(
            ["git", "-C", str(path), "rev-parse", "--short=8", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
        if not short.isdigit():
            return short
    raise AssertionError("twenty all-digit short hashes is not chance")


def test_a_commits_in_tree_that_is_not_there_refuses(tmp_path):
    """The same fail-open `resolve_in` was taught to refuse, one layer deeper.

    A corpus checked out beside a developer's tree and gitignored in CI is the
    live case: the citations settle locally, the declaration silently stops
    settling them where the gate actually runs, and both runs are green.
    """
    write(tmp_path, "notes/doc.md", "Commit `deadbee1` did it.\n")
    with pytest.raises(ClaimsError, match="not a directory"):
        verify(tmp_path / "notes", commits_in=["../corpus"])


def test_a_commits_in_tree_that_is_not_a_repository_refuses(tmp_path):
    """Present and inert is the same failure as absent, and looks healthier.

    `_known_commits` keeps only the roots that are repositories, so a directory
    that is merely *there* disappears into that filter exactly as a missing one
    does -- while a reader checking the declaration by eye sees a real path.
    """
    (tmp_path / "corpus").mkdir()
    write(tmp_path, "notes/doc.md", "Commit `deadbee1` did it.\n")
    with pytest.raises(ClaimsError, match="not a git repository"):
        verify(tmp_path / "notes", commits_in=["../corpus"])


def test_commits_in_settles_a_hash_from_the_named_repository(tmp_path):
    """The refusals above are worth nothing if the feature never worked.

    Negative control in the same test: the same hash is a finding when the
    repository holding it is not declared.
    """
    real = _repository(tmp_path / "corpus")
    # The scanned tree is a repository too, or commit checking reports itself
    # unavailable and the control below would pass for the wrong reason.
    _repository(tmp_path / "notes")
    write(tmp_path, "notes/doc.md", f"Their commit `{real}` did it.\n")

    assert verify(tmp_path / "notes", commits_in=["../corpus"]).broken == []
    assert broken(verify(tmp_path / "notes")) == {("commit", real)}
