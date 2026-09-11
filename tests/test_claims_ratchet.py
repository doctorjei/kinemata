"""The ratchet over documentation, and the boundary it draws around a claim.

A gate that only works on a clean tree is a gate almost nobody can turn on. That
argument was made about code and is exactly as true of prose -- this repository
is the case in point: `[claims] suffixes` cannot include `.py` here while arming
it means 10 permanently unresolved citations of evidence that lives in other
people's repositories, gitignored here and absent from a clean clone.

The design question is the one `test_baseline.py` opens with, asked of a
different subject: what is *the same claim* across commits. Too coarse and a
record absorbs the next dead reference silently; too fine and ordinary editing
looks like regression, which trains people to re-record -- and a re-record
absorbs whatever else arrived in that commit. These pin it from both sides.
"""

from __future__ import annotations

import json
import subprocess
import textwrap
from datetime import date

import pytest

from kinemata.baseline import Baseline, BaselineError, record
from kinemata.bypass import Bypass
from kinemata.claims import CLAIM_PREFIX, CLAIMS_REGISTRY, Promise, verify
from kinemata.cli import main
from kinemata.config import ConfigError, load

#: Far enough out that these tests are about fingerprints, not expiry.
LATER = date(2099, 1, 1)


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def cfg(project):
    return str(project / "kinemata.toml")


