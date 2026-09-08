"""The gate inventory: declaring which checks must run.

The failure being defended against is not a check that fails. It is a check that
*stops running* and reports nothing, which is indistinguishable from a clean
tree. These tests are mostly about the ways a step can be gone.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.gates import Gate, enforced


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


WORKFLOW = """
    name: checks
    jobs:
      tests:
        steps:
          - run: pytest -q
          - run: kinemata check
"""


# -- finding a step, and failing to ------------------------------------------


def test_a_declared_gate_present_in_the_workflow_verifies(tmp_path):
    write(tmp_path, ".github/workflows/checks.yml", WORKFLOW)
    report = enforced(tmp_path, (Gate(command="kinemata check"),))
    assert report.verified and not report.absent
    assert report.searched == (".github/workflows/checks.yml",)


def test_a_gate_nothing_runs_is_reported(tmp_path):
    write(tmp_path, ".github/workflows/checks.yml", WORKFLOW)
    report = enforced(tmp_path, (Gate(command="kinemata claims"),))
    assert report.failed
    assert "not found in" in str(report.absent[0])


def test_a_commented_out_step_does_not_satisfy_its_own_declaration(tmp_path):
    """The likeliest way a gate dies: commented out to unblock a merge, never
    restored. A plain text search would call that step present."""
    write(
        tmp_path,
        ".github/workflows/checks.yml",
        """
        jobs:
          tests:
            steps:
              # - run: kinemata check
              - run: pytest -q
        """,
    )
    report = enforced(tmp_path, (Gate(command="kinemata check"),))
    assert report.failed


def test_a_trailing_comment_leaves_the_step_running(tmp_path):
    """The inverse mistake: stripping from the first ``#`` anywhere would read
    a live step as commented out."""
    write(
        tmp_path,
        ".github/workflows/checks.yml",
        """
        jobs:
          tests:
            steps:
              - run: kinemata check   # the tool against its own source
        """,
    )
    assert not enforced(tmp_path, (Gate(command="kinemata check"),)).failed


def test_no_workflows_at_all_is_a_failure_that_says_so(tmp_path):
    """Distinct from "searched and did not find": a project declaring gates with
    nowhere to run them is misconfigured, not merely failing."""
    report = enforced(tmp_path, (Gate(command="kinemata check"),))
    assert report.failed
    assert "no workflow files" in str(report.absent[0])


def test_a_gate_can_name_the_file_that_must_carry_it(tmp_path):
    """``where`` is any file, not only a workflow. A project whose checks are
    run by hand can still declare that the instruction to run them exists."""
    write(tmp_path, "docs/CONVENTIONS.md", "Run `kinemata check` before pushing.\n")
    gate = Gate(command="kinemata check", where=("docs/CONVENTIONS.md",))
    assert not enforced(tmp_path, (gate,)).failed

    missing = Gate(command="kinemata check", where=("docs/ABSENT.md",))
    report = enforced(tmp_path, (missing,))
    assert report.failed
    assert "does not exist" in str(report.absent[0])


def test_any_declared_file_may_carry_it(tmp_path):
    """Projects split checks across jobs and files; requiring all of them to
    carry every gate would make the declaration unusable."""
    write(tmp_path, ".github/workflows/a.yml", "steps:\n  - run: pytest -q\n")
    write(tmp_path, ".github/workflows/b.yml", "steps:\n  - run: kinemata check\n")
    gate = Gate(command="kinemata check", where=(".github/workflows/a.yml",
                                                 ".github/workflows/b.yml"))
    assert not enforced(tmp_path, (gate,)).failed


def test_both_workflow_spellings_are_read(tmp_path):
    write(tmp_path, ".github/workflows/checks.yaml", WORKFLOW)
    assert not enforced(tmp_path, (Gate(command="kinemata check"),)).failed


# -- declaring them ----------------------------------------------------------


def test_a_gate_without_a_command_is_refused(tmp_path):
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

        [[gate]]
        note = "declares nothing"
        """,
    )
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    with pytest.raises(ConfigError):
        load(tmp_path / "kinemata.toml")


def test_declared_gates_reach_the_settings(tmp_path):
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

        [[gate]]
        command = "pytest -q"
        note = "the suite"
        """,
    )
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    (gate,) = load(tmp_path / "kinemata.toml").gates
    assert (gate.command, gate.note) == ("pytest -q", "the suite")


# -- through the gate it rides on --------------------------------------------


@pytest.fixture
def project(tmp_path):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, ".github/workflows/checks.yml", WORKFLOW)
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

        [[gate]]
        command = "kinemata check"
        note = "the tool against its own source"
        """,
    )
    return tmp_path


def cfg(project):
    return str(project / "kinemata.toml")


def test_claims_carries_the_inventory(project, capsys):
    """No fifth command: a check verifying that other checks are wired up is
    worthless if nothing guarantees it runs itself."""
    assert main(["claims", "-c", cfg(project)]) == 0
    assert "gates: 1 of 1" in capsys.readouterr().out


def test_a_gate_removed_from_ci_fails_the_build(project, capsys):
    (project / ".github/workflows/checks.yml").write_text("steps:\n  - run: pytest -q\n")
    assert main(["claims", "-c", cfg(project)]) == 1
    out = capsys.readouterr()
    assert "kinemata check" in out.out
    assert "1 declared gate(s) do not run" in out.err


def test_the_count_survives_quiet(project, capsys):
    """A declaration list shrinking to nothing is the one failure this cannot
    fail on, so the number stays in front of a reader."""
    assert main(["claims", "-c", cfg(project), "-q"]) == 0
    out = capsys.readouterr().out
    assert "gates: 1 of 1" in out
    assert "documentation claim(s) checked" not in out


