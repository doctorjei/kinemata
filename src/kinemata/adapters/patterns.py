"""Hand-authored entries, for canonical things that are *code*.

The gap this closes was found by running the tool on a second corpus and getting
nothing. kanibako-cli's canonical things are values -- ``WORKSET_META_FILE =
"workset.yaml"`` -- so deriving antipatterns from constants works there. But
kento-core's are *code*::

    run_or_die     the helper 11 sites bypassed by inlining ``check=True``
    read_mode()    the accessor one site bypassed by hardcoding ``mode = 'vm'``

Neither is a string constant, so nothing auto-derives them, and the tool
reported a clean tree on a codebase whose own history documents the duplication.

There is no zero-config path here and that is fine: a helper you want every
caller routed through is worth one config entry. The cost is bounded by how many
such helpers a project actually has -- a handful, not hundreds.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from ..contract import BaseRegistry, Entry


class CodePatterns(BaseRegistry):
    """Entries declared explicitly, matched against executable code.

    ``match_mode`` is ``"code"``: comments and docstrings are stripped, but
    matching is not confined to string literals, because ``check=True`` is a
    code shape rather than a value.
    """

    name = "patterns"
    match_mode = "code"

    def __init__(
        self,
        declarations: Sequence[Mapping[str, Any]],
        *,
        name: str = "patterns",
        closed: bool = False,
    ) -> None:
        self.name = name
        self.closed = closed
        self._entries: list[Entry] = []

        for index, spec in enumerate(declarations):
            identifier = spec.get("id")
            if not identifier:
                raise ValueError(f"entry {index}: 'id' is required")
            antipatterns = spec.get("antipatterns", ())
            if not antipatterns:
                raise ValueError(
                    f"entry {identifier!r}: 'antipatterns' is required -- an entry "
                    "with none is invisible to every check"
                )
            self._entries.append(
                Entry(
                    id=str(identifier),
                    antipatterns=tuple(str(p) for p in antipatterns),
                    home=tuple(str(h) for h in spec.get("home", ())),
                    clauses=tuple(str(c) for c in spec.get("clauses", ())),
                    extra={
                        k: v
                        for k, v in spec.items()
                        if k not in {"id", "antipatterns", "home", "clauses"}
                    },
                )
            )

    def entries(self) -> Iterable[Entry]:
        return list(self._entries)

    def line(self, entry: Entry) -> str:
        note = entry.extra.get("note")
        return f"{entry.id}  {note}" if note else entry.id
