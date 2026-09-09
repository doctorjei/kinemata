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

from ..contract import _BOUNDARY, BaseRegistry, Entry


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


def identified(word: str) -> str:
    """A pattern matching ``word`` as a whole *identifier*.

    Prose boundaries are the wrong rule for identifier-shaped spellings, and the
    failure is a false positive on the live name rather than a miss. Measured
    2026-09-08 on a real clause-ID scheme: ``bounded("spec~box-vault")`` asserts
    ``\b`` after ``vault``, ``-`` supplies that boundary, and the pattern matches
    inside ``spec~box-vault-enable`` -- reporting a surviving reference to a
    retired ID at exactly the site that proves the rename happened. Shared
    hyphenated prefixes are the natural spelling for a family of related clauses,
    so a project meets this at its first such rename.

    The boundary class is ``contract._BOUNDARY``, the one this package already
    declares for the same question, rather than a second opinion about what a
    word is -- two matchers disagreeing about that was the finding.
    """
    return rf"(?<!{_BOUNDARY}){re.escape(word)}(?!{_BOUNDARY})"


#: How a forbidden spelling is bounded. A row here, not a branch: the two are
#: different jobs and neither is a better version of the other. ``prose`` catches
#: ``behaviour.`` at a sentence end, which ``identifier`` rejects because ``.``
#: abuts an identifier; ``identifier`` refuses to fire inside a longer name,
#: which ``prose`` cannot do. Declared per registry, because only the project
#: knows which kind of thing its list holds.
BOUNDARIES = {"prose": bounded, "identifier": identified}


class Substitutions(BaseRegistry):
    """Entries drawn from a ``{forbidden: preferred}`` mapping.

    :param words: what must not appear, and what to write instead.
    :param case_sensitive: off by default, because a sentence-initial
        ``Behaviour`` is the same violation as ``behaviour``. Turn it on for
        identifiers, where case carries meaning.
    :param boundary: which rule decides where a spelling ends -- ``prose`` by
        default, ``identifier`` for names that live in code and configuration.
        A list of retired identifiers wants the second: see :func:`identified`
        for the measurement that forced the distinction.
    """

    name = "substitutions"
    match_mode = "prose"

    # These spellings are declared so that nothing says them. Absence is the
    # convention being kept, so disuse is not a question this registry answers.
    mentions_are_uses = False

    def __init__(
        self,
        words: Mapping[str, str],
        *,
        name: str = "substitutions",
        closed: bool = False,
        case_sensitive: bool = False,
        boundary: str = "prose",
    ) -> None:
        if boundary not in BOUNDARIES:
            raise ValueError(
                f"unknown boundary {boundary!r} "
                f"(known: {', '.join(sorted(BOUNDARIES))})"
            )
        self.name = name
        self.closed = closed
        self._case_sensitive = case_sensitive
        self._entries: list[Entry] = []
        # **The boundary choice carries the match mode with it**, because the
        # second half of this defect is where identifiers are written. ``prose``
        # blanks inline code spans -- which is right for a word list, since a
        # document correcting ``recognisable`` must spell it -- and wrong for a
        # name list, because a retired identifier is nearly always written in
        # backticks. Measured 2026-09-08: a retired filename in a code span was
        # invisible to the scan, so the registry reported clean over documents
        # that carried it.
        #
        # The cost, stated rather than discovered later: a document narrating
        # the rename ("`old` is now `new`") now reports the old name. That is
        # what ``exclude``, ``historical`` and the baseline are for -- a
        # legitimate mention is declared, not guessed at.
        self.match_mode = "prose" if boundary == "prose" else "raw"

        for forbidden, preferred in words.items():
            if not forbidden:
                raise ValueError("a forbidden spelling may not be empty")
            pattern = BOUNDARIES[boundary](str(forbidden))
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
