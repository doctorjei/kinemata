"""Watching a declared funnel while the project's own code runs.

Every other mechanism here reads a tree at rest or asks a declared oracle a
question about one. Neither can see an identifier the code **fabricates
internally** and hands straight to a store: it never appears as a literal, it
crosses no boundary a static check guards, and no command prints it. The
adopting project's largest single conformance item is exactly that shape, and
they built it themselves -- one patch on one write funnel, every path written
during a test session recorded and judged, the patch removed at the end.

**This module is the half of that which is not theirs.** Their file says so
outright: the classification rules "are not defined here", they live in the
project's own keyspace module. What is generic is the *interposition* -- install
on a declared callable, collect what crosses it, judge each identifier against a
declared registry, report and fail at the end of a run. What is not, and must
not be guessed at, is **how a call becomes an identifier**: theirs is a hundred
lines of path tagging with a retroactive correction pass, and a kinemata that
tried to infer it would be a second, worse copy of the project's own model.

So the project declares two things -- the funnel and an ``identify`` -- and this
supplies the rest. See ``docs/introduction.md`` [0TN49Y3-Pa0004] § Commands.

**What this is not.** It does not run the project's tests, arrange inputs, or
decide anything beyond *declared or not*. :mod:`kinemata.access` remains the
complement for a project that would rather assert against the declaration
itself; this one is for the case where nothing in the code is in a position to
assert, because the identifier is assembled somewhere no test can see.

⚑ **The dangerous mistake here is an origin discriminator**, and it is worth
naming because it is the obvious design. An earlier revision of their census
excused a write by *where it came from*, matched by code object. It hid roughly
forty real violations, and the frame walk that implemented it was the most
fragile machinery in the file. **An identifier is judged by what it is.** A
crossing's site is recorded for the report and decides nothing -- which is also
why an observation is keyed on the identifier alone and never on the site.
"""

from __future__ import annotations

import importlib
import sys
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from .contract import Registry

#: How a funnel and an extractor are spelled. One module, one attribute in it,
#: both named outright -- the same rule ``[[registry]]``'s ``target`` follows,
#: and for the same reason: the code a config causes to run should be readable
#: in the diff that adds it.
TARGET_FORM = 'target = "package.module:ClassName.method"'

#: Collector faults kept before the rest are dropped. Enough to see a pattern,
#: bounded because a fault in a hot funnel would otherwise fill memory with one
#: repeated line.
MAX_ERRORS = 20


class InterposeError(Exception):
    """A funnel that cannot be installed as declared."""


@dataclass(frozen=True)
class Crossing:
    """One call that reached the funnel and was accepted by it.

    ``result`` is what the original returned, and the receiver is ``args[0]``
    for a patched method -- both are here because an extractor usually needs to
    look at what actually landed rather than at what was asked for. Their
    container rule turns on precisely that difference: a write of a plain dict
    becomes a node on the way in, and the argument does not say so.
    """

    args: tuple[Any, ...]
    kwargs: Mapping[str, Any]
    result: Any


#: What an extractor may return. A string is the identifier; ``None`` says this
#: call carried none, and is **counted rather than dropped**, because a run in
#: which nothing was identified must not read like a run in which nothing was
#: wrong. A zero-argument callable defers the answer to drain -- their nodes are
#: written *before* being attached to a parent, so a path known at crossing time
#: is sometimes wrong, and their answer is a mutable box this generalizes. One
#: union member, forced by a real row rather than by symmetry.
Identifier = str | None | Callable[[], "str | None"]


@dataclass(frozen=True)
class Funnel:
    """One declared callable, and how to read an identifier out of a call."""

    registry: str
    target: str
    identify: str


