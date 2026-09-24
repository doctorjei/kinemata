"""What a project's ``exclude`` removes, and whether it removed what it named.

**One carrier for one predicate, and one reading of it.** A fragment names
**whole path segments**: :shown:`tests/` is a directory called ``tests`` at any
depth, :shown:`LICENSE.md` is anything called exactly that at any depth,
:shown:`docs/api/` is that pair of directories at any depth, and a **leading
slash** anchors to the project root. A trailing slash changes nothing. **A
fragment is never a substring.** Every check reads ``exclude`` -- and
``machinery`` and ``historical``, which arrive here too -- through
:func:`matches` and nothing else.

⚑ **Decided 2026-09-24 (user: "a consistent, always-runs-the-same solution").**
Until then a fragment was an unanchored substring, and :mod:`claims`,
:mod:`confirm` and :mod:`provenance` stripped its trailing slash first while the
scans did not -- so ``exclude = ["tests/"]`` removed an adopter's
:shown:`docs/plans/2026-03-07-smoke-tests-design.md` from ``claims`` and left it
in ``check``, costing them two documentation claims silently. The substring
reading was never argued for; it was the first thing written. It had been
published as a limit needing a deprecation, and replaced outright instead:
**every exclude found in a real config -- this repository's, two validation
projects' and the reporting adopter's -- is a directory or an exact file name**,
which the segment reading removes exactly as before. What it stops removing is a
path matched inside a name, which is the defect.

A fragment that relied on matching part of a name now removes nothing, and
:func:`audit` says so on every run of ``check`` and ``review`` -- the change is
never silent.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


def matches(rel: str, fragment: str) -> bool:
    """Does one fragment remove this path?

    The fragment's segments must appear as consecutive whole segments of the
    path -- at the start when it is anchored with ``/``, anywhere otherwise. A
    fragment with no segments (``""``, ``/``) removes nothing rather than
    everything.
    """
    want = [part for part in fragment.split("/") if part]
    if not want:
        return False
    parts = rel.split("/")
    if fragment.startswith("/"):
        return parts[: len(want)] == want
    return any(
        parts[start : start + len(want)] == want
        for start in range(len(parts) - len(want) + 1)
    )


def excluded(rel: str, fragments: Sequence[str]) -> bool:
    """Is this path removed by any of them?"""
    return any(matches(rel, fragment) for fragment in fragments)


@dataclass(frozen=True)
class Removed:
    """What one fragment did on one run."""

    fragment: str
    #: Every path it removed.
    paths: tuple[str, ...] = ()

    @property
    def anchored(self) -> bool:
        return self.fragment.startswith("/")

    @property
    def inert(self) -> bool:
        """It removed nothing, so it is a line asserting something untrue.

        An adopter shipped three excludes that removed nothing at all, on a
        reason inherited from a comment nobody had measured. This repository
        shipped one too: ``deliverables/`` names a directory that has never
        existed here. It is also what a fragment written to match *part* of a
        name looks like once fragments name whole segments.
        """
        return not self.paths


@dataclass(frozen=True)
class Audit:
    """Every fragment, and what it removed."""

    removed: tuple[Removed, ...] = ()

    @property
    def inert(self) -> tuple[Removed, ...]:
        return tuple(item for item in self.removed if item.inert)

    def lines(self) -> tuple[str, ...]:
        """One line per fragment that removed nothing, or nothing.

        Silent when every fragment removed something, because a report that
        speaks on a clean run trains its reader to skip it.
        """
        return tuple(
            f"exclude {item.fragment!r} removed 0 files: no path in this tree "
            "has it as whole segments. A fragment names a directory or a file, "
            "never part of a name."
            for item in self.inert
        )


def audit(
    paths: Iterable[str], fragments: Sequence[str], *, pruned: Sequence[str] = ()
) -> Audit:
    """What each fragment removed from a set of relative paths.

    Takes the paths rather than walking, so the caller that already walked the
    tree does not pay for a second one -- the reason :mod:`citations` reuses the
    scan's walk instead of writing a third.

    ``pruned`` names directories the walk never descends into. The first draft
    reported :shown:`.venv/` as removing nothing, which is false in the way that
    matters: the directory is there, and the walk prunes it first. A fragment
    naming one is a redundancy rather than a mistake, so it is not reported.
    """
    listed = list(paths)
    skip = {name.strip("/") for name in pruned}
    return Audit(
        removed=tuple(
            Removed(
                fragment=fragment,
                paths=tuple(rel for rel in listed if matches(rel, fragment)),
            )
            for fragment in fragments
            if fragment and fragment.strip("/") not in skip
        )
    )


def relative_paths(root: str | Path, walker: Iterable[Path]) -> tuple[str, ...]:
    """The walked paths as the exclusion test sees them."""
    base = Path(root)
    return tuple(str(path.relative_to(base)) for path in walker)
