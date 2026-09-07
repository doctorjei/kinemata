"""The ratchet: what it accepts, what it refuses to absorb, and what it costs.

The design question in a baseline is not whether it can silence findings -- that
is trivial -- but what it treats as *the same finding* across commits. Too
coarse and it absorbs new bypasses silently; too fine and ordinary edits look
like regressions, which trains people to re-record and absorbs everything. These
tests pin that boundary from both sides.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from kinemata.baseline import Baseline, BaselineError, record
from kinemata.bypass import Bypass
from kinemata.cli import main


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def hit(path="src/app.py", line=10, text='p = root / "box.yaml"', entry="BOX_META_FILE"):
    return Bypass(
        entry_id=entry,
        antipattern=r"box\.yaml",
        path=path,
        line=line,
        text=text,
    )


def one(*hits):
    """Findings tagged with the registry that produced them."""
    return [("constants", h) for h in hits]


# -- what counts as the same finding ------------------------------------------


def test_a_finding_that_moved_down_the_file_is_still_the_same_finding(tmp_path):
    """The churn case. Any edit above a bypass shifts its line number.

    A baseline that reported those as new findings would be re-recorded
    reflexively, and a re-record absorbs whatever else arrived in that commit.
    """
    base = record(tmp_path / "b.json", one(hit(line=10)))
    split = base.split(one(hit(line=847)))
    assert not split.new
    assert len(split.accepted) == 1


def test_re_indenting_does_not_make_a_finding_new(tmp_path):
    """Wrapping a block in an ``if`` re-indents every line inside it."""
    base = record(tmp_path / "b.json", one(hit(text='p = root / "box.yaml"')))
    split = base.split(one(hit(text='        p = root / "box.yaml"')))
    assert not split.new


def test_the_same_bypass_in_another_file_is_a_new_finding(tmp_path):
    """Scope. kanibako-cli's own tripwire watched one module and missed eight
    sites in six others (``42ece129``); a baseline keyed without the path would
    reproduce that failure on purpose."""
    base = record(tmp_path / "b.json", one(hit(path="src/app.py")))
    split = base.split(one(hit(path="src/other.py")))
    assert len(split.new) == 1
    assert len(split.stale) == 1


def test_a_fourth_copy_of_three_accepted_sites_is_an_increase(tmp_path):
    """Multiplicity is recorded, so identical sites cannot hide behind each
    other. A single record exempting a file's every future repetition of the
    same literal is the allowlist absorbing new findings."""
    text = 'p = root / "box.yaml"'
    base = record(tmp_path / "b.json", one(*[hit(line=n, text=text) for n in (1, 2, 3)]))
    assert base.size == 3
    assert len(base.accepted) == 1  # one record, count 3

    split = base.split(one(*[hit(line=n, text=text) for n in (1, 2, 3, 4)]))
    assert len(split.new) == 1
    assert len(split.accepted) == 3


def test_rewriting_the_line_reports_it_as_new(tmp_path):
    """A cost of keying on the matched text, stated rather than hidden.

    Editing the line a bypass sits on produces one new finding for a bypass that
    was already accepted. That is the price of telling two different bypasses of
    the same entry in the same file apart, and it is paid in the direction that
    over-reports. Measured against real history in
    ``test_corpus_validation.py``.
    """
    base = record(tmp_path / "b.json", one(hit(text='p = root / "box.yaml"')))
    split = base.split(one(hit(text='p = root / "box.yaml" if flag else None')))
    assert len(split.new) == 1


# -- driving it down ----------------------------------------------------------


def test_a_fixed_bypass_becomes_stale_and_is_not_an_error(tmp_path):
    """Work that removes a finding must never fail the build."""
    base = record(tmp_path / "b.json", one(hit(), hit(path="src/other.py")))
    split = base.split(one(hit()))
    assert not split.new
    assert len(split.stale) == 1
    assert split.stale[0].path == "src/other.py"


def test_size_counts_exemptions_not_records(tmp_path):
    text = 'p = root / "box.yaml"'
    base = record(tmp_path / "b.json", one(*[hit(line=n, text=text) for n in (1, 2)]))
    assert (len(base.accepted), base.size) == (1, 2)


# -- the file -----------------------------------------------------------------


def test_a_baseline_survives_a_round_trip(tmp_path):
    path = tmp_path / "b.json"
    record(path, one(hit(), hit(line=11, text='q = "box.yaml"'))).save()
    loaded = Baseline.load(path)
    assert loaded.size == 2
    assert not loaded.split(one(hit(line=99), hit(line=100, text='q = "box.yaml"'))).new


def test_the_file_says_what_it_exempts(tmp_path):
    """Readable records, not digests: a reviewer who cannot see what is being
    exempted cannot catch a baseline absorbing real findings."""
    path = tmp_path / "b.json"
    record(path, one(hit())).save()
    written = json.loads(path.read_text())["findings"][0]
    assert written["entry"] == "BOX_META_FILE"
    assert written["path"] == "src/app.py"
    assert "box.yaml" in written["text"]


def test_a_missing_baseline_is_empty_but_an_unreadable_one_raises(tmp_path):
    """Never recorded is a normal state. Cannot be read is not: an unparseable
    baseline could mean no exemptions or every exemption, and guessing beats
    stopping in neither direction."""
    assert Baseline.load(tmp_path / "absent.json").size == 0

    broken = tmp_path / "broken.json"
    broken.write_text("{not json")
    with pytest.raises(BaselineError):
        Baseline.load(broken)


def test_an_unknown_format_version_raises(tmp_path):
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"version": 99, "findings": []}))
    with pytest.raises(BaselineError):
        Baseline.load(path)


def test_a_malformed_record_raises_rather_than_being_skipped(tmp_path):
    """Skipping it would silently narrow the exemption list, which fails in the
    safe direction -- but it also hides that the file is damaged."""
    path = tmp_path / "b.json"
    path.write_text(json.dumps({"version": 1, "findings": [{"entry": "X"}]}))
    with pytest.raises(BaselineError):
        Baseline.load(path)


# -- the command line ---------------------------------------------------------


@pytest.fixture
def project(tmp_path):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", 'p = root / "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """,
    )
    return tmp_path


