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


def test_a_value_parity_can_translate_its_identifiers_as_well(tmp_path):
    """The second hop, and the reason it is a capability rather than a nicety.

    A declaration whose keys are spelled one way and whose values are spelled
    another needs a hop on each side of the seam. With one translation, the
    side it lands on is decided by ``field`` -- so a value run left identifiers
    untranslated and reported both as membership findings, and the only way to
    green it was to have the *oracle* re-key its own output, putting the hop
    where no reader of the config can see it. Measured on an adopter's real
    manifest before this existed.
    """
    result = compare(
        Registry("keyspace.old", extra={"keyspace.old": {"default": "THEME"}}),
        value_oracle(
            command=("{python}", "-c", "print('keyspace.new=theme')"),
            translate=Translation(pattern="^THEME$", replacement="theme"),
            translate_identifier=Translation(pattern=r"\.old$", replacement=".new"),
        ),
        tmp_path,
    )
    assert not result.failed
    assert result.undeclared == () and result.unproduced == ()


def test_a_divergence_names_the_identifier_as_translated(tmp_path):
    """The spelling the oracle printed, which is the run the reader is holding.

    Membership is compared in the translated vocabulary, so a value finding
    naming the untranslated one would make a single run speak two languages.
    """
    result = compare(
        Registry("keyspace.old", extra={"keyspace.old": {"default": "THEME"}}),
        value_oracle(
            command=("{python}", "-c", "print('keyspace.new=other')"),
            translate_identifier=Translation(pattern=r"\.old$", replacement=".new"),
        ),
        tmp_path,
    )
    (found,) = result.divergent
    assert found.identifier == "keyspace.new"


def test_translate_identifier_without_a_field_is_refused(tmp_path):
    """Two keys naming one side is a declaration saying the same thing twice.

    Without a field there is only the identifier side, and `translate` already
    reaches it -- so this is refused rather than resolved by preferring one,
    which would leave the other line inert in a config that reads as if both
    applied.
    """
    declare(tmp_path, extra=(
        'translate_identifier = { pattern = "^a$", replacement = "b" }'
    ))
    with pytest.raises(ConfigError) as caught:
        load(Path(cfg(tmp_path)))
    assert "already translates its identifiers" in str(caught.value)


def test_a_list_valued_field_says_it_was_compared_as_a_set(tmp_path):
    """The rule above is deliberate; reporting nothing about it was not.

    Measured against an adopter's real manifest, a declaration pinning an enum's
    ``choices`` against the code's own tuple printed *in agreement, agreeing on
    choices* while the oracle listed the three tiers in **reverse** -- and
    nothing in the run said the order half had gone unchecked. Every other
    suppression in this package prints a line; this was the one that did not,
    which is the same defect ``claims`` carried until a withdrawn path claim
    gained ``negated:``.
    """
    result = compare(
        Registry("app.name", extra={"app.name": {"default": ["b", "a"]}}),
        value_oracle(
            command=("{python}", "-c",
                     "print('app.name=a'); print('app.name=b')"),
        ),
        tmp_path,
    )
    assert not result.failed
    assert result.set_valued == ("app.name",)


def test_a_scalar_field_is_not_called_set_valued(tmp_path):
    """The disclosure is about lists, not about every value comparison.

    A line on every run is a line nobody reads, and the fact being disclosed --
    that an order was discarded -- is not true of a scalar.
    """
    result = compare(
        Registry("app.name", extra={"app.name": {"default": "truecolor"}}),
        value_oracle(),
        tmp_path,
    )
    assert not result.failed
    assert result.set_valued == ()


