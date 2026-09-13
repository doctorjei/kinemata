"""Membership parity: a declaration against what the code actually produces.

The mechanism exists because every other catch here has to *find* something in
text, and both of its known weaknesses follow from that -- a mention read as a
use, and a closed-world question nobody can ask without an identifier
recognizer. An oracle removes the search, so the tests below are mostly about
the two directions staying apart and about an oracle that cannot answer being a
failure rather than a quiet pass.

The hazard specific to this subject is direction. "Declared, produced by
nothing" and "produced, declared by nothing" are opposite mistakes with opposite
fixes, and a check that collapsed them would send a reader to delete a
declaration the code still needs.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.parity import Oracle, compare, parity_scope, produced


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def cfg(project):
    return str(project / "kinemata.toml")


def declare(tmp_path, *, declared=("app.name",), prints=("app.name",),
            extra=""):
    """A keyspace registry and an oracle printing what the code produces."""
    rows = "".join(
        f"  {key}:\n    spec: \"§1\"\n" for key in declared
    )
    write(tmp_path, "keys.yaml", f"keys:\n{rows}")
    write(tmp_path, "src/a.py", "NAME = \"app.name\"\n")
    printer = "; ".join(f"print({key!r})" for key in prints) or "pass"
    write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."

        [[registry]]
        name = "keyspace"
        kind = "yaml-mapping"
        source = "keys.yaml"
        section = "keys"
        clause_field = "spec"
        syntax = '\\bapp\\.[a-z_]+'

        [[parity]]
        registry = "keyspace"
        command = ["{{python}}", "-c", "{printer}"]
        extract = '(app\\.[a-z_]+)'
        {extra}
        """)
    return tmp_path


def oracle(**kwargs):
    spec = {
        "registry": "keyspace",
        "command": ("{python}", "-c", "print('app.name')"),
        "extract": r"(app\.[a-z_]+)",
    }
    spec.update(kwargs)
    return Oracle(**spec)


class Registry:
    """The smallest thing `compare` needs: entries with ids."""

    name = "keyspace"

    def __init__(self, *ids):
        self._ids = ids

    def entries(self):
        from kinemata.contract import Entry

        return [Entry(id=identifier) for identifier in self._ids]


# -- the two directions -------------------------------------------------------


def test_agreement_is_not_a_finding(tmp_path):
    result = compare(Registry("app.name"), oracle(), tmp_path)
    assert not result.failed
    assert (result.declared, result.produced) == (1, 1)


def test_produced_and_undeclared_is_a_finding(tmp_path):
    """Catch A's question, answered without an identifier recognizer."""
    result = compare(Registry(), oracle(), tmp_path)
    assert result.undeclared == ("app.name",)
    assert result.unproduced == ()


def test_declared_and_unproduced_is_a_finding(tmp_path):
    """The disuse question, answered without mistaking a mention for a use."""
    result = compare(Registry("app.name", "app.legacy"), oracle(), tmp_path)
    assert result.unproduced == ("app.legacy",)
    assert result.undeclared == ()


def test_the_two_directions_get_different_scopes(tmp_path):
    """Opposite mistakes with opposite fixes; a shared scope would merge them."""
    result = compare(Registry("app.legacy"), oracle(), tmp_path)
    scopes = {scope for scope, _ in result.findings()}
    assert scopes == {
        parity_scope("keyspace", "undeclared"),
        parity_scope("keyspace", "unproduced"),
    }


def test_a_run_declares_both_scopes_even_when_one_is_clean(tmp_path):
    """A scope missing from a run is one `--prune` deletes for never looking."""
    result = compare(Registry("app.name"), oracle(), tmp_path)
    assert set(result.scopes()) == {
        parity_scope("keyspace", "undeclared"),
        parity_scope("keyspace", "unproduced"),
    }


# -- an oracle that cannot answer ---------------------------------------------


def test_an_oracle_that_cannot_run_blocks_rather_than_passing(tmp_path):
    result = compare(Registry("app.name"),
                     oracle(command=("definitely-not-a-command-here",)),
                     tmp_path)
    assert result.failed and "could not be run" in result.blocked
    assert result.undeclared == () and result.unproduced == ()


def test_an_oracle_that_never_returns_is_killed_and_blocks(tmp_path):
    result = compare(
        Registry("app.name"),
        oracle(command=("{python}", "-c", "import time; time.sleep(30)")),
        tmp_path,
        timeout=0.5,
    )
    assert result.failed and "did not finish within 0.5s" in result.blocked


def test_an_extract_with_no_capture_group_blocks(tmp_path):
    """Refused, not treated as an empty world."""
    result = compare(Registry("app.name"), oracle(extract=r"app\.[a-z_]+"),
                     tmp_path)
    assert "no capture group" in result.blocked


