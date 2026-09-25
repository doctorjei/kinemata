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

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .bypass import Bypass
from .claims import ORACLE_TIMEOUT, run_oracle
from .contract import MISSING, Entry, Registry, at_path, field_path, spell_path

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

#: On both sides, where the declaration claims nothing is. Its own scope for
#: the reason :data:`VALUE_DIRECTION` is: only a ``disjoint`` run judges it, and
#: a scope a run cannot judge is a set of records ``--prune`` deletes in
#: silence.
OVERLAP_DIRECTION = "overlapping"

#: Every scope a parity run can produce.
SCOPES = (*DIRECTIONS, VALUE_DIRECTION, OVERLAP_DIRECTION)

#: What a declaration claims about the two sets. ``equal`` is what this
#: mechanism did before there was a choice, and is the default.
#:
#: Spelled as the claim rather than as a subtraction from ``equal`` -- not
#: ``direction = "one"`` -- because membership otherwise *means* "and there is
#: nothing else", and a reader of a config has to be able to see that a
#: particular parity is not closed-world. The first sketch of this key was a
#: direction and reached one of the three rows that wanted it: a disjointness is
#: not a direction.
RELATIONS = ("equal", "declared_contains", "produced_contains", "disjoint")

#: Which membership sets a relation calls a finding. Everything not named here
#: is computed and then *expected*, which is the whole point of the key.
RELATION_FINDS: dict[str, tuple[str, ...]] = {
    "equal": DIRECTIONS,
    "declared_contains": ("undeclared",),
    "produced_contains": ("unproduced",),
    "disjoint": (OVERLAP_DIRECTION,),
}

#: What each relation claims, in the words a refusal and a report use.
RELATION_SAYS = {
    "equal": "the declaration and the code name the same identifiers",
    "declared_contains": "every identifier the code produces is declared",
    "produced_contains": "every identifier declared is produced by the code",
    "disjoint": "no identifier is both declared and produced",
}

#: Which side of a value comparison is the claim. Required of a declaration
#: that compares values and meaningless without one: see :class:`Divergence`.
AUTHORITIES = ("declared", "produced")

