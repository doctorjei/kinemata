"""The registry contract.

A *registry* is one declared place holding information used broadly across a
project's code, so that the information has a single source of truth. What that
information *is* — settings keys, error codes, event types, capabilities — is the
project's choice. This module defines only what a data model must *do* to serve
the role.

The contract is deliberately small: one required method, three with defaults
derived from it, and one more required only if the registry wants to be closed.

See ``canon/workbook/designs/registry-contract.md``.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from functools import cached_property
from typing import Any, Protocol, runtime_checkable

#: Bytes a projection may occupy before it stops being loadable. A byte budget,
#: not a token count -- tokenizers differ, bytes do not.
DEFAULT_BUDGET = 16 * 1024

#: Bytes a single projected entry may occupy.
DEFAULT_LINE_BUDGET = 160

# Characters that may not abut an identifier for a match to count, when the
# identifier *contains* its separators -- a dotted keyspace key, a hyphenated
# clause ID. Keeps ``box.vault`` from matching inside ``box.vault_mode`` or
# ``box.vault.opts``.
_BOUNDARY = r"[A-Za-z0-9_.\-]"

# The same question for an identifier that is *reached through* a dot rather
# than containing one: a Python constant read as ``bootstrap.CHANNELS_PATH``.
# Here the dot is the access operator, so it has to be allowed to abut.
_NAME_BOUNDARY = r"[A-Za-z0-9_]"


@dataclass(frozen=True)
class Entry:
    """One declared thing.

    Only ``id``, ``clauses`` and ``antipatterns`` are part of the contract.
    Everything else a project cares about rides along in ``extra`` and is never
    interpreted here -- kanibako's entries carry ``scope``/``type``/``default``;
    a capability registry's would carry something else entirely.
    """

    id: str
    clauses: tuple[str, ...] = ()
    extra: Mapping[str, Any] = field(default_factory=dict)

    #: Spellings that mean somebody re-derived this instead of routing through
    #: it. ``WORKSET_META_FILE`` declares the literal ``"workset.yaml"``;
    #: ``run_or_die`` declares ``check=True``. These are *syntactic* claims an
    #: entry makes about itself -- not a semantic equivalence test, which no
    #: mechanism here attempts.
    antipatterns: tuple[str, ...] = ()

    #: Where the entry itself is defined, as repo-relative path fragments. A
    #: match inside its own definition is the canonical use, not a duplicate.
    home: tuple[str, ...] = ()


@runtime_checkable
class Registry(Protocol):
    """Structural type for anything that can serve the registry role."""

    name: str
    closed: bool

    def entries(self) -> Iterable[Entry]: ...
    def declared(self, identifier: str) -> bool: ...
    def resolve(self, identifier: str) -> tuple[str, ...]: ...
    def detect(self, text: str) -> list[str]: ...


class BaseRegistry(ABC):
    """Implements the whole contract from :meth:`entries`.

    Subclasses override a default only when it is wrong for their data model.
    """

    name: str = "registry"

    #: Is an undeclared identifier an error? A legacy codebase cannot close on
    #: day one, so an open registry routes undeclared identifiers to a review
    #: list instead of a failure. Closing is a ratchet, not a switch.
    closed: bool = False

    budget: int = DEFAULT_BUDGET
    line_budget: int = DEFAULT_LINE_BUDGET

    #: Which characters may not abut an identifier for :meth:`detect` to count
    #: a match. **A property of the data model, not of the matcher** -- the two
    #: answers below are each right for some registry and wrong for others, and
    #: for the life of the project one module-level constant decided it for all
    #: of them.
    #:
    #: Reported by an adopting project on 2026-09-09 and proved against the
    #: constants adapter rather than inferred::
    #:
    #:     '_CHANNELROOT_LEAF = bootstrap.CHANNELS_PATH'  -> detect(): []
    #:     '_CHANNELROOT_LEAF = CHANNELS_PATH'            -> detect(): ['CHANNELS_PATH']
    #:
    #: Four of that project's constants were reported as unmentioned; all four
    #: are read through their module. Every check built on :meth:`detect`
    #: inherited the blindness, not only :func:`~kinemata.bypass.unused`.
    #:
    #: The default stays ``_BOUNDARY``, because a registry that has not thought
    #: about the question is likelier to hold dotted identifiers, where the dot
    #: belongs to the name.
    boundary: str = _BOUNDARY

    #: How this registry's antipatterns should be matched. The registry knows
    #: what its patterns describe, so it chooses -- a caller passing the wrong
    #: mode is how a value registry ends up matching identifiers.
    #:
    #: ``"strings"``  only inside string literals. For antipatterns that are a
    #:                *value* (a constant's contents, a declared default).
    #: ``"code"``     executable code, comments and docstrings stripped. For
    #:                antipatterns that are a *code shape* (``check=True``).
    #: ``"raw"``      everything, prose included. Rarely right.
    match_mode: str = "strings"

    #: File suffixes this registry applies to, overriding the project's. ``None``
    #: means the project's own list.
    #:
    #: A retired name is a registry like any other -- one declared set of
    #: spellings that must not appear -- but it lives in *prose*, while the code
    #: registries live in ``.py``. Without a per-registry override, widening the
    #: project list to reach documentation points every other registry at it
    #: too, and a value registry matching prose is the over-reporting failure.
    suffixes: tuple[str, ...] | None = None

    #: Files that *declare* these entries rather than use them -- a key table, an
    #: inventory, the manifest itself. Path fragments, matched as substrings.
    #:
    #: Distinct from the project's ``exclude``, which names build and test trees.
    #: This names the declaring machinery, and it exists because mentions there
    #: are not uses: kanibako-cli ``d8037cf5`` records three keys with no reader
    #: at all, and every one of them appears in the project's own key table.
    #: Only :func:`~kinemata.bypass.unused` reads it -- the machinery is where a
    #: declaration is *supposed* to be, so no other check treats it specially.
    machinery: tuple[str, ...] = ()

    #: Does an entry nobody mentions mean anything is wrong? True for entries
    #: meant to be *routed through* -- a constant, a key, a capability.
    #:
    #: False for a registry whose entries are declared to be **absent**: a list
    #: of retired names or forbidden spellings is honored precisely when nothing
    #: mentions it. Asking such a registry what is unused returns the whole list
    #: and reads as a page of findings, which is the check reporting compliance
    #: as a problem. Found by running :func:`~kinemata.bypass.unused` over this
    #: project's own spelling registry.
    mentions_are_uses: bool = True

    # -- the one required method ------------------------------------------

    @abstractmethod
    def entries(self) -> Iterable[Entry]:
        """Every declared entry. The only thing a registry must implement."""

    # -- derived, overridable ---------------------------------------------

    @cached_property
    def _index(self) -> dict[str, Entry]:
        return {e.id: e for e in self.entries()}

    def declared(self, identifier: str) -> bool:
        """Closed-world membership. Override when enumeration is too large."""
        return identifier in self._index

    def resolve(self, identifier: str) -> tuple[str, ...]:
        """Governing clauses. Override when linkage lives outside the entry."""
        entry = self._index.get(identifier)
        return entry.clauses if entry else ()

    def detect(self, text: str) -> list[str]:
        """Declared identifiers referenced in a span of source.

        Default is a literal match bounded by :attr:`boundary`. Override when
        identifiers are constructed dynamically, aliased, or ambiguous as
        substrings.
        """
        if not self._detector:
            return []
        seen: dict[str, None] = {}
        for match in self._detector.finditer(text):
            seen.setdefault(match.group(0), None)
        return list(seen)

    def line(self, entry: Entry) -> str:
        """One projected line for ``entry``.

        The default is the bare identifier, because that is all the contract
        knows about. A registry may override to add its own summary -- the
        per-line budget is what keeps that from growing into commentary.
        """
        return entry.id

    @cached_property
    def _detector(self) -> re.Pattern[str] | None:
        ids = sorted(self._index, key=len, reverse=True)
        if not ids:
            return None
        alternation = "|".join(re.escape(i) for i in ids)
        edge = self.boundary
        return re.compile(rf"(?<!{edge})(?:{alternation})(?!{edge})")

    # -- required only to be closed ---------------------------------------

    def candidates(self, text: str) -> list[str]:
        """Things *shaped* like this registry's identifiers, declared or not.

        Distinct from :meth:`detect`, which only ever finds declared entries and
        so can never notice an undeclared one. Closure needs this: to say "that
        is not a key" you must first recognize it as trying to be one.

        A registry that cannot recognize its own identifier syntax **cannot be
        closed**; it can still report on what is declared. Raises rather than
        guessing, because a silent empty list would look like a clean check.
        """
        raise NotImplementedError(
            f"{type(self).__name__} does not implement candidates(); it cannot "
            "be closed. Set closed=False, or implement identifier recognition."
        )

    def __post_init_check__(self) -> None:
        if self.closed:
            self.candidates("")


def missing_members(obj: object) -> tuple[str, ...]:
    """Which parts of :class:`Registry` ``obj`` does not have.

    Read off the protocol rather than listed again, because a second copy of the
    member names is precisely the re-derivation this package reports on, and it
    would go stale the first time the contract grows a member. Used to tell a
    project *what* its class is missing: "does not satisfy the contract" sends
    somebody back to the documentation, and a list of names does not.
    """
    annotated = frozenset(getattr(Registry, "__annotations__", {}))
    methods = frozenset(
        name
        for name, value in vars(Registry).items()
        if callable(value) and not name.startswith("_")
    )
    return tuple(sorted(name for name in annotated | methods if not hasattr(obj, name)))


def closure_guard(registry: Registry) -> None:
    """Ask a registry whether it can keep the promise ``closed`` makes.

    :meth:`BaseRegistry.__post_init_check__` is the guard, and this reaches it
    for a **project-supplied** class too -- one that satisfies the protocol
    without inheriting the base has no such method, and calling it directly
    would raise ``AttributeError`` where the honest answer is "this class cannot
    be closed." Written after the ``import`` kind made that class reachable from
    a config file: a closed registry nobody asked the question of is the inert
    check the guard exists to prevent, and skipping it for exactly the registries
    a project wrote itself would be the worst place to skip it.
    """
    check = getattr(registry, "__post_init_check__", None)
    if check is not None:
        check()
    elif registry.closed:
        candidates = getattr(registry, "candidates", None)
        if candidates is None:
            # Raises, naming the project's own class. Borrowed rather than
            # re-worded so there is one wording of this refusal.
            BaseRegistry.candidates(registry, "")  # type: ignore[arg-type]
        else:
            candidates("")


def undeclared(registry: BaseRegistry, text: str) -> list[str]:
    """Identifiers used in ``text`` that the registry does not declare.

    This is the catch. It must run where the agent cannot reach it -- host-side
    or in CI -- or it is a reminder wearing a catch's clothes.
    """
    return [c for c in registry.candidates(text) if not registry.declared(c)]
