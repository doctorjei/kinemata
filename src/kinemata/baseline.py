"""The ratchet: adopt the gate on a codebase that is already failing it.

``check`` on an existing project is red on day one. kanibako-cli produces 111
strong findings at ``main``; a team that turns the gate on sees a wall of
failures for code nobody is touching, and the rational response is to turn it
back off. A gate that only works on a greenfield tree is a gate almost nobody
can adopt.

So the accepted state is recorded, and the gate fails on *increase* --
``design.md`` §4.3: "record the baseline, fail on any increase, drive it down on
a separate schedule that does not block feature work."

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
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

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
        precisely by being scoped to one module (``42ece129``).
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
    new: tuple[tuple[str, Bypass], ...] = ()
    #: Findings the baseline already covers.
    accepted: tuple[tuple[str, Bypass], ...] = ()
    #: Records nothing matched -- the bypass was fixed, moved or rewritten. Never
    #: an error: work that removes a finding must not fail the build. Reported so
    #: the list can be driven down, which is the half of a ratchet that is easy
    #: to forget.
    stale: tuple[Accepted, ...] = ()


@dataclass
class Baseline:
    """Accepted findings, loaded from or written to one file."""

    path: Path
    accepted: tuple[Accepted, ...] = ()

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
        return cls(path=path, accepted=tuple(records))

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
        document = {"version": FORMAT_VERSION, "findings": findings}
        self.path.write_text(json.dumps(document, indent=2) + "\n")

    def split(self, findings: Iterable[tuple[str, Bypass]]) -> Split:
        """Divide a scan into new, accepted and no-longer-present.

        Matching consumes: a record for three identical sites accepts three, and
        the fourth is new. Without that, one record would exempt a file's every
        future repetition of the same literal.
        """
        remaining: Counter[tuple[str, ...]] = Counter()
        by_key: dict[tuple[str, ...], Accepted] = {}
        for item in self.accepted:
            remaining[item.key] += item.count
            by_key[item.key] = item

        new: list[tuple[str, Bypass]] = []
        accepted: list[tuple[str, Bypass]] = []
        for registry, hit in findings:
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
        return Split(new=tuple(new), accepted=tuple(accepted), stale=stale)


def record(path: str | Path, findings: Iterable[tuple[str, Bypass]]) -> Baseline:
    """Build a baseline covering exactly ``findings``.

    Identical sites collapse into one record carrying their count, which is what
    makes the file readable at 111 findings and still exact.
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
    return Baseline(path=Path(path), accepted=accepted)
