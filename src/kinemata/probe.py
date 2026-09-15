"""A declared probe corpus: what a project's own code accepts and refuses.

Every other mechanism here ends at a **value**. The scan compares a declared
value to one re-derived, :mod:`kinemata.parity` compares a declared set or cell
to what an oracle prints, :mod:`kinemata.shape` compares a declaration to the
rules it states about itself. This one has no value on either side: the fact is
that a callable **accepted** an input or **refused** it.

**Why that earned a mechanism.** Measured 2026-09-14 against all 125 manifest
parity functions of an adopting project, 15 of them assert exactly this and
nothing else -- ``_check_whitelist`` raising on a denied entry, ``key_validity``
returning a message for a key one segment past its family, a copier refusing an
uncovered destination. It was the largest block no mechanism here reached, and
it was built because that ranking said so rather than because it appealed --
the same pass predicted which shape was biggest and the data missed it by 3x.

⚑ **THE CONSTRAINT, and it comes from the sample rather than from this package:
a probe corpus must carry BOTH polarities or it does not run.** Three separate
docstrings in that suite state it, and the clearest is worth quoting because it
is the whole argument:

    *"Deny-by-default means a refusal case passes for any string that is not
    allowed -- including a typo. Showing the same predicate ACCEPTS the allowed
    entries is what proves it discriminates rather than refusing everything put
    to it."*

A refusal-only corpus is satisfied by a callable that refuses everything; an
acceptance-only corpus is satisfied by one that accepts everything. **That is
the same vacuity this package already fails on everywhere else** -- a
:mod:`kinemata.shape` rule that examined no entry, a ``[[count]]`` whose pattern
matched no line, a parity oracle printing an empty set. Same rule, same answer.

⚑ **And kinemata counts the polarities itself**, on the rows it was handed. That
is what makes a project-supplied corpus safe to accept, and it is
:mod:`kinemata.shape`'s answer to the same problem reused rather than re-argued:
*the count is this module's, never self-reported by the code on trial.*

**The seam, and the line the project may not cross.** The project supplies the
**cases** -- only it knows what its own allow-list contains, and only it knows
how it composes a key out of a prefix and a family. It supplies the **target**.
It does **not** supply the reading of the outcome.

**Why that last one is a line rather than a missing feature.** A mechanism that
*extracts* a fact leaves the judging here, where it can be audited; one that
asks the project to classify its own outcome takes the judgement ready-made.
When such a classifier is wrong, the run reports agreement between a wrong
classifier and a wrong declaration -- two errors cancelling into a pass, which
is worse than no check because it produces evidence.

So there is **no predicate escape for reading an outcome**, though
:mod:`kinemata.shape` has one for describing a row and this module would
otherwise have copied it. The two are not the same seam: a shape predicate
supplies a *model of what a row is*, an outcome predicate supplies *the
judgement*. ``docs/introduction.md`` [0TN7FP9-Pa0004] § Known limits carries
what that costs -- an outcome convention neither mode below can read stays in
the project's own tests.

**It is a reminder, not a catch.** An agent can edit a case list and the code it
probes in one commit, exactly as it can edit a ``[[gate]]`` and its workflow.
What it buys is that a corpus which stopped discriminating says so.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from .bypass import Bypass
from .targets import TargetError, resolve

#: The name probe findings travel under in a baseline record.
PROBE_SCOPE = "probe"

#: What a case may claim. Spelled out rather than boolean: ``expect = False`` at
#: a call site says nothing about which polarity it means.
ACCEPT = "accept"
REFUSE = "refuse"
POLARITIES = (ACCEPT, REFUSE)

#: How a target's *answer* may be read. Two dull modes and no third -- see this
#: module's note on why an outcome predicate is refused rather than deferred.
OUTCOME_MODES = ("raises", "returns")

#: What ``accepted`` may say under ``outcome = "returns"``. No inference from
#: the value's type: a callable returning ``0`` for success and one returning
#: ``0`` errors are the same bytes and the opposite meaning.
ACCEPTED_SPELLINGS = ("none", "falsy", "truthy")


class ProbeError(Exception):
    """A probe that cannot be evaluated as declared."""


def probe_scope(name: str) -> str:
    """The baseline scope for one probe's findings.

    **Per probe**, for :func:`kinemata.shape.shape_scope`'s reason: a probe that
    could not run must not let ``--prune`` delete another's records and call
    them fixed.
    """
    return f"{PROBE_SCOPE}:{name}"


def is_probe_scope(name: str) -> bool:
    return name == PROBE_SCOPE or name.startswith(f"{PROBE_SCOPE}:")


@dataclass(frozen=True)
class Case:
    """One probe row: what to call the target with, and what is claimed about it.

    **Named fields rather than a tuple**, and the reason is two days old in this
    tree: :class:`kinemata.targets.Target` was moved off a three-tuple because
    the one caller that wanted a single member indexed ``[2]`` to get it, and
    ``[2]`` does not say what it took. A project writing these by hand gets the
    same benefit.

    ``label`` is optional and exists so a finding names the row in the project's
    own vocabulary. Without one the arguments stand in, which is right for
    ``("box", "bind")`` and unreadable for a constructed object -- so a corpus
    whose rows are objects should label them.
    """

    expect: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    label: str = ""

    def __post_init__(self) -> None:
        if self.expect not in POLARITIES:
            raise ProbeError(
                f"case expects {self.expect!r}, which is not a polarity "
                f"(write one of: {', '.join(POLARITIES)})"
            )

    @property
    def name(self) -> str:
        if self.label:
            return self.label
        shown = [repr(item) for item in self.args]
        shown += [f"{key}={value!r}" for key, value in sorted(self.kwargs.items())]
        return ", ".join(shown) or "()"


@dataclass(frozen=True)
class Outcome:
    """How to read what the target did. **kinemata's reading, never a project's.**

    Each mode carries a **required** discriminator rather than a default, which
    is :func:`kinemata.claims.run_oracle`'s ``answers_on_failure`` precedent: a
    mechanism that grows a convention decides rather than inherits, and an
    adopter who has not thought about it gets a refusal instead of a silent
    policy.
    """

    mode: str
    #: Under ``raises``: the exception type that *means* refusal, resolved at
    #: run time. **Never "any exception"** -- an ``AttributeError`` from a
    #: renamed function would then read as the code correctly refusing, which is
    #: the permissive-oracle hazard in one line.
    refusal: str = ""
    #: Under ``returns``: which returned values mean acceptance.
    accepted: str = ""


@dataclass(frozen=True)
class Probe:
    """One declared ``[[probe]]``."""

    name: str
    target: str
    cases: str
    outcome: Outcome


@dataclass(frozen=True)
class Mismatch:
    """One case whose observed polarity is not the one it claimed."""

    probe: str
    case: str
    expected: str
    observed: str

    @property
    def scope(self) -> str:
        return probe_scope(self.probe)

    def __str__(self) -> str:
        return (
            f"{self.case}: declared {self.expected}, the code {self.observed}s "
            f"-- the declaration is the expected outcome and the code is on trial"
        )

    def finding(self) -> Bypass:
        """The record the ratchet fingerprints.

        ``antipattern`` is empty and the line is zero for the reason
        :meth:`kinemata.shape.Violation.finding` gives: nothing matched a
        pattern and there is no site in a file. The probe's name stands in
        ``path`` because it is the only locator a case has.
        """
        return Bypass(
            entry_id=self.case,
            antipattern="",
            path=self.probe,
            line=0,
            text=f"{self.probe}: {self.case} declared {self.expected}",
        )


@dataclass
class Probed:
    """One probe, run: what it looked at, and what disagreed."""

    probe: str
    accepting: int = 0
    refusing: int = 0
    mismatches: tuple[Mismatch, ...] = ()
    #: Why this probe could not be evaluated -- an unresolvable target, a case
    #: list that is not one, a call neither outcome mode could read. Empty when
    #: it ran.
    blocked: str = ""

    @property
    def examined(self) -> int:
        return self.accepting + self.refusing

    @property
    def vacuous(self) -> bool:
        """Carried fewer than both polarities. **A failure, and the whole point.**

        Covers an empty corpus and a one-sided one in one test, because they are
        one defect: a corpus that cannot tell a discriminating callable from a
        constant one.
        """
        return not self.blocked and not (self.accepting and self.refusing)

    @property
    def failed(self) -> bool:
        return bool(self.blocked) or self.vacuous or bool(self.mismatches)

    def why_vacuous(self) -> str:
        """What is missing, in the words a reader can act on."""
        if not self.examined:
            return "the case list is empty"
        missing = ACCEPT if not self.accepting else REFUSE
        have = REFUSE if not self.accepting else ACCEPT
        return (
            f"{self.examined} case(s), all of them {have}: a corpus with no "
            f"{missing} case is satisfied by a callable that {have}s everything"
        )

    def findings(self) -> list[tuple[str, Bypass]]:
        return [(hit.scope, hit.finding()) for hit in self.mismatches]

    def scopes(self) -> tuple[str, ...]:
        """The scope this run is in a position to judge, if any.

        **Claimed only by a run that actually discriminated.** A blocked probe
        did not evaluate, and a vacuous one looked at one polarity -- so in
        either case a ``--prune`` driven by this run must leave its records
        alone. That is the 2026-09-13 baseline defect's rule generalized past
        oracles: *running a check is not the check answering.*
        """
        if self.blocked or self.vacuous:
            return ()
        return (probe_scope(self.probe),)

    def unjudged(self) -> str:
        """Why this probe could not judge, for a writer to refuse on."""
        if self.blocked:
            return f"{self.probe}: {self.blocked}"
        return f"{self.probe}: {self.why_vacuous()}"


def _rows(probe: Probe) -> list[Case]:
    """Ask the project for its cases, and refuse anything that is not one.

    A project handing back dicts or tuples is not a smaller version of handing
    back cases -- it is a corpus this module would have to guess at, and
    guessing is how a check starts quietly doing less.
    """
    supplier = resolve(probe.cases).value
    produced = supplier()
    if isinstance(produced, (str, bytes)) or not isinstance(produced, Iterable):
        raise ProbeError(
            f"cases {probe.cases!r} returned {type(produced).__name__}, "
            f"not an iterable of Case"
        )
    rows = list(produced)
    for index, row in enumerate(rows):
        if not isinstance(row, Case):
            raise ProbeError(
                f"cases {probe.cases!r} row {index} is "
                f"{type(row).__name__}, not a Case"
            )
    return rows


def _refusal_type(probe: Probe) -> type[BaseException]:
    """Resolve the exception type that means refusal.

    Resolved at run time rather than at config load, the way every other target
    here is: importing the project's own modules belongs inside a run, and the
    config checks only the spelling.
    """
    found = resolve(probe.outcome.refusal).value
    if not (isinstance(found, type) and issubclass(found, BaseException)):
        raise ProbeError(
            f"refusal {probe.outcome.refusal!r} names "
            f"{getattr(found, '__name__', type(found).__name__)!r}, which is "
            f"not an exception type"
        )
    # `except` matches subclasses, so a declared base admits every one of them.
    # That is the project's judgement to make and is not policed here -- except
    # at the root, where it stops being a judgement: `Exception` reads *any*
    # failure as a refusal, which is precisely the permissive reading this
    # module's two modes exist to prevent. Measured on a real adopter's tree,
    # where a base class two levels up still passed every case.
    if found in (Exception, BaseException):
        raise ProbeError(
            f"refusal {probe.outcome.refusal!r} is {found.__name__}, which "
            f"every failure is. A probe declaring it reads a renamed function "
            f"or a broken import as the code correctly refusing. Name the "
            f"exception the project raises to mean refusal."
        )
    return found


def _observe(call: Any, case: Case, outcome: Outcome, refusal: Any) -> str:
    """Call the target once and read the answer. Returns a polarity.

    **An exception the mode cannot read is an error, never a refusal.** Reading
    every exception as a refusal is what would let a renamed function report a
    corpus in perfect order, which is the failure this package reports in other
    people's checks.
    """
    if outcome.mode == "raises":
        try:
            call(*case.args, **case.kwargs)
        except refusal:
            return REFUSE
        # Anything else is the probe being unable to judge, not the code
        # refusing. Reported as blocked, with the case named.
        except Exception as exc:
            raise ProbeError(
                f"case {case.name} raised {type(exc).__name__}: {exc} -- "
                f"declared refusal is {outcome.refusal}"
            ) from exc
        return ACCEPT

    try:
        value = call(*case.args, **case.kwargs)
    except Exception as exc:
        raise ProbeError(
            f"case {case.name} raised {type(exc).__name__}: {exc} -- "
            f'outcome is "returns", so a raise is not an answer'
        ) from exc
    if outcome.accepted == "none":
        return ACCEPT if value is None else REFUSE
    if outcome.accepted == "falsy":
        return ACCEPT if not value else REFUSE
    return ACCEPT if value else REFUSE


def examine(probe: Probe) -> Probed:
    """Run one declared probe: ask the project for rows, call the target, judge.

    A failure to resolve, a case list that is not one, or a call neither mode
    could read **blocks the whole probe** rather than dropping the row. Per-row
    recovery would leave a run reporting findings from a corpus it had silently
    thinned, and a thinned corpus is exactly what the polarity count exists to
    catch.
    """
    try:
        target = resolve(probe.target).value
        rows = _rows(probe)
        refusal: Any = (
            _refusal_type(probe) if probe.outcome.mode == "raises" else None
        )
    except (TargetError, ProbeError) as exc:
        return Probed(probe=probe.name, blocked=str(exc))

    accepting = sum(1 for row in rows if row.expect == ACCEPT)
    refusing = len(rows) - accepting
    result = Probed(probe=probe.name, accepting=accepting, refusing=refusing)
    if result.vacuous:
        # Nothing is called. A corpus that cannot discriminate has not earned
        # the right to run the project's code, and a finding from it would be
        # read as evidence.
        return result

    found: list[Mismatch] = []
    for row in rows:
        try:
            observed = _observe(target, row, probe.outcome, refusal)
        except ProbeError as exc:
            return Probed(probe=probe.name, blocked=str(exc))
        if observed != row.expect:
            found.append(
                Mismatch(
                    probe=probe.name,
                    case=row.name,
                    expected=row.expect,
                    observed=observed,
                )
            )
    return Probed(
        probe=probe.name,
        accepting=accepting,
        refusing=refusing,
        mismatches=tuple(found),
    )


def survey(probes: Sequence[Probe]) -> list[Probed]:
    """Every declared ``[[probe]]``, run in declaration order."""
    return [examine(item) for item in probes]