#: How an oracle spells the values it prints, and so how they are compared.
#:
#: ``text``, the default and what every parity meant before the key existed:
#: the printed text against the declared cell rendered with ``str``, a scalar or
#: a flat list of them. ``json``: each printed value is JSON, and both sides are
#: compared **as data** -- see :attr:`Oracle.format`.
FORMATS = ("text", "json")

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

    The two rows it was built for are a manifest writing a directory prefix with
    a trailing separator where the code carries none, and a spec's outcome
    vocabulary mapped onto the code's own constants. Both are notation rather
    than drift.

    **It exists to make that translation visible in the config.** The capability
    was never missing -- an oracle can always print whatever the declaration
    spells -- but there it is invisible, and a reader of the config cannot see
    that a comparison is not literal.

    ⚑ **One is not enough for real declarations, and this docstring used to say
    it was.** The sentence generalized a three-row sample; see
    ``docs/introduction.md`` [0TN7FP9-Pa0004] § Known limits, which carries the
    measurement that withdrew it and what a wider form would take.

    ⚑ **One per SIDE, since 2026-09-19.** A value comparison spends this on the
    values, so :attr:`Oracle.translate_identifier` is the identifier hop -- see
    that attribute for why it is a capability rather than a convenience. Still
    one translation per side: a pipeline of them is what nobody can read off a
    config.

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
    #:
    #: A key, or a **path** into ``extra`` written as a list --
    #: ``["default", "primary"]`` reaches the ``primary`` arm of a mode-keyed
    #: map. A bare string is one key however many dots it holds; see
    #: :func:`kinemata.contract.field_path`.
    field: str | tuple[str, ...] = ""
    #: Which side is the claim, from :data:`AUTHORITIES`. Required alongside
    #: :attr:`field` and optional without it.
    authority: str = ""
    #: Applied to the **declared** side of whatever comparison this makes: the
    #: identifiers when :attr:`field` is empty, the values when it is not. One
    #: target, so what a translation touches is a thing a reader can settle from
    #: the config rather than infer.
    translate: Translation | None = None
    #: Applied to the declared **identifiers**, in a run that also compares
    #: values. Without it such a run has no way to spell an identifier hop, and
    #: membership runs regardless -- so a declaration whose keys are spelled one
    #: way and whose values are spelled another could be made to pass only by
    #: having the **oracle** re-key its own output.
    #:
    #: ⚑ **That escape is why this exists rather than being a convenience.**
    #: Measured on an adopter's real manifest: the oracle route turns the run
    #: green and puts the hop somewhere no reader of the config can see it,
    #: which is the exact visibility :class:`Translation` was built to buy.
    #: A capability whose absence is routed around silently is not absent, it
    #: is undeclared.
    #:
    #: Refused alongside a bare :attr:`translate` when :attr:`field` is empty:
    #: there is one side to translate then, and two keys naming it is a
    #: declaration saying the same thing twice.
    translate_identifier: Translation | None = None
    #: What this declaration claims about the two sets, from :data:`RELATIONS`.
    #: ``equal`` is the default and is what every parity meant before the key
    #: existed, so no declaration written without it changes.
    relation: str = "equal"
    #: Compare a list-valued cell **in order** rather than as a set. Opt-in, and
    #: refused without :attr:`field`: membership compares identifiers, where
    #: there is no cell to order.
    #:
    #: The set rule is deliberate and stays the default --
    #: ``test_a_list_valued_field_is_compared_as_a_set`` argues it, and a
    #: declaration matched order-independently by the code that reads it should
    #: not file a finding on a harmless reorder. What was missing is any way to
    #: state the **other** claim: measured on an adopter's real manifest, an
    #: oracle printing the three access tiers reversed reported *agreeing on
    #: choices*, and the stronger claim could not be spelled at all -- not by
    #: printing the container, whose declared side renders sorted, and not by
    #: addressing a list by index, which :func:`kinemata.contract.at_path` does
    #: not do. That manifest states the order as the meaning in its own
    #: comments: an authority cascade, a containment chain, a tier list.
    #:
    #: ⚑ **It pins the order the ORACLE prints in**, which nothing here can
    #: verify is the code's own order rather than an accident of how the command
    #: iterates. Positional rather than semantic, like
    #: :attr:`kinemata.claims.Counted.occurrence` -- an oracle that sorts its
    #: output makes a correct declaration red.
    ordered: bool = False
    #: How the oracle spells each printed value, from :data:`FORMATS`.
    #:
    #: ``json`` compares **data rather than text**: each printed value is parsed
    #: as JSON, the declared cell is taken as the value the declaration holds,
    #: and they must be equal -- a mapping whatever its key order, a list in
    #: order, and ``1``, ``"1"`` and ``true`` three different things. Written
    #: because the ``text`` form refuses any cell holding a mapping, and one such
    #: cell stands the whole registry's value comparison down: an adopter
    #: measured 18 of their 66 ``default`` rows as mode-keyed maps. A path into
    #: one arm reaches each map a view at a time; comparing the column whole,
    #: scalars and maps together, needed a spelling for a map, and **JSON is one
    #: the declaration does not have to invent** -- any oracle can print it, and
    #: parsing it back leaves nothing to agree on by accident.
    #:
    #: It also tells a declared ``null`` from a field the declaration does not
    #: carry, which the ``text`` form collapses: ``null`` must meet a printed
    #: ``null``, while an absent field stays *the declaration records nothing*.
    #:
    #: Refused without :attr:`field` and beside :attr:`ordered` (a JSON list is
    #: already ordered). :attr:`translate` rewrites every string inside the
    #: declared value, never a mapping's key -- see :func:`_declared_json`.
    format: str = "text"


