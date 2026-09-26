"""What each gate covers, for the baseline's coverage lock.

The lock (:meth:`kinemata.baseline.Baseline.shrunk`) fails a gate whose run
covers less than it did when the baseline was recorded, so a check narrowed by
an edit to its own declaration cannot pass on what it has left. ``parity`` came
first (:func:`kinemata.parity.coverage`); this module carries the others, one
function per gate, each returning ``key -> identifiers``.

**Every row is read from a declaration, or from what a run was declared to
examine -- never from what the project's code printed or what the tree
happens to contain.** A lock that moved with the code would move on its own.
That is why ``check`` locks entries rather than the files it read, and why
``claims`` locks the declared ``[[count]]`` and ``[[gate]]`` rows rather than
the documents or the claims in them, which change with every edit to prose.
Both were the user's choice on 2026-09-25, each alternative offered with the
friction it would bring: every deleted or renamed file, or document, would
have been a coverage drop needing a re-record.

**A row may leave only by leaving the data, with the declaration that reads the
data unchanged** (the user's decision, 2026-09-26). The config declares a
*population* -- a ``[[registry]]`` table, a ``[[probe]]`` table -- and the data
fills it. A ``where``, a guard or a ``field`` narrowing what is covered leaves
the row in the population, so it still fails. A row renamed or retired from the
data leaves the population, and passes while the table reading it is unchanged:
this repository's own lock turned ``parity`` red on a version bump, the
identifier of a ``toml-value`` registry being the version itself. When the
table changed, which rows it dropped cannot be told from which the data did, so
the rows are judged strictly -- a module struck from ``modules`` still fails.
The table's :func:`fingerprint` is recorded beside the rows to tell the two
apart. Rows declared in the config itself -- ``[[count]]`` labels, gate
commands, a registry's closure -- have no population apart from the config and
are always strict.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .contract import Registry, population
from .probe import Probed
from .shape import Shaped


@dataclass(frozen=True)
class Covered:
    """What one check covers now, and what it could have covered.

    ``rows`` is what the lock records. ``population`` is every row the
    declaration named by ``source`` reads, before anything narrows it, and
    ``fingerprint`` is that declaration's :func:`fingerprint` now. ``None`` for
    both means the rows live in the config itself and are judged strictly.
    """

    rows: tuple[str, ...]
    population: frozenset[str] | None = None
    source: str = ""
    fingerprint: str = ""


def fingerprint(table: Mapping[str, Any]) -> str:
    """A short digest of one declaration's table, canonical under key order.

    **The whole table**, ``where`` included: an edit to any of it makes its
    rows strict for a run, which costs a re-record at worst, where leaving a
    key out would let an edit to it pass as a data edit.
    """
    text = json.dumps(table, sort_keys=True, default=str)
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def registry_source(name: str) -> str:
    """The key a registry's fingerprint is recorded under."""
    return f"registry:{name}"


def probe_source(name: str) -> str:
    """The key a probe's fingerprint is recorded under."""
    return f"probe:{name}"


def _declared(
    registry: Registry, rows: Iterable[str], prints: Mapping[str, str]
) -> Covered:
    """``rows`` against the registry's whole population."""
    source = registry_source(registry.name)
    return Covered(
        rows=tuple(sorted(set(rows))),
        population=frozenset(entry.id for entry in population(registry)),
        source=source,
        fingerprint=prints.get(source, ""),
    )

#: What a gate's run covers, by coverage key: a :class:`Covered` where the rows
#: have a population apart from the config, a plain tuple where they do not.
Coverage = dict[str, Covered | tuple[str, ...]]


def check(
    registries: Iterable[Registry], prints: Mapping[str, str] | None = None
) -> Coverage:
    """Each registry's entries that carry an antipattern -- what ``check`` can
    report a bypass of. A registry removed, a module dropped from a
    ``python-constants`` list, or a ``where`` keeping fewer entries shrinks it;
    a constant deleted from its module does not.

    **Not the files read**: an ``exclude``, ``only`` or ``suffixes`` narrowing is
    not caught, and ``docs/introduction.md`` § Known limits says so.
    """
    return {
        f"check:{registry.name}:entries": _declared(
            registry,
            (entry.id for entry in registry.entries() if entry.antipatterns),
            prints or {},
        )
        for registry in registries
    }


def undeclared(registries: Iterable[Registry]) -> Coverage:
    """Each closed registry. Opening one is the whole of how Catch A narrows by
    declaration, so the row is the fact of closure itself."""
    return {
        f"undeclared:{registry.name}": ("closed",)
        for registry in registries
        if getattr(registry, "closed", False)
    }


def claims(counts: Sequence[str], gates: Sequence[str]) -> Coverage:
    """The declared ``[[count]]`` labels and ``[[gate]]`` commands. A count
    deleted, or a gate row dropped from the inventory, shrinks it."""
    covered: Coverage = {}
    if counts:
        covered["claims:counts"] = tuple(sorted(set(counts)))
    if gates:
        covered["claims:gates"] = tuple(sorted(set(gates)))
    return covered


def shape(
    results: Iterable[Shaped],
    registries: Iterable[Registry] = (),
    prints: Mapping[str, str] | None = None,
) -> tuple[Coverage, set[str]]:
    """The entries each rule examined, and the keys of rules that could not run.

    A rule's group is chosen by its guard, which is part of the declaration, so
    a guard narrowed by an edit drops rows here. A **blocked** rule has already
    failed on its own, and its key is returned apart so that failure is not
    reported a second time as lost coverage.
    """
    by_name = {registry.name: registry for registry in registries}
    covered: Coverage = {}
    blocked: set[str] = set()
    for result in results:
        registry = by_name.get(result.registry)
        for item in result.judged:
            key = f"shape:{result.registry}:{item.rule.name}"
            if item.blocked:
                blocked.add(key)
            elif registry is None:
                covered[key] = tuple(sorted(item.names))
            else:
                covered[key] = _declared(registry, item.names, prints or {})
    return covered, blocked


def probe(
    results: Iterable[Probed], prints: Mapping[str, str] | None = None
) -> tuple[Coverage, set[str]]:
    """The cases each corpus ran, and the keys of probes that could not run --
    returned apart for the reason :func:`shape`'s are.

    **The population is the corpus itself**: a probe runs every case it is
    handed, so a case gone from the corpus is a data edit and passes, while a
    ``cases`` pointed at a thinner corpus changes the table and does not.
    """
    covered: Coverage = {}
    blocked: set[str] = set()
    for result in results:
        key = f"probe:{result.probe}"
        if result.blocked:
            blocked.add(key)
        else:
            source = probe_source(result.probe)
            covered[key] = Covered(
                rows=tuple(sorted(set(result.cases))),
                population=frozenset(result.cases),
                source=source,
                fingerprint=(prints or {}).get(source, ""),
            )
    return covered, blocked


def owned_by(
    prefix: str, narrowed_to: str | None = None, skip: Iterable[str] = ()
) -> Callable[[str], bool]:
    """The keys a gate judges: its own prefix, one registry's when a run was
    narrowed to it, and never a key whose check could not run."""
    head = f"{prefix}:{narrowed_to}:" if narrowed_to else f"{prefix}:"
    skipped = set(skip)
    return lambda key: (key.startswith(head) or key == head.rstrip(":")) and key not in skipped