def test_an_oracle_printing_nothing_is_an_empty_set_not_a_block(tmp_path):
    """A real answer: everything declared is unproduced, which is a finding."""
    printed, why = produced(
        oracle(command=("{python}", "-c", "pass")), tmp_path
    )
    assert printed == frozenset() and why == ""

    result = compare(Registry("app.name"),
                     oracle(command=("{python}", "-c", "pass")), tmp_path)
    assert result.unproduced == ("app.name",) and not result.blocked


# -- the comparison is exact --------------------------------------------------


def test_case_and_spacing_are_not_normalized_away(tmp_path):
    """A normalization that is wrong does not fail; it passes."""
    result = compare(
        Registry("app.name"),
        oracle(command=("{python}", "-c", "print('app.NAME')"),
               extract=r"(app\.[A-Za-z_]+)"),
        tmp_path,
    )
    assert result.undeclared == ("app.NAME",)
    assert result.unproduced == ("app.name",)


def test_edge_whitespace_is_stripped_from_the_oracle(tmp_path):
    """The newline a command's output ends in is not something it asserts."""
    result = compare(
        Registry("app.name"),
        oracle(command=("{python}", "-c", r"print('  app.name  ')"),
               extract=r"( +app\.[a-z_]+ +)"),
        tmp_path,
    )
    assert not result.failed


# -- the config surface -------------------------------------------------------


def test_a_parity_naming_an_unknown_registry_is_refused(tmp_path):
    declare(tmp_path)
    body = (tmp_path / "kinemata.toml").read_text().replace(
        'registry = "keyspace"\ncommand', 'registry = "nope"\ncommand'
    )
    (tmp_path / "kinemata.toml").write_text(body)
    with pytest.raises(ConfigError, match="no \\[\\[registry\\]\\] declares"):
        load(tmp_path / "kinemata.toml")


def test_a_parity_missing_its_extract_is_refused(tmp_path):
    declare(tmp_path)
    body = (tmp_path / "kinemata.toml").read_text()
    body = "\n".join(
        line for line in body.splitlines() if not line.strip().startswith("extract")
    )
    (tmp_path / "kinemata.toml").write_text(body)
    with pytest.raises(ConfigError, match="is missing extract"):
        load(tmp_path / "kinemata.toml")


def test_a_parity_declaration_alone_is_a_declared_check(tmp_path):
    """A config carrying only this one still configures something real."""
    settings = load(Path(declare(tmp_path) / "kinemata.toml"))
    assert len(settings.parities) == 1
    assert settings.parities[0].registry == "keyspace"


# -- the command --------------------------------------------------------------


def test_the_command_refuses_when_nothing_declares_an_oracle(tmp_path):
    """Exit 2, the way `context` refuses a project with no ceiling."""
    write(tmp_path, "keys.yaml", "keys:\n  app.name:\n    spec: \"§1\"\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [[registry]]
        name = "keyspace"
        kind = "yaml-mapping"
        source = "keys.yaml"
        section = "keys"
        clause_field = "spec"
        """)
    assert main(["parity", "-c", cfg(tmp_path)]) == 2


def test_the_command_gates_on_a_disagreement(tmp_path, capsys):
    declare(tmp_path, declared=("app.name", "app.legacy"))
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "app.legacy" in capsys.readouterr().out


def test_the_command_is_clean_when_both_sides_agree(tmp_path):
    declare(tmp_path)
    assert main(["parity", "-c", cfg(tmp_path)]) == 0


def test_a_blocked_oracle_fails_the_command(tmp_path):
    declare(tmp_path)
    body = (tmp_path / "kinemata.toml").read_text().replace(
        '"{python}", "-c"', '"definitely-not-a-command-here", "-c"'
    )
    (tmp_path / "kinemata.toml").write_text(body)
    assert main(["parity", "-c", cfg(tmp_path)]) == 1


# -- the ratchet --------------------------------------------------------------


def test_recording_turns_a_failing_parity_green(tmp_path, capsys):
    declare(tmp_path, declared=("app.name", "app.legacy"))
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    capsys.readouterr()

    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()
    assert main(["parity", "-c", cfg(tmp_path)]) == 0


def test_a_new_disagreement_still_fails_after_recording(tmp_path, capsys):
    """The ratchet: adopted on a tree that does not satisfy it, and still a gate."""
    declare(tmp_path, declared=("app.name", "app.legacy"))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    declare(tmp_path, declared=("app.name", "app.legacy", "app.newer"))
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "app.newer" in capsys.readouterr().out


def test_the_baseline_writer_runs_the_parity_scan(tmp_path, capsys):
    """A source the writing command does not run is records `--prune` deletes."""
    declare(tmp_path, declared=("app.name", "app.legacy"))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    from kinemata.baseline import Baseline

    accepted = Baseline.load(tmp_path / ".kinemata-baseline.json")
    assert any(
        item.registry.startswith("parity:") and item.entry_id == "app.legacy"
        for item in accepted.accepted
    )