def _canonical(value: object) -> str:
    """One spelling per value, so equal data compares equal as text.

    Keys sorted and separators fixed, so a mapping's order cannot make two equal
    values differ; ``allow_nan`` off, because ``NaN`` is not JSON and is not
    equal to itself.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    )


def _printed_json(text: str) -> str:
    """A printed value, parsed and respelled -- or marked as not JSON at all.

    The mark cannot equal a declared value, which is always valid JSON once
    spelled, so an oracle printing something unparseable diverges on that row
    and says what it printed, rather than blocking every other row with it.
    """
    try:
        return _canonical(json.loads(text))
    except ValueError:
        return f"<not JSON: {text}>"


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
        if self.direction == OVERLAP_DIRECTION:
            return f"{self.identifier}: declared and produced, where neither may be"
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
    ``docs/structure.md`` [0TN7FP9-Pa0001] uses: the authority is recorded, and
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
    #:
    #: **Sorted except under** :attr:`ordered`, where the sequence *is* the
    #: claim and sorting it would throw away the thing that disagreed.
    declared: tuple[str, ...] = ()
    produced: tuple[str, ...] = ()
    #: The declaration compared this cell in order, so both sides are reported
    #: in full. A pure reorder has no set difference at all, and the message
    #: below would otherwise say *declared by nothing* about values both sides
    #: carry.
    ordered: bool = False
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
        elif self.ordered:
            # Both sides in full, and the reorder named when that is all it is:
            # a set difference is empty there, so naming only what differs would
            # print two empty lists about a real disagreement.
            same = sorted(self.declared) == sorted(self.produced)
            head = (f"{self.identifier}: {self.field} declared "
                    f"{_listed(self.declared)} in this order, code produces "
                    f"{_listed(self.produced)}"
                    + (" (the same values, reordered)" if same else ""))
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
    #: On both sides. Only ever populated by a ``disjoint`` run, where being on
    #: both sides is the mistake; under every other relation an identifier both
    #: sides carry is the agreement being looked for.
    overlapping: tuple[str, ...] = ()
    #: What the declaration claimed about the two sets, which decides which of
    #: the sets above are findings and which are expected.
    relation: str = "equal"
    #: Entries both sides carry and disagree about, empty when the declaration
    #: named no field to compare.
    divergent: tuple[Divergence, ...] = ()
    #: The field this run compared, empty when it compared membership alone.
    #: Read by :meth:`scopes` rather than inferred from :attr:`divergent`, which
    #: is empty both when nothing was compared and when everything agreed.
    compared: str = ""
    #: Entries whose declared cell held a **list**, and whose comparison was
    #: therefore a set comparison with the declaration's order discarded.
    #:
    #: **Reported because it is a suppression that reported nothing.** A
    #: declaration pinning ``choices`` against the code's own tuple reads
    #: ``in agreement, agreeing on choices`` while the code's *order* changes
    #: underneath it -- measured against an adopter's real manifest, where an
    #: oracle printing the three access tiers reversed still agreed. The
    #: set rule itself is deliberate and argued in
    #: ``test_a_list_valued_field_is_compared_as_a_set``; what was missing is
    #: any way for a reader of the run to learn that the weaker question was
    #: the one answered. Every other suppression in this package prints a line.
    #:
    #: **Only the cells compared as sets**: one compared in order is not a
    #: suppression, and is counted in :attr:`ordered_cells` instead.
    set_valued: tuple[str, ...] = ()
    #: The declaration asked for an ordered comparison, whether or not any cell
    #: held a list. Carried so a run can say that the key did **nothing** --
    #: over a registry of scalars it is inert, and an inert key that prints
    #: nothing is this mechanism's own subject.
    ordered: bool = False
    #: Entries whose declared cell held a list and whose order was therefore
    #: part of the claim. The other half of :attr:`set_valued`, so the two
    #: counts together say which question every list cell was asked.
    ordered_cells: tuple[str, ...] = ()

    @property
    def failed(self) -> bool:
        return bool(self.blocked or self.disagreements() or self.divergent)

    def disagreements(self) -> list[Disagreement]:
        """The membership half, in whichever directions this relation calls a
        mistake.

        A set the relation does not name is still computed -- it is the shape of
        the claim, not a filter on the output -- and is *expected* rather than
        suppressed: under ``declared_contains`` a declared identifier the code
        never produces is the declaration being allowed to name more, which is
        the whole reason somebody wrote that relation down.
        """
        return [
            Disagreement(self.registry, identifier, direction)
            for direction in RELATION_FINDS[self.relation]
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

        ⚑ **Both membership directions are claimed under every relation**, not
        only the ones it calls findings. The run computed both sets and ruled on
        them, so records that stopped being findings because the relation
        changed are correctly pruned -- that is the claim moving, not a scope
        going unexamined. **``overlapping`` is the exception**: only a
        ``disjoint`` run is in a position to judge it.
        """
        names = [*DIRECTIONS]
        if self.relation == "disjoint":
            names.append(OVERLAP_DIRECTION)
        if self.compared:
            names.append(VALUE_DIRECTION)
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
    #: declaration named no field. Every match rather than the first: an oracle
    #: printing one identifier twice is stating two values, and picking one is
    #: the mistake ``finditer`` is here to avoid in the first place.
    #:
    #: **In the order the oracle printed them**, duplicates kept, for the reason
    #: :class:`_DeclaredSide` keeps its own: an ordered comparison cannot be
    #: recovered from a set, and the unordered one -- still the default -- takes
    #: ``set()`` of this and is unchanged by the sequence underneath it.
    values: Mapping[str, tuple[str, ...]] | None = None


