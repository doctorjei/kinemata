"""A declaration checked against its own shape.

The mechanism exists because an adopting project's 31 conformance functions
asserting things about their *own registry* -- a field set, a vocabulary, an axis
that is a cross product -- had no expression here at all, and it was the largest
unmet class of the 125 measured on 2026-09-14.

The hazard specific to this subject is **vacuity**, and it is sharper here than
anywhere else in this package because a rule brings its own way to check
nothing: a guard that selects no entry runs, reports no violation, and looks
exactly like a rule that is satisfied. So the cases below are mostly about that
staying visible, and about the predicate escape not becoming a way to smuggle a
pass in from the project's own code.
"""

from __future__ import annotations

import re
import textwrap

import pytest

from kinemata.baseline import Accepted, Baseline
from kinemata.cli import main
from kinemata.config import SHAPE_CLAIMS, ConfigError, load
from kinemata.contract import Entry
from kinemata.shape import (
    ENTRY_OPERATORS,
    SET_OPERATORS,
    Condition,
    Predicate,
    Rule,
    Shape,
    ShapeError,
    examine,
    is_shape_scope,
    shape_scope,
    survey,
)


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


class Rows:
    """A registry of whatever entries a case needs."""

    name = "keys"
    closed = False

    def __init__(self, *entries):
        self._entries = list(entries)

    def entries(self):
        return list(self._entries)


def entry(name, **extra):
    return Entry(id=name, extra=extra)


def judge(rule, *entries):
    """One rule against some entries, as the single `Judged` it produces."""
    return examine(Rows(*entries), [rule]).judged[0]


def rule(name="a rule", **kwargs):
    claim = kwargs.pop("claim")
    return Rule(name=name, claim=claim, guard=kwargs.pop("guard", None))


# -- the operators ------------------------------------------------------------


def test_present_and_absent_read_a_field_by_name():
    rows = (entry("a", type="str"), entry("b"))
    got = judge(rule(claim=Condition("present", "type")), *rows)
    assert [hit.name for hit in got.violations] == ["b"]
    got = judge(rule(claim=Condition("absent", "type")), *rows)
    assert [hit.name for hit in got.violations] == ["a"]


def test_equals_compares_exactly_and_falsehood_is_a_value():
    """``equals = false`` is a claim, not an absent operator.

    The case that forced ``in spec`` rather than truthiness at the config layer:
    a declaration really does pin a flag to ``false``, and reading that as "no
    claim given" would drop the rule while the config still looked like it had
    one.
    """
    rows = (entry("a", internal=False), entry("b", internal=True))
    got = judge(rule(claim=Condition("equals", False, "internal")), *rows)
    assert [hit.name for hit in got.violations] == ["b"]


def test_choices_is_a_declared_vocabulary():
    rows = (entry("a", kind="str"), entry("b", kind="bogus"))
    got = judge(rule(claim=Condition("choices", ["str", "int"], "kind")), *rows)
    assert [hit.name for hit in got.violations] == ["b"]


def test_matches_reads_a_field_and_id_matches_reads_the_identifier():
    rows = (entry("alpha", root="<box_dir>"), entry("beta", root="/real/path"))
    got = judge(rule(claim=Condition("matches", "^<.+>$", "root")), *rows)
    assert [hit.name for hit in got.violations] == ["beta"]
    # The same operator with no field named is the identifier -- which is why
    # the config spells that `id_matches` instead of leaving the field off.
    got = judge(rule(claim=Condition("matches", "^al")), *rows)
    assert [hit.name for hit in got.violations] == ["beta"]


def test_each_matches_holds_every_item_of_a_list_field():
    rows = (
        entry("a", allow=["home/", "canon/"]),
        entry("b", allow=["home/", "notes.md"]),
    )
    got = judge(rule(claim=Condition("each_matches", "/$", "allow")), *rows)
    assert [hit.name for hit in got.violations] == ["b"]


def test_contains_asks_for_one_member_of_a_list_field():
    rows = (entry("a", filters=["valid_key", "tiers"]), entry("b", filters=["tiers"]))
    got = judge(rule(claim=Condition("contains", "valid_key", "filters")), *rows)
    assert [hit.name for hit in got.violations] == ["b"]


def test_exists_names_the_ids_that_are_missing():
    got = judge(
        rule(claim=Condition("exists", ["keys", "policy"])),
        entry("keys"),
    )
    assert [hit.name for hit in got.violations] == ["policy"]


