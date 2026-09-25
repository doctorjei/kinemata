"""The coverage lock: a parity view that narrows fails, rather than passing on
what it has left.

Reported by an adopter on 2026-09-25, as a mutation on a copy of their tree:
removing ``field`` from a view over 18 rows left ``parity`` green, checking that
the rows exist and no longer what they hold. They had retired the tests pinning
those values on the strength of that view. The baseline now records what each
view covers, and a run covering less fails.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from kinemata.baseline import Baseline, BaselineError
from kinemata.cli import main

REGISTRY = """
    [project]
    root = "."

    [[registry]]
    name = "keys"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"
    {where}

    [[registry]]
    name = "other"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"
"""

PARITY = """
    [[parity]]
    registry = "{registry}"
    command = ["{{python}}", "oracle.py"]
    extract = '(?m)^(\\S+) (.*)$'
    {extra}
"""

VALUES = 'field = "default"\nauthority = "declared"'


def write(tmp_path, *parities, where="", rows=("a.x", "b.y")):
    (tmp_path / "keys.yaml").write_text("keys:\n" + "".join(
        f'  {row}: {{default: "{row}"}}\n' for row in rows
    ))
    (tmp_path / "oracle.py").write_text(
        "print(" + repr("\n".join(f"{row} {row}" for row in rows)) + ")\n"
    )
    config = textwrap.dedent(REGISTRY.format(where=where)) + "".join(
        textwrap.dedent(PARITY.format(registry=registry, extra=extra))
        for registry, extra in parities
    )
    (tmp_path / "kinemata.toml").write_text(config)
    return str(tmp_path / "kinemata.toml")


def run(capsys, *argv):
    status = main(list(argv))
    captured = capsys.readouterr()
    return status, captured.out + captured.err


def record(capsys, path):
    status, out = run(capsys, "baseline", "--config", path, "--record", "--until", "2099-01-01")
    assert status == 0, out


def test_removing_the_field_fails_the_view_that_used_to_compare_values(tmp_path, capsys):
    """The adopter's mutation, exactly."""
    record(capsys, write(tmp_path, ("keys", VALUES)))
    status, out = run(capsys, "parity", "--config", write(tmp_path, ("keys", "")))
    assert status == 1
    assert "parity:keys:values:default:text: no longer claimed at all" in out
    assert "coverage claim(s) narrowed" in out
    # Not a disagreement: what is left agrees perfectly.
    assert "disagreement(s)" not in out


def test_a_where_that_drops_rows_fails_naming_them(tmp_path, capsys):
    record(capsys, write(tmp_path, ("keys", VALUES)))
    path = write(tmp_path, ("keys", VALUES), where='where = { id_matches = "^a" }')
    (tmp_path / "oracle.py").write_text("print('a.x a.x')\n")
    status, out = run(capsys, "parity", "--config", path)
    assert status == 1
    assert "parity:keys:values:default:text: 1 row(s) no longer covered: b.y" in out
    assert "parity:keys:members:equal: 1 row(s) no longer covered: b.y" in out


def test_deleting_the_declaration_fails(tmp_path, capsys):
    record(capsys, write(tmp_path, ("keys", VALUES), ("other", "")))
    status, out = run(capsys, "parity", "--config", write(tmp_path, ("other", "")))
    assert status == 1
    assert "parity:keys:members:equal: no longer claimed at all" in out


def test_a_changed_relation_reads_as_the_recorded_claim_gone(tmp_path, capsys):
    record(capsys, write(tmp_path, ("keys", "")))
    path = write(tmp_path, ("keys", 'relation = "declared_contains"'))
    status, out = run(capsys, "parity", "--config", path)
    assert status == 1
    assert "parity:keys:members:equal: no longer claimed at all" in out


def test_covering_more_is_never_a_finding(tmp_path, capsys):
    record(capsys, write(tmp_path, ("keys", VALUES)))
    path = write(tmp_path, ("keys", VALUES), rows=("a.x", "b.y", "c.z"))
    status, out = run(capsys, "parity", "--config", path)
    assert status == 0, out


