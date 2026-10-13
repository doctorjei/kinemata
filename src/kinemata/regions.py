"""Where an antipattern counts, as opposed to where its entry is declared.

Two questions a project asks about a declared rule, and until now this package
answered only the first:

- **Where is the thing defined?** ``home``, and a match inside it is the
  canonical use rather than a duplicate (:mod:`kinemata.sites`).
- **Where does the rule apply?** Nothing. :func:`kinemata.bypass.scan` matched
  every line of every file the registry reads, so a rule about one section of
  one document also fired on every other section of it, and on every other
  document.

Reported by kanibako 2026-10-13, whose task board carries a section whose rows
must carry a marker and a section whose rows must not. Written unscoped, the
first rule reported every row in the second and the second reported every row in
the first -- **and on a board with two genuinely misfiled rows, the report was
indistinguishable from a correct one**. The defect was not that it was noisy;
five findings is what an unscoped run gives on a correct board too.

**A region is a heading's section**, running from the heading to the next heading
of the same or higher level. That is markdown's own containment rule rather than
one invented here, and it is the only nesting a markdown document states about
itself. ``under`` names a region by the heading's **title text**, exactly --
a section is a place, like a path, rather than a spelling, so this is the
analogue of ``home`` and not of ``antipatterns``.

**The reader is a table keyed by suffix, as :mod:`kinemata.languages` is**, so a
second kind of region is a row rather than a new branch at each of the call
sites, and a suffix with no reader is **refused at load** rather than reading as
a rule that quietly matches nothing.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence

from .prose import outside_fenced_blocks

#: A test for one heading's title, built by :func:`matchers`.
Matcher = Callable[[str], object]

#: A reader for one file kind, answering ``(line, level, title)`` per heading in
#: document order. Line numbers are the source file's, so they address a match
#: the way :func:`kinemata.bypass._inside` already does.
Reader = Callable[[str], "tuple[tuple[int, int, str], ...]"]

#: An ATX heading: up to three spaces of indent (CommonMark's limit), one to six
#: ``#``, whitespace, then the title.
#:
#: **The closing run is CommonMark's and is easy to get wrong in the other
#: direction.** ``## HIS GATE ##`` titles the section ``HIS GATE``; keeping the
#: trailing marks would name a region no document can declare. And the title is
#: non-greedy precisely so the trailing ``#*`` is what gets them.
#:
#: ``##`` alone and ``#hashtag`` are **not** headings -- both need whitespace
#: after the marks, which is what the reader for headings itself requires. A
#: pattern that treated them as headings would find a section under every
#: ``##`` in a document.
HEADING = re.compile(r"^ {0,3}(?P<marks>#{1,6})[ \t]+(?P<title>.*?)[ \t]*#*[ \t]*$")


def markdown_headings(source: str) -> tuple[tuple[int, int, str], ...]:
    """Every ATX heading outside a fenced block, as ``(line, level, title)``.

    **Fences are consulted, and it matters in both directions.** A ``# comment``
    inside a shell fence is not a heading, and treating it as one would end the
    preceding section early and invent a region no document declared. A fence
    *inside* a section is the other half of the same problem: a markdown document
    that displays a whole board is showing it, and reading the displayed copy's
    headings would give the declaration a region that exists only in the
    illustration.
    """
    outside = outside_fenced_blocks(source)
    found: list[tuple[int, int, str]] = []
    for number, line in enumerate(outside.splitlines(), start=1):
        match = HEADING.match(line)
        if match is not None:
            found.append(
                (number, len(match.group("marks")), match.group("title").strip())
            )
    return tuple(found)


#: Which reader answers for which file kind. **Markdown only, deliberately.**
#: reStructuredText headings are underline-delimited rather than ``#``-prefixed,
#: so a reader for them is a second parser rather than a second row -- and
#: guessing at one would give a project regions that do not line up with the
#: document it wrote.
READERS: dict[str, Reader] = {".md": markdown_headings}


def reader(suffix: str) -> Reader | None:
    """The reader for ``suffix``, or ``None`` when nothing here can read it."""
    return READERS.get(suffix)


def titles(headings: Sequence[tuple[int, int, str]]) -> tuple[str, ...]:
    """The headings present, for saying what a misspelt ``under`` should have said."""
    return tuple(title for _, _, title in headings)


#: Marks an ``under`` entry as a regular expression rather than a title.
PATTERN = "re:"


class BadPattern(ValueError):
    """An ``under`` entry wrote ``re:`` and then not a regex.

    Refused at load, like every other thing a config declares badly: a pattern
    that does not compile would otherwise become a section matching nothing on
    every file, which is the inert declaration this module exists to prevent.
    """


def matchers(wanted: Sequence[str]) -> tuple[Matcher, ...]:
    """Compile each declared section name into a test for a heading's title.

    **A string is a title however many regex characters it holds, and is never
    compiled as one.** Compiling every ``under`` would break a declaration
    silently rather than loudly, and the first config it would break is a real
    one: kanibako titles their section
    :shown:`🔴 HIS GATE — OPEN DECISIONS (🛑 no count here; ...)`, where a regex
    reads the parentheses as a group and no longer matches the title it was
    copied from.

    That is the same rule :func:`kinemata.contract.field_path` argues for a
    string holding dots -- **one spelling of a literal, and a deliberate second
    spelling for the other thing** -- rather than a normalization that does not
    fail.
    """
    built: list[Matcher] = []
    for name in wanted:
        if name.startswith(PATTERN):
            try:
                compiled = re.compile(name[len(PATTERN):])
            except re.error as why:
                raise BadPattern(
                    f"{name!r} names a section by pattern and does not compile: {why}"
                ) from why
            built.append(compiled.search)
        else:
            built.append(lambda title, wanted=name: title == wanted)
    return tuple(built)


def spans(
    headings: Sequence[tuple[int, int, str]],
    wanted: Sequence[Matcher],
    last: int,
) -> tuple[tuple[int, int], ...]:
    """The lines of every region whose heading a matcher accepts, inclusive.

    A region runs **to the next heading of the same or higher level**, which is
    what makes ``## HIS GATE`` own a ``### subheading`` inside it and stop at the
    next ``##``. Ending at the next heading of *any* level would leave a document
    with a subsection unable to declare the section it belongs to.

    The heading's own line is inside its region: a heading that repeats a
    forbidden spelling is as reportable as the prose under it.

    **Two sections both matched is two regions, not an ambiguity.** A pattern too
    broad names more of the document than its author meant, which is a fact about
    the declaration rather than a choice this function has to make for them --
    and unlike the ``path:N`` basename case, every heading it matched is visible
    in the document.
    """
    found: list[tuple[int, int]] = []
    for index, (line, level, title) in enumerate(headings):
        if not any(accepts(title) for accepts in wanted):
            continue
        end = last
        for other_line, other_level, _ in headings[index + 1:]:
            if other_level <= level:
                end = other_line - 1
                break
        found.append((line, end))
    return tuple(found)