def test_keys_of_compares_both_ways_and_says_which_side():
    rows = (
        entry("cells", bind={}, mask={}, extra_row={}),
        entry("kinds", value=["bind", "mask", "copy"]),
    )
    got = judge(rule(claim=Condition("keys_of", "kinds", "cells")), *rows)
    said = [hit.name for hit in got.violations]
    assert "extra_row: keyed, not a value of kinds" in said
    assert "copy: a value of kinds, not keyed" in said


def test_exhausts_finds_the_dead_token():
    """An outcome nobody writes is a promise the declaration does not keep."""
    rows = (
        entry("outcomes", value=["refuse", "sweep", "nest"]),
        entry("bind", outcome="refuse"),
        entry("mask", outcome="sweep"),
    )
    got = judge(rule(claim=Condition("exhausts", "outcomes", "outcome")), *rows)
    assert [hit.name for hit in got.violations] == ["nest: declared, used by nothing"]


def test_a_set_operator_naming_no_such_entry_is_blocked_not_silent():
    got = judge(rule(claim=Condition("exhausts", "nowhere", "outcome")), entry("a"))
    assert got.blocked
    assert got.failed
    assert "nowhere" in got.blocked


def test_keys_of_refuses_a_field_that_has_no_keys():
    rows = (entry("kinds", value=["bind"]), entry("flat", value=["bind"]))
    got = judge(rule(claim=Condition("keys_of", "flat", "kinds")), *rows)
    assert "has no keys to compare" in got.blocked


# -- the guard ----------------------------------------------------------------


def test_a_guard_narrows_the_group_and_the_narrowing_is_reported():
    rows = (
        entry("a", user_key=False, value="x"),
        entry("b", user_key=True, default="y"),
        entry("c", user_key=False),
    )
    got = judge(
        rule(
            claim=Condition("present", "value"),
            guard=Condition("equals", False, "user_key"),
        ),
        *rows,
    )
    assert got.examined == 2
    assert [hit.name for hit in got.violations] == ["c"]


def test_an_unguarded_rule_judges_every_entry():
    got = judge(rule(claim=Condition("present", "type")), entry("a"), entry("b"))
    assert got.examined == 2


# -- vacuity, which is the whole point ----------------------------------------


def test_a_rule_that_selects_nothing_fails():
    """⚑ The property the predicate escape rests on.

    Revert :attr:`kinemata.shape.Judged.vacuous` to ``False`` and this case is
    what goes red -- there is no violation to catch it, because the rule found
    no entry to be wrong about.
    """
    got = judge(
        rule(
            claim=Condition("present", "type"),
            guard=Condition("present", "nonesuch"),
        ),
        entry("a", type="str"),
    )
    assert got.examined == 0
    assert got.vacuous
    assert got.failed
    assert not got.violations


def test_a_rule_over_an_empty_registry_is_vacuous_too():
    """The emptiness belongs to the declaration either way.

    Deliberately NOT the behavior :mod:`kinemata.interpose` has for a funnel
    nothing crossed, where zero is reported and does not fail: a funnel's
    coverage is the project's suite's, and a rule's group is entirely present
    the moment the rule runs.
    """
    got = examine(Rows(), [rule(claim=Condition("present", "type"))]).judged[0]
    assert got.vacuous and got.failed


def test_a_vacuous_rule_does_not_claim_its_scope():
    """So that ``--prune`` cannot delete records a run never looked at."""
    result = examine(
        Rows(entry("a")),
        [
            rule("real", claim=Condition("present", "id")),
            rule(
                "vacuous",
                claim=Condition("present", "type"),
                guard=Condition("present", "nonesuch"),
            ),
        ],
    )
    assert result.scopes() == (shape_scope("keys", "real"),)
    assert result.unjudged() == ["vacuous: examined no entry"]


def test_a_set_operator_over_nothing_is_vacuous_on_the_other_branch():
    """The third way to examine nothing, and it takes a different code path.

    A set rule never has a guard, so a sentence saying *the guard selected no
    entry* reads as though this case were out of scope. The test is the count:
    `over_set` reports `len(entries)` and zero is zero.
    """
    got = examine(
        Rows(), [Rule(name="ids are unique", claim=Condition("unique", "id"))]
    ).judged[0]
    assert got.examined == 0
    assert got.vacuous and got.failed


# -- the predicate escape -----------------------------------------------------


