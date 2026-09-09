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


def test_an_archive_may_cite_a_url_that_has_since_died(tmp_path, server):
    """A record citing a page that later went away is a record, not a defect."""
    write(tmp_path, "archives/old.md", f"We used {server}/gone-404 at the time.\n")
    result = verify(tmp_path, external=True, historical=["archives/"])
    assert not result.broken


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
