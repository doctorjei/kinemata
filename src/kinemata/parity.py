"""Declared entries against the set a project's code actually produces.

Every other catch here has to *find* something in text, and that is where its
weaknesses come from: :func:`~kinemata.bypass.unused` reads a mention and calls
it a use, and the closed-world catch cannot ask its question at all unless the
registry can recognize its own identifiers
(:meth:`~kinemata.contract.BaseRegistry.candidates`). Both limits are consequences
of searching rather than of the question being hard.

An oracle removes the search. The project runs a command that prints what its
code really produces, and the comparison against the declaration runs in three
directions:

``undeclared``
    produced, and the registry does not declare it. The closed-world question,
    answered without a recognizer.
``unproduced``
    declared, and nothing produces it. The disuse question, answered without
    mistaking a mention for a use.
``divergent``
    declared and produced, and the two do not say the same thing. Asked only
    when a config names the field to compare, and it does not replace the
    membership pair -- it runs on top of them, so *"and there is nothing else"*
    stays part of every value claim. See :func:`compare`.

**This is the positive twin of the registry scan**, and the first mechanism here
that reads a registry *and* runs a command. What makes it safe is that it
borrows the discipline already settled for a declared oracle rather than
restating it: one oracle form, an exact comparison, and an oracle that cannot
answer is a **failure** and never a pass. See :mod:`kinemata.claims`, where that
rule was written and is enforced for the other oracle this package runs.

**Why membership was built first.** An adopting project inventoried 326
conformance checks against this tool on 2026-09-09 and found 291 inexpressible;
their largest block was 125 test functions asserting that a manifest row equals
what the code produces. Membership is the half of that needing no new surface on
:class:`~kinemata.contract.Entry`, and it is the half that reaches two published
limits at once. The value half followed the same day, designed against three
worked rows from that project rather than guessed at -- which is where
:class:`Translation` and the authority marker come from.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .bypass import Bypass
from .claims import ORACLE_TIMEOUT, run_oracle
from .contract import Entry, Registry

#: The name parity findings travel under in a baseline record, so a reader can
#: tell which scan produced an exemption and no scan reports another's records
#: as fixed.
PARITY_SCOPE = "parity"

#: Produced but not declared, and declared but not produced. Kept apart down to
#: the scope name because they are opposite mistakes with opposite fixes: one
#: says the declaration is short, the other says it has outlived the code. A
#: reader auditing an exemption list should not have to work out which.
DIRECTIONS = ("undeclared", "unproduced")

#: Declared *and* produced, and the two do not say the same thing. A third
#: scope rather than a third member of :data:`DIRECTIONS`, because the
#: membership pair is answerable by any parity run and this one is answerable
#: only by a run that was told which field to compare -- and a scope a run
#: cannot judge is a set of records ``--prune`` deletes in silence.
VALUE_DIRECTION = "divergent"

#: Every scope a parity run can produce.
SCOPES = (*DIRECTIONS, VALUE_DIRECTION)

#: Which side of a value comparison is the claim. Required of a declaration
#: that compares values and meaningless without one: see :class:`Divergence`.
AUTHORITIES = ("declared", "produced")

#: What each authority makes a divergence *mean*. The declared wording is an
#: adopting project's own, from the class docstring of the conformance test this
#: mechanism was designed against: the manifest cell is the expected value and
#: the code is on trial.
AUTHORITY_SAYS = {
    "declared": "the declaration is the expected value and the code is on trial",
    "produced": "the code is the expected value and the declaration has not kept up",
}


def parity_scope(registry: str, direction: str) -> str:
    """The baseline scope for one registry's findings in one direction."""
    if direction not in SCOPES:
        raise ValueError(f"unknown parity direction: {direction!r}")
    return f"{PARITY_SCOPE}:{registry}:{direction}"


def is_parity_scope(name: str) -> bool:
    """Does this baseline record come from a parity run?"""
    return name == PARITY_SCOPE or name.startswith(f"{PARITY_SCOPE}:")


