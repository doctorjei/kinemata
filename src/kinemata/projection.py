"""Projections: the reminder half of the design.

A projection is the compact, always-loadable view of a registry. It exists so an
agent can see what already exists before writing something that already exists.

Two properties make it work, and both are mechanical:

* It is **generated**, never hand-maintained, so it cannot drift from the
  registry the way a second hand-written copy would.
* It is **budgeted**, so it stays small enough to actually be loaded. The budget
  check is a catch: CI fails when the projection outgrows its ceiling, which is
  the moment it stops being a reminder and starts being more context to drown in.

See ``docs/design.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contract import Entry, Registry, member


@dataclass(frozen=True)
class BudgetViolation:
    """One way a projection exceeded what it was allowed to occupy."""

    kind: str  # "total" or "line"
    limit: int
    actual: int
    identifier: str | None = None

    def __str__(self) -> str:
        if self.kind == "total":
            over = self.actual - self.limit
            return (
                f"projection is {self.actual} B, over its {self.limit} B budget "
                f"by {over} B"
            )
        return (
            f"{self.identifier!r} projects to {self.actual} B, over the "
            f"{self.limit} B per-entry budget"
        )


@dataclass(frozen=True)
class Projection:
    """A rendered registry view, with its budget verdict attached."""

    name: str
    text: str
    count: int
    violations: tuple[BudgetViolation, ...]

    @property
    def ok(self) -> bool:
        return not self.violations

    @property
    def size(self) -> int:
        return len(self.text.encode("utf-8"))


def project(registry: Registry) -> Projection:
    """Render ``registry`` to its projection and check it against its budget.

    Entries are sorted by identifier: a projection that reorders itself between
    runs produces diff noise, and noisy diffs are how a real change gets missed.
    """
    entries: list[Entry] = sorted(registry.entries(), key=lambda e: e.id)

    lines: list[str] = []
    violations: list[BudgetViolation] = []
    render = member(registry, "line")
    line_budget = member(registry, "line_budget")
    budget = member(registry, "budget")

    for entry in entries:
        rendered = render(entry)
        size = len(rendered.encode("utf-8"))
        if size > line_budget:
            violations.append(
                BudgetViolation(
                    kind="line",
                    limit=line_budget,
                    actual=size,
                    identifier=entry.id,
                )
            )
        lines.append(rendered)

    text = "\n".join(lines) + ("\n" if lines else "")
    total = len(text.encode("utf-8"))
    if total > budget:
        violations.append(
            BudgetViolation(kind="total", limit=budget, actual=total)
        )

    return Projection(
        name=registry.name,
        text=text,
        count=len(entries),
        violations=tuple(violations),
    )


def listed_elsewhere(projections: list[Projection]) -> dict[str, str]:
    """Which projections are wholly inside another, and the one to point at.

    A project comparing several fields of one declaration declares a view per
    field, each ``where`` stating which rows carry that field, and every view
    then projected the same identifiers again: measured on an adopter's 99-row
    manifest, three views printed 240 lines. **The views are right and the copy
    is not** -- ``tests/test_projection_views.py`` carries the measurement.

    Compared by **rendered line**, not identifier, so a pointer never hides a
    line that reads differently under the other header. A projection is replaced
    only when every line is elsewhere; of two identical ones the first declared
    prints; and the one pointed at is always printed, which holds because a
    superset that is itself covered has a printed superset of its own. An empty
    projection is not covered by anything: it has no lines to be elsewhere.
    """
    lines = [frozenset(p.text.splitlines()) for p in projections]

    def covers(outer: int, inner: int) -> bool:
        return outer != inner and lines[inner] <= lines[outer] and (
            lines[inner] != lines[outer] or outer < inner
        )

    printed = [
        i for i in range(len(projections))
        if not lines[i] or not any(covers(o, i) for o in range(len(projections)))
    ]
    return {
        projections[i].name: projections[next(o for o in printed if covers(o, i))].name
        for i in range(len(projections))
        if i not in printed
    }
