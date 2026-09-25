"""A declaration checked against its own shape.

Every other mechanism here compares a declaration to *something else*: the scan
to the code that re-derives it, :mod:`kinemata.parity` to the set the code
produces, :mod:`kinemata.interpose` to what crosses a funnel while the project
runs, :mod:`kinemata.claims` to the world. This one reads only the declaration
and asks whether it is the shape the project says it is.

**Why that earned a mechanism.** An adopting project's registry is a
3,000-line hand-maintained YAML edited by agents, and **31 of their conformance
test functions exist to stop a row being silently mis-shaped** -- a missing
flag, a value outside the vocabulary, an axis that stopped being a cross
product. Measured 2026-09-14 against all 125 of their manifest-parity
functions: that was the largest unmet class, larger than either shape anybody
had written down, and this package could express none of it. It passes the
spend-mechanism test on all three counts -- violation is cheap (one line in a
hundred-row table), invisible (nothing reads the row until a launch does) and
rewarded (the edit that omits the flag is shorter).

⚑ **The word is ``shape``, not ``schema``, deliberately.** It is what the
adopter's own suite calls these cases throughout, and it does not promise JSON
Schema by increments. There is no expression syntax here, no coercion and no
inference: two small tables of dull operators, and one escape to a predicate the
project names. An expression language was declined **on its cost** -- it would
re-derive a solved thing, the core takes no runtime dependency so none could be
borrowed, and the result would be a second worse copy. Nothing in this design
forecloses one: ``docs/introduction.md`` [0TN7FP9-Pa0004] § Known limits carries
the disposition and what would revive it.

**One form throughout: a rule is a guard and a claim.** A rule with no guard
judges every entry; a guarded rule judges the group its guard selects. That
unification came out of the measurement rather than out of tidiness -- an IFF is
two guarded rules, and *"this value appears at exactly these positions"* is two
guarded rules -- and it is what stops the operator table growing a second axis.

⚑ **A rule that examined no entry FAILS.** This is the property that makes the
predicate escape safe, and it is only available because the seam is two
predicates rather than one function returning a verdict: the group is *this*
module's to count, so vacuity is detected here rather than self-reported by the
project's code. Their own suite says why -- *"an empty parametrize list runs
ZERO cases and stays green"*.

**The test is the count and not the guard**, which is narrower than it was once
written: a guard matching nothing is only the commonest way to examine nothing.
An unguarded rule over a registry that produced no entries and a set operator
selecting nothing are the same vacuity, and the code has always caught all
three. The sentence that named the guard let a reader conclude the opposite.

⚑ **And that is the opposite of what :mod:`kinemata.interpose` does with an
unexercised funnel, on purpose.** A funnel nothing crossed is reported and does
not fail, because a funnel's coverage belongs to the project's *suite*. A rule's
group belongs to the *declaration*, which is entirely present at the moment the
rule runs -- so a rule selecting nothing is the rule being wrong, not a gap in
somebody's tests. **Do not reconcile the two behaviors; the difference is whose
fault the emptiness is.**

**It is a reminder, not a catch.** An agent can edit a rule and the row it
governs in one commit, exactly as it can edit a ``[[gate]]``'s declaration and
the workflow that runs it. See ``docs/introduction.md`` [0TN7FP9-Pa0004]
§ Known limits, which also publishes the limit this module cannot close: a
predicate answering True for everything is indistinguishable from a declaration
in good order.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .bypass import Bypass
from .contract import MISSING, Entry, Registry, at_path, field_path, spell_path
from .targets import TargetError, resolve

#: The name shape findings travel under in a baseline record.
SHAPE_SCOPE = "shape"


class ShapeError(Exception):
    """A rule that cannot be evaluated as declared."""


def shape_scope(registry: str, rule: str) -> str:
    """The baseline scope for one rule's findings.

    **Per rule, not per registry**, and the reason was paid for on 2026-09-13: a
    run that could not evaluate one rule must not let ``--prune`` delete
    another's records and call them fixed.
    """
    return f"{SHAPE_SCOPE}:{registry}:{rule}"


def is_shape_scope(name: str) -> bool:
    return name == SHAPE_SCOPE or name.startswith(f"{SHAPE_SCOPE}:")


def _value(entry: Entry, field_name: object) -> Any:
    """One field of an entry, or the entry's own id when no field is named.

    A path reaching nothing reads as ``None``, which is what a missing flat key
    already read as -- so every operator below behaves on a path exactly as it
    always has on a key.
    """
    path = field_path(field_name)
    if not path:
        return entry.id
    found = at_path(entry.extra, path)
    return None if found is MISSING else found


def _listed(value: Any) -> list[Any]:
    """A field as a list. A scalar is a list of one; a mapping is its keys.

    Nothing is coerced *between* types here -- a string stays a string -- but a
    field that holds a container has to be walked somehow, and the two shapes a
    declaration writes are a list and a map.
    """
    if isinstance(value, str) or value is None:
        return [value]
    if isinstance(value, dict):
        return list(value)
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _matches(value: Any, pattern: Any) -> bool:
    """Whether ``value`` has ``pattern``'s shape. **Nothing has no shape.**

    A field the entry does not carry reads as ``None`` (:func:`_value`), and so
    does a null in the declaration. Both used to be matched as the text
    ``"None"``, so ``matches = "^N"`` or any pattern that fits that word was
    satisfied by an entry missing the field entirely -- measured 2026-09-24
    while scoping an adopter's report, with no test arguing for it. Whether a
    field must be present is ``present``'s claim, and a pattern making it
    silently in the permissive direction was the wrong way round.
    """
    if value is None:
        return False
    return bool(re.search(str(pattern), str(value)))


def _each_value_matches(value: Any, pattern: Any) -> bool:
    """Every *value* a field holds has ``pattern``'s shape.

    A mapping is its values, a list its items, and anything else is one value
    -- so a field declared as a scalar on some rows and as a mode-keyed map on
    others is one rule. ``each_matches`` cannot say this, because it reads a
    mapping as its **keys**, and it keeps doing so: that is published behavior,
    and silently re-reading it would flip rules somebody already wrote.

    Asked for by an adopting project on 2026-09-22 -- *"every arm of the default
    is a whole-value host ``$VAR``"* -- whose manifest writes a default either
    as a scalar or as ``{primary: ..., named: ..., standalone: ...}``.

    **An empty container fails.** It has no value that could be the thing
    claimed, and the same manifest declares ``default: {}`` on rows a vacuous
    pass would have certified as whole-value ``$VAR`` defaults. A value that is
    itself a container is matched as its text, which a pattern anchored for a
    scalar rejects; this reads one level, not a tree.
    """
    if isinstance(value, dict):
        values = list(value.values())
    elif isinstance(value, (list, tuple, set, frozenset)):
        values = list(value)
    else:
        values = [value]
    return bool(values) and all(_matches(item, pattern) for item in values)


#: What a rule may claim about ONE entry. Each takes the entry, the field named
#: (empty meaning the entry's id) and the declared argument, and answers whether
#: it holds. A table rather than a chain of branches, the way
#: :data:`kinemata.claims.CLAIM_KINDS` is: a reader auditing what a config can
#: say should find one list of the answers.
ENTRY_OPERATORS: dict[str, Callable[[Entry, str, Any], bool]] = {
    # These two name their subject in the *argument*, not in `field`, so a path
    # spelling reaches them there: `present = ["default", "primary"]` asks for
    # an arm of a map rather than a key of the row.
    "present": lambda entry, _field, want: at_path(entry.extra, field_path(want))
    is not MISSING,
    "absent": lambda entry, _field, want: at_path(entry.extra, field_path(want))
    is MISSING,
    "equals": lambda entry, field_name, want: _value(entry, field_name) == want,
    "choices": lambda entry, field_name, want: _value(entry, field_name) in list(want),
    "matches": lambda entry, field_name, want: _matches(
        _value(entry, field_name), want
    ),
    "each_matches": lambda entry, field_name, want: all(
        _matches(item, want) for item in _listed(_value(entry, field_name))
    ),
    "each_value_matches": lambda entry, field_name, want: _each_value_matches(
        _value(entry, field_name), want
    ),
    "contains": lambda entry, field_name, want: want
    in _listed(_value(entry, field_name)),
}

#: What a rule may claim about the SET. Each returns the names that violate it,
#: so a finding has something to point at -- an id nobody declared, a key on the
#: wrong side of a comparison, a vocabulary member nothing uses.
SET_OPERATORS: dict[str, Callable[[Sequence[Entry], str, Any], list[str]]] = {}


def _op_exists(entries: Sequence[Entry], _field: str, want: Any) -> list[str]:
    """Every id named must be declared. The missing ones are the finding."""
    declared = {entry.id for entry in entries}
    return [str(name) for name in _listed(want) if str(name) not in declared]


def _op_keys_of(entries: Sequence[Entry], field_name: str, want: Any) -> list[str]:
    """One field's keys are exactly another field's values, both ways.

    The message names which side each difference is on, because a bare
    ``set == set`` says nothing actionable at the moment it fires -- the
    adopter's own words for the case this operator carries.
    """
    by_id = {entry.id: entry for entry in entries}
    holder, source = str(field_name), str(want)
    absent = sorted({holder, source} - set(by_id))
    if absent:
        raise ShapeError(
            f"keys_of compares {holder!r} against {source!r}, and "
            f"{', '.join(repr(name) for name in absent)} is not a declared entry"
        )
    body = _entry_body(by_id[holder])
    if not isinstance(body, dict):
        raise ShapeError(
            f"keys_of names {holder!r}, which holds a "
            f"{type(body).__name__} and has no keys to compare"
        )
    keys = {str(name) for name in body}
    values = {str(item) for item in _listed(_entry_body(by_id[source]))}
    return [
        f"{name}: keyed, not a value of {source}" for name in sorted(keys - values)
    ] + [
        f"{name}: a value of {source}, not keyed" for name in sorted(values - keys)
    ]


def _op_exhausts(entries: Sequence[Entry], field_name: str, want: Any) -> list[str]:
    """Every member of the named vocabulary is used by some entry's field.

    ⚑ **A dead token is the quiet failure** -- an outcome nobody writes is a
    promise the declaration does not keep, and nothing else here would notice.
    The vocabulary is another entry, so that it stays declared in one place.
    """
    by_id = {entry.id: entry for entry in entries}
    source = str(want)
    if source not in by_id:
        raise ShapeError(f"exhausts names {source!r}, which is not a declared entry")
    vocabulary = {str(item) for item in _listed(_entry_body(by_id[source]))}
    used: set[str] = set()
    for entry in entries:
        if entry.id == source:
            continue
        used.update(str(item) for item in _listed(_value(entry, field_name)))
    return [f"{name}: declared, used by nothing" for name in sorted(vocabulary - used)]


def _entry_body(entry: Entry) -> Any:
    """What an entry *is* when it holds a list rather than a record.

    A ``MappingRegistry`` row whose value is a list arrives with the list in
    ``extra['value']``; a row whose value is a record arrives with the record's
    fields. Both shapes are real in the one declaration this was measured
    against, so the fallback is the record itself rather than a refusal.
    """
    if "value" in entry.extra and len(entry.extra) == 1:
        return entry.extra["value"]
    return entry.extra


SET_OPERATORS.update(
    exists=_op_exists,
    keys_of=_op_keys_of,
    exhausts=_op_exhausts,
)


@dataclass(frozen=True)
class Condition:
    """One question asked of an entry, or of the set.

    ``field`` empty means the entry's own id -- which is what lets a rule claim
    something about an identifier's spelling without a separate operator for it.
    """

    operator: str
    argument: Any = None
    #: A key, or a path into ``extra`` written as a list. See
    #: :func:`kinemata.contract.field_path` for why a string is never split.
    field: str | tuple[str, ...] = ""

    @property
    def over_set(self) -> bool:
        return self.operator in SET_OPERATORS

    def holds(self, entry: Entry) -> bool:
        return ENTRY_OPERATORS[self.operator](entry, self.field, self.argument)

    def violations(self, entries: Sequence[Entry]) -> list[str]:
        return SET_OPERATORS[self.operator](entries, self.field, self.argument)

    def __str__(self) -> str:
        where = spell_path(self.field) or "id"
        if self.operator in ("present", "absent"):
            return f"{spell_path(self.argument)!r} is {self.operator}"
        return f"{where} {self.operator} {self.argument!r}"


@dataclass(frozen=True)
class Predicate:
    """A rule the project states in its own code, named in the config.

    **The escape, and the thing it exists for.** Ten of the measured 31 are
    rules about *computed groups* -- ``set: never`` iff the key is under
    ``meta.``, every refusing cell claimed by some numbered refusal -- and those
    are the project's own model of its own declaration. The house precedent is
    exact and twice over: ``[[interpose]]`` takes ``identify`` from the project
    because how a call becomes an identifier is its own model, and
    :func:`kinemata.claims.verify` takes ``elsewhere`` from its caller so that
    module never learns what a registry is.

    ⚑ **What it receives is an :class:`~kinemata.contract.Entry` and nothing
    else.** No registry, no settings, no tree. A predicate that needs to read
    another section of its own declaration reads it *itself* -- it is the
    project's file.

    ⚑ **A predicate that always answers True is not detectable**, and that limit
    is published rather than papered over. What *is* detectable is the vacuous
    group, and this module counts that itself.
    """

    target: str

    def __str__(self) -> str:
        return self.target


@dataclass(frozen=True)
class Rule:
    """One named rule: a guard, and the claim it makes about what it selects."""

    name: str
    claim: Condition | Predicate
    #: ``None`` judges every entry.
    guard: Condition | Predicate | None = None

    @property
    def over_set(self) -> bool:
        return isinstance(self.claim, Condition) and self.claim.over_set


@dataclass(frozen=True)
class Violation:
    """One entry a rule selected and that failed it."""

    registry: str
    rule: str
    name: str

    @property
    def scope(self) -> str:
        return shape_scope(self.registry, self.rule)

    def __str__(self) -> str:
        return f"{self.name}: {self.rule}"

    def finding(self) -> Bypass:
        """The record the ratchet fingerprints.

        ``antipattern`` is empty and the line is zero for the reason
        :meth:`kinemata.parity.Disagreement.finding` gives: nothing matched a
        pattern, and this finding has no site in a file -- the declaration is
        where it came from. The registry name stands in ``path`` because it is
        the only locator the finding has, and the rule is carried by the scope
        rather than by a field, so two rules' records cannot be confused in a
        list somebody is auditing.
        """
        return Bypass(
            entry_id=self.name,
            antipattern="",
            path=self.registry,
            line=0,
            text=f"{self.rule}: {self.name}",
        )


@dataclass(frozen=True)
class Judged:
    """What one rule did: how many entries it selected, and which failed.

    ``examined`` is here to be *reported*, not only to be tested against zero.
    A rule quietly narrowing from ninety entries to two is not a failure and is
    worth seeing, the way ``review -v`` prints its suppressions rather than
    applying them in silence.
    """

    rule: Rule
    examined: int = 0
    #: The entries it examined, by id -- what the coverage lock records, so a
    #: guard narrowed by an edit drops rows (:mod:`kinemata.coverage`).
    names: tuple[str, ...] = ()
    violations: tuple[Violation, ...] = ()
    #: Why this rule could not be evaluated -- an unresolvable predicate, an
    #: operator naming an entry that is not there. Empty when it ran.
    blocked: str = ""

    @property
    def vacuous(self) -> bool:
        """Examined nothing. A failure, and see this module's note on why.

        The count, never the guard: an unguarded rule over an empty registry
        examines nothing just as surely as a guard that matched nothing.
        """
        return not self.blocked and self.examined == 0

    @property
    def failed(self) -> bool:
        return bool(self.blocked) or self.vacuous or bool(self.violations)


@dataclass
class Shaped:
    """One registry's rules, run."""

    registry: str
    judged: list[Judged] = field(default_factory=list)

    @property
    def blocked(self) -> list[Judged]:
        return [item for item in self.judged if item.blocked]

    @property
    def vacuous(self) -> list[Judged]:
        return [item for item in self.judged if item.vacuous]

    @property
    def violations(self) -> list[Violation]:
        return [hit for item in self.judged for hit in item.violations]

    @property
    def failed(self) -> bool:
        return any(item.failed for item in self.judged)

    def findings(self) -> list[tuple[str, Bypass]]:
        return [(hit.scope, hit.finding()) for hit in self.violations]

    def scopes(self) -> tuple[str, ...]:
        """Every scope this run is in a position to judge.

        A blocked rule's scope is **not** claimed: the run did not evaluate it,
        so a ``--prune`` driven by this run must leave its records alone. That is
        the same reason a parity run names only the directions it compared.

        ⚑ **Nor is a vacuous rule's.** It ran, and it looked at nothing -- so
        every record under it would be deleted as fixed by a run that examined
        no entry, which is the baseline defect measured on 2026-09-13 wearing
        different clothes. *Running a rule is not the rule answering.*
        """
        return tuple(
            shape_scope(self.registry, item.rule.name)
            for item in self.judged
            if not item.blocked and not item.vacuous
        )

    def unjudged(self) -> list[str]:
        """Why each rule that could not judge could not, for a writer to refuse on."""
        return [
            f"{item.rule.name}: {item.blocked}" if item.blocked
            else f"{item.rule.name}: examined no entry"
            for item in self.judged
            if item.blocked or item.vacuous
        ]


