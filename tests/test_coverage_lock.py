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