def project_module(monkeypatch, body):
    import types

    made = types.ModuleType("projectrules")
    exec(compile(textwrap.dedent(body), "projectrules", "exec"), made.__dict__)
    monkeypatch.setitem(__import__("sys").modules, "projectrules", made)
    return made


def test_a_predicate_states_a_rule_the_operators_cannot(monkeypatch):
    """``set: never`` iff the key is under ``meta.`` -- one of the measured ten."""
    project_module(
        monkeypatch,
        """
        def is_never(entry):
            return entry.extra.get("set") == "never"

        def is_meta(entry):
            return entry.id.startswith("meta.")
        """,
    )
    rows = (
        entry("meta.box.home", set="never"),
        entry("box.image", set="cli+file"),
        entry("box.leak", set="never"),
    )
    got = judge(
        rule(
            claim=Predicate("projectrules:is_meta"),
            guard=Predicate("projectrules:is_never"),
        ),
        *rows,
    )
    assert got.examined == 2
    assert [hit.name for hit in got.violations] == ["box.leak"]


def test_a_predicate_that_cannot_be_imported_blocks_and_fails():
    got = judge(rule(claim=Predicate("no_such_module_at_all:rule")), entry("a"))
    assert got.blocked
    assert got.failed
    assert "cannot import" in got.blocked


def test_a_predicate_that_raises_is_not_a_pass(monkeypatch):
    """A rule whose body blew up must not be reported as satisfied."""
    project_module(
        monkeypatch,
        """
        def explodes(entry):
            raise ValueError("no")
        """,
    )
    with pytest.raises(ValueError):
        judge(rule(claim=Predicate("projectrules:explodes")), entry("a"))


def test_a_predicate_that_always_passes_is_not_detectable(monkeypatch):
    """⚑ The published limit, asserted so nobody claims otherwise later.

    The group is this package's to count and a vacuous one fails; the *verdict*
    is the project's, and a predicate that returns ``True`` for everything is
    indistinguishable from a declaration in good shape. That is why it is in
    ``docs/introduction.md`` § Known limits rather than in a docstring promising
    it away.
    """
    project_module(
        monkeypatch,
        """
        def always(entry):
            return True
        """,
    )
    got = judge(rule(claim=Predicate("projectrules:always")), entry("a"), entry("b"))
    assert got.examined == 2
    assert not got.failed


def test_a_set_operator_cannot_be_a_guard():
    got = judge(
        rule(claim=Condition("present", "x"), guard=Condition("exists", ["a"])),
        entry("a"),
    )
    assert "cannot judge one entry" in got.blocked


def test_a_set_rule_refuses_a_guard():
    got = judge(
        rule(claim=Condition("exists", ["a"]), guard=Condition("present", "x")),
        entry("a", x=1),
    )
    assert "a guard would select entries nothing then reads" in got.blocked


# -- findings and the ratchet -------------------------------------------------


def test_a_violation_becomes_a_record_the_baseline_can_fingerprint():
    got = judge(
        rule("every row declares a type", claim=Condition("present", "type")),
        entry("b"),
    )
    scope, finding = examine(
        Rows(entry("b")),
        [rule("every row declares a type", claim=Condition("present", "type"))],
    ).findings()[0]
    assert scope == "shape:keys:every row declares a type"
    assert is_shape_scope(scope)
    assert finding.entry_id == "b"
    assert finding.line == 0
    assert finding.antipattern == ""
    assert got.violations[0].scope == scope


def test_a_record_reads_as_its_own_sentence_with_a_colon_in_the_rule_name():
    """A rule quoting a declaration's field carries a colon, and must survive it."""
    got = judge(
        rule("set: never iff meta.", claim=Condition("present", "type")),
        entry("box.leak"),
    ).violations[0]
    finding = got.finding()
    accepted = Accepted(
        registry=got.scope,
        entry_id=finding.entry_id,
        antipattern=finding.antipattern,
        path=finding.path,
        text=finding.text,
    )
    assert "breaks 'set: never iff meta.'" in str(accepted)


def test_two_registries_are_surveyed_and_a_missing_one_raises():
    rows = Rows(entry("a", type="str"))
    declared = [Shape("keys", (rule(claim=Condition("present", "type")),))]
    assert not survey([rows], declared)[0].failed
    with pytest.raises(KeyError, match="not declared"):
        survey([rows], [Shape("absent", ())])


# -- the two tables must agree ------------------------------------------------


