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

# Characters that may not abut an identifier for a match to count. Keeps
# ``box.vault`` from matching inside ``box.vault_mode`` or ``box.vault.opts``.
_BOUNDARY = r"[A-Za-z0-9_.\-]"


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

        Default is a boundary-aware literal match. Override when identifiers are
        constructed dynamically, aliased, or ambiguous as substrings.
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
        return re.compile(rf"(?<!{_BOUNDARY})(?:{alternation})(?!{_BOUNDARY})")

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


def undeclared(registry: BaseRegistry, text: str) -> list[str]:
    """Identifiers used in ``text`` that the registry does not declare.

    This is the catch. It must run where the agent cannot reach it -- host-side
    or in CI -- or it is a reminder wearing a catch's clothes.
    """
    return [c for c in registry.candidates(text) if not registry.declared(c)]
