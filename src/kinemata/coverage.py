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
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

from .contract import Registry
from .probe import Probed
from .shape import Shaped


def check(registries: Iterable[Registry]) -> dict[str, tuple[str, ...]]:
    """Each registry's entries that carry an antipattern -- what ``check`` can
    report a bypass of. A registry removed, a module dropped from a
    ``python-constants`` list, or a ``where`` keeping fewer entries shrinks it.

    **Not the files read**: an ``exclude``, ``only`` or ``suffixes`` narrowing is
    not caught, and ``docs/introduction.md`` § Known limits says so.
    """
    return {
        f"check:{registry.name}:entries": tuple(sorted(
            entry.id for entry in registry.entries() if entry.antipatterns
        ))
        for registry in registries
    }


def undeclared(registries: Iterable[Registry]) -> dict[str, tuple[str, ...]]:
    """Each closed registry. Opening one is the whole of how Catch A narrows by
    declaration, so the row is the fact of closure itself."""
    return {
        f"undeclared:{registry.name}": ("closed",)
        for registry in registries
        if getattr(registry, "closed", False)
    }


def claims(counts: Sequence[str], gates: Sequence[str]) -> dict[str, tuple[str, ...]]:
    """The declared ``[[count]]`` labels and ``[[gate]]`` commands. A count
    deleted, or a gate row dropped from the inventory, shrinks it."""
    covered: dict[str, tuple[str, ...]] = {}
    if counts:
        covered["claims:counts"] = tuple(sorted(set(counts)))
    if gates:
        covered["claims:gates"] = tuple(sorted(set(gates)))
    return covered


def shape(results: Iterable[Shaped]) -> tuple[dict[str, tuple[str, ...]], set[str]]:
    """The entries each rule examined, and the keys of rules that could not run.

    A rule's group is chosen by its guard, which is part of the declaration, so
    a guard narrowed by an edit drops rows here. A **blocked** rule has already
    failed on its own, and its key is returned apart so that failure is not
    reported a second time as lost coverage.
    """
    covered: dict[str, tuple[str, ...]] = {}
    blocked: set[str] = set()
    for result in results:
        for item in result.judged:
            key = f"shape:{result.registry}:{item.rule.name}"
            if item.blocked:
                blocked.add(key)
            else:
                covered[key] = tuple(sorted(item.names))
    return covered, blocked


def probe(results: Iterable[Probed]) -> tuple[dict[str, tuple[str, ...]], set[str]]:
    """The cases each corpus ran, and the keys of probes that could not run --
    returned apart for the reason :func:`shape`'s are."""
    covered: dict[str, tuple[str, ...]] = {}
    blocked: set[str] = set()
    for result in results:
        key = f"probe:{result.probe}"
        if result.blocked:
            blocked.add(key)
        else:
            covered[key] = tuple(sorted(result.cases))
    return covered, blocked


def owned_by(
    prefix: str, narrowed_to: str | None = None, skip: Iterable[str] = ()
) -> Callable[[str], bool]:
    """The keys a gate judges: its own prefix, one registry's when a run was
    narrowed to it, and never a key whose check could not run."""
    head = f"{prefix}:{narrowed_to}:" if narrowed_to else f"{prefix}:"
    skipped = set(skip)
    return lambda key: (key.startswith(head) or key == head.rstrip(":")) and key not in skipped