def test_every_config_spelling_is_an_operator_shape_can_evaluate():
    """⚑ Both directions.

    A spelling the config accepts and the mechanism cannot evaluate would be a
    rule accepted at load and blocked at every run; an operator with no spelling
    is a capability no config can reach. Neither shows up in any other case
    here, because each table is exercised only through the other.
    """
    known = set(ENTRY_OPERATORS) | set(SET_OPERATORS)
    spelled = {
        claim.operator or name
        for name, claim in SHAPE_CLAIMS.items()
        if name != "holds"
    }
    assert spelled - known == set()
    assert known - spelled == set()


# -- the config layer ---------------------------------------------------------


def declare(tmp_path, rules, *, registry="keys", rows=None, extra=""):
    write(
        tmp_path,
        "decl.yaml",
        rows
        or """
        keys:
          alpha:
            type: str
          beta:
            type: int
        """,
    )
    write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."

        [[registry]]
        name = "keys"
        kind = "yaml-mapping"
        source = "decl.yaml"
        section = "keys"

        [[shape]]
        registry = "{registry}"
        {rules}
        {extra}
        """)
    return tmp_path


def test_a_declared_rule_loads_into_the_settings(tmp_path):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "every row declares a type"
        present = "type"
        """)
    settings = load(project / "kinemata.toml")
    assert len(settings.shapes) == 1
    assert settings.shapes[0].registry == "keys"
    assert settings.shapes[0].rules[0].name == "every row declares a type"


def test_a_guard_table_and_a_guard_predicate_both_load(tmp_path):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "guarded declaratively"
        when = { field = "type", equals = "str" }
        present = "type"

        [[shape.rule]]
        name = "guarded by the project"
        when = "projectrules:is_never"
        present = "type"
        """)
    settings = load(project / "kinemata.toml")
    first, second = settings.shapes[0].rules
    assert isinstance(first.guard, Condition)
    assert isinstance(second.guard, Predicate)


@pytest.mark.parametrize(
    ("rules", "message"),
    [
        ("""
         [[shape.rule]]
         present = "type"
         """, "is missing name"),
        ("""
         [[shape.rule]]
         name = "claims nothing"
         field = "type"
         """, "claims nothing"),
        ("""
         [[shape.rule]]
         name = "claims two things"
         field = "type"
         present = "type"
         equals = "str"
         """, "claims 2 things at once"),
        ("""
         [[shape.rule]]
         name = "no field named"
         equals = "str"
         """, "without naming a field"),
        ("""
         [[shape.rule]]
         name = "keys_of with no are"
         keys_of = "cells"
         """, "without 'are'"),
        ("""
         [[shape.rule]]
         name = "an unusable pattern"
         field = "type"
         matches = "([unclosed"
         """, "not a usable pattern"),
        ("""
         [[shape.rule]]
         name = "not a target"
         holds = "projectrules"
         """, "is not a target"),
        ("""
         [[shape.rule]]
         name = "a set operator as a guard"
         when = { exists = ["alpha"] }
         present = "type"
         """, "asks about the whole set"),
        ("""
         [[shape.rule]]
         name = "a guard that is neither"
         when = 3
         present = "type"
         """, "is a int"),
    ],
)
def test_a_rule_that_cannot_be_honored_is_refused(tmp_path, rules, message):
    project = declare(tmp_path, rules)
    with pytest.raises(ConfigError, match=message):
        load(project / "kinemata.toml")


def test_two_rules_with_one_name_are_refused(tmp_path):
    """The scope is built from the name, so a shared one is an unauditable list."""
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "the same name"
        present = "type"

        [[shape.rule]]
        name = "the same name"
        present = "spec"
        """)
    with pytest.raises(ConfigError, match="already uses"):
        load(project / "kinemata.toml")


def test_a_block_with_no_rule_is_refused(tmp_path):
    project = declare(tmp_path, "")
    with pytest.raises(ConfigError, match=re.escape("declares no [[shape.rule]]")):
        load(project / "kinemata.toml")


def test_a_block_naming_an_undeclared_registry_is_refused(tmp_path):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "a rule"
        present = "type"
        """, registry="nowhere")
    with pytest.raises(ConfigError, match=re.escape("which no [[registry]] declares")):
        load(project / "kinemata.toml")


def test_two_blocks_for_one_registry_are_refused(tmp_path):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "a rule"
        present = "type"
        """, extra="""
        [[shape]]
        registry = "keys"

          [[shape.rule]]
          name = "another rule"
          present = "type"
        """)
    with pytest.raises(ConfigError, match="already does"):
        load(project / "kinemata.toml")