@dataclass(frozen=True)
class Translation:
    """The one translation a declaration may apply to its own side.

    Real rows need at most one, and the accurate characterization an adopting
    project reached for their own suite is **exact after at most one declared,
    single-purpose translation**: a manifest writing a directory prefix with a
    trailing separator where the code carries none, or a spec's outcome
    vocabulary mapped onto the code's own constants. Both are notation rather
    than drift.

    **It exists to make that translation visible in the config.** The capability
    was never missing -- an oracle can always print whatever the declaration
    spells -- but there it is invisible, and a reader of the config cannot see
    that a comparison is not literal.

    Two forms, never both, and each is deliberately dull:

    ``table``
        an exact lookup. A value the table does not name **passes through**,
        which is the exact comparison rather than the absence of one.
    ``pattern`` / ``replacement``
        one :func:`re.sub` per value.

    Nothing here casefolds, strips or coerces. A translation is a thing the
    project declared and a reader can see; a normalization that is wrong does
    not fail, it passes.
    """

    table: Mapping[str, str] | None = None
    pattern: str = ""
    #: Never defaulted from ``pattern``'s presence. An empty replacement is a
    #: legitimate translation -- stripping a suffix is the motivating case -- so
    #: a missing one is refused at load rather than guessed at, because the
    #: guess silently deletes text.
    replacement: str = ""

    def apply(self, value: str) -> str:
        if self.table is not None:
            return self.table.get(value, value)
        if self.pattern:
            return re.sub(self.pattern, self.replacement, value)
        return value


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
    #: Group 1 of every match is one identifier, and group 2 -- required only
    #: when :attr:`field` is set -- is that identifier's value. Applied with
    #: ``finditer``, not ``search``: a set is the whole point, and reading one
    #: match would settle the first identifier and silently ignore the rest.
    #:
    #: Matched against the **whole** output rather than line by line, so a
    #: pattern anchored with ``^`` needs an inline ``(?m)``. No flag is set
    #: here, because the other declared oracle compiles its ``extract`` the same
    #: way and two spellings of "what a pattern means" in one config file is the
    #: divergence this package reports.
    extract: str
    directory: str = "."
    #: The key in :attr:`~kinemata.contract.Entry.extra` whose value must equal
    #: what the oracle prints for that identifier. Empty compares membership
    #: alone.
    #:
    #: A key rather than a contract attribute, because the fields worth
    #: comparing are the project's -- a manifest row's ``default``, ``scope``,
    #: ``type`` -- and ``extra`` is where a project's own fields already ride.
    #: **kinemata never picks the field**; a config names it or no value is
    #: compared.
    field: str = ""
    #: Which side is the claim, from :data:`AUTHORITIES`. Required alongside
    #: :attr:`field` and optional without it.
    authority: str = ""
    #: Applied to the **declared** side of whatever comparison this makes: the
    #: identifiers when :attr:`field` is empty, the values when it is not. One
    #: target, so "at most one declared translation" stays a sentence a reader
    #: can check against the config.
    translate: Translation | None = None


def _listed(values: Iterable[str]) -> str:
    """Values as a reader should see them: quoted, so an empty one is visible."""
    return ", ".join(repr(value) for value in values)


@dataclass(frozen=True)
class Disagreement:
    """One identifier the declaration and the oracle do not agree about."""

    registry: str
    identifier: str
    direction: str

    @property
    def scope(self) -> str:
        return parity_scope(self.registry, self.direction)

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
class Divergence:
    """One entry both sides carry, whose declared value is not what ran.

    **Which side is right is not derivable and is not guessed.** For the rows
    this was designed against it is a real property of the row rather than a
    convention: where a shipped manifest cell is the expected value and the code
    is on trial, a divergence is an approved-breakage question, and a form that
    lets either side be edited to match the other has lost what the check
    existed for. So :attr:`authority` is carried into the message, and a
    declaration comparing values without one is refused at load -- a finding a
    reader cannot act on is the inert signal this package exists to prevent.

    ⚠ What that buys is a **reminder** in the sense
    ``docs/structure.md`` [0TN49Y3-Pa0001] uses: the authority is recorded, and
    nothing here can stop the authoritative side being edited to silence the
    finding. The baseline has the same shape and the same answer -- it is a
    visible change to a committed file.
    """

    registry: str
    identifier: str
    field: str
    authority: str
    #: Both sides in full, sorted, after any declared translation. The
    #: **message** names only what differs, but the record fingerprints all of
    #: it, so a disagreement that changes into a different disagreement re-fires
    #: instead of resting under a record written for the old one.
    declared: tuple[str, ...] = ()
    produced: tuple[str, ...] = ()
    #: The declaration carries no such field at all. Kept apart from *declared
    #: nothing* because they read differently to whoever has to fix it: one is a
    #: value that disagrees, the other is a fact the registry does not record.
    absent: bool = False

    @property
    def scope(self) -> str:
        return parity_scope(self.registry, VALUE_DIRECTION)

    def _sides(self) -> tuple[tuple[str, ...], tuple[str, ...]]:
        """What each side has and the other does not."""
        declared, produced = set(self.declared), set(self.produced)
        return (
            tuple(value for value in self.declared if value not in produced),
            tuple(value for value in self.produced if value not in declared),
        )

    def __str__(self) -> str:
        mine, theirs = self._sides()
        if self.absent:
            head = (f"{self.identifier}: the declaration records no "
                    f"{self.field}, and the code produces {_listed(theirs)}")
        elif mine and theirs:
            head = (f"{self.identifier}: {self.field} declared {_listed(mine)}, "
                    f"code produces {_listed(theirs)}")
        elif mine:
            head = (f"{self.identifier}: {self.field} declared {_listed(mine)}, "
                    "produced by nothing")
        else:
            head = (f"{self.identifier}: {self.field} produced "
                    f"{_listed(theirs)}, declared by nothing")
        return f"{head} -- {AUTHORITY_SAYS[self.authority]}"

    def finding(self) -> Bypass:
        """The record the ratchet fingerprints.

        **The field is the antipattern**, mapping this finding's two questions
        -- *what about this entry* and *which entry* -- onto the two a bypass
        record already has. ``claims`` and ``provenance`` map theirs the same
        way, and a third mapping for a third finding type would leave the
        baseline file unreadable by pattern.
        """
        return Bypass(
            entry_id=self.identifier,
            antipattern=self.field,
            path=self.registry,
            line=0,
            text=f"{_listed(self.declared) or 'nothing'} != "
                 f"{_listed(self.produced) or 'nothing'}",
        )


