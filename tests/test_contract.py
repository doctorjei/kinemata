"""Contract behavior: what a registry must do, and what it must refuse to do."""

from __future__ import annotations

import pytest

from kinemata import BaseRegistry, Entry, project, undeclared
from kinemata.adapters.mapping import MappingRegistry
from kinemata.contract import _BOUNDARY, _NAME_BOUNDARY, usable_boundary


class Tiny(BaseRegistry):
    name = "tiny"

    def __init__(self, ids, clauses=None):
        self._ids = ids
        self._clauses = clauses or {}

    def entries(self):
        for i in self._ids:
            yield Entry(id=i, clauses=tuple(self._clauses.get(i, ())))


# -- the one required method carries the rest ---------------------------------


def test_entries_is_the_only_thing_a_registry_must_implement():
    r = Tiny(["a.one", "a.two"])
    assert r.declared("a.one")
    assert not r.declared("a.three")
    assert r.detect("touching a.two here") == ["a.two"]


def test_resolve_reads_clauses_from_the_entry():
    r = Tiny(["a.one"], {"a.one": ["spec~x~1", "spec~y~2"]})
    assert r.resolve("a.one") == ("spec~x~1", "spec~y~2")
    assert r.resolve("nope") == ()


def test_clauses_may_be_empty_traceability_is_not_required():
    assert Tiny(["a.one"]).resolve("a.one") == ()


# -- detect() boundaries ------------------------------------------------------


def test_detect_does_not_match_inside_a_longer_identifier():
    r = Tiny(["box.vault"])
    assert r.detect("box.vault_mode = 1") == []
    assert r.detect("box.vault.opts") == []
    assert r.detect("set box.vault = true") == ["box.vault"]


def test_detect_prefers_the_longest_declared_identifier():
    r = Tiny(["box.vault", "box.vault.opts"])
    assert r.detect("box.vault.opts") == ["box.vault.opts"]


def test_detect_deduplicates_but_keeps_order():
    r = Tiny(["a.one", "a.two"])
    assert r.detect("a.two a.one a.two") == ["a.two", "a.one"]


def test_the_boundary_is_a_property_of_the_registry_not_the_matcher():
    """One module-level boundary decided this for every registry, and the two
    kinds want opposite answers: a dotted key contains its separator, a Python
    constant is reached through one."""

    class Reached(Tiny):
        boundary = _NAME_BOUNDARY

    assert Tiny(["CHANNELS_PATH"]).detect("bootstrap.CHANNELS_PATH") == []
    assert Reached(["CHANNELS_PATH"]).detect("bootstrap.CHANNELS_PATH") == [
        "CHANNELS_PATH"
    ]


def test_the_narrower_boundary_still_refuses_a_longer_name():
    class Reached(Tiny):
        boundary = _NAME_BOUNDARY

    r = Reached(["CHANNELS_PATH"])
    assert r.detect("CHANNELS_PATHS = 1") == []
    assert r.detect("OLD_CHANNELS_PATH = 1") == []


def test_detect_only_ever_finds_declared_entries():
    # The reason candidates() has to exist: detect() is structurally blind to
    # anything undeclared, so it can never be the closure check.
    assert Tiny(["a.one"]).detect("a.undeclared") == []


# -- a boundary a project declares --------------------------------------------


def test_a_boundary_may_be_named_rather_than_respelled():
    """The two answers this module already settled, reachable by name.

    Re-spelling a character class in a config file is how two matchers come to
    disagree about what a word is, which is the finding that produced the second
    class in the first place.
    """
    assert usable_boundary("identifier") == _BOUNDARY
    assert usable_boundary("name") == _NAME_BOUNDARY


def test_a_class_the_project_writes_is_accepted_and_bounds_what_it_says():
    """Neither built-in answer fits every data model, which is the whole point.

    Checked through ``detect`` rather than by comparing strings: the value is
    only worth accepting if it works in the position the matcher puts it in.
    """
    declared = usable_boundary(r"[A-Za-z0-9_~]")

    class Tilde(Tiny):
        boundary = declared

    r = Tilde(["box.vault"])
    assert r.detect("read box.vault here") == ["box.vault"]
    assert r.detect("spec~box.vault") == []