def produced(
    spec: Oracle, root: Path, timeout: float = ORACLE_TIMEOUT
) -> tuple[Printed | None, str]:
    """What the oracle printed, or ``None`` and why not.

    An oracle that *succeeds* and matches nothing returns the empty set rather
    than ``None``, and that is a real answer: a project whose code produces no
    identifiers has a declaration that is entirely unproduced, which is a
    finding and not a broken check. Collapsing the two would let a silent oracle
    read as an empty world.

    An oracle that **fails** is the other way round, which is why the exit
    status is fatal here and not in :func:`kinemata.claims.actual_count`. A set
    extraction cannot tell a wreck from an empty world -- both are text with no
    matches in it -- so a command dying on ``ImportError`` used to put the whole
    declaration into ``unproduced`` without blocking anything, and
    ``baseline --record`` accepted every identifier as an exemption. An oracle
    that legitimately exits non-zero has to say so in its own command.
    """
    output, why = run_oracle(
        spec.command, root, spec.directory, timeout, answers_on_failure=False
    )
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
            f"compares the {spell_path(spec.field)!r} field but its extract has one "
            "capture "
            "group; group 1 is the identifier and group 2 is its value"
        )
    matches = list(pattern.finditer(output))
    ids = frozenset(match.group(1).strip() for match in matches)
    if not spec.field:
        return Printed(ids=ids), ""
    values: dict[str, list[str]] = {}
    for match in matches:
        values.setdefault(match.group(1).strip(), []).append(
            (match.group(2) or "").strip()
        )
    return Printed(
        ids=ids,
        values={key: tuple(seen) for key, seen in values.items()},
    ), ""


# Rendered rather than compared as they arrive, because one side of this
# comparison is always text: an oracle prints. `str` is exact for a string and
# unambiguous for a number or a bool, and a project whose oracle spells `true`
# where TOML holds `true` declares a translation -- which is a thing a reader
# can see, unlike a coercion rule nobody wrote down.
_SCALARS = (str, int, float, bool)


def _rendered(value: object) -> str | None:
    return str(value) if isinstance(value, _SCALARS) else None