@dataclass(frozen=True)
class Parity:
    """What one registry's oracle said, against what the registry declares."""

    registry: str
    #: Why nothing was settled, empty when the comparison ran. **A failure**,
    #: never a note: a declared check that silently does nothing is the inert
    #: signal this package exists to prevent. An oracle that could not answer is
    #: the usual reason; a declared value this cannot compare is the other.
    blocked: str = ""
    declared: int = 0
    produced: int = 0
    undeclared: tuple[str, ...] = ()
    unproduced: tuple[str, ...] = ()
    #: Entries both sides carry and disagree about, empty when the declaration
    #: named no field to compare.
    divergent: tuple[Divergence, ...] = ()
    #: The field this run compared, empty when it compared membership alone.
    #: Read by :meth:`scopes` rather than inferred from :attr:`divergent`, which
    #: is empty both when nothing was compared and when everything agreed.
    compared: str = ""

    @property
    def failed(self) -> bool:
        return bool(
            self.blocked or self.undeclared or self.unproduced or self.divergent
        )

    def disagreements(self) -> list[Disagreement]:
        """The membership half, in both directions."""
        return [
            Disagreement(self.registry, identifier, direction)
            for direction in DIRECTIONS
            for identifier in getattr(self, direction)
        ]

    def reports(self) -> list[Disagreement | Divergence]:
        """Everything this run found, in the order a reader should see it.

        Membership first: an identifier missing from one side is the larger
        mistake, and a value divergence read before it invites fixing a value on
        an entry that should not have existed.
        """
        return [*self.disagreements(), *self.divergent]

    def findings(self) -> list[tuple[str, Bypass]]:
        """Every disagreement, tagged with the scope that produced it."""
        return [(item.scope, item.finding()) for item in self.reports()]

    def scopes(self) -> tuple[str, ...]:
        """The scopes this run is in a position to judge.

        Both membership directions always, and not only the ones that found
        something: a scope missing from a run is a scope whose accepted records
        a prune would delete for never having been looked at.

        **The value scope only when a field was compared**, for the same reason
        read the other way -- a membership-only run has not looked at value
        records and must not be counted as having found them gone.
        """
        names = (*DIRECTIONS, VALUE_DIRECTION) if self.compared else DIRECTIONS
        return tuple(parity_scope(self.registry, name) for name in names)


@dataclass(frozen=True)
class Printed:
    """What one oracle run said, read once and used for both comparisons.

    One run, because a value declaration asks two questions of the same output
    -- *which identifiers* and *what is each one worth* -- and running the
    oracle twice would let the two halves of one report disagree about a tree
    that changed underneath them.
    """

    ids: frozenset[str]
    #: Identifier to the value or values printed for it, empty when the
    #: declaration named no field. A set per identifier: an oracle printing one
    #: identifier twice is stating a set, and the alternative is picking a match
    #: and discarding the rest, which is the mistake ``finditer`` is here to
    #: avoid in the first place.
    values: Mapping[str, frozenset[str]] | None = None