def test_re_recording_accepts_a_narrower_claim(tmp_path, capsys):
    """The lock is accepted the way a finding is: by re-recording, in the diff."""
    record(capsys, write(tmp_path, ("keys", VALUES)))
    narrower = write(tmp_path, ("keys", ""))
    assert run(capsys, "parity", "--config", narrower)[0] == 1
    record(capsys, narrower)
    assert run(capsys, "parity", "--config", narrower)[0] == 0


def test_pruning_keeps_the_lock(tmp_path, capsys):
    """A coverage drop is not a finding that went away, so --prune leaves it."""
    path = write(tmp_path, ("keys", VALUES))
    record(capsys, path)
    before = json.loads((tmp_path / ".kinemata-baseline.json").read_text())["coverage"]
    assert run(capsys, "baseline", "--config", path, "--prune")[0] == 0
    after = json.loads((tmp_path / ".kinemata-baseline.json").read_text())["coverage"]
    assert after == before


def test_a_run_for_one_registry_does_not_judge_another_registrys_lock(tmp_path, capsys):
    record(capsys, write(tmp_path, ("keys", VALUES), ("other", "")))
    path = write(tmp_path, ("keys", ""), ("other", ""))
    assert run(capsys, "parity", "--config", path, "--registry", "other")[0] == 0
    assert run(capsys, "parity", "--config", path, "--registry", "keys")[0] == 1


def test_a_baseline_recorded_before_the_lock_locks_nothing(tmp_path, capsys):
    """Every baseline written before 2026-09-25 has no coverage, and must not
    start failing on upgrade."""
    path = write(tmp_path, ("keys", ""))
    (tmp_path / ".kinemata-baseline.json").write_text(json.dumps(
        {"version": 1, "until": "2099-01-01", "findings": []}
    ))
    status, out = run(capsys, "parity", "--config", path)
    assert status == 0, out


def test_coverage_is_read_off_the_declaration_not_the_output(tmp_path, capsys):
    """A row the code stops printing is a membership finding already; a lock
    that moved with the code's output would move on its own."""
    record(capsys, write(tmp_path, ("keys", VALUES)))
    (tmp_path / "oracle.py").write_text("print('a.x a.x')\n")
    status, out = run(capsys, "parity", "--config", str(tmp_path / "kinemata.toml"))
    assert status == 1
    assert "coverage claim(s) narrowed" not in out
    assert "b.y" in out  # reported as declared and not produced


def test_malformed_coverage_is_refused(tmp_path):
    path = tmp_path / ".kinemata-baseline.json"
    path.write_text(json.dumps(
        {"version": 1, "until": "2099-01-01", "coverage": {"k": "not a list"}}
    ))
    with pytest.raises(BaselineError, match="'coverage' must map"):
        Baseline.load(path)


# -- phase 2: the other gates ------------------------------------------------------
#
# The user's definitions, 2026-09-25: `check` locks the entries each registry can
# report a bypass of, not the files it read; `claims` locks the declared
# `[[count]]` and `[[gate]]` rows, not the documents. Every row comes from a
# declaration, so a code or prose edit never moves the lock.


def config(tmp_path, body):
    (tmp_path / "kinemata.toml").write_text(
        '[project]\nroot = "."\n\n' + textwrap.dedent(body)
    )
    return str(tmp_path / "kinemata.toml")


def test_check_fails_when_a_registry_loses_an_entry(tmp_path, capsys):
    (tmp_path / "consts.py").write_text('A_FILE = "a.yaml"\nB_FILE = "b.yaml"\n')
    (tmp_path / "more.py").write_text('C_FILE = "c.yaml"\n')
    both = """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["consts.py", "more.py"]
    """
    record(capsys, config(tmp_path, both))
    path = config(tmp_path, both.replace(', "more.py"', ""))
    status, out = run(capsys, "check", "--config", path)
    assert status == 1
    assert "check:constants:entries: 1 row(s) no longer covered: C_FILE" in out


def test_check_does_not_lock_the_files_it_read(tmp_path, capsys):
    """The user's choice: a deleted source file is not a coverage drop."""
    (tmp_path / "consts.py").write_text('A_FILE = "a.yaml"\n')
    (tmp_path / "user.py").write_text("import consts\n")
    path = config(tmp_path, """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["consts.py"]
    """)
    record(capsys, path)
    (tmp_path / "user.py").unlink()
    assert run(capsys, "check", "--config", path)[0] == 0


