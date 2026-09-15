"""A registry narrowed to a group, by a declared selector.

A ``[[parity]]`` compares a whole registry against a whole oracle, so a project
whose oracle answers for part of its declaration pays an ``unproduced`` finding
for every row outside it. Measured on a real adopter's manifest rather than
guessed at: their ``keys`` table holds 99 rows and the oracle behind their
anchor-floor tests covers 10, so the comparison reports **93** findings of which
**1** is real.

**The selector lives on the registry rather than on the check that wanted it**,
which was the decision and not an implementation detail. On ``[[parity]]`` it
would make membership's *"and there is nothing else"* subset-relative for every
adopter, and would break the uniqueness of ``parity:<registry>:<direction>`` so
that two narrowed parities' ``--prune`` deleted each other's records. Here the
registry *is* the set: membership keeps its meaning, and the scan, ``undeclared``,
``shape`` and ``unused`` all see the same narrowing for free.
"""

from __future__ import annotations

import sys
import textwrap
import types

import pytest

from kinemata.config import ConfigError, load

MANIFEST = """
    keys:
      mode_keyed:
        type: path
        default: {primary: "/a", named: "/a", standalone: "/b"}
      also_mode_keyed:
        type: path
        default: {primary: "/c", named: "/c", standalone: "/d"}
      uniform:
        type: path
        default: "/e"
      no_default:
        type: path
    """


def build(tmp_path, *, where='where = { present = ["default", "primary"] }',
          registry_extra="", manifest=MANIFEST):
    (tmp_path / "keys.yaml").write_text(textwrap.dedent(manifest).lstrip())
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            root = "."

            [[registry]]
            name = "keyspace"
            kind = "yaml-mapping"
            source = "keys.yaml"
            section = "keys"
            {where}
            {registry_extra}
            """
        ).lstrip()
    )
    return load(tmp_path / "kinemata.toml")


def ids(settings):
    return sorted(entry.id for entry in settings.registries[0].entries())


# -- what it selects ----------------------------------------------------------


def test_a_selector_keeps_the_group_and_drops_the_rest(tmp_path):
    """`present = "default"` would keep the uniform row too, which is the point
    of a path: the discriminator is the arm, not the field."""
    assert ids(build(tmp_path)) == ["also_mode_keyed", "mode_keyed"]


def test_without_a_selector_every_row_is_declared(tmp_path):
    settings = build(tmp_path, where="")
    assert ids(settings) == ["also_mode_keyed", "mode_keyed", "no_default", "uniform"]


def test_the_whole_guard_vocabulary_is_available(tmp_path):
    """Reused rather than invented -- a second operator table would eventually
    disagree with the first."""
    settings = build(tmp_path, where='where = { field = "type", equals = "path" }')
    assert len(ids(settings)) == 4
    settings = build(tmp_path, where='where = { absent = "default" }')
    assert ids(settings) == ["no_default"]


def test_a_project_predicate_can_select(tmp_path, monkeypatch):
    """The escape `[[shape]]` already publishes, reaching the other mechanism:
    how a row becomes a member of a group is the project's own model."""
    made = types.ModuleType("projectrules")
    exec(
        "def is_mode_keyed(entry):\n"
        '    return isinstance(entry.extra.get("default"), dict)\n',
        made.__dict__,
    )
    monkeypatch.setitem(sys.modules, "projectrules", made)
    settings = build(tmp_path, where='where = "projectrules:is_mode_keyed"')
    assert ids(settings) == ["also_mode_keyed", "mode_keyed"]


# -- what the narrowing reaches ----------------------------------------------


def test_everything_derived_is_re_derived_from_the_kept_entries(tmp_path):
    """The property that makes this safe to put on the registry. `detect` over a
    subset must not recognize an identifier the subset excludes, or a scan would
    report a bypass against a declaration this view does not carry."""
    registry = build(tmp_path).registries[0]
    assert registry.declared("mode_keyed")
    assert not registry.declared("uniform")
    assert registry.detect("touching uniform here") == []
    assert registry.detect("touching mode_keyed here") == ["mode_keyed"]


def test_the_configured_attributes_carry_over(tmp_path):
    settings = build(
        tmp_path,
        registry_extra='machinery = ["keys.yaml"]\nmatch_mode = "code"',
    )
    registry = settings.registries[0]
    assert registry.name == "keyspace"
    assert registry.machinery == ("keys.yaml",)
    assert registry.match_mode == "code"


def test_the_adapters_own_projection_still_answers(tmp_path):
    """`line` and `candidates` are delegated rather than re-derived: they ask
    what the data model looks like, not what is in it, and narrowing the set
    changes neither."""
    whole = build(tmp_path, where="").registries[0]
    narrowed = build(tmp_path).registries[0]
    entry = next(e for e in narrowed.entries() if e.id == "mode_keyed")
    assert narrowed.line(entry) == whole.line(entry)


# -- what it refuses ----------------------------------------------------------


def test_a_selector_that_keeps_nothing_is_refused(tmp_path):
    """The vacuity rule this package applies everywhere: running a check is not
    the check answering. Refused at load rather than reported, because one
    selector that kept nothing makes every mechanism reading the view vacuous
    at once."""
    with pytest.raises(ConfigError, match="kept none of the entries"):
        build(tmp_path, where='where = { present = "no_such_field" }')


def test_an_empty_source_is_named_as_such_rather_than_blamed_on_the_selector(
    tmp_path,
):
    """Two causes, opposite fixes: point the registry somewhere else, or widen
    the selector. A message naming the wrong one sends a reader to the wrong
    line."""
    with pytest.raises(ConfigError, match="produced no entries at all"):
        build(tmp_path, manifest="keys: {}\n")


def test_closed_and_where_together_are_refused(tmp_path):
    """A closed registry answers *"nothing declares this identifier"*. Over a
    subset, every identifier belonging to an excluded row is a finding that is
    wrong -- and the excluded rows are still in the project's own file."""
    with pytest.raises(ConfigError, match="both 'closed' and 'where'"):
        build(
            tmp_path,
            registry_extra="closed = true\nsyntax = '\\\\b[a-z_]+'",
        )


def test_a_set_operator_cannot_select_a_group(tmp_path):
    with pytest.raises(ConfigError, match="asks about the whole set"):
        build(tmp_path, where='where = { exists = ["mode_keyed"] }')


def test_a_selector_that_is_not_a_table_or_a_target_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="A guard is either a table"):
        build(tmp_path, where="where = 3")


def test_a_predicate_that_will_not_resolve_is_refused_at_load(tmp_path):
    """At load, like every other target this config resolves: a selector that
    fails at run time would leave each mechanism to report it separately."""
    with pytest.raises(ConfigError, match="no_such_module"):
        build(tmp_path, where='where = "no_such_module:rule"')