def produced(
    spec: Oracle, root: Path, timeout: float = ORACLE_TIMEOUT
) -> tuple[Printed | None, str]:
    """What the oracle printed, or ``None`` and why not.

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
    if spec.field and pattern.groups < 2:
        return None, (
            f"compares the {spec.field!r} field but its extract has one capture "
            "group; group 1 is the identifier and group 2 is its value"
        )
    matches = list(pattern.finditer(output))
    ids = frozenset(match.group(1).strip() for match in matches)
    if not spec.field:
        return Printed(ids=ids), ""
    values: dict[str, set[str]] = {}
    for match in matches:
        values.setdefault(match.group(1).strip(), set()).add(
            (match.group(2) or "").strip()
        )
    return Printed(
        ids=ids,
        values={key: frozenset(seen) for key, seen in values.items()},
    ), ""


# Rendered rather than compared as they arrive, because one side of this
# comparison is always text: an oracle prints. `str` is exact for a string and
# unambiguous for a number or a bool, and a project whose oracle spells `true`
# where TOML holds `true` declares a translation -- which is a thing a reader
# can see, unlike a coercion rule nobody wrote down.
_SCALARS = (str, int, float, bool)


def _rendered(value: object) -> str | None:
    return str(value) if isinstance(value, _SCALARS) else None


def _declared_values(
    entry: Entry, spec: Oracle, translate: Translation
) -> tuple[frozenset[str] | None, bool, str]:
    """One entry's declared side: the values, whether absent, and why not.

    A container that is not a flat list is **refused** rather than rendered. It
    has an internal order and a spelling no two sides agree on by accident, so
    ``str``-ing it would be a normalization that does not fail -- it passes.
    """
    raw = entry.extra.get(spec.field)
    if raw is None:
        return frozenset(), True, ""
    items = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    rendered = [_rendered(item) for item in items]
    if any(item is None for item in rendered):
        kinds = ", ".join(sorted({type(item).__name__ for item in items}))
        return None, False, (
            f"declares {entry.id} with a {spec.field!r} holding {kinds}, which "
            "is not a scalar or a list of them and has no spelling an oracle "
            "could be expected to print"
        )
    return frozenset(translate.apply(item) for item in rendered), False, ""


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
    match, because a normalization that is wrong does not fail -- it passes. The
    one exception is declared and visible: see :class:`Translation`.

    **Order is not part of the claim.** Sets, deliberately: the declarations this
    checks are matched order-independently by the code that reads them, so
    pinning a sequence would file a finding on a harmless reorder. Adopters
    writing this assertion by hand reached the same rule and put it in their own
    words -- assert the rule, not the inventory.

    **Membership is the "and there is nothing else" half**, which is why it was
    built before per-entry values. A declaration that pins only the members it
    names passes while an unregistered addition walks past it; that is the defect
    hand-written parity tests guard against most often.

    ⚑ **A value comparison does not replace that half, it adds to it.** Membership
    runs whether or not a field is named, and the alternative -- comparing values
    only for the identifiers both sides happen to mention -- would pass on an
    oracle that printed nothing at all. That is the failure an adopting project
    ruled out on 2026-08-23 before this existed: the dangerous oracle is the
    permissive one, because a vacuous run and a clean run read identically.
    Making membership part of the shape means nobody has to remember the rule.
    """
    if spec.field and spec.authority not in AUTHORITIES:
        # The config layer refuses this first; this is the second answer, for a
        # caller assembling specs itself. A value divergence with no
        # authoritative side is two strings and no claim.
        raise ValueError(
            f"a parity comparing {spec.field!r} needs an authority "
            f"({' or '.join(AUTHORITIES)}): which side is the claim is a "
            "property of the row and cannot be inferred"
        )
    printed, why = produced(spec, root, timeout)
    entries = list(registry.entries())
    translate = spec.translate or Translation()
    # The translation has one target, and which one depends on what is being
    # compared: a membership declaration's own side is its identifiers, a value
    # declaration's is its values. Applying it to both would be two
    # translations wearing one name.
    declared = {
        entry.id if spec.field else translate.apply(entry.id) for entry in entries
    }
    if printed is None:
        return Parity(registry=spec.registry, blocked=why, declared=len(declared))

    membership = dict(
        undeclared=tuple(sorted(printed.ids - declared)),
        unproduced=tuple(sorted(declared - printed.ids)),
    )
    if not spec.field:
        return Parity(
            registry=spec.registry,
            declared=len(declared),
            produced=len(printed.ids),
            **membership,
        )

    values = printed.values or {}
    divergent: list[Divergence] = []
    for entry in entries:
        if entry.id not in values:
            continue  # membership above has already said so
        mine, absent, problem = _declared_values(entry, spec, translate)
        if mine is None:
            return Parity(
                registry=spec.registry,
                blocked=problem,
                declared=len(declared),
                produced=len(printed.ids),
                compared=spec.field,
            )
        theirs = values[entry.id]
        if mine != theirs:
            divergent.append(
                Divergence(
                    registry=spec.registry,
                    identifier=entry.id,
                    field=spec.field,
                    authority=spec.authority,
                    declared=tuple(sorted(mine)),
                    produced=tuple(sorted(theirs)),
                    absent=absent,
                )
            )
    return Parity(
        registry=spec.registry,
        declared=len(declared),
        produced=len(printed.ids),
        divergent=tuple(divergent),
        compared=spec.field,
        **membership,
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
