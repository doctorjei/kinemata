"""A registry whose entries are *values*, not the keys that hold them.

Every other adapter here makes an identifier out of a **name**:
:class:`~kinemata.adapters.mapping.MappingRegistry` yields ``Entry(id=key)``,
``python-constants`` yields the constant's name. That is right whenever the
declaration is a table of records, and it is exactly wrong when the fact being
declared *is* the scalar -- a version string, a schema revision, a wire format
name.

The case that forced it, and it is not ours: an adopter reproduced this
project's own packaging defect independently -- a tree carrying a version that
is already on the index, so ``pip install <pkg> @ git+...`` builds the metadata,
sees the version already installed and **skips**, leaving a green run against
code that was never fetched. Expressing "the version this tree declares is not
one the index already has" needs the version on the *declared* side of a
:mod:`~kinemata.parity` ``disjoint``, and until this adapter the only way to put
it there was a project-written ``kind = "import"`` class. The relation itself
needed nothing: it was measured answering both directions against the live index
before a line of this was written.

**``extra`` is empty, deliberately.** There is no record here -- the value is the
identifier -- so carrying ``{"value": ...}`` beside it would make ``id`` and
``extra["value"]`` two spellings of one fact, which is the duplication this
package exists to report. ``MappingRegistry`` wraps a non-mapping record that
way because *there* the record is data about the identifier; here there is none.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence

from ..contract import BaseRegistry, Entry


class ValueRegistry(BaseRegistry):
    """Entries drawn from scalars a structured document declares.

    :param values: the identifiers, already read out of the document and
        rendered. Reading and rendering belong to whatever loaded the file --
        the same split :class:`MappingRegistry` makes, where the adapter takes
        the mapping and the config layer takes the path to it.
    :param name: registry name, used in reports.
    :param syntax: pattern recognizing *anything shaped like* an identifier of
        this registry, declared or not. Required to be ``closed``.
    """

    def __init__(
        self,
        values: Sequence[str],
        *,
        name: str = "values",
        syntax: str | re.Pattern[str] | None = None,
        closed: bool = False,
        budget: int | None = None,
        line_budget: int | None = None,
    ) -> None:
        self._values = tuple(values)
        self.name = name
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
        # Order is the document's and duplicates are kept: a list declaring the
        # same value twice is a fact about the declaration, and collapsing it
        # here would hide it from a check that wanted to see it.
        for value in self._values:
            yield Entry(id=value)

    def candidates(self, text: str) -> list[str]:
        if self._syntax is None:
            return super().candidates(text)  # raises, with the reason
        seen: dict[str, None] = {}
        for match in self._syntax.finditer(text):
            seen.setdefault(match.group(0), None)
        return list(seen)