def test_a_boundary_that_lets_nothing_abut_is_refused():
    """``.`` reads like "any character" and means "the registry finds nothing".

    Every neighbor is excluded, so a match can only occur where the identifier
    has no neighbors at all. The command still exits 0, which is the inert
    signal this package exists to prevent.
    """
    with pytest.raises(ValueError, match="every character"):
        usable_boundary(".")


def test_a_boundary_that_bounds_nothing_is_refused():
    """A bare word is a regular expression that matches no single character.

    ``prose`` is the likeliest one to be written: it is a real value of the
    *other* boundary table, the one deciding how a forbidden spelling is built
    into a pattern. Accepted here it would compile, exclude nothing, and quietly
    turn matching into a substring search that reports a name inside a longer
    one.
    """
    with pytest.raises(ValueError, match="bounds nothing"):
        usable_boundary("prose")


def test_a_boundary_that_is_not_a_pattern_at_all_is_refused():
    with pytest.raises(ValueError, match="cannot bound a match"):
        usable_boundary("[A-Za-z")


def test_a_boundary_that_is_not_a_string_is_refused():
    """An empty one included: it matches at every position, so nothing counts."""
    for declared in ("", None, 12, [r"[A-Za-z]"]):
        with pytest.raises(ValueError, match="not a character class"):
            usable_boundary(declared)


# -- closure ------------------------------------------------------------------


def test_a_registry_without_identifier_syntax_cannot_be_closed():
    with pytest.raises(NotImplementedError, match="cannot be closed"):
        Tiny(["a.one"]).candidates("anything")


def test_closed_registry_flags_undeclared_identifiers():
    r = MappingRegistry(
        {"box.vault": {}, "box.name": {}},
        name="keys",
        syntax=r"box\.[a-z_]+",
        closed=True,
    )
    assert undeclared(r, "box.vault and box.rogue") == ["box.rogue"]


def test_open_registry_still_reports_but_does_not_have_to_close():
    r = MappingRegistry({"box.vault": {}}, name="keys", syntax=r"box\.[a-z_]+")
    assert r.closed is False
    assert undeclared(r, "box.rogue") == ["box.rogue"]


def test_closed_without_syntax_is_refused_at_construction():
    with pytest.raises(ValueError, match="closed but has no identifier syntax"):
        MappingRegistry({"a": {}}, closed=True)


# -- budget: the catch on context overwhelm -----------------------------------


def test_projection_within_budget_passes():
    p = project(Tiny(["a.one", "a.two"]))
    assert p.ok
    assert p.count == 2
    assert p.text == "a.one\na.two\n"


def test_projection_over_total_budget_fails():
    class Fat(Tiny):
        budget = 10

    p = project(Fat(["a.one", "a.two", "a.three"]))
    assert not p.ok
    assert any(v.kind == "total" for v in p.violations)


def test_projection_over_per_entry_budget_names_the_entry():
    class Narrow(Tiny):
        line_budget = 5

    p = project(Narrow(["short", "an.identifier.that.is.long"]))
    violations = [v for v in p.violations if v.kind == "line"]
    assert [v.identifier for v in violations] == ["an.identifier.that.is.long"]


def test_projection_is_sorted_so_diffs_stay_readable():
    assert project(Tiny(["z.last", "a.first"])).text == "a.first\nz.last\n"


def test_empty_registry_projects_to_nothing():
    p = project(Tiny([]))
    assert p.text == ""
    assert p.ok


# -- adapter ------------------------------------------------------------------


def test_mapping_adapter_passes_unknown_fields_through_untouched():
    r = MappingRegistry(
        {"box.vault": {"scope": "box", "type": "bool", "whatever": 42}},
        name="keys",
    )
    (entry,) = r.entries()
    assert entry.extra["whatever"] == 42
    assert entry.clauses == ()


def test_mapping_adapter_reads_clauses_from_a_named_field():
    r = MappingRegistry(
        {"box.vault": {"spec": ["spec~a~1", "spec~b~1"]}},
        clause_field="spec",
    )
    assert r.resolve("box.vault") == ("spec~a~1", "spec~b~1")


def test_mapping_adapter_accepts_a_scalar_clause_field():
    r = MappingRegistry({"box.vault": {"spec": "§2a"}}, clause_field="spec")
    assert r.resolve("box.vault") == ("§2a",)


def test_mapping_adapter_tolerates_non_mapping_records():
    r = MappingRegistry({"flag": True}, clause_field="spec")
    (entry,) = r.entries()
    assert entry.extra == {"value": True}
    assert entry.clauses == ()