def asked(what: Condition | Predicate) -> Callable[[Entry], bool]:
    """One entry-scope question as a callable, resolving a predicate if needed.

    ⚑ **Public since 2026-09-15, when a second mechanism needed it**:
    ``[[registry]] where`` narrows a registry with the same guard vocabulary,
    and :class:`~kinemata.contract.Selected` takes a plain callable so that
    module never learns what a condition is. Two spellings of *"turn a guard
    into a question"* is this package's own subject, and :mod:`kinemata.targets`
    is the exact precedent for extracting one when the second caller arrives.
    """
    if isinstance(what, Predicate):
        found = resolve(what.target)
        return lambda entry: bool(found.value(entry))
    if what.over_set:
        raise ShapeError(
            f"{what.operator!r} asks about the whole set and cannot judge one entry"
        )
    return what.holds


def examine(registry: Registry, rules: Sequence[Rule]) -> Shaped:
    """Every rule against the entries the registry declares.

    A rule that cannot be evaluated is **blocked and reported**, never skipped:
    a run that printed nothing because a predicate failed to import is
    indistinguishable from a declaration that is in good shape, which is the
    inert signal this package exists to prevent.
    """
    entries = list(registry.entries())
    result = Shaped(registry=registry.name)
    for rule in rules:
        try:
            result.judged.append(_run(registry.name, rule, entries))
        except (ShapeError, TargetError) as exc:
            result.judged.append(Judged(rule=rule, blocked=str(exc)))
    return result