@pytest.fixture
def project(tmp_path):
    """A project whose only declared check is its documentation.

    Deliberately registry-free. That is the cheapest adoption `init` writes and
    the one this work exists to unblock, so if the ratchet cannot be recorded
    here it cannot be recorded by the projects most likely to want it.
    """
    write(tmp_path, "docs/guide.md", "The loader is `src/loader.py`.\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]
        """)
    return tmp_path


# -- what counts as the same claim --------------------------------------------


def test_a_claim_that_moved_down_the_file_is_still_the_same_claim(tmp_path):
    """The churn case, and the one the brief asked to be pinned.

    Every edit above a claim shifts its line number. A ratchet that reported
    those as new findings would be re-recorded reflexively, and a re-record
    absorbs whatever else arrived in that commit. Measured on the code side at
    one spurious report over two hundred commits; the fingerprint is the same
    fingerprint, so the property has to hold here too.
    """
    write(tmp_path, "doc.md", "The loader is `src/loader.py`.\n")
    before = record(tmp_path / "b.json", verify(tmp_path).findings(), until=LATER)
    assert before.size == 1

    write(tmp_path, "doc.md", """
        A new opening paragraph.

        And a second one.

        The loader is `src/loader.py`.
        """)
    assert before.split(verify(tmp_path).findings()).new == ()


def test_rewriting_the_sentence_is_a_new_claim(tmp_path):
    """The boundary from the other side.

    The matched line is in the fingerprint, so a record does not outlive the
    sentence it was recorded against. That is the same rule every other finding
    here is held to, and the cost of the alternative is an exemption that
    survives the text a reviewer read when they granted it.
    """
    write(tmp_path, "doc.md", "The loader is `src/loader.py`.\n")
    before = record(tmp_path / "b.json", verify(tmp_path).findings(), until=LATER)

    write(tmp_path, "doc.md", "Every request is routed through `src/loader.py`.\n")
    split = before.split(verify(tmp_path).findings())
    assert len(split.new) == 1
    assert len(split.stale) == 1


def test_the_same_claim_in_another_document_is_a_new_claim(tmp_path):
    """The path is in the key deliberately. A catch scoped to one module is not
    a catch -- kanibako-cli's own tripwire failed exactly that way -- and a dead
    reference that spread to a second document spread."""
    write(tmp_path, "a.md", "The loader is `src/loader.py`.\n")
    before = record(tmp_path / "b.json", verify(tmp_path).findings(), until=LATER)

    write(tmp_path, "b.md", "The loader is `src/loader.py`.\n")
    split = before.split(verify(tmp_path).findings())
    assert len(split.new) == 1
    assert split.new[0][0] == CLAIMS_REGISTRY


def test_three_accepted_sites_do_not_exempt_a_fourth(tmp_path):
    """Multiplicity, which is what makes a fingerprint list different from a
    recorded total. A count of three is satisfied by any three; recording *how
    many* is what makes the fourth an increase rather than an indistinguishable
    duplicate."""
    line = "The loader is `src/loader.py`.\n"
    write(tmp_path, "doc.md", line * 3)
    before = record(tmp_path / "b.json", verify(tmp_path).findings(), until=LATER)
    assert before.size == 3
    assert len(before.accepted) == 1  # one record, carrying its count
    assert before.split(verify(tmp_path).findings()).new == ()

    write(tmp_path, "doc.md", line * 4)
    assert len(before.split(verify(tmp_path).findings()).new) == 1


def test_the_kind_is_the_entry_and_the_target_is_the_antipattern(tmp_path):
    """The mapping, asserted rather than left to a reader of the JSON.

    A bypass names a declared entry and the spelling that went around it; a
    claim names a sort of assertion and the target that did not resolve. Those
    are the same two questions, and `provenance` mapped them the same way --
    a third mapping for a third finding type would make the file unreadable by
    pattern.
    """
    write(tmp_path, "doc.md", "The loader is `src/loader.py`.\n")
    (registry, hit), = verify(tmp_path).findings()
    assert registry == CLAIMS_REGISTRY
    assert hit.entry_id == f"{CLAIM_PREFIX}path"
    assert hit.antipattern == "src/loader.py"
    assert hit.path == "doc.md"
    assert hit.text == "The loader is `src/loader.py`."


def test_a_commit_claim_fingerprints_by_its_hash(tmp_path):
    """The class this was built for: seven of the ten findings blocking `.py`
    in this repository are commit hashes in corpus repositories.

    A repository is required, not incidental: outside one the kind reports
    itself unavailable and yields nothing, so the same assertion against a bare
    directory passes by checking nothing at all.
    """
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "doc.md", "Recorded in `abcdef1234`.\n")
    (_, hit), = verify(tmp_path).findings()
    assert hit.entry_id == f"{CLAIM_PREFIX}commit"
    assert hit.antipattern == "abcdef1234"


# -- one list, and the two gates that read it ---------------------------------


def test_recording_turns_a_failing_documentation_gate_green(project, capsys):
    """The whole point, and the demonstration the brief asked for in miniature.

    Without this the only two states available to a project with genuine
    unresolvable citations are "permanently red" and "not checking prose".
    """
    assert main(["claims", "-c", cfg(project)]) == 1
    assert "src/loader.py" in capsys.readouterr().out

    argv = ["baseline", "-c", cfg(project), "--record", "--until", "2099-01-01"]
    assert main(argv) == 0
    assert "Recorded 1" in capsys.readouterr().out

    assert main(["claims", "-c", cfg(project)]) == 0
    out = capsys.readouterr().out
    assert "1 claim(s) accepted as pre-existing" in out
    # Not "all resolve": the accepted ones are still broken, they are accepted.
    assert "all resolve" not in out


def test_a_new_dead_reference_still_fails(project, capsys):
    """An accepted population goes quiet; the next one does not."""
    main(["baseline", "-c", cfg(project), "--record", "--until", "2099-01-01"])
    write(project, "docs/guide.md", """
        The loader is `src/loader.py`.
        The writer is `src/writer.py`.
        """)
    capsys.readouterr()

    assert main(["claims", "-c", cfg(project)]) == 1
    out, err = capsys.readouterr()
    assert "src/writer.py" in out
    assert "src/loader.py" not in out  # accepted, so not reported again
    assert "1 of" in err and "new claim(s) do not resolve" in err


def test_one_file_holds_both_kinds(tmp_path, capsys):
    """No second baseline and no second exemption list.

    Two lists eventually disagree about what a project accepted, and the one
    nobody is reading is the one still exempting something real. So a project
    with both a re-derived constant and a dead reference records once, and both
    gates go green off the same file.
    """
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", 'p = root / "box.yaml"\n')
    write(tmp_path, "docs/guide.md", "The loader is `src/loader.py`.\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """)
    assert main(["check", "-c", cfg(tmp_path)]) == 1
    assert main(["claims", "-c", cfg(tmp_path)]) == 1
    capsys.readouterr()

    assert main(["baseline", "-c", cfg(tmp_path), "--record",
                 "--until", "2099-01-01"]) == 0
    assert "Recorded 2" in capsys.readouterr().out

    written = json.loads((tmp_path / ".kinemata-baseline.json").read_text())
    assert {row["registry"] for row in written["findings"]} == {
        "constants", CLAIMS_REGISTRY
    }

    assert main(["check", "-c", cfg(tmp_path)]) == 0
    assert main(["claims", "-c", cfg(tmp_path)]) == 0


