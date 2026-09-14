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
from kinemata.parity import (
    VALUE_DIRECTION,
    Oracle,
    Translation,
    compare,
    parity_scope,
    produced,
)


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


def declare_values(tmp_path, *, declared=(("app.name", "truecolor"),),
                   prints=(("app.name", "truecolor"),), extra=""):
    """The same, for a declaration that compares a field as well as membership."""
    rows = "".join(
        f'  {key}:\n    spec: "§1"\n    default: "{value}"\n'
        for key, value in declared
    )
    write(tmp_path, "keys.yaml", f"keys:\n{rows}")
    write(tmp_path, "src/a.py", 'NAME = "app.name"\n')
    printer = "; ".join(
        f"print({f'{key}={value}'!r})" for key, value in prints
    ) or "pass"
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
        extract = '(?m)^(\\S+)=(.*)$'
        field = "default"
        authority = "declared"
        {extra}
        """)
    return tmp_path


def value_oracle(**kwargs):
    spec = {
        "registry": "keyspace",
        "command": ("{python}", "-c", "print('app.name=truecolor')"),
        "extract": r"(?m)^(\S+)=(.*)$",
        "field": "default",
        "authority": "declared",
    }
    spec.update(kwargs)
    return Oracle(**spec)


class Registry:
    """The smallest thing `compare` needs: entries with ids."""

    name = "keyspace"

    def __init__(self, *ids, extra=None):
        self._ids = ids
        self._extra = extra or {}

    def entries(self):
        from kinemata.contract import Entry

        return [
            Entry(id=identifier, extra=self._extra.get(identifier, {}))
            for identifier in self._ids
        ]


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


def test_a_crashed_oracle_blocks_rather_than_reporting_an_empty_world(tmp_path):
    """The case the two tests above do not reach: a command that ran and died.

    A failed command prints no identifiers, and neither does a project whose
    code produces none. Read as an answer, the first one makes the entire
    declaration `unproduced` -- and because nothing is *blocked*, the refusal
    guarding `baseline --record` never fires and every declared identifier is
    accepted as an exemption. Found in the shipped tool, not reasoned about.
    """
    result = compare(
        Registry("app.name"),
        oracle(command=("{python}", "-c", "import no_such_module_here")),
        tmp_path,
    )
    assert result.failed and "exited 1" in result.blocked
    assert result.unproduced == () and result.undeclared == ()


def test_the_block_says_what_the_oracle_last_printed(tmp_path):
    """Named, never dropped -- and the reason is what makes it actionable."""
    result = compare(
        Registry("app.name"),
        oracle(command=("{python}", "-c", "import no_such_module_here")),
        tmp_path,
    )
    assert "ModuleNotFoundError" in result.blocked


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
    assert printed is not None and printed.ids == frozenset() and why == ""

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


# -- per-entry values ---------------------------------------------------------
#
# The hazard here is not the comparison, which is a string equality. It is that
# a value check can be made vacuous without looking wrong: compare only the
# identifiers both sides mention and an oracle that printed nothing reports
# agreement. So most of what follows is about the membership half staying
# attached, and about a declared value nobody can compare failing rather than
# being skipped.


def test_a_value_both_sides_agree_on_is_not_a_finding(tmp_path):
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "truecolor"}}),
        value_oracle(),
        tmp_path,
    )
    assert not result.failed and result.compared == "default"


def test_a_value_the_code_contradicts_is_a_finding(tmp_path):
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "truecolour"}}),
        value_oracle(),
        tmp_path,
    )
    (found,) = result.divergent
    assert (found.declared, found.produced) == (("truecolour",), ("truecolor",))
    assert "declared 'truecolour', code produces 'truecolor'" in str(found)


def test_membership_runs_even_when_a_field_is_compared(tmp_path):
    """The anti-vacuity half: an oracle printing nothing is not agreement.

    A value check comparing only the identifiers both sides mention would
    report a clean sheet here, which is the permissive-oracle failure an
    adopting project ruled out before this mechanism existed.
    """
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "truecolor"}}),
        value_oracle(command=("{python}", "-c", "pass")),
        tmp_path,
    )
    assert result.unproduced == ("app.name",) and result.divergent == ()
    assert result.failed


def test_an_unregistered_addition_still_walks_into_the_undeclared_direction(tmp_path):
    result = compare(
        Registry(extra={}),
        value_oracle(),
        tmp_path,
    )
    assert result.undeclared == ("app.name",)


def test_a_field_the_declaration_does_not_carry_is_a_finding(tmp_path):
    """Not a skip: half a registry silently exempt is the vacuity again."""
    result = compare(Registry("app.name"), value_oracle(), tmp_path)
    (found,) = result.divergent
    assert found.absent
    assert "the declaration records no default" in str(found)


def test_a_list_valued_field_is_compared_as_a_set(tmp_path):
    """Assert the rule, not the inventory: a reorder is not a finding."""
    result = compare(
        Registry("app.name", extra={"app.name": {"default": ["b", "a"]}}),
        value_oracle(
            command=("{python}", "-c",
                     "print('app.name=a'); print('app.name=b')"),
        ),
        tmp_path,
    )
    assert not result.failed


def test_a_set_valued_divergence_names_the_side_each_difference_is_on(tmp_path):
    result = compare(
        Registry("app.name", extra={"app.name": {"default": ["a", "gone"]}}),
        value_oracle(
            command=("{python}", "-c",
                     "print('app.name=a'); print('app.name=new')"),
        ),
        tmp_path,
    )
    (found,) = result.divergent
    assert "declared 'gone', code produces 'new'" in str(found)


def test_a_declared_value_no_oracle_could_print_blocks(tmp_path):
    """A container has no spelling two sides agree on by accident."""
    result = compare(
        Registry("app.name", extra={"app.name": {"default": {"a": 1}}}),
        value_oracle(),
        tmp_path,
    )
    assert result.failed and "not a scalar" in result.blocked


def test_a_number_is_rendered_rather_than_coerced(tmp_path):
    result = compare(
        Registry("app.name", extra={"app.name": {"default": 3}}),
        value_oracle(command=("{python}", "-c", "print('app.name=3')")),
        tmp_path,
    )
    assert not result.failed


def test_an_extract_with_one_group_blocks_when_a_field_is_compared(tmp_path):
    result = compare(
        Registry("app.name"),
        value_oracle(extract=r"(?m)^(\S+)=.*$"),
        tmp_path,
    )
    assert "one capture group" in result.blocked


def test_a_value_comparison_with_no_authority_is_refused_in_code_too(tmp_path):
    """The config refuses first; this is the answer for a direct caller."""
    with pytest.raises(ValueError, match="needs an authority"):
        compare(Registry("app.name"), value_oracle(authority=""), tmp_path)


def test_the_message_says_which_side_is_the_claim(tmp_path):
    """A divergence with no authoritative side is a finding nobody can act on."""
    declared = compare(
        Registry("app.name", extra={"app.name": {"default": "a"}}),
        value_oracle(), tmp_path,
    )
    produced_side = compare(
        Registry("app.name", extra={"app.name": {"default": "a"}}),
        value_oracle(authority="produced"), tmp_path,
    )
    assert "the code is on trial" in str(declared.divergent[0])
    assert "has not kept up" in str(produced_side.divergent[0])


def test_the_value_direction_has_its_own_scope(tmp_path):
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "a"}}),
        value_oracle(), tmp_path,
    )
    assert [scope for scope, _ in result.findings()] == [
        parity_scope("keyspace", VALUE_DIRECTION)
    ]


def test_a_membership_only_run_does_not_claim_the_value_scope(tmp_path):
    """It has not looked, so a prune must not count its records as gone."""
    membership = compare(Registry("app.name"), oracle(), tmp_path)
    values = compare(
        Registry("app.name", extra={"app.name": {"default": "truecolor"}}),
        value_oracle(), tmp_path,
    )
    assert parity_scope("keyspace", VALUE_DIRECTION) not in membership.scopes()
    assert parity_scope("keyspace", VALUE_DIRECTION) in values.scopes()


# -- the one declared translation ---------------------------------------------


def test_a_pattern_translation_applies_to_the_declared_identifiers(tmp_path):
    """A manifest writing a directory prefix the code carries without."""
    result = compare(
        Registry("home/", "canon/handbook/"),
        oracle(
            command=("{python}", "-c",
                     "print('home'); print('canon/handbook')"),
            extract=r"(?m)^(\S+)$",
            translate=Translation(pattern="/$", replacement=""),
        ),
        tmp_path,
    )
    assert not result.failed


def test_a_map_translation_applies_to_the_declared_values(tmp_path):
    """A spec's outcome vocabulary against the code's own constants."""
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "refuse"}}),
        value_oracle(
            command=("{python}", "-c", "print('app.name=REFUSE_MOUNT')"),
            translate=Translation(table={"refuse": "REFUSE_MOUNT"}),
        ),
        tmp_path,
    )
    assert not result.failed


def test_a_value_the_map_does_not_name_passes_through(tmp_path):
    """Pass-through is the exact comparison, not the absence of one."""
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "sweep"}}),
        value_oracle(
            command=("{python}", "-c", "print('app.name=sweep')"),
            translate=Translation(table={"refuse": "REFUSE_MOUNT"}),
        ),
        tmp_path,
    )
    assert not result.failed


def test_a_translation_reaches_one_side_only(tmp_path):
    """Translating the oracle's side too would be two translations, one name."""
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "home"}}),
        value_oracle(
            command=("{python}", "-c", "print('app.name=home/')"),
            translate=Translation(pattern="/$", replacement=""),
        ),
        tmp_path,
    )
    assert result.failed


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