def cfg(project):
    return str(project / "kinemata.toml")


def test_recording_turns_a_failing_gate_green(project, capsys):
    """The whole point: a codebase already failing the gate can adopt it."""
    assert main(["check", "-c", cfg(project)]) == 1
    capsys.readouterr()

    assert main(["baseline", "-c", cfg(project), "--record"]) == 0
    assert "Recorded 1" in capsys.readouterr().out

    assert main(["check", "-c", cfg(project)]) == 0


def test_check_prints_the_size_of_the_exemption_list_every_run(project, capsys):
    """An allowlist nobody reads the size of is how an allowlist rots."""
    main(["baseline", "-c", cfg(project), "--record"])
    capsys.readouterr()

    assert main(["check", "-c", cfg(project), "-q"]) == 0
    assert "baseline: 1 accepted finding(s)" in capsys.readouterr().out


def test_a_new_bypass_fails_and_the_accepted_one_stays_quiet(project, capsys):
    main(["baseline", "-c", cfg(project), "--record"])
    write(project, "src/later.py", 'q = open("box.yaml")\n')
    capsys.readouterr()

    assert main(["check", "-c", cfg(project)]) == 1
    out = capsys.readouterr()
    assert "later.py" in out.out
    assert "app.py" not in out.out          # accepted, so not reported
    assert "1 new bypass(es)" in out.err


def test_status_is_the_default_and_writes_nothing(project, capsys):
    """Recording is how the gate goes quiet, so it is never what happens when
    somebody types the noun to see what it means."""
    assert main(["baseline", "-c", cfg(project)]) == 0
    assert not (project / ".kinemata-baseline.json").exists()
    assert "would accept 1 finding(s)" in capsys.readouterr().out


def test_pruning_drops_records_whose_finding_is_gone(project, capsys):
    main(["baseline", "-c", cfg(project), "--record"])
    (project / "src/app.py").write_text("p = root / meta_file\n")
    capsys.readouterr()

    assert main(["baseline", "-c", cfg(project), "--prune"]) == 0
    assert "Dropped 1 record(s)" in capsys.readouterr().out
    assert Baseline.load(project / ".kinemata-baseline.json").size == 0


def test_recording_says_how_much_it_newly_accepted(project, capsys):
    main(["baseline", "-c", cfg(project), "--record"])
    write(project, "src/later.py", 'q = open("box.yaml")\n')
    capsys.readouterr()

    assert main(["baseline", "-c", cfg(project), "--record"]) == 0
    out = capsys.readouterr().out
    assert "(+1 against the previous baseline)" in out
    assert "1 finding(s) newly accepted" in out


def test_review_ignores_the_baseline(project, capsys):
    """The ratchet governs the gate, not the advice. An advisory scan that hid
    known problems would be lying about the tree."""
    main(["baseline", "-c", cfg(project), "--record"])
    capsys.readouterr()

    assert main(["review", "-c", cfg(project)]) == 0
    assert "BOX_META_FILE" in capsys.readouterr().out


def test_record_and_prune_together_are_refused(project, capsys):
    assert main(["baseline", "-c", cfg(project), "--record", "--prune"]) == 2
    assert "pick one" in capsys.readouterr().err


def test_an_unreadable_baseline_stops_the_gate(project, capsys):
    (project / ".kinemata-baseline.json").write_text("{not json")
    assert main(["check", "-c", cfg(project)]) == 2
    assert "error" in capsys.readouterr().err


def test_a_partial_scan_may_not_rewrite_the_baseline(project, capsys):
    """A baseline describes the project, so a scan of one registry or one
    directory cannot author it. Rewriting from a partial scan would drop every
    record the scan could not produce -- the exemption list shrinks, `check`
    goes red on untouched code, and re-recording looks like the fix."""
    main(["baseline", "-c", cfg(project), "--record"])
    capsys.readouterr()

    assert main(["baseline", "-c", cfg(project), "--record", "-r", "constants"]) == 2
    assert "refusing to rewrite" in capsys.readouterr().err

    assert main(["baseline", "-c", cfg(project), "--prune", "src"]) == 2
    assert "refusing to rewrite" in capsys.readouterr().err

    assert Baseline.load(project / ".kinemata-baseline.json").size == 1


def test_a_narrowed_check_does_not_call_the_rest_of_the_baseline_stale(project, capsys):
    """Findings the scan never looked for are absent, not fixed."""
    main(["baseline", "-c", cfg(project), "--record"])
    capsys.readouterr()

    assert main(["check", "-c", cfg(project), "src/consts.py"]) == 0
    assert "no longer present" not in capsys.readouterr().out
