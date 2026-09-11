"""Citations that carry no time, and citations whose time has gotten old.

Section 6 of ``docs/citations.md`` settles both halves and separates them:

* **Every citation carries provenance, with no exemptions.** An earlier draft
  argued a commit hash needs no stamp because a hash is self-dating. That was
  wrong. A hash is immutable *content* identity, not a place and not a
  guarantee of existence -- rebase, amend and a dropped branch rewrite history
  in ordinary practice, so a hash can stop resolving. Without a stamp there is
  no way to tell *true when written, history rewritten since* from *wrong when
  written*, and telling those apart is the entire purpose of provenance. Asked
  which kinds would be exempt, the answer was: which ones wouldn't.
* **The clock is a different axis and is not a gate.** A path or a commit is
  settled locally on every run, so a clock over them only restates what the run
  already knows. An address has to leave the machine, which is why settling it
  is opt-in, and which is why the date on it is worth keeping. See
  :data:`CLOCKED`.

Archived material is left alone on both axes, honoring ``[claims] historical``:
a record cites what was true when it was written.

**The catch is opt-in and off by default.** Armed in this repository it would
report every citation in it, and a gate that fires on everything on day one is
one somebody switches off -- which is the failure :mod:`kinemata.baseline`
exists to prevent. So a project declares ``provenance = true`` under
``[citations]``, and its existing population goes into the same ratchet every
other finding uses. There is no second baseline and no second exemption list.

The findings are :class:`kinemata.bypass.Bypass` records for that reason and no
other. A finding needs an identity that survives an edit above it, and that is
what ``Bypass`` plus ``baseline.Accepted.key`` already is; a second finding type
would mean a second ratchet, and two ratchets eventually disagree about what a
project has accepted.

Association -- which stamp dates which citation -- is the part that was left
unbuilt until now, and :func:`survey` states its rule rather than guessing it.
See :data:`SEPARATORS`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from . import stamps
from .bypass import Bypass, _walk, git_ignored
from .claims import (
    _BACKTICKED,
    _LINK,
    _SHA,
    _URL,
    CLAIM_KINDS,
    FILE_SUFFIXES,
    ClaimKind,
    _excluded,
)
from .prose import UNFENCED_FILTERS

#: The name these findings travel under, so a baseline record says which check
#: accepted it. Not a registry -- nothing here is declared data -- but the
#: ratchet tags every finding with the thing that produced it, and inventing a
#: second tagging scheme for one check is how two spellings of one idea start.
PROVENANCE_REGISTRY = "citations"

#: How the finding names itself in a baseline record and in a report. Prefixed,
#: so a reader scanning the baseline file can tell an accepted undated citation
#: from an accepted duplication at a glance -- the two are driven down by
#: different people doing different work.
FINDING_PREFIX = "provenance:"

#: Days a citation may go unconfirmed before the clock surfaces it. A week,
#: because that is the interval the policy was settled at; declared as
#: ``[citations] stale_after`` because a project reading its own documents on a
#: different rhythm has a different answer, and a number nobody chose enforced
#: as though somebody had is what this package refuses everywhere else.
DEFAULT_STALE_AFTER = 7

#: What may stand between a citation and the stamp that dates it: nothing, or
#: one space.
#:
#: **This is the whole association rule, and it is deliberately this narrow.**
#: Section 5.6 says a citation accompanies its target, and section 2 shows the
#: stamp following the citation it annotates. Anything looser starts guessing
#: which of a sentence's several backticked words a stamp was about, and a
#: false accusation of an undated citation is worse than a missed one: it
#: teaches the reader that the check is noise, which switches off the check for
#: the findings that were real.
#:
#: It is the mirror of :func:`kinemata.confirm._accompanied`, which reads the
#: same adjacency backwards -- from a stamp to the target beside it -- and
#: allows the same single space. Two rules for one relation would eventually
#: disagree about one line, so ``tests/test_provenance.py`` asserts the two
#: directions agree on the same text.
SEPARATORS = ("", " ")

#: Citation kinds the clock applies to: the ones whose oracle is outside this
#: machine. Derived from the claim table rather than spelled out, so a fifth
#: kind that needs the network is clocked without an edit here -- and so that
#: nothing can name a kind the claim table does not have.
CLOCKED: frozenset[str] = frozenset(
    kind.name for kind in CLAIM_KINDS if kind.needs_network
)


class ProvenanceError(Exception):
    """A citation policy that cannot mean what it says.

    Raised rather than skipped. A check that quietly stops checking is worse
    than no check, and a provenance run that silently covered three of four
    citation kinds would read exactly like a clean tree.
    """


@dataclass(frozen=True)
class Locator:
    """Where on a line a claim of one kind is written.

    ``claims`` decides *what* is a citation -- which backticked tokens are
    paths, which hex runs are commits, which of them a sentence negates -- and
    its extractors answer with text and no position. This table supplies the
    position and nothing else: it reuses the same compiled patterns the
    extractors do, so there is no second opinion about where a token starts.

    **A row is a pattern, never a group number.** The first draft named the
    capture group holding the token, and on 2026-09-10 -- the same afternoon --
    ``_BACKTICKED`` gained a delimiter group in front of it and every path
    citation in a scratch tree became unplaceable. The index was a fact about
    somebody else's regex, restated here, which is the shape of duplication
    this package exists to report. :func:`_placed` asks the match instead.

    A citation ends at the end of the **whole match**, not of the token: a path
    claim's ends after its closing backtick and a link's after its closing
    parenthesis, and that is the character a stamp follows on the page.
    """

    kind: str
    pattern: re.Pattern[str]


#: One row per claim kind. Checked against :data:`kinemata.claims.CLAIM_KINDS`
#: below rather than trusted to stay in step, the way ``confirm.SETTLERS`` is
#: checked against the interpreted type codes: a kind with no locator is a kind
#: this check silently skips, and the policy has no exemption list.
LOCATORS: tuple[Locator, ...] = (
    Locator("path", _BACKTICKED),
    Locator("link", _LINK),
    Locator("commit", _SHA),
    Locator("url", _URL),
)

_BY_KIND: dict[str, Locator] = {locator.kind: locator for locator in LOCATORS}

if set(_BY_KIND) != {kind.name for kind in CLAIM_KINDS}:
    raise ImportError(
        "the citation kinds and the locators that place them on a line have "
        f"drifted apart: {sorted(set(_BY_KIND) ^ {k.name for k in CLAIM_KINDS})}. "
        "Every citation kind requires a stamp and there is no exemption list, "
        "so a kind this check cannot place is one it would pass over while "
        "reporting a clean tree."
    )


@dataclass(frozen=True)
class Sighting:
    """One target cited on one line, and the stamp that dates it, if any.

    **The unit is a target cited on a line, not every occurrence of it.** A
    line spelling one address twice cites it once; the extractors disagree
    about that (``_url_claims`` collapses repeats, ``_path_claims`` does not),
    and counting occurrences would make the finding count depend on which
    extractor happened to produce it. Occurrences that disagree with each other
    are not reported at all -- see :attr:`Survey.ambiguous`.
    """

    kind: str
    #: The cited target, spelled as the document spells it.
    text: str
    path: str
    line: int
    #: The whole line, which is what a baseline record fingerprints.
    source: str
    #: The stamp standing immediately after the citation, or ``None``.
    stamp: stamps.Stamp | None = None

    @property
    def dated(self) -> bool:
        return self.stamp is not None

    @property
    def entry_id(self) -> str:
        return f"{FINDING_PREFIX}{self.kind}"

    def finding(self) -> Bypass:
        """This sighting as the ratchet already knows how to record one."""
        return Bypass(
            entry_id=self.entry_id,
            antipattern=self.text,
            path=self.path,
            line=self.line,
            text=self.source,
        )

    def age(self, now: datetime) -> timedelta:
        if self.stamp is None:
            raise ProvenanceError(
                f"{self.path}:{self.line}: {self.text!r} carries no stamp, so "
                "nothing here has an age. An undated citation is the catch's "
                "finding, not the clock's."
            )
        return now - self.stamp.moment


@dataclass(frozen=True)
class Survey:
    """Every citation the run could place, and everything it could not.

    The three tallies that are not findings are carried rather than dropped
    because a run that quietly declined to judge part of a tree reads on stdout
    exactly like a run that judged all of it and found nothing.
    """

    sightings: tuple[Sighting, ...] = ()
    #: Targets cited more than once on one line, where the occurrences do not
    #: agree about being stamped. Nothing is reported for these: the extractor
    #: yields text without position, so which occurrence was the claim cannot
    #: be recovered, and guessing would put a false accusation in the report.
    ambiguous: tuple[Sighting, ...] = ()
    #: Claims no locator could find on the line that produced them. Should be
    #: empty; named rather than counted-and-forgotten, because a non-empty one
    #: means the extractors and the locators have come apart in a way the
    #: import-time check above cannot see.
    unlocatable: tuple[Sighting, ...] = ()
    #: Documents left unread as superseded records (section 6).
    archived: tuple[str, ...] = ()
    #: Documents read.
    scanned: int = 0

    @property
    def undated(self) -> tuple[Sighting, ...]:
        return tuple(seen for seen in self.sightings if not seen.dated)

    def findings(self) -> list[tuple[str, Bypass]]:
        """Undated citations, tagged the way the ratchet expects them."""
        return [
            (PROVENANCE_REGISTRY, seen.finding()) for seen in self.undated
        ]

    def clocked(self) -> tuple[Sighting, ...]:
        """Dated citations the clock applies to. See :data:`CLOCKED`."""
        return tuple(
            seen for seen in self.sightings
            if seen.dated and seen.kind in CLOCKED
        )

    def unclocked(self) -> tuple[Sighting, ...]:
        """Citations the clock is meant to cover and cannot, being undated.

        Reported by ``kinemata stale`` for the same reason the baseline prints
        its own size: a review list that silently omits the citations with no
        date at all is one whose emptiness means nothing.
        """
        return tuple(
            seen for seen in self.sightings
            if not seen.dated and seen.kind in CLOCKED
        )

    def stale(
        self, *, after: timedelta, now: datetime | None = None
    ) -> tuple[Sighting, ...]:
        """Clocked citations not confirmed within ``after``, oldest first."""
        moment = now or datetime.now(UTC)
        past = [seen for seen in self.clocked() if seen.age(moment) > after]
        past.sort(key=lambda seen: (seen.stamp.moment, seen.path, seen.line))  # type: ignore[union-attr]
        return tuple(past)


def _placed(
    line: str, kind: ClaimKind, tokens: set[str]
) -> dict[str, list[tuple[int, int]]]:
    """Where each cited token sits on the line: token -> (start, end) spans.

    **A match carries a token when one of its capture groups spells that token
    exactly.** The match is asked which of its groups holds the token rather
    than told, so a pattern that gains or reorders a group stays placeable --
    which is not hypothetical: ``_BACKTICKED`` gained a delimiter group on
    2026-09-10 and a hardcoded index stopped placing anything.

    **A pattern with no capture groups falls back to longest prefix.** That is
    the bare address: ``_url_claims`` strips trailing sentence punctuation, so
    the text on the page is longer than the token it yielded, and there is no
    group to ask. Longest-prefix covers it without this module keeping a second
    copy of which characters get stripped, and it stays right when one address
    is a prefix of another on the same line.

    The fallback is deliberately **not** used where groups exist. Applied to
    backticked tokens it would attribute a span of a backup file's name to a
    claim of the document it was copied from -- the same stem with a suffix
    after it -- and a span in the wrong place is how a citation gets accused of
    being undated when it is not.
    """
    locator = _BY_KIND[kind.name]
    spans: dict[str, list[tuple[int, int]]] = {}
    for match in locator.pattern.finditer(line):
        named = [group for group in match.groups() if group in tokens]
        if named:
            spans.setdefault(max(named, key=len), []).append(match.span())
            continue
        if match.re.groups:
            continue
        candidates = [token for token in tokens if match.group().startswith(token)]
        if candidates:
            spans.setdefault(max(candidates, key=len), []).append(match.span())
    return spans


def _dating(line: str, end: int, marks: Sequence[stamps.Stamp]) -> stamps.Stamp | None:
    """The stamp that dates a citation ending at ``end``, or ``None``.

    :data:`SEPARATORS` is the whole rule.
    """
    for mark in marks:
        start = mark.span[0]
        if start >= end and line[end:start] in SEPARATORS:
            return mark
    return None


def survey(
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".md",),
    exclude: Iterable[str] = (),
    historical: Iterable[str] = (),
    file_suffixes: Iterable[str] = (),
    kinds: Sequence[ClaimKind] = CLAIM_KINDS,
) -> Survey:
    """Every citation under ``root``, and whether a stamp stands beside it.

    Reads. Writes nothing, and is reachable from the gate for that reason:
    section 7 draws the boundary at the gate only ever reporting.

    **Fenced blocks are not read.** A document specifying a notation writes
    whole examples of it, and an illustration of a citation is not a citation --
    this project's own specification is where that was first measured, against
    the closed-world catch. It is the same filter
    :func:`kinemata.citations.citations` uses, so the catch and the reverse
    index describe the same tree. It is a deliberate difference from
    ``claims.verify``, which reads fences: a fenced path that does not exist is
    still a wrong thing to print, while a fenced citation is a picture of one.

    :param historical: path fragments holding superseded records, left unread
        whole. Section 6 leaves an archive alone on **both** axes, which is
        wider than ``claims``' per-kind ``current_only`` -- there, a URL in an
        archive is still a dead link a reader will follow; here, the archive's
        citations were dated when they were written and re-dating them would
        overwrite the record.
    """
    root = Path(root)
    exclusions = tuple(fragment.rstrip("/") for fragment in exclude if fragment)
    # Asked here as well as in the settings, the way ``claims`` and ``confirm``
    # ask: a caller reaching this as a library gets the same answer about whose
    # material this is as one reaching it through the command line. Pointing a
    # registry at prose is where the cost of not asking was measured -- sixteen
    # violations, thirteen of them in other authors' documents that sit in the
    # tree only as test corpora.
    exclusions += git_ignored(root)
    archives = tuple(fragment for fragment in historical if fragment)
    known = FILE_SUFFIXES | {str(suffix) for suffix in file_suffixes}

    sightings: list[Sighting] = []
    ambiguous: list[Sighting] = []
    unlocatable: list[Sighting] = []
    archived: list[str] = []
    scanned = 0

    for path in sorted(_walk(root, tuple(suffixes))):
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, exclusions):
            continue
        if _excluded(rel, archives):
            archived.append(rel)
            continue
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue
        scanned += 1
        # Blanked rather than dropped, so a reported line number still points
        # at the line the reader has to edit.
        filtered = UNFENCED_FILTERS.get(path.suffix)
        if filtered is not None:
            source = filtered(source)

        previous = ""
        for number, line in enumerate(source.splitlines(), start=1):
            marks = stamps.find(line)
            for kind in kinds:
                tokens = set(kind.extract(line, previous, known))
                if not tokens:
                    continue
                spans = _placed(line, kind, tokens)
                for token in sorted(tokens):
                    here = spans.get(token, [])
                    seen = Sighting(kind.name, token, rel, number, line)
                    if not here:
                        unlocatable.append(seen)
                        continue
                    dating = [_dating(line, end, marks) for _, end in here]
                    if len({mark is None for mark in dating}) > 1:
                        ambiguous.append(seen)
                        continue
                    sightings.append(
                        Sighting(kind.name, token, rel, number, line, dating[0])
                    )
            previous = line

    sightings.sort(key=lambda seen: (seen.path, seen.line, seen.kind, seen.text))
    return Survey(
        sightings=tuple(sightings),
        ambiguous=tuple(ambiguous),
        unlocatable=tuple(unlocatable),
        archived=tuple(archived),
        scanned=scanned,
    )