def test_a_second_parity_on_one_registry_is_refused(tmp_path):
    """Two would compare membership twice and record one finding as two."""
    declare(tmp_path, extra="""
        [[parity]]
        registry = "keyspace"
        command = ["{python}", "-c", "pass"]
        extract = '(app\\.[a-z_]+)'
        """)
    with pytest.raises(ConfigError, match="already does"):
        load(tmp_path / "kinemata.toml")


def test_a_field_without_an_authority_is_refused(tmp_path):
    declare(tmp_path, extra='field = "default"')
    with pytest.raises(ConfigError, match="declares no authority"):
        load(tmp_path / "kinemata.toml")


def test_an_unknown_authority_is_refused(tmp_path):
    declare(tmp_path, extra='field = "default"\nauthority = "whoever"')
    with pytest.raises(ConfigError, match="it must be one of"):
        load(tmp_path / "kinemata.toml")


def test_an_authority_without_a_field_is_allowed(tmp_path):
    """Membership names its own sides, so this is optional rather than refused."""
    declare(tmp_path, extra='authority = "declared"')
    settings = load(tmp_path / "kinemata.toml")
    assert settings.parities[0].authority == "declared"


def test_a_translation_declaring_both_forms_is_refused(tmp_path):
    declare(tmp_path, extra="""
        [parity.translate]
        map = { a = "b" }
        pattern = "/$"
        replacement = ""
        """)
    with pytest.raises(ConfigError, match="at most one translation"):
        load(tmp_path / "kinemata.toml")


