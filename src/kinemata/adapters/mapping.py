"""A worked adapter: registries whose entries are a mapping of id -> record.

This covers the common shape -- a YAML or JSON file with a section holding one
record per identifier -- without assuming anything about what the records
contain. It is an *example* of satisfying the contract, not a privileged path;
a registry backed by a database catalog or a type system writes its own adapter
and is no worse off.

The point being demonstrated: a project plugs in by saying where its entries
live and how to spell an identifier, and gets the rest for free.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from ..contract import BaseRegistry, Entry


class MappingRegistry(BaseRegistry):
    """Entries drawn from a ``{identifier: record}`` mapping.

    :param source: the mapping itself.
    :param name: registry name, used in reports.
    :param clause_field: record field holding governing clause IDs, if any.
    :param syntax: pattern recognizing *anything shaped like* an identifier of
        this registry, declared or not. Required to be ``closed`` -- see
        :meth:`BaseRegistry.candidates`.
    """

    def __init__(
        self,
        source: Mapping[str, Any],
        *,
        name: str = "registry",
        clause_field: str | None = None,
        syntax: str | re.Pattern[str] | None = None,
        closed: bool = False,
        budget: int | None = None,
        line_budget: int | None = None,
    ) -> None:
        self._source = source
        self.name = name
        self._clause_field = clause_field
        self._syntax = re.compile(syntax) if isinstance(syntax, str) else syntax
        self.closed = closed
        if budget is not None:
            self.budget = budget
        if line_budget is not None:
            self.line_budget = line_budget

        if self.closed and self._syntax is None:
            raise ValueError(
                f"registry {name!r} is closed but has no identifier syntax; "
                "closure requires recognizing undeclared identifiers"
            )

    def entries(self) -> Iterable[Entry]:
        for identifier, record in self._source.items():
            yield Entry(
                id=str(identifier),
                clauses=self._clauses_of(record),
                extra=record if isinstance(record, Mapping) else {"value": record},
            )

    def _clauses_of(self, record: Any) -> tuple[str, ...]:
        if not self._clause_field or not isinstance(record, Mapping):
            return ()
        raw = record.get(self._clause_field)
        if raw is None:
            return ()
        if isinstance(raw, str):
            return (raw,)
        if isinstance(raw, (list, tuple)):
            return tuple(str(c) for c in raw)
        return (str(raw),)

    def candidates(self, text: str) -> list[str]:
        if self._syntax is None:
            return super().candidates(text)  # raises, with the reason
        seen: dict[str, None] = {}
        for match in self._syntax.finditer(text):
            seen.setdefault(match.group(0), None)
        return list(seen)
