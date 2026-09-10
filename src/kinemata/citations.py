"""Every place a reference key is cited: the reverse direction of a bibliography.

Forward -- what a key points at -- a bibliography answers on its own. This is
the other direction, **and it is what makes accompanying a citation
affordable**. Without it, moving a source means finding every mention by hand;
with it, a move is one edit to the bibliography plus a generated worklist. That
is this project's argument applied to its own citations: silent rot becomes a
task list.

**A third tree walk is not built here.** ``bypass._walk`` already prunes the
directories nothing should read and follows the same links every other scan
follows, and ``stamps.find`` already reads a line into stamps carrying their
spans. Two mechanisms that could disagree about which files are the project's
eventually will, and a catch scoped to one module is not a catch.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import stamps
from .bypass import _walk

#: How long a citation target can be and still read comfortably beside its key,
#: in characters.
#:
#: **Measured rather than chosen.** Distinct citation targets in this project's
#: own working notes run to a median of 20 characters and a 90th percentile of
#: 50, with a maximum of 107 -- a dated mailbox filename, which beside a token
#: makes a 120-character line carrying one citation. Fifty accepts the short
#: case, which is the common one, and lets the real tail stand alone.
#:
#: **A default, and a declared one.** A project whose paths run longer sets
#: ``[citations] accompany_max``. Nothing enforces the number: section 5.6 of
#: ``docs/citations.md`` is a reminder about legibility, and a document that
#: cannot be read without resolving a key against a second file has caused the
#: context overwhelm this project exists to prevent -- which is a judgment about
#: a sentence, not a fact a checker can settle.
DEFAULT_ACCOMPANY_MAX = 50


@dataclass(frozen=True)
class Citation:
    """One place a key is cited.

    ``span`` rides along from the stamp for the reason the stamp records it:
    associating a citation with the text it annotates is not built, and
    recovering the position afterward means matching the line a second time,
    where the second match is free to disagree with the first.
    """

    key: str
    path: str
    line: int
    span: tuple[int, int]

    def __str__(self) -> str:
        """``file:line``, and nothing else.

        The reverse direction exists to be fed to an editor or to ``sed``, so it
        is deliberately undecorated -- a worklist a person can act on without
        first stripping the tool's own commentary off it.
        """
        return f"{self.path}:{self.line}"


def citations(
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".md",),
    exclude: Iterable[str] = (),
) -> list[Citation]:
    """Every keyed citation under ``root``, in the order the files are walked.

    Only *keyed* citations. A stamp carrying a type alone is a dated citation
    that names no bibliography entry, which is a legitimate thing to write and
    nothing this index can say anything about.

    Refuses on a malformed token, because :func:`kinemata.stamps.find` does: a
    key of the wrong width is one fact with two spellings, and reporting a
    worklist that quietly omitted it would be the worse of the two outcomes.
    """
    root = Path(root)
    exclusions = tuple(exclude)
    found: list[Citation] = []
    for path in _walk(root, tuple(suffixes)):
        rel = path.relative_to(root).as_posix()
        if any(fragment in rel for fragment in exclusions):
            continue
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue
        for number, line in enumerate(source.splitlines(), start=1):
            for stamp in stamps.find(line):
                if stamp.key is None:
                    continue
                found.append(
                    Citation(
                        key=stamps.canonical_key(stamp.key),
                        path=rel,
                        line=number,
                        span=stamp.span,
                    )
                )
    return found


def index(found: Iterable[Citation]) -> dict[str, list[Citation]]:
    """Citations grouped by key, keeping the order they were found in."""
    grouped: dict[str, list[Citation]] = {}
    for citation in found:
        grouped.setdefault(citation.key, []).append(citation)
    return grouped