# -- the command --------------------------------------------------------------


def test_the_command_refuses_a_project_with_no_rules(tmp_path, capsys):
    write(tmp_path, "decl.yaml", "keys:\n  alpha:\n    type: str\n")
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [[registry]]
        name = "keys"
        kind = "yaml-mapping"
        source = "decl.yaml"
        section = "keys"
        """)
    assert main(["shape", "--config", str(tmp_path / "kinemata.toml")]) == 2
    assert "no [[shape]] declared" in capsys.readouterr().err


def test_a_satisfied_declaration_passes_and_says_what_ran(tmp_path, capsys):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "every row declares a type"
        present = "type"
        """)
    assert main(["shape", "--config", str(project / "kinemata.toml")]) == 0
    out = capsys.readouterr().out
    assert "2 entry(s), all satisfied" in out
    assert "every row declares a type: 2 examined" in out


def test_a_violation_gates(tmp_path, capsys):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "every row declares a role"
        present = "role"
        """)
    assert main(["shape", "--config", str(project / "kinemata.toml")]) == 1
    assert "2 rule(s) a declaration does not satisfy" in capsys.readouterr().err


def test_a_vacuous_rule_gates_and_is_named_as_vacuous(tmp_path, capsys):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "a rule nothing selects"
        when = { present = "nonesuch" }
        present = "type"
        """)
    assert main(["shape", "--config", str(project / "kinemata.toml")]) == 1
    err = capsys.readouterr().err
    assert "VACUOUS 'a rule nothing selects'" in err


def test_the_baseline_accepts_a_violation_and_the_gate_passes(tmp_path, capsys):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "every row declares a role"
        present = "role"
        """)
    config = str(project / "kinemata.toml")
    assert main(["baseline", "--config", config, "--record",
                 "--until", "2099-01-01"]) == 0
    capsys.readouterr()
    assert main(["shape", "--config", config]) == 0
    assert "2 violation(s) accepted as pre-existing" in capsys.readouterr().out


def test_the_writer_refuses_while_a_rule_judged_nothing(tmp_path, capsys):
    """⚑ *Running a rule is not the rule answering.*

    The 2026-09-13 baseline defect in its shape-rule clothes: a rebuild driven
    by a run whose rule selected no entry would delete that rule's records and
    report the findings as fixed.
    """
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "a rule nothing selects"
        when = { present = "nonesuch" }
        present = "type"
        """)
    assert main(["baseline", "--config", str(project / "kinemata.toml"),
                 "--record", "--until", "2099-01-01"]) == 2
    err = capsys.readouterr().err
    assert "refusing to rewrite the baseline" in err
    assert "examined no entry" in err


def test_a_recorded_rule_survives_a_prune_driven_by_a_run_that_could_not_judge(
    tmp_path, capsys
):
    """Scope isolation, end to end.

    One rule fails and is recorded; a second rule is then added that judges
    nothing. The prune must refuse rather than drop the first rule's record --
    and the record must still be there afterwards.
    """
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "every row declares a role"
        present = "role"
        """)
    config = str(project / "kinemata.toml")
    assert main(["baseline", "--config", config, "--record",
                 "--until", "2099-01-01"]) == 0
    before = Baseline.load(project / ".kinemata-baseline.json").size

    declare(tmp_path, """
        [[shape.rule]]
        name = "every row declares a role"
        present = "role"

        [[shape.rule]]
        name = "a rule nothing selects"
        when = { present = "nonesuch" }
        present = "type"
        """)
    assert main(["baseline", "--config", config, "--prune"]) == 2
    assert Baseline.load(project / ".kinemata-baseline.json").size == before


def test_a_blocked_predicate_is_reported_by_the_command(tmp_path, capsys):
    project = declare(tmp_path, """
        [[shape.rule]]
        name = "a rule the project cannot supply"
        holds = "no_such_module_at_all:rule"
        """)
    assert main(["shape", "--config", str(project / "kinemata.toml")]) == 1
    assert "BLOCKED 'a rule the project cannot supply'" in capsys.readouterr().err


def test_the_shape_error_type_is_what_a_caller_catches():
    """``ShapeError`` is the module's own, so a caller need not know about targets."""
    with pytest.raises(ShapeError):
        Condition("exhausts", "nowhere", "outcome").violations([entry("a")])