@dataclass(frozen=True)
class _DeclaredSide:
    """One entry's declared side, rendered for comparison.

    **A named field rather than a tuple**, on the same reasoning
    :class:`kinemata.targets.Target` records: :attr:`listed` was added to a
    three-tuple every caller unpacked positionally, and a fourth slot nobody
    can read at the call site is how a fact gets carried and then ignored.
    """

    #: The values to compare, or ``None`` when the cell cannot be rendered.
    #: **In the order the cell declares them, duplicates kept**, because a set is
    #: derivable from a sequence and a sequence is not derivable from a set --
    #: the unordered comparison, which is still the default, takes ``set()`` of
    #: this and reads exactly as it did when this was a ``frozenset``.
    values: tuple[str, ...] | None
    #: The declaration records nothing here, which is a claim rather than a gap.
    absent: bool
    #: Why it could not be rendered, empty when it could.
    problem: str
    #: The cell held a **list**, so the comparison that follows is a set
    #: comparison and its order was discarded. Carried out of here rather than
    #: re-derived by the caller: the lookup is a path walk, and doing it twice
    #: to learn one fact about the first walk is this package's own subject.
    listed: bool


def _declared_values(
    entry: Entry, spec: Oracle, translate: Translation
) -> _DeclaredSide:
    """One entry's declared side: the values, whether absent, and why not.

    A container that is not a flat list is **refused** rather than rendered. It
    has an internal order and a spelling no two sides agree on by accident, so
    ``str``-ing it would be a normalization that does not fail -- it passes.
    """
    found = at_path(entry.extra, field_path(spec.field))
    # A path reaching nothing and a declared ``null`` collapse here, and did
    # before paths existed: for a comparison, "this row has no such arm" and
    # "this row declares nothing there" are the same claim. The distinction
    # :data:`~kinemata.contract.MISSING` keeps is for a *selector*, where it
    # decides membership rather than a value.
    raw = None if found is MISSING else found
    if raw is None:
        return _DeclaredSide((), True, "", False)
    listed = isinstance(raw, (list, tuple))
    items = list(raw) if listed else [raw]
    rendered = [_rendered(item) for item in items]
    if any(item is None for item in rendered):
        kinds = ", ".join(sorted({type(item).__name__ for item in items}))
        return _DeclaredSide(None, False, (
            f"declares {entry.id} with a {spell_path(spec.field)!r} holding {kinds}, "
            "which "
            "is not a scalar or a list of them and has no spelling an oracle "
            "could be expected to print"
        ), listed)
    return _DeclaredSide(
        tuple(translate.apply(item) for item in rendered), False, "", listed
    )


def _rewritten(value: object, translate: Translation) -> object:
    """``value`` with ``translate`` applied to every string in it.

    A scalar, a list item, a mapping's **value** -- never a mapping's key, which
    is the data's shape rather than its content: a mode-keyed map's keys are the
    modes, and an identifier hop has :attr:`Oracle.translate_identifier`.
    Anything that is not a string passes through untouched, since a translation
    is a rewrite of text and nothing here coerces a number into one.
    """
    if isinstance(value, str):
        return translate.apply(value)
    if isinstance(value, (list, tuple)):
        return [_rewritten(item, translate) for item in value]
    if isinstance(value, Mapping):
        return {key: _rewritten(item, translate) for key, item in value.items()}
    return value