def test_a_project_declaring_no_gates_says_nothing(tmp_path, capsys):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
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
    assert main(["claims", "-c", str(tmp_path / "kinemata.toml")]) == 0
    assert "gates:" not in capsys.readouterr().out


def test_the_promise_count_is_printed_even_when_quiet(tmp_path, capsys):
    """A promise is a claim nobody is checking, so the number of them is not
    optional reading -- the same rule as the gate count and the exemption
    count, and for the same reason."""
    write(tmp_path, "design.md", "It writes `out/report.json` when it runs.\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [claims]
        promised = [{ path = "out/report.json", until = "2027-01-01" }]

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["consts.py"]
        """,
    )
    write(tmp_path, "consts.py", 'BOX_META_FILE = "box.yaml"\n')

    assert main(["claims", "-c", str(tmp_path / "kinemata.toml"), "-q"]) == 0
    assert "promised: 1 declared, 1 claim(s) held open" in capsys.readouterr().out


# -- a command declared once, used by several counts --------------------------


def _count_config(tmp_path, body):
    write(tmp_path, "consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        body + """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["consts.py"]
        """,
    )
    return tmp_path / "kinemata.toml"


def test_one_declared_command_settles_several_counts(tmp_path):
    """This package's own config format forced the duplication it exists to
    catch: `[[count]]` binds one command to one number and TOML cannot share a
    value, so a real integration carried eight inline programs of which four
    were distinct -- one copied three times, differing only in its argument."""
    write(tmp_path, "one.md", "a\nb\nc\n")
    write(tmp_path, "two.md", "a\nb\n")
    write(tmp_path, "doc.md", "one holds **3 lines** and two holds **2 lines**.\n")
    config = _count_config(tmp_path, """
        [command]
        lines = ["wc", "-l"]

        [[count]]
        label = "one"
        pattern = 'one holds \\*\\*(\\d+) lines\\*\\*'
        run = "lines"
        args = ["one.md"]
        extract = '(\\d+)'

        [[count]]
        label = "two"
        pattern = 'two holds \\*\\*(\\d+) lines\\*\\*'
        run = "lines"
        args = ["two.md"]
        extract = '(\\d+)'
        """)
    settings = load(config)
    assert [spec.command for spec in settings.counts] == [
        ("wc", "-l", "one.md"), ("wc", "-l", "two.md"),
    ]
    assert main(["claims", "-c", str(config)]) == 0

    write(tmp_path, "doc.md", "one holds **9 lines** and two holds **2 lines**.\n")
    assert main(["claims", "-c", str(config)]) == 1


def test_a_count_that_runs_an_undeclared_command_is_refused(tmp_path):
    """Refused rather than defaulted, like an unknown `strip` transform: the
    alternative is a count that looks configured and settles nothing."""
    config = _count_config(tmp_path, """
        [command]
        lines = ["wc", "-l"]

        [[count]]
        label = "one"
        pattern = '(\\d+) lines'
        run = "words"
        extract = '(\\d+)'
        """)
    with pytest.raises(ConfigError, match="which no \\[command\\] declares"):
        load(config)


def test_a_count_cannot_name_its_oracle_twice(tmp_path):
    """`command` and `run` are two answers to one question, and a config that
    gives both has not decided which oracle is authoritative."""
    config = _count_config(tmp_path, """
        [command]
        lines = ["wc", "-l"]

        [[count]]
        label = "one"
        pattern = '(\\d+) lines'
        command = ["wc", "-l", "one.md"]
        run = "lines"
        extract = '(\\d+)'
        """)
    with pytest.raises(ConfigError, match="both 'command' and 'run'"):
        load(config)


def test_a_command_declared_as_a_bare_string_is_refused(tmp_path):
    """TOML takes it happily and it would run as a one-character program."""
    config = _count_config(tmp_path, """
        [command]
        lines = "wc -l"

        [[count]]
        label = "one"
        pattern = '(\\d+) lines'
        run = "lines"
        extract = '(\\d+)'
        """)
    with pytest.raises(ConfigError, match="non-empty list of arguments"):
        load(config)


def test_a_promise_date_must_be_a_date(tmp_path):
    """Refused rather than ignored: a misparsed date would leave a deferral that
    looks bounded and lapses never."""
    config = _count_config(tmp_path, """
        [claims]
        promised = [{ path = "out/report.json", until = "next quarter" }]
        """)
    with pytest.raises(ConfigError, match="not a date"):
        load(config)


def test_a_promise_must_name_the_date_it_lapses(tmp_path):
    """The shorthand this replaced -- a bare path -- said nothing about when the
    deferral stops holding, so it never did. A promise that cannot lapse is an
    ignore list with a better name."""
    config = _count_config(tmp_path, """
        [claims]
        promised = ["out/report.json"]
        """)
    with pytest.raises(ConfigError, match="date its deferral lapses"):
        load(config)


def test_a_promise_with_an_unknown_key_is_refused(tmp_path):
    """A misspelled `until` is reported as the typo it is, not as a missing
    field -- being told `until` is missing sends a reader to stare at a line
    where they believe they wrote it."""
    config = _count_config(tmp_path, """
        [claims]
        promised = [{ path = "out/report.json", untl = "2026-12-01" }]
        """)
    with pytest.raises(ConfigError, match="which means nothing here"):
        load(config)


def test_a_toml_native_date_is_accepted(tmp_path):
    """TOML parses a bare 2026-12-01 into a date object and a quoted one into a
    string; both are the same declaration to a reader, so both work."""
    config = _count_config(tmp_path, """
        [claims]
        promised = [{ path = "out/report.json", until = 2026-12-01 }]
        """)
    (promise,) = load(config).promised
    assert promise.until.isoformat() == "2026-12-01"