def test_a_pattern_translation_without_a_replacement_is_refused(tmp_path):
    """Defaulting it would silently delete text on a mistyped key."""
    declare(tmp_path, extra="""
        [parity.translate]
        pattern = "/$"
        """)
    with pytest.raises(ConfigError, match="no 'replacement'"):
        load(tmp_path / "kinemata.toml")


def test_an_unusable_translation_pattern_is_refused_at_load(tmp_path):
    declare(tmp_path, extra="""
        [parity.translate]
        pattern = "([a-"
        replacement = ""
        """)
    with pytest.raises(ConfigError, match="unusable pattern"):
        load(tmp_path / "kinemata.toml")


def test_a_translation_declaring_neither_form_is_refused(tmp_path):
    declare(tmp_path, extra="""
        [parity.translate]
        """)
    with pytest.raises(ConfigError, match="neither 'map' nor 'pattern'"):
        load(tmp_path / "kinemata.toml")


def test_an_empty_map_is_refused(tmp_path):
    """A comparison pretending to have a translation."""
    declare(tmp_path, extra="""
        [parity.translate]
        map = {}
        """)
    with pytest.raises(ConfigError, match="empty or non-table"):
        load(tmp_path / "kinemata.toml")


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


def test_a_blocked_oracle_refuses_to_rewrite_the_baseline(tmp_path, capsys):
    """A machine that merely lacks the command must not delete the exemptions.

    Running every scan is half the guarantee. An oracle that cannot answer
    produces no findings, which reads exactly like a tree where it found none,
    and both `--record` and `--prune` rebuild the file from what the run
    produced.
    """
    from kinemata.baseline import Baseline

    declare(tmp_path, declared=("app.name", "app.legacy"))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    body = (tmp_path / "kinemata.toml").read_text().replace(
        '"{python}", "-c"', '"definitely-not-a-command-here", "-c"'
    )
    (tmp_path / "kinemata.toml").write_text(body)

    assert main(["baseline", "-c", cfg(tmp_path), "--prune"]) == 2
    assert "BLOCKED" in capsys.readouterr().err
    assert Baseline.load(tmp_path / ".kinemata-baseline.json").size == 1