KEYSPACE = """
    [[registry]]
    name = "keys"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"
    syntax = '\\bbox\\.[a-z_]+\\b'
    {closed}
"""


def test_undeclared_fails_when_a_closed_registry_is_opened(tmp_path, capsys):
    (tmp_path / "keys.yaml").write_text("keys:\n  box.name: {}\n")
    record(capsys, config(tmp_path, KEYSPACE.format(closed="closed = true")))
    path = config(tmp_path, KEYSPACE.format(closed=""))
    status, out = run(capsys, "undeclared", "--config", path)
    assert status == 1
    assert "undeclared:keys: no longer claimed at all" in out


COUNT = """
    [claims]
    suffixes = [".md"]

    [[count]]
    label = "answer"
    pattern = 'answer is (\\d+)'
    command = ["{python}", "-c", "print(42)"]
    extract = '(\\d+)'
"""


def test_claims_fails_when_a_declared_count_is_deleted(tmp_path, capsys):
    (tmp_path / "README.md").write_text("The answer is 42.\n")
    record(capsys, config(tmp_path, COUNT))
    path = config(tmp_path, '[claims]\nsuffixes = [".md"]\n')
    status, out = run(capsys, "claims", "--config", path)
    assert status == 1
    assert "claims:counts: no longer claimed at all" in out


SHAPE = """
    [[registry]]
    name = "keys"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"

    [[shape]]
    registry = "keys"

      [[shape.rule]]
      name = "typed"
      when = {{ id_matches = "{guard}" }}
      present = "type"
"""


def test_shape_fails_when_a_guard_selects_fewer_entries(tmp_path, capsys):
    (tmp_path / "keys.yaml").write_text(
        "keys:\n  box.a: {type: str}\n  box.b: {type: str}\n"
    )
    record(capsys, config(tmp_path, SHAPE.format(guard="^box")))
    path = config(tmp_path, SHAPE.format(guard="^box\\\\.a"))
    status, out = run(capsys, "shape", "--config", path)
    assert status == 1
    assert "shape:keys:typed: 1 row(s) no longer covered: box.b" in out


PROBE = """
    [[probe]]
    name = "scopes"
    target = "lock_subject:check"
    cases = "lock_corpus:{cases}"
    outcome = "raises"
    refusal = "lock_subject:Refused"
"""


def test_probe_fails_when_the_corpus_hands_over_fewer_cases(tmp_path, capsys, monkeypatch):
    (tmp_path / "lock_subject.py").write_text(textwrap.dedent("""
        class Refused(Exception):
            pass


        def check(name):
            if name not in {"box", "workset"}:
                raise Refused(name)
    """))
    (tmp_path / "lock_corpus.py").write_text(textwrap.dedent("""
        from kinemata.probe import Case


        def full():
            return [Case(expect="accept", args=("box",), label="box"),
                    Case(expect="accept", args=("workset",), label="workset"),
                    Case(expect="refuse", args=("nope",), label="nope")]


        def thinned():
            return [Case(expect="accept", args=("box",), label="box"),
                    Case(expect="refuse", args=("nope",), label="nope")]
    """))
    # Named apart from test_probe.py's `subject` and `corpus`: an import is
    # cached for the whole session, and sharing a name hands that file ours.
    monkeypatch.syspath_prepend(str(tmp_path))
    record(capsys, config(tmp_path, PROBE.format(cases="full")))
    path = config(tmp_path, PROBE.format(cases="thinned"))
    status, out = run(capsys, "probe", "--config", path)
    assert status == 1
    assert "probe:scopes: 1 row(s) no longer covered: workset" in out


def test_a_rule_that_could_not_run_is_not_reported_again_as_lost_coverage(tmp_path, capsys):
    """It already fails as blocked; a second line calling it narrowed would
    send a reader after the wrong cause."""
    (tmp_path / "keys.yaml").write_text("keys:\n  box.a: {type: str}\n")
    record(capsys, config(tmp_path, SHAPE.format(guard="^box")))
    broken = SHAPE.format(guard="^box").replace(
        'present = "type"', 'holds = "no_such_module:predicate"'
    )
    status, out = run(capsys, "shape", "--config", config(tmp_path, broken))
    assert status == 1
    assert "BLOCKED" in out or "could not" in out
    assert "no longer claimed" not in out
