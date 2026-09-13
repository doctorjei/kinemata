"""Declared entries against the set a project's code actually produces.

Every other catch here has to *find* something in text, and that is where its
weaknesses come from: :func:`~kinemata.bypass.unused` reads a mention and calls
it a use, and the closed-world catch cannot ask its question at all unless the
registry can recognize its own identifiers
(:meth:`~kinemata.contract.BaseRegistry.candidates`). Both limits are consequences
of searching rather than of the question being hard.

An oracle removes the search. The project runs a command that prints the
identifiers its code really produces, and the comparison against the declaration
is a set difference in two directions:

``undeclared``
    produced, and the registry does not declare it. The closed-world question,
    answered without a recognizer.
``unproduced``
    declared, and nothing produces it. The disuse question, answered without
    mistaking a mention for a use.

**This is the positive twin of the registry scan**, and the first mechanism here
that reads a registry *and* runs a command. What makes it safe is that it
borrows the discipline already settled for a declared oracle rather than
restating it: one oracle form, an exact comparison, and an oracle that cannot
answer is a **failure** and never a pass. See :mod:`kinemata.claims`, where that
rule was written and is enforced for the other oracle this package runs.

**Why membership before values.** An adopting project inventoried 326
conformance checks against this tool on 2026-09-09 and found 291 inexpressible;
their largest block was 125 test functions asserting that a manifest row equals
what the code produces. Membership is the half of that needing no new surface on
:class:`~kinemata.contract.Entry`, and it is the half that reaches two published
limits at once.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from .bypass import Bypass
from .claims import ORACLE_TIMEOUT, run_oracle
from .contract import Registry

#: The name parity findings travel under in a baseline record, so a reader can
#: tell which scan produced an exemption and no scan reports another's records
#: as fixed.
PARITY_SCOPE = "parity"

#: Produced but not declared, and declared but not produced. Kept apart down to
#: the scope name because they are opposite mistakes with opposite fixes: one
#: says the declaration is short, the other says it has outlived the code. A
#: reader auditing an exemption list should not have to work out which.
DIRECTIONS = ("undeclared", "unproduced")


def parity_scope(registry: str, direction: str) -> str:
    """The baseline scope for one registry's findings in one direction."""
    if direction not in DIRECTIONS:
        raise ValueError(f"unknown parity direction: {direction!r}")
    return f"{PARITY_SCOPE}:{registry}:{direction}"


def is_parity_scope(name: str) -> bool:
    """Does this baseline record come from a parity run?"""
    return name == PARITY_SCOPE or name.startswith(f"{PARITY_SCOPE}:")


@dataclass(frozen=True)
class Oracle:
    """The command that prints what a project's code actually produces.

    ``extract`` is required rather than defaulted to whole lines. A default
    would read a traceback, a progress bar or a shell warning as identifiers,
    and the resulting disagreement would be reported against the project's
    declaration -- a check that fails for a reason unrelated to the thing it
    checks teaches its reader to ignore it.
    """

    registry: str
    command: tuple[str, ...]
    #: Group 1 of every match is one identifier. Applied with ``finditer``, not
    #: ``search``: a set is the whole point, and reading one match would settle
    #: the first identifier and silently ignore the rest.
    #:
    #: Matched against the **whole** output rather than line by line, so a
    #: pattern anchored with ``^`` needs an inline ``(?m)``. No flag is set
    #: here, because the other declared oracle compiles its ``extract`` the same
    #: way and two spellings of "what a pattern means" in one config file is the
    #: divergence this package reports.
    extract: str
    directory: str = "."


@dataclass(frozen=True)
class Disagreement:
    """One identifier the declaration and the oracle do not agree about."""

    registry: str
    identifier: str
    direction: str

    def __str__(self) -> str:
        if self.direction == "undeclared":
            return f"{self.identifier}: produced, declared by nothing"
        return f"{self.identifier}: declared, produced by nothing"

    def finding(self) -> Bypass:
        """The record the ratchet fingerprints.

        ``antipattern`` is empty and the line is zero for the same reason a
        stray's are: nothing matched a pattern, and a parity finding has no site
        in a file -- the oracle is where it came from. The registry name stands
        in ``path`` because it is the only locator the finding has, and the
        direction is carried by the scope rather than by a field, so the two
        halves cannot be confused in a list somebody is auditing.
        """
        return Bypass(
            entry_id=self.identifier,
            antipattern="",
            path=self.registry,
            line=0,
            text=self.identifier,
        )