def test_a_blocked_oracle_refuses_to_record_too(tmp_path, capsys):
    """`--record` rebuilds the file from this run, so it loses them the same way."""
    declare(tmp_path, declared=("app.name", "app.legacy"))
    body = (tmp_path / "kinemata.toml").read_text().replace(
        '"{python}", "-c"', '"definitely-not-a-command-here", "-c"'
    )
    (tmp_path / "kinemata.toml").write_text(body)
    assert main(
        ["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"]
    ) == 2


def test_a_crashed_oracle_refuses_to_rewrite_the_baseline(tmp_path, capsys):
    """The same refusal, reached by the failure that used to walk past it.

    An oracle that cannot be *spawned* was already blocked. One that spawns,
    raises and exits non-zero was an answer, so the whole declaration read as
    unproduced and `--prune` deleted the records of findings nobody had looked
    at -- while `--record` wrote the rest of the declaration in as exempt.
    """
    from kinemata.baseline import Baseline

    declare(tmp_path, declared=("app.name", "app.legacy"))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    body = (tmp_path / "kinemata.toml").read_text().replace(
        "print('app.name')", "import no_such_module_here"
    )
    (tmp_path / "kinemata.toml").write_text(body)

    assert main(["baseline", "-c", cfg(tmp_path), "--prune"]) == 2
    assert "BLOCKED" in capsys.readouterr().err
    assert Baseline.load(tmp_path / ".kinemata-baseline.json").size == 1

    assert main(
        ["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"]
    ) == 2
    assert Baseline.load(tmp_path / ".kinemata-baseline.json").size == 1


def test_a_blocked_oracle_still_shows_the_baseline(tmp_path, capsys):
    """Reading is not writing: the refusal is about rewriting the file."""
    declare(tmp_path, declared=("app.name", "app.legacy"))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    body = (tmp_path / "kinemata.toml").read_text().replace(
        '"{python}", "-c"', '"definitely-not-a-command-here", "-c"'
    )
    (tmp_path / "kinemata.toml").write_text(body)
    capsys.readouterr()
    assert main(["baseline", "-c", cfg(tmp_path)]) == 0


# -- values, end to end through the command -----------------------------------


def test_the_command_gates_on_a_value_divergence(tmp_path, capsys):
    declare_values(tmp_path, prints=(("app.name", "truecolour"),))
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "code is on trial" in capsys.readouterr().out


def test_the_command_is_clean_when_the_values_agree(tmp_path, capsys):
    declare_values(tmp_path)
    assert main(["parity", "-c", cfg(tmp_path)]) == 0
    assert "agreeing on default" in capsys.readouterr().out


def test_recording_turns_a_failing_value_parity_green(tmp_path, capsys):
    declare_values(tmp_path, prints=(("app.name", "truecolour"),))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()
    assert main(["parity", "-c", cfg(tmp_path)]) == 0


def test_a_divergence_that_changes_re_fires_after_recording(tmp_path, capsys):
    """The record fingerprints both values, so a new disagreement is new."""
    declare_values(tmp_path, prints=(("app.name", "truecolour"),))
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    declare_values(tmp_path, prints=(("app.name", "something-else"),))
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "something-else" in capsys.readouterr().out
