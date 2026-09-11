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

from ..contract import _NAME_BOUNDARY, BaseRegistry, Entry


class CodePatterns(BaseRegistry):
    """Entries declared explicitly, matched against executable code.

    ``match_mode`` is ``"code"``: comments and docstrings are stripped, but
    matching is not confined to string literals, because ``check=True`` is a
    code shape rather than a value.
    """

    name = "patterns"
    match_mode = "code"

    #: These ids are the names of things in code -- ``run_or_die``,
    #: ``read_mode`` -- and a helper is most often reached through the module
    #: that defines it. With the dotted default ``helpers.run_or_die(cmd)``
    #: detected nothing, so the entry was reported as mentioned by nobody at
    #: the very site that routes through it.
    #:
    #: The same defect the adopter's ``bootstrap.CHANNELS_PATH`` measurement
    #: forced :class:`~kinemata.adapters.constants.PythonConstants` to fix on
    #: 2026-09-09, left here that day because no entry in this repository was
    #: written module-qualified. That is a fact about this repository and not
    #: about the adapter, and the failure it hides is a silent one -- so it is
    #: fixed here on the evidence from there rather than waiting for a second
    #: project to be bitten. Verified against this tree first: with the change,
    #: ``check``, ``review``, ``unused`` and ``undeclared`` report exactly what
    #: they did before.
    #:
    #: It buys the same false positive that adapter documents, in the same
    #: direction, and a registry whose ids really do carry dots -- a clause
    #: scheme, a dotted key declared by hand -- says so with
    #: ``boundary = "identifier"`` rather than being told which it must be.
    boundary = _NAME_BOUNDARY

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
