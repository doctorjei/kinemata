"""Spellings that must not appear, and what to use instead.

A retired name, a deprecated helper, and a style convention are one shape: a
declared set of forbidden spellings, each with a preferred replacement. Written
by hand they become a table in some checker's source, which is the failure this
package is named for -- a registry that lives nowhere and is maintained by
whoever remembers.

The evidence is cheap and recent. A hand-maintained British-spelling table in a
prototype checker was missing ``recognisable`` and ``neighbour``; both sat in
live documents on the same day while the checker reported clean. A word list is
data. Kept as data, the same scan that catches a re-derived constant catches a
word the project has retired, and the list is visible in the config where
someone can see what it does and does not cover.

**Matched as prose.** ``code-patterns`` strips comments and docstrings because a
code shape in prose is documentation. A *spelling* is the opposite case: prose is
exactly where it matters, and a retired name in a docstring is still a retired
name. What ``prose`` mode strips instead is inline code spans, because a document
recording that ``recognisable`` was corrected has to spell the word to say so.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping

from ..contract import BaseRegistry, Entry


def bounded(word: str) -> str:
    """A pattern matching ``word`` as a whole token.

    ``\\b`` is asserted only where the neighboring character is one a word
    boundary can exist against. Wrapping ``enumerate()`` in ``\\b`` on both
    sides never matches, because there is no boundary after ``)`` -- and a
    pattern that cannot match is a declaration that silently checks nothing.
    """
    escaped = re.escape(word)
    left = r"\b" if word[:1].isalnum() or word[:1] == "_" else ""
    right = r"\b" if word[-1:].isalnum() or word[-1:] == "_" else ""
    return f"{left}{escaped}{right}"


class Substitutions(BaseRegistry):
    """Entries drawn from a ``{forbidden: preferred}`` mapping.

    :param words: what must not appear, and what to write instead.
    :param case_sensitive: off by default, because a sentence-initial
        ``Behaviour`` is the same violation as ``behaviour``. Turn it on for
        identifiers, where case carries meaning.
    """

    name = "substitutions"
    match_mode = "prose"

    def __init__(
        self,
        words: Mapping[str, str],
        *,
        name: str = "substitutions",
        closed: bool = False,
        case_sensitive: bool = False,
    ) -> None:
        self.name = name
        self.closed = closed
        self._case_sensitive = case_sensitive
        self._entries: list[Entry] = []

        for forbidden, preferred in words.items():
            if not forbidden:
                raise ValueError("a forbidden spelling may not be empty")
            pattern = bounded(str(forbidden))
            if not case_sensitive:
                pattern = f"(?i){pattern}"
            self._entries.append(
                Entry(
                    id=str(preferred),
                    antipatterns=(pattern,),
                    extra={"instead_of": str(forbidden)},
                )
            )

    def entries(self) -> Iterable[Entry]:
        return list(self._entries)

    def line(self, entry: Entry) -> str:
        return f"{entry.id}  not {entry.extra['instead_of']}"