def test_neither_gate_calls_the_other_half_stale(tmp_path, capsys):
    """One list, two commands, and no command runs every check.

    Unscoped, `check` would report an accepted dead reference as no longer
    present -- over a command that never read a document -- under a line
    recommending `--prune`, which is the command that would then delete it.
    """
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", 'p = root / "box.yaml"\n')
    write(tmp_path, "docs/guide.md", "The loader is `src/loader.py`.\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """)
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    assert main(["check", "-c", cfg(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no longer present" not in out
    # Silence about the other half would be its own inert signal: a reader would
    # take `check`'s report for the whole exemption list.
    assert f"belong to {CLAIMS_REGISTRY}" in out

    assert main(["claims", "-c", cfg(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "no longer present" not in out
    assert "belong to constants" in out


def test_a_registry_may_not_take_a_reserved_name(tmp_path):
    """One file, so the names in it have to mean one thing each.

    A registry answering to `claims` would file its records under a name the
    gates read as the documentation scan's, and both would decline to judge
    them: the exemption sits there reading as accepted while nothing accepts it.
    Refused rather than renamed -- guessing what the project meant is how a
    declaration stops saying what it says.
    """
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [[registry]]
        name = "claims"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """)
    with pytest.raises(ConfigError, match="reserves"):
        load(tmp_path / "kinemata.toml")


def test_a_finding_from_outside_the_scope_refuses(tmp_path):
    """Refuse, don't no-op. Counted as new it would gate CI on a check the
    caller already said this run does not cover -- a failure that is both
    silent in its cause and loud in its effect."""
    base = Baseline(path=tmp_path / "b.json", until=LATER)
    stray = [("constants", Bypass("X", "box.yaml", "src/app.py", 1, "x"))]
    with pytest.raises(BaselineError, match="does not cover"):
        base.split(stray, scope=(CLAIMS_REGISTRY,))


# -- pruning ------------------------------------------------------------------


def test_pruning_drops_a_claim_that_was_fixed(project, capsys):
    main(["baseline", "-c", cfg(project), "--record", "--until", "2099-01-01"])
    write(project, "docs/guide.md", "The loader is `src/app.py`.\n")
    write(project, "src/app.py", "x = 1\n")
    capsys.readouterr()

    assert main(["baseline", "-c", cfg(project), "--prune"]) == 0
    assert "Dropped 1 record(s)" in capsys.readouterr().out
    assert Baseline.load(project / ".kinemata-baseline.json").size == 0


def test_pruning_keeps_a_claim_that_is_still_there(project):
    """`--prune` rebuilds the file from what the scan produced, so a source it
    did not run is a set of records silently deleted. This is the assertion
    that the documentation scan is actually wired into the writing command."""
    main(["baseline", "-c", cfg(project), "--record", "--until", "2099-01-01"])
    assert main(["baseline", "-c", cfg(project), "--prune"]) == 0
    assert Baseline.load(project / ".kinemata-baseline.json").size == 1


def test_a_stale_claim_record_is_reported(project, capsys):
    main(["baseline", "-c", cfg(project), "--record", "--until", "2099-01-01"])
    write(project, "docs/guide.md", "Nothing here.\n")
    capsys.readouterr()

    assert main(["claims", "-c", cfg(project)]) == 0
    assert "1 no longer present" in capsys.readouterr().out


# -- the list still lapses -----------------------------------------------------


def lapse(project):
    path = project / ".kinemata-baseline.json"
    document = json.loads(path.read_text())
    document["until"] = "2020-01-01"
    path.write_text(json.dumps(document))


def test_claims_fails_once_the_baseline_lapses(project, capsys):
    """The date is the whole mechanism and this is not allowed a way around it.

    It fails with nothing new: the exemptions are still in force and nobody has
    looked at them since the day somebody said they would.
    """
    main(["baseline", "-c", cfg(project), "--record", "--until", "2099-01-01"])
    assert main(["claims", "-c", cfg(project)]) == 0
    capsys.readouterr()

    lapse(project)
    assert main(["claims", "-c", cfg(project)]) == 1
    assert "lapsed on 2020-01-01" in capsys.readouterr().err


def test_a_lapse_with_no_claims_in_it_is_the_other_gate_s_red(tmp_path, capsys):
    """Not a softer rule -- the same rule addressed to the right reader.

    A second command going red for a list it has no records in teaches both
    readers that red means "look somewhere else", which is how a gate stops
    being read at all.
    """
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", 'p = root / "box.yaml"\n')
    write(tmp_path, "docs/guide.md", "The loader is `src/consts.py`.\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """)
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    lapse(tmp_path)
    capsys.readouterr()

    assert main(["check", "-c", cfg(tmp_path)]) == 1
    assert "lapsed" in capsys.readouterr().err
    assert main(["claims", "-c", cfg(tmp_path)]) == 0


def test_an_overdue_promise_cannot_be_baselined_into_silence(tmp_path, capsys):
    """The failures with no site are never offered to the ratchet.

    Mechanically they have no path and line to key a record on. The deciding
    reason is that accepting one would build what both `Promise` and `Baseline`
    refuse by construction: a deferral that never lapses.
    """
    write(tmp_path, "docs/guide.md", "It will write `out/report.json`.\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]

        [[promise]]
        path = "out/report.json"
        until = "2020-01-01"
        """)
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    assert main(["claims", "-c", cfg(tmp_path)]) == 1
    assert "past their date" in capsys.readouterr().err


def test_declarations_are_not_offered_to_the_ratchet(tmp_path):
    """The same rule at the library boundary, where it is enforced."""
    write(tmp_path, "docs/guide.md", "It will write `out/report.json`.\n")
    found = verify(
        tmp_path,
        promised=[Promise(path="out/report.json", until=date(2020, 1, 1))],
    )
    assert found.overdue
    assert found.declarations_failed
    assert found.findings() == []  # nothing here for a baseline to accept