@dataclass(frozen=True)
class Parity:
    """What one registry's oracle said, against what the registry declares."""

    registry: str
    #: Why the oracle settled nothing, empty when it answered. **A failure**,
    #: never a note: a declared check that silently does nothing is the inert
    #: signal this package exists to prevent.
    blocked: str = ""
    declared: int = 0
    produced: int = 0
    undeclared: tuple[str, ...] = ()
    unproduced: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return bool(self.blocked or self.undeclared or self.unproduced)

    def disagreements(self) -> list[Disagreement]:
        return [
            Disagreement(self.registry, identifier, direction)
            for direction in DIRECTIONS
            for identifier in getattr(self, direction)
        ]

    def findings(self) -> list[tuple[str, Bypass]]:
        """Every disagreement, tagged with the scope that produced it."""
        return [
            (parity_scope(self.registry, item.direction), item.finding())
            for item in self.disagreements()
        ]

    def scopes(self) -> tuple[str, ...]:
        """The scopes this run is in a position to judge.

        Both directions, always, and not only the ones that found something: a
        scope missing from a run is a scope whose accepted records a prune would
        delete for never having been looked at.
        """
        return tuple(parity_scope(self.registry, name) for name in DIRECTIONS)


def produced(
    spec: Oracle, root: Path, timeout: float = ORACLE_TIMEOUT
) -> tuple[frozenset[str] | None, str]:
    """The identifier set the oracle printed, or ``None`` and why not.

    An oracle that runs and matches nothing returns the empty set rather than
    ``None``, and that is a real answer: a project whose code produces no
    identifiers has a declaration that is entirely unproduced, which is a
    finding and not a broken check. Collapsing the two would let a silent oracle
    read as an empty world.
    """
    output, why = run_oracle(spec.command, root, spec.directory, timeout)
    if output is None:
        return None, why
    try:
        pattern = re.compile(spec.extract)
    except re.error as error:
        return None, f"has an unusable extract ({error})"
    if pattern.groups < 1:
        return None, "has an extract with no capture group"
    return frozenset(
        match.group(1).strip() for match in pattern.finditer(output)
    ), ""


def compare(
    registry: Registry,
    spec: Oracle,
    root: Path,
    timeout: float = ORACLE_TIMEOUT,
) -> Parity:
    """One registry's declaration against one oracle's output.

    The comparison is exact: identifiers are compared as the strings both sides
    spelled, with edge whitespace stripped from the oracle's and nothing else
    touched. Nothing is lowercased, stripped of punctuation or otherwise made to
    match, because a normalization that is wrong does not fail -- it passes.
    """
    printed, why = produced(spec, root, timeout)
    declared = {entry.id for entry in registry.entries()}
    if printed is None:
        return Parity(registry=spec.registry, blocked=why, declared=len(declared))
    return Parity(
        registry=spec.registry,
        declared=len(declared),
        produced=len(printed),
        undeclared=tuple(sorted(printed - declared)),
        unproduced=tuple(sorted(declared - printed)),
    )


def survey(
    registries: Iterable[Registry],
    specs: Sequence[Oracle],
    root: Path,
    timeout: float = ORACLE_TIMEOUT,
) -> list[Parity]:
    """Every declared oracle against the registry it names.

    A spec naming a registry that does not exist raises rather than being
    skipped; the config layer refuses it first, and this is the second answer
    for a caller assembling specs itself.
    """
    by_name = {registry.name: registry for registry in registries}
    results: list[Parity] = []
    for spec in specs:
        registry = by_name.get(spec.registry)
        if registry is None:
            raise KeyError(
                f"[[parity]] names registry {spec.registry!r}, which is not "
                f"declared (known: {', '.join(sorted(by_name)) or 'none'})"
            )
        results.append(compare(registry, spec, root, timeout))
    return results
