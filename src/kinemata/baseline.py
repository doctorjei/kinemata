"""The ratchet: adopt the gate on a codebase that is already failing it.

``check`` on an existing project is red on day one. kanibako-cli produces 111
strong findings at ``main``; a team that turns the gate on sees a wall of
failures for code nobody is touching, and the rational response is to turn it
back off. A gate that only works on a greenfield tree is a gate almost nobody
can adopt.

So the accepted state is recorded, and the gate fails on *increase* --
``design.md`` §4.3: "record the baseline, fail on any increase, drive it down on
a separate schedule that does not block feature work."

**Every gate here rides this one list**, and that is a decision rather than an
accident of layering. The argument above is about code only because code is
where it was first measured; it is exactly as true of prose, and this repository
is the demonstration -- ``[claims] suffixes`` could not include ``.py`` while
arming it meant 10 permanently unresolvable citations of evidence that lives in
other people's repositories. ``bypass``, ``provenance`` and ``claims`` therefore
all emit :class:`kinemata.bypass.Bypass` records into this file. A second
exemption list for documentation was the obvious alternative and is the failure:
two lists eventually disagree about what a project accepted, and the one nobody
is reading is the one still exempting something real.

**A baseline is an allowlist, and allowlists rot.** Three properties exist to
make the rot visible rather than quiet:

* **Fingerprints, not a count.** A recorded total of 111 is satisfied by any 111
  findings, so fixing one and adding another nets to silence. Each accepted
  finding is recorded individually, including how many times it occurs.
* **The size is printed on every run**, clean or not. An exemption list that
  grows without anyone reading the number is the inert-signal failure this
  project has already shipped twice.
* **The records are readable.** Entry, antipattern, path and the matched text,
  not opaque digests. A reviewer who cannot see what is being exempted cannot
  catch a baseline absorbing real findings.

**Honest reach.** An agent can silence a real finding by re-recording the
baseline. What makes that survivable is that it is a committed file change --
``design.md``'s Catch B, a new declaration visible in the diff and routed to
review. This is a catch with an escape hatch, and saying otherwise would be
claiming reach it does not have.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .bypass import Bypass

#: Where a project's accepted findings live when it does not say otherwise.
#: Dotted and in the project root: it belongs to the repository, not to a
#: person, and it must appear in diffs.
BASELINE_NAME = ".kinemata-baseline.json"

#: JSON, though every other file this project reads is TOML. The baseline is
#: machine-written and the standard library has no TOML writer -- hand-rolling
#: one would be a second spelling of a format we otherwise only read, which is
#: the duplication this package exists to report.
FORMAT_VERSION = 1

#: Characters of matched text kept in a fingerprint. Long enough to tell two
#: sites apart, short enough that an edit at the far end of a long line does not
#: invalidate the record.
TEXT_WIDTH = 120

_WHITESPACE = re.compile(r"\s+")


class BaselineError(Exception):
    """A baseline file that cannot be trusted.

    Raised rather than ignored. An unreadable baseline could mean no exemptions
    or every exemption, and guessing either way is worse than stopping.
    """


def normalize(text: str) -> str:
    """The matched line, reduced to what identifies it.

    Whitespace is collapsed because indentation moves: wrapping a block in an
    ``if`` re-indents every line inside it, and a baseline that treats that as a
    hundred new findings gets re-recorded reflexively -- which absorbs whatever
    else arrived in the same commit.
    """
    return _WHITESPACE.sub(" ", text).strip()[:TEXT_WIDTH]


@dataclass(frozen=True)
class Accepted:
    """One finding a project has recorded as pre-existing.

    ``count`` because identical sites recur: a file may spell the same literal
    three times. Recording the multiplicity is what makes a fourth an increase
    instead of an indistinguishable duplicate.
    """

    registry: str
    entry_id: str
    antipattern: str
    path: str
    text: str
    count: int = 1

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        """What identifies this finding across commits.

        The line number is deliberately absent -- every edit above a finding
        shifts it, and churn reported as new findings trains people to
        re-record. The path is deliberately present: a bypass that moved to
        another file is a new site, and kanibako-cli's own tripwire failed
        precisely by being scoped to one module (``42ece129`` [0TMVXHC-Cx0001]).
        """
        return (self.registry, self.entry_id, self.antipattern, self.path,
                normalize(self.text))

    def __str__(self) -> str:
        times = f" (x{self.count})" if self.count > 1 else ""
        return (
            f"{self.path}: {self.antipattern!r} bypasses {self.entry_id}{times} "
            f"-- {self.text[:60]}"
        )


def _record(registry: str, hit: Bypass, count: int = 1) -> Accepted:
    return Accepted(
        registry=registry,
        entry_id=hit.entry_id,
        antipattern=hit.antipattern,
        path=hit.path,
        text=normalize(hit.text),
        count=count,
    )


@dataclass(frozen=True)
class Split:
    """A scan divided against what was already accepted."""

    #: Findings with no matching record. **These are what gates.**
    #:
    #: The pairs are the ones handed in, unchanged and by identity, so a caller
    #: can carry its own richer object alongside each finding and recover it
    #: here. ``claims`` does exactly that: a ``Bypass`` is what the ratchet
    #: fingerprints, and ``Claim.__str__`` is what a reader should be shown.
    new: tuple[tuple[str, Bypass], ...] = ()
    #: Findings the baseline already covers.
    accepted: tuple[tuple[str, Bypass], ...] = ()
    #: Records nothing matched -- the bypass was fixed, moved or rewritten. Never
    #: an error: work that removes a finding must not fail the build. Reported so
    #: the list can be driven down, which is the half of a ratchet that is easy
    #: to forget.
    stale: tuple[Accepted, ...] = ()
    #: Records this scan was not in a position to judge, because it did not run
    #: the check that produces them. **Not stale**, and keeping the two apart is
    #: the whole reason this field exists: ``check`` does not read documentation
    #: and ``claims`` does not read source, so each would otherwise report the
    #: other's records as no longer present and recommend pruning findings that
    #: are sitting right there.
    #:
    #: Carried rather than dropped, for the reason the baseline prints its own
    #: size: a run that quietly ignored part of an exemption list reads exactly
    #: like a run that accounted for all of it.
    unscanned: tuple[Accepted, ...] = ()


@dataclass
class Baseline:
    """Accepted findings, loaded from or written to one file.

    **The list carries the date it lapses**, for the reason the README already
    admitted about it: a baseline is an allowlist, and an allowlist that cannot
    expire is a decision nobody revisits. Every other deferral this package
    understands names its own end -- a promised path, an open question -- and
    an accepted finding is the same shape: *not now*, which is only honest with
    a *when*.

    ``until`` is not a repair estimate. It is when somebody looks at the list
    again: extend it deliberately, or drive it down.
    """

    path: Path
    accepted: tuple[Accepted, ...] = ()
    until: date | None = None
    #: Who accepted these, and why. ``by`` is required when there is a note, as
    #: it is on a promise: an unsigned reason is a reason with nobody behind it.
    by: str = ""
    note: str = ""

    def lapsed(self, today: date | None = None) -> bool:
        return self.until is not None and self.until < (today or date.today())

    @property
    def size(self) -> int:
        """Total accepted findings, counting multiplicity.

        Not ``len(accepted)``: a record covering three identical sites exempts
        three findings, and a size that under-reports its own exemptions is the
        thing this file exists to prevent.
        """
        return sum(item.count for item in self.accepted)

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @classmethod
    def load(cls, path: str | Path) -> Baseline:
        """Read a baseline. A missing file is an empty one, not an error.

        Missing means *not yet recorded*, and that state has to be reachable:
        the first ``--record`` writes it. A file that exists but cannot be read
        is different, and raises.
        """
        path = Path(path)
        if not path.is_file():
            return cls(path=path)
        try:
            document = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise BaselineError(f"cannot read baseline {path}: {exc}") from exc

        raw_until = document.get("until")
        if not raw_until:
            raise BaselineError(
                f"{path}: this baseline names no date it lapses. Every finding "
                "in it is exempt on a decision nobody has to revisit. "
                "Re-record it with --until YYYY-MM-DD."
            )
        try:
            until = date.fromisoformat(str(raw_until))
        except ValueError as exc:
            raise BaselineError(
                f"{path}: 'until' is {raw_until!r}, which is not a date. "
                "Write it as YYYY-MM-DD."
            ) from exc

        version = document.get("version")
        if version != FORMAT_VERSION:
            raise BaselineError(
                f"{path}: baseline format version {version!r}, expected "
                f"{FORMAT_VERSION}. Re-record it rather than editing by hand."
            )
        records = []
        for index, raw in enumerate(document.get("findings", [])):
            try:
                records.append(
                    Accepted(
                        registry=str(raw["registry"]),
                        entry_id=str(raw["entry"]),
                        antipattern=str(raw["antipattern"]),
                        path=str(raw["path"]),
                        text=str(raw["text"]),
                        count=int(raw.get("count", 1)),
                    )
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise BaselineError(
                    f"{path}: finding {index} is malformed: {exc}"
                ) from exc
        return cls(
            path=path,
            accepted=tuple(records),
            until=until,
            by=str(document.get("by", "")),
            note=str(document.get("note", "")),
        )

    def save(self) -> None:
        """Write the baseline, sorted so a diff shows only what changed."""
        findings = []
        for item in sorted(self.accepted, key=lambda r: r.key):
            written: dict[str, str | int] = {
                "registry": item.registry,
                "entry": item.entry_id,
                "antipattern": item.antipattern,
                "path": item.path,
                "text": item.text,
            }
            if item.count > 1:
                written["count"] = item.count
            findings.append(written)
        if self.until is None:
            raise BaselineError(
                f"{self.path}: refusing to write a baseline with no date it "
                "lapses. Give --until YYYY-MM-DD."
            )
        if self.note and not self.by:
            raise BaselineError(
                f"{self.path}: the note on this baseline is unsigned. Give "
                "--by as well, so a later reader knows whose decision it was."
            )
        document: dict[str, object] = {
            "version": FORMAT_VERSION,
            "until": self.until.isoformat(),
        }
        if self.by:
            document["by"] = self.by
        if self.note:
            document["note"] = self.note
        document["findings"] = findings
        self.path.write_text(json.dumps(document, indent=2) + "\n")

    def split(
        self,
        findings: Iterable[tuple[str, Bypass]],
        *,
        scope: Iterable[str] | None = None,
    ) -> Split:
        """Divide a scan into new, accepted and no-longer-present.

        Matching consumes: a record for three identical sites accepts three, and
        the fourth is new. Without that, one record would exempt a file's every
        future repetition of the same literal.

        :param scope: the finding sources this scan actually ran, or ``None``
            for all of them. One file holds the exemptions for every check here,
            deliberately -- two exemption lists eventually disagree about what a
            project accepted -- but no single command runs every check: ``check``
            reads source and ``claims`` reads prose. Without a scope, each
            reports the other's records as :attr:`Split.stale` and points the
            reader at ``--prune``, which is a command that would delete live
            exemptions on the strength of a scan that never looked for them.

            A finding tagged with a source outside ``scope`` **raises**, because
            the alternative is silent and expensive: it would be counted as new
            and gate CI on a finding the caller already said this run does not
            cover.

            The cost, named because it is real: under a scope, records left
            behind by a registry that was *deleted from the config* land in
            :attr:`Split.unscanned` rather than in ``stale``. They are still
            reported and ``baseline --prune`` -- which runs every check, and is
            the only command that writes -- still drops them.
        """
        covered = None if scope is None else {str(name) for name in scope}
        remaining: Counter[tuple[str, ...]] = Counter()
        by_key: dict[tuple[str, ...], Accepted] = {}
        unscanned: list[Accepted] = []
        for item in self.accepted:
            if covered is not None and item.registry not in covered:
                unscanned.append(item)
                continue
            remaining[item.key] += item.count
            by_key[item.key] = item

        new: list[tuple[str, Bypass]] = []
        accepted: list[tuple[str, Bypass]] = []
        for registry, hit in findings:
            if covered is not None and registry not in covered:
                raise BaselineError(
                    f"{self.path}: a finding from {registry!r} was handed to a "
                    f"split scoped to {sorted(covered)}. It would be counted as "
                    "new and fail the gate on a check this run said it does not "
                    "cover."
                )
            key = _record(registry, hit).key
            if remaining.get(key, 0) > 0:
                remaining[key] -= 1
                accepted.append((registry, hit))
            else:
                new.append((registry, hit))

        stale = tuple(
            Accepted(
                registry=by_key[key].registry,
                entry_id=by_key[key].entry_id,
                antipattern=by_key[key].antipattern,
                path=by_key[key].path,
                text=by_key[key].text,
                count=count,
            )
            for key, count in sorted(remaining.items())
            if count > 0
        )
        return Split(
            new=tuple(new),
            accepted=tuple(accepted),
            stale=stale,
            unscanned=tuple(sorted(unscanned, key=lambda item: item.key)),
        )


def record(
    path: str | Path,
    findings: Iterable[tuple[str, Bypass]],
    *,
    until: date,
    by: str = "",
    note: str = "",
) -> Baseline:
    """Build a baseline covering exactly ``findings``, and the date it lapses.

    Identical sites collapse into one record carrying their count, which is what
    makes the file readable at 111 findings and still exact.

    ``until`` has no default, deliberately. A date this package chose would be a
    number nobody decided, enforced as though somebody had -- the same refusal
    as the context ceiling's missing default.
    """
    counts: Counter[tuple[str, ...]] = Counter()
    first: dict[tuple[str, ...], Accepted] = {}
    for registry, hit in findings:
        candidate = _record(registry, hit)
        counts[candidate.key] += 1
        first.setdefault(candidate.key, candidate)

    accepted = tuple(
        Accepted(
            registry=first[key].registry,
            entry_id=first[key].entry_id,
            antipattern=first[key].antipattern,
            path=first[key].path,
            text=first[key].text,
            count=count,
        )
        for key, count in sorted(counts.items())
    )
    return Baseline(path=Path(path), accepted=accepted, until=until, by=by, note=note)