@dataclass
class Observation:
    """One identifier seen crossing a funnel, however many times."""

    identifier: str
    #: The first ``file:line`` that produced it. **Reporting only** -- see this
    #: module's note on origin discriminators.
    site: str
    count: int = 1
    declared: bool = False
    #: Every crossing of this identifier came from a test that declared it.
    #: Folded with ``and``, never ``or``: one crossing from outside a declaring
    #: test is enough to make it a finding again.
    excused: bool = False

    @property
    def finding(self) -> bool:
        return not self.declared and not self.excused

    def __str__(self) -> str:
        times = f" (x{self.count})" if self.count > 1 else ""
        if self.declared:
            return f"{self.identifier}: declared{times}"
        if self.excused:
            return (
                f"{self.identifier}: undeclared, and the test declared it{times}"
            )
        return f"{self.identifier}: written, declared by nothing{times} -- {self.site}"


@dataclass(frozen=True)
class Watch:
    """What one session saw at one funnel."""

    registry: str
    target: str
    #: Why nothing was watched, empty when the funnel was installed. **A
    #: failure**: a declared check that could not run is the inert signal this
    #: package exists to prevent, and it is the same rule a blocked oracle
    #: already follows.
    blocked: str = ""
    #: Calls that reached the funnel, whether or not they carried an identifier.
    #: Reported even when zero, because *observed nothing* and *found nothing*
    #: are different answers and only one of them is reassuring.
    crossings: int = 0
    observations: tuple[Observation, ...] = ()
    #: Faults raised by the collector or the project's extractor. **These fail
    #: the run**, deliberately unlike the census this is drawn from: a fault
    #: means some crossings went unrecorded, so the check has holes in it and
    #: nothing else would say so.
    errors: tuple[str, ...] = ()

    @property
    def findings(self) -> tuple[Observation, ...]:
        return tuple(item for item in self.observations if item.finding)

    @property
    def failed(self) -> bool:
        return bool(self.blocked or self.findings or self.errors)