def _run(name: str, rule: Rule, entries: Sequence[Entry]) -> Judged:
    if rule.over_set:
        if rule.guard is not None:
            raise ShapeError(
                f"{rule.name!r} asks about the whole set, so a guard would "
                "select entries nothing then reads"
            )
        assert isinstance(rule.claim, Condition)  # narrowed by `over_set`
        failures = rule.claim.violations(entries)
        return Judged(
            rule=rule,
            examined=len(entries),
            names=tuple(entry.id for entry in entries),
            violations=tuple(
                Violation(registry=name, rule=rule.name, name=text)
                for text in failures
            ),
        )

    claim = asked(rule.claim)
    selects = asked(rule.guard) if rule.guard is not None else None
    group = [entry for entry in entries if selects is None or selects(entry)]
    return Judged(
        rule=rule,
        examined=len(group),
        names=tuple(entry.id for entry in group),
        violations=tuple(
            Violation(registry=name, rule=rule.name, name=entry.id)
            for entry in group
            if not claim(entry)
        ),
    )


@dataclass(frozen=True)
class Shape:
    """One registry, and the rules a config states about it."""

    registry: str
    rules: tuple[Rule, ...]


def survey(registries: Iterable[Registry], declarations: Sequence[Shape]) -> list[Shaped]:
    """Every declared ``[[shape]]`` against the registry it names.

    A declaration naming a registry that does not exist raises rather than being
    skipped; the config layer refuses it first, and this is the second answer for
    a caller assembling declarations itself.
    """
    by_name = {registry.name: registry for registry in registries}
    results: list[Shaped] = []
    for declared in declarations:
        registry = by_name.get(declared.registry)
        if registry is None:
            raise KeyError(
                f"[[shape]] names registry {declared.registry!r}, which is not "
                f"declared (known: {', '.join(sorted(by_name)) or 'none'})"
            )
        results.append(examine(registry, declared.rules))
    return results