def _declared_json(
    entry: Entry, spec: Oracle, translate: Translation
) -> _DeclaredSide:
    """One entry's declared side under :attr:`Oracle.format` ``json``.

    **A field the declaration does not carry is absent; a declared ``null`` is
    the value** ``null``. The text form collapses the two, and has to: it has no
    spelling for nothing. A value JSON cannot spell -- a YAML date, say -- is
    refused for the registry as a container is in the text form, since
    rendering it some other way would be the guess this form exists to avoid.

    ``translate`` reaches **every string inside the value** (:func:`_rewritten`)
    before it is compared as data. This was refused until 2026-09-25 as *a
    rewrite of text, which data does not have* -- but data's strings are text,
    and an adopter's manifest spells values in its own notation inside
    mode-keyed maps (``"(@system.canon/handbook/general)"``). With the refusal
    the claim *after this rewrite, compare as data* had no form: they split
    each map into one ``text`` view per mode, and built maps on the oracle side,
    where no reader of the config can see the rewrite.
    """
    found = at_path(entry.extra, field_path(spec.field))
    if found is MISSING:
        return _DeclaredSide((), True, "", False)
    try:
        return _DeclaredSide(
            (_canonical(_rewritten(found, translate)),), False, "", False
        )
    except (TypeError, ValueError):
        return _DeclaredSide(None, False, (
            f"declares {entry.id} with a {spell_path(spec.field)!r} holding "
            f"{type(found).__name__}, which JSON cannot spell"
        ), False)


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

    **Order is not part of the claim by default.** Sets, deliberately: the
    declarations this checks are matched order-independently by the code that
    reads them, so pinning a sequence would file a finding on a harmless
    reorder. Adopters writing this assertion by hand reached the same rule and
    put it in their own words -- assert the rule, not the inventory. A
    declaration whose order *is* the claim says :attr:`Oracle.ordered`, which
    leaves that default untouched and is refused without a field to compare.

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
    if spec.relation not in RELATIONS:
        raise ValueError(
            f"unknown parity relation: {spec.relation!r} "
            f"(known: {', '.join(RELATIONS)})"
        )
    if spec.field and spec.relation != "equal":
        # The config refuses this first; this is the second answer, for a caller
        # assembling specs itself. A value comparison pairs identifiers both
        # sides carry: under `disjoint` there are none by construction, and
        # under a containment the pairing is defined only over the intersection,
        # which is a claim nothing has asked for.
        raise ValueError(
            f"a parity claiming {spec.relation!r} cannot also compare "
            f"{spell_path(spec.field)!r}: a value comparison needs identifiers "
            "on both sides, which is the thing this relation is about"
        )
    if spec.ordered and not spec.field:
        # The config refuses this first; this is the second answer, for a caller
        # assembling specs itself. Membership compares identifiers, which are a
        # set on both sides by construction -- there is no cell to put in order.
        raise ValueError(
            "a parity comparing membership alone cannot be ordered: order is a "
            "property of a declared cell, and this declaration names no field "
            "to compare"
        )
    if spec.format not in FORMATS:
        raise ValueError(
            f"unknown parity format: {spec.format!r} (known: {', '.join(FORMATS)})"
        )
    if spec.format == "json" and (not spec.field or spec.ordered):
        # The config refuses each of these first, naming which; this is the
        # second answer, for a caller assembling specs itself.
        raise ValueError(
            "a json parity compares one field's values as data: it needs a "
            "field, and cannot take ordered"
        )
    if spec.field and spec.authority not in AUTHORITIES:
        # The config layer refuses this first; this is the second answer, for a
        # caller assembling specs itself. A value divergence with no
        # authoritative side is two strings and no claim.
        raise ValueError(
            f"a parity comparing {spell_path(spec.field)!r} needs an authority "
            f"({' or '.join(AUTHORITIES)}): which side is the claim is a "
            "property of the row and cannot be inferred"
        )
    printed, why = produced(spec, root, timeout)
    entries = list(registry.entries())
    translate = spec.translate or Translation()
    # `translate` keeps its published target -- the identifiers of a membership
    # declaration, the values of a value one -- and `translate_identifier` is
    # the second hop, which only a value run can need: without a field there is
    # one side and `translate` already reaches it. The config refuses the pair
    # in that case rather than silently preferring one.
    identify = spec.translate_identifier or (
        Translation() if spec.field else translate
    )
    declared = {identify.apply(entry.id) for entry in entries}
    if printed is None:
        return Parity(
            registry=spec.registry,
            blocked=why,
            declared=len(declared),
            relation=spec.relation,
        )

    # An oracle that produced nothing satisfies `declared_contains` and
    # `disjoint` by having nothing to violate them with, and a vacuous run reads
    # exactly like a clean one. `equal` needs no such rule -- an empty side puts
    # every declared identifier in `unproduced` and fails loudly -- which is why
    # this guard arrived with the relations rather than before them. Applied to
    # `produced_contains` too, where it is not strictly needed: the rule is
    # easier to hold without an exception, and it turns a pile of findings into
    # the one diagnosis that explains them.
    if spec.relation != "equal" and not printed.ids:
        return Parity(
            registry=spec.registry,
            blocked=(
                f"claims {RELATION_SAYS[spec.relation]}, and its oracle produced "
                "no identifiers at all. Nothing can violate that, so the run "
                "would pass by looking at nothing"
            ),
            declared=len(declared),
            relation=spec.relation,
        )

    membership = dict(
        undeclared=tuple(sorted(printed.ids - declared)),
        unproduced=tuple(sorted(declared - printed.ids)),
        overlapping=tuple(sorted(declared & printed.ids)),
    )
    if not spec.field:
        return Parity(
            registry=spec.registry,
            declared=len(declared),
            produced=len(printed.ids),
            relation=spec.relation,
            **membership,
        )

    values = printed.values or {}
    divergent: list[Divergence] = []
    set_valued: list[str] = []
    ordered_cells: list[str] = []
    for entry in entries:
        # Paired on the identifier as *translated*, which is the vocabulary
        # both sides were compared in above. A finding names that spelling for
        # the same reason: it is the one the oracle printed, so a reader can
        # find it in the run they are holding.
        key = identify.apply(entry.id)
        if key not in values:
            continue  # membership above has already said so
        as_data = spec.format == "json"
        side = (
            _declared_json(entry, spec, translate) if as_data
            else _declared_values(entry, spec, translate)
        )
        mine, absent, problem = side.values, side.absent, side.problem
        if side.listed:
            (ordered_cells if spec.ordered else set_valued).append(key)
        if mine is None:
            # **Membership rides along**, and leaving it out was the defect an
            # adopter reported: 18 of their 66 rows hold a dict, so one
            # unrenderable cell threw away a membership answer that was already
            # computed and is unaffected by it. This package's own rule is that
            # a value comparison runs *on top of* membership, never instead of
            # it -- the blocked return was the one place that did not honor it.
            return Parity(
                registry=spec.registry,
                blocked=problem,
                declared=len(declared),
                produced=len(printed.ids),
                compared=spell_path(spec.field),
                relation=spec.relation,
                **membership,
            )
        theirs = (
            tuple(_printed_json(text) for text in values[key]) if as_data
            else values[key]
        )
        # The default asks whether the two sides hold the same values; an
        # ordered declaration asks whether they hold them in the same sequence.
        # Strictly narrower rather than different: everything the set
        # comparison calls a disagreement is one here too. As data, each side is
        # one value -- an oracle printing two for one identifier diverges.
        exact = spec.ordered or as_data
        agrees = mine == theirs if exact else set(mine) == set(theirs)
        if not agrees:
            divergent.append(
                Divergence(
                    registry=spec.registry,
                    identifier=key,
                    field=spell_path(spec.field),
                    authority=spec.authority,
                    declared=mine if exact else tuple(sorted(mine)),
                    produced=theirs if exact else tuple(sorted(theirs)),
                    absent=absent,
                    ordered=spec.ordered,
                )
            )
    return Parity(
        registry=spec.registry,
        declared=len(declared),
        produced=len(printed.ids),
        divergent=tuple(divergent),
        compared=spell_path(spec.field),
        set_valued=tuple(sorted(set_valued)),
        ordered=spec.ordered,
        ordered_cells=tuple(sorted(ordered_cells)),
        relation=spec.relation,
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