def test_the_command_discloses_a_set_comparison_on_a_CLEAN_run(tmp_path, capsys):
    """The clean run is the whole point: a failing one is already being read."""
    write(tmp_path, "keys.yaml",
          'keys:\n  app.name:\n    spec: "§1"\n    default:\n      - a\n      - b\n')
    write(tmp_path, "src/a.py", 'NAME = "app.name"\n')
    write(tmp_path, "kinemata.toml", """
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
        command = ["{python}", "-c", "print('app.name=b'); print('app.name=a')"]
        extract = '(?m)^(\\S+)=(.*)$'
        field = "default"
        authority = "declared"
        """)
    assert main(["parity", "-c", cfg(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "in agreement, agreeing on default" in out
    assert "set-valued: 1" in out
    assert "order is not part of the claim" in out


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


def test_a_blocking_cell_does_not_take_the_membership_answer_with_it(tmp_path):
    """🛑 The value half blocks; the membership half was already computed.

    Reported by an adopter for whom 18 of 66 rows hold a dict: one
    unrenderable cell threw away a membership answer that is complete,
    correct and unaffected by it. **This package's own rule is that a value
    comparison runs on top of membership, never instead of it** -- and the
    blocked return was the single place that did not honor it.

    It still fails, and it still stalls ``baseline --record``, because the
    value half genuinely did not answer. What it no longer does is report a
    tree as having no membership disagreements when it has one.
    """
    result = compare(
        Registry("app.name", extra={"app.name": {"default": {"a": 1}}}),
        value_oracle(
            command=("{python}", "-c",
                     "print('app.name=x'); print('rogue.key=y')"),
        ),
        tmp_path,
    )
    assert "not a scalar" in result.blocked
    assert result.undeclared == ("rogue.key",)


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


# -- a field addressed by path ------------------------------------------------


def test_a_field_path_reaches_an_arm_of_a_mode_keyed_map(tmp_path):
    """The shape this was built for. An adopting project states a third of its
    defaults as `{primary: ..., named: ..., standalone: ...}` and its oracle
    answers per mode, so the comparison is one arm against one run."""
    registry = Registry(
        "app.name",
        extra={"app.name": {"default": {"primary": "truecolor", "named": "ansi"}}},
    )
    result = compare(
        registry, value_oracle(field=("default", "primary")), tmp_path
    )
    assert not result.failed, result.divergent


def test_a_field_path_reports_the_arm_that_diverged(tmp_path):
    registry = Registry(
        "app.name",
        extra={"app.name": {"default": {"primary": "ansi", "named": "ansi"}}},
    )
    result = compare(
        registry, value_oracle(field=("default", "primary")), tmp_path
    )
    assert result.failed
    assert "default.primary" in str(result.divergent[0])


def test_a_dotted_string_field_is_one_key_and_is_never_split(tmp_path):
    """The property that keeps the two spellings independent. `extra` keys
    legitimately contain dots -- this package's first adopter declares
    identifiers spelled `workset.boxes` -- so splitting one would resolve an
    ambiguity by guessing, and a guess that is wrong here compares the wrong
    cell and *passes*. A string means exactly what it meant before paths."""
    registry = Registry(
        "app.name",
        extra={
            "app.name": {
                "default.primary": "truecolor",          # the flat key
                "default": {"primary": "WRONG"},          # the path
            }
        },
    )
    result = compare(registry, value_oracle(field="default.primary"), tmp_path)
    assert not result.failed, result.divergent


def test_a_path_through_a_scalar_reads_as_no_value_rather_than_an_error(tmp_path):
    """47 of the adopter's 99 manifest rows hold a scalar `default` where 18
    hold a mode-keyed map. Refusing on the scalars would make the mixed table
    unreadable, which is the thing a path exists to read."""
    registry = Registry(
        "app.name", extra={"app.name": {"default": "truecolor"}}
    )
    result = compare(
        registry, value_oracle(field=("default", "primary")), tmp_path
    )
    assert result.failed
    finding = str(result.divergent[0])
    assert "records no default.primary" in finding
    assert result.blocked == ""


def test_a_field_path_is_declared_as_a_list(tmp_path):
    declare_values(tmp_path, extra="")
    body = (tmp_path / "kinemata.toml").read_text()
    body = body.replace('field = "default"', 'field = ["default", "primary"]')
    (tmp_path / "kinemata.toml").write_text(body)
    settings = load(tmp_path / "kinemata.toml")
    assert settings.parities[0].field == ("default", "primary")


def test_an_empty_field_path_is_refused(tmp_path):
    declare_values(tmp_path)
    body = (tmp_path / "kinemata.toml").read_text()
    body = body.replace('field = "default"', "field = []")
    (tmp_path / "kinemata.toml").write_text(body)
    with pytest.raises(ConfigError, match="reaches the entry itself"):
        load(tmp_path / "kinemata.toml")


def test_a_field_path_step_that_is_not_a_key_is_refused(tmp_path):
    declare_values(tmp_path)
    body = (tmp_path / "kinemata.toml").read_text()
    body = body.replace('field = "default"', 'field = ["default", ""]')
    (tmp_path / "kinemata.toml").write_text(body)
    with pytest.raises(ConfigError, match=r"every.*step is the name of a key"):
        load(tmp_path / "kinemata.toml")


def test_an_inline_command_declared_as_a_bare_string_is_refused(tmp_path):
    """The `[command]` table has refused this since it was written; the inline
    spelling iterated the string instead, so `command = "python -m tool"` ran as
    one argument per character and died on `"p"`. What made it worse than noise
    is where the report landed: the *oracle* was named unrunnable, and a blocked
    parity oracle makes `baseline --record` refuse -- so a config typo read as
    the project's own command going missing, and disarmed the writer with it."""
    declare(tmp_path)
    body = (tmp_path / "kinemata.toml").read_text()
    body = body.replace(
        'command = ["{python}", "-c", "print(\'app.name\')"]',
        'command = "{python} -c pass"',
    )
    (tmp_path / "kinemata.toml").write_text(body)
    with pytest.raises(ConfigError, match="one argument per character"):
        load(tmp_path / "kinemata.toml")


def test_inline_args_declared_as_a_bare_string_are_refused(tmp_path):
    """`args` appends to whichever form named the command, so it is the same
    defect one line down -- and quieter, because a string here corrupts an
    argument list that is otherwise valid rather than stopping the run."""
    declare(tmp_path, extra='args = "--verbose"')
    with pytest.raises(ConfigError, match="one argument per character"):
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


# -- what the two sets are claimed to be --------------------------------------
#
# The key exists because membership could claim exactly one thing -- that the
# sets are equal -- and three of an adopter's conformance rows want a weaker or
# an inverted relation. The hazard here is the mirror of the direction hazard
# above: a relation that suppressed the wrong set would pass on the mistake it
# was declared to catch, and a relation with no anti-vacuity rule passes on an
# oracle that printed nothing at all.


def test_a_containment_does_not_report_the_side_it_allows(tmp_path, capsys):
    """`declared_contains` is "the declaration may name more", and must not
    then report the extras it just permitted."""
    declare(
        tmp_path,
        declared=("app.name", "app.extra"),
        prints=("app.name",),
        extra='relation = "declared_contains"',
    )
    assert main(["parity", "-c", cfg(tmp_path)]) == 0
    assert "every identifier the code produces is declared" in capsys.readouterr().out


def test_a_containment_still_reports_the_side_it_claims(tmp_path, capsys):
    """The negative control, and the one that matters: the relation is not a
    way to turn the check off."""
    declare(
        tmp_path,
        declared=("app.name",),
        prints=("app.name", "app.surprise"),
        extra='relation = "declared_contains"',
    )
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "app.surprise: produced, declared by nothing" in capsys.readouterr().out


def test_the_other_containment_reports_the_other_side(tmp_path, capsys):
    declare(
        tmp_path,
        declared=("app.name", "app.missing"),
        prints=("app.name",),
        extra='relation = "produced_contains"',
    )
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "app.missing: declared, produced by nothing" in capsys.readouterr().out


def test_disjoint_reports_what_is_on_both_sides(tmp_path, capsys):
    """The inverted claim: these are the rows the code must NOT produce."""
    declare(
        tmp_path,
        declared=("app.name",),
        prints=("app.name",),
        extra='relation = "disjoint"',
    )
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert "app.name: declared and produced, where neither may be" in (
        capsys.readouterr().out
    )


def test_disjoint_is_clean_when_the_code_produces_something_else(tmp_path):
    declare(
        tmp_path,
        declared=("app.name",),
        prints=("app.other",),
        extra='relation = "disjoint"',
    )
    assert main(["parity", "-c", cfg(tmp_path)]) == 0


@pytest.mark.parametrize(
    "relation", ["declared_contains", "produced_contains", "disjoint"]
)
def test_a_relation_blocks_when_the_oracle_produced_nothing(relation, tmp_path):
    """🛑 The anti-vacuity rule, written before the capability existed.

    `declared_contains` and `disjoint` are both satisfied by an oracle with
    nothing to violate them, and a vacuous run reads exactly like a clean one --
    the permissive-oracle hazard an adopting project ruled out in August. Under
    `equal` no such rule is needed, since an empty side puts every declared
    identifier in `unproduced` and fails loudly; the rule covers
    `produced_contains` anyway, because one without an exception is easier to
    hold and it turns a pile of findings into the diagnosis behind them.
    """
    declare(tmp_path, prints=(), extra=f'relation = "{relation}"')
    assert main(["parity", "-c", cfg(tmp_path)]) == 1


def test_equal_is_the_default_and_did_not_move(tmp_path):
    """Every declaration written before the key meant `equal`, so the absence
    of the key has to keep meaning exactly what it did."""
    declare(tmp_path, declared=("app.name", "app.extra"), prints=("app.name",))
    assert main(["parity", "-c", cfg(tmp_path)]) == 1
    assert oracle().relation == "equal"


def test_only_a_disjoint_run_claims_the_overlap_scope(tmp_path):
    """A scope a run cannot judge is a set of records `--prune` deletes in
    silence, so `overlapping` is claimed by the one relation that rules on it --
    while both membership directions are claimed under every relation, the run
    having computed and ruled on both.
    """
    equal = compare(*_registry_and(tmp_path, "equal"))
    disjoint = compare(*_registry_and(tmp_path, "disjoint"))
    assert parity_scope("keyspace", "overlapping") not in equal.scopes()
    assert parity_scope("keyspace", "overlapping") in disjoint.scopes()
    for result in (equal, disjoint):
        assert parity_scope("keyspace", "undeclared") in result.scopes()
        assert parity_scope("keyspace", "unproduced") in result.scopes()


def _registry_and(tmp_path, relation):
    declare(tmp_path)
    settings = load(cfg(tmp_path))
    registry = next(r for r in settings.registries if r.name == "keyspace")
    return registry, oracle(relation=relation), tmp_path


def test_an_unknown_relation_is_refused_by_name(tmp_path):
    declare(tmp_path, extra='relation = "sort-of-equal"')
    with pytest.raises(ConfigError, match="sort-of-equal"):
        load(cfg(tmp_path))


def test_a_relation_and_a_value_comparison_are_refused_together(tmp_path):
    """A value comparison pairs identifiers both sides carry, which is the
    thing a relation other than `equal` is about."""
    declare_values(tmp_path, extra='relation = "disjoint"')
    with pytest.raises(ConfigError, match="identifiers on both sides"):
        load(cfg(tmp_path))