def resolve(target: str) -> tuple[Any, str, Any]:
    """The owner, attribute name and current value ``target`` names.

    Resolved here rather than when the config loads, and the distinction is not
    cosmetic: importing the project's own modules is a thing to do inside the
    project's own test session, not inside every ``kinemata check``. The config
    checks the *shape* of a target; this resolves it, and a failure is the
    session's rather than the file's.
    """
    module_name, _, attribute = target.partition(":")
    if not module_name.strip() or not attribute.strip():
        raise InterposeError(f"{target!r} is not a target. Write {TARGET_FORM}.")
    try:
        owner: Any = importlib.import_module(module_name.strip())
    # Importing runs the project's module, so anything can come back out of it.
    except Exception as exc:
        raise InterposeError(
            f"cannot import {module_name!r} for target {target!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    parts = attribute.strip().split(".")
    for step in parts[:-1]:
        if not hasattr(owner, step):
            raise InterposeError(f"{target!r}: {step!r} is not there to patch")
        owner = getattr(owner, step)
    name = parts[-1]
    if not hasattr(owner, name):
        raise InterposeError(f"{target!r}: {name!r} is not there to patch")
    original = getattr(owner, name)
    if not callable(original):
        raise InterposeError(f"{target!r} names a {type(original).__name__}, not a callable")
    return owner, name, original


_HERE = __file__


def _caller() -> str:
    """The first ``file:line`` outside this module -- the line that made the call.

    One frame, not two. Their census takes a second frame outside the *settings
    package*, because the settings stack writes most of their store and the
    nearest frame names the mechanism rather than the decision. That is a fact
    about their layout, and a generic guess at which package is "the mechanism"
    would be wrong for everyone else. A project needing the second frame reads
    it in its own extractor, where it knows.
    """
    frame: Any = sys._getframe()
    while frame is not None:
        if frame.f_code.co_filename != _HERE:
            return f"{frame.f_code.co_filename}:{frame.f_lineno}"
        frame = frame.f_back
    return "<unknown>"


class Census:
    """One funnel, patched, collecting until told to stop.

    Not a context manager, because the two ends are two different events in a
    test runner and a ``with`` would suggest they are one. :meth:`uninstall` is
    idempotent and must be reachable from a finalizer that runs whatever else
    happened -- **the class is never left patched** is the property their file
    puts first, and a poisoned class outlives the run that poisoned it.
    """

    def __init__(
        self,
        funnel: Funnel,
        registry: Registry,
        identify: Callable[[Crossing], Identifier],
        site: Callable[[], str] | None = None,
    ) -> None:
        self.funnel = funnel
        self.registry = registry
        self.identify = identify
        self._site = site or _caller
        self._owner: Any = None
        self._name = ""
        self._original: Any = None
        self.blocked = ""
        self.crossings = 0
        self._pending: dict[tuple[Any, str], list[Any]] = {}
        self._rows: dict[str, Observation] = {}
        self._armed: frozenset[str] = frozenset()
        self._used: set[str] = set()
        self._errors: list[str] = []

    # -- the two ends ---------------------------------------------------------

    def install(self) -> None:
        """Patch the funnel, or record why not. Never raises at the caller."""
        if self._original is not None:
            return
        try:
            owner, name, original = resolve(self.funnel.target)
        except InterposeError as exc:
            self.blocked = str(exc)
            return
        self._owner, self._name, self._original = owner, name, original

        def watched(*args: Any, **kwargs: Any) -> Any:
            # The original **first**, and only what it accepted is recorded: a
            # call the real funnel refused is not a write, and censusing one
            # would invent a finding out of a test asserting a refusal.
            result = original(*args, **kwargs)
            try:
                self._observe(args, kwargs, result)
            except Exception as exc:
                # The collector must never raise into the project's own code.
                # It still fails the run at the end -- see `Watch.errors`.
                self._note(exc)
            return result

        watched.__name__ = getattr(original, "__name__", name)
        watched.__doc__ = getattr(original, "__doc__", None)
        watched.__kinemata_watched__ = True  # type: ignore[attr-defined]
        setattr(owner, name, watched)

    def uninstall(self) -> None:
        """Put the original back. Safe to call more than once, and must be."""
        if self._original is not None:
            setattr(self._owner, self._name, self._original)
            self._original = None

    @property
    def installed(self) -> bool:
        return self._original is not None

    # -- collecting -----------------------------------------------------------

    def _note(self, exc: Exception) -> None:
        if len(self._errors) < MAX_ERRORS:
            self._errors.append(f"{type(exc).__name__}: {exc}")

    def _observe(self, args: tuple[Any, ...], kwargs: Mapping[str, Any],
                 result: Any) -> None:
        self.crossings += 1
        value = self.identify(Crossing(args, kwargs, result))
        if value is None:
            return
        # Keyed by the string itself where there is one, and by identity where
        # the answer is deferred -- which is what makes a reused box collapse
        # into one pending slot exactly as it does in the census this follows.
        # Bounded by one test's crossings, since `drain` empties it per test.
        key = (value if isinstance(value, str) else id(value), self._site())
        slot = self._pending.get(key)
        if slot is None:
            self._pending[key] = [value, key[1], 1, self._armed]
        else:
            slot[2] += 1

    def arm(self, identifiers: Iterable[str]) -> None:
        """What the running test says it will write undeclared, on purpose."""
        self._armed = frozenset(identifiers)

    def drain(self) -> None:
        """Fold pending crossings into observations, resolving deferred names.

        Per test rather than at the end, so the pending table -- and whatever
        the project's deferred answers are holding open -- stays bounded.
        """
        for value, site, count, armed in self._pending.values():
            try:
                identifier = value() if callable(value) else value
            except Exception as exc:
                self._note(exc)
                continue
            if identifier is None:
                continue
            identifier = str(identifier)
            excused = identifier in armed
            row = self._rows.get(identifier)
            if row is None:
                self._rows[identifier] = Observation(
                    identifier=identifier,
                    site=site,
                    count=count,
                    declared=self._declared(identifier),
                    excused=excused,
                )
                continue
            row.count += count
            # `and`, never `or`: one crossing from outside a declaring test is
            # enough to make this a finding again.
            row.excused = row.excused and excused
        self._pending.clear()

    def _declared(self, identifier: str) -> bool:
        try:
            return self.registry.declared(identifier)
        except Exception as exc:
            # A registry that cannot answer is not an identifier that is fine.
            self._note(exc)
            return False

    # -- the end of a run -----------------------------------------------------

    def watch(self) -> Watch:
        """What this funnel saw. Call after the last :meth:`drain`."""
        for row in self._rows.values():
            if row.excused and not row.declared:
                # A declaration counts as exercised only where it changed a
                # verdict. One naming a path that is declared, or that the test
                # stopped writing, changed nothing -- and saying so is the whole
                # point of the check.
                self._used.add(row.identifier)
        return Watch(
            registry=self.funnel.registry,
            target=self.funnel.target,
            blocked=self.blocked,
            crossings=self.crossings,
            observations=tuple(
                sorted(self._rows.values(), key=lambda row: (-row.count, row.identifier))
            ),
            errors=tuple(self._errors),
        )

    @property
    def exercised(self) -> frozenset[str]:
        """Declared identifiers whose declaration actually changed a verdict."""
        return frozenset(self._used)


@dataclass
class Session:
    """Every funnel a project declared, and the marker accounting across them.

    The accounting is here rather than in :class:`Census` because a project may
    watch several funnels feeding one registry -- a second write path is the
    usual reason -- and a declaration exercised at either of them is exercised.
    Asking each census on its own would report a live marker as stale.
    """

    watches: tuple[Watch, ...] = ()
    #: Identifiers declared by tests that actually ran. Registered when a test
    #: *runs* rather than when it is set up: a skipped test never got the chance
    #: to write what it declared, and reporting it unused would fail a run for a
    #: test that did not execute.
    declared_by_tests: frozenset[str] = frozenset()
    exercised: frozenset[str] = frozenset()
    errors: tuple[str, ...] = field(default_factory=tuple)

    @property
    def unused_markers(self) -> tuple[str, ...]:
        """Declarations that changed no verdict. **Each one fails the run.**

        A declaration that no longer describes what its test writes is a stale
        blessing, and the difference between this and an exemption list is that
        this one says so by itself instead of waiting to be driven down.
        """
        return tuple(sorted(self.declared_by_tests - self.exercised))

    @property
    def findings(self) -> tuple[Observation, ...]:
        return tuple(item for watch in self.watches for item in watch.findings)

    @property
    def blocked(self) -> tuple[Watch, ...]:
        return tuple(watch for watch in self.watches if watch.blocked)

    @property
    def silent(self) -> tuple[Watch, ...]:
        """Funnels nothing crossed.

        **Not a failure**, and that is a judgement rather than an oversight:
        running one test file is an ordinary thing to do and failing it would
        teach people to turn this off. It is reported instead, because a run
        that observed nothing must not read like a run that found nothing.
        """
        return tuple(
            watch for watch in self.watches if not watch.blocked and not watch.crossings
        )

    @property
    def failed(self) -> bool:
        return bool(
            self.findings or self.unused_markers or self.blocked or self.errors
            or any(watch.errors for watch in self.watches)
        )

    def lines(self) -> list[str]:
        """The report, as a runner should print it."""
        out: list[str] = []
        for watch in self.watches:
            if watch.blocked:
                out.append(f"# {watch.target}")
                out.append(f"  BLOCKED: {watch.blocked}")
                continue
            seen = len(watch.observations)
            out.append(
                f"# {watch.target}: {watch.crossings} crossing(s), "
                f"{seen} identifier(s), against {watch.registry}"
            )
            if not watch.crossings:
                out.append(
                    "  nothing crossed this funnel, so this run says nothing "
                    "about it"
                )
            for item in watch.findings:
                out.append(f"  {item}")
            for line in watch.errors:
                out.append(f"  COLLECTOR: {line}")
        for identifier in self.unused_markers:
            out.append(
                f"  STALE: {identifier} was declared by a test and never written "
                "undeclared"
            )
        return out
