"""Documents whose citations are dated in a list rather than in the prose.

A citation stamp is apparatus. It records when a checker last confirmed a
reference, and that is worth having everywhere a citation is written -- but in
the first page a reader of the project sees it is a token they have to learn to
ignore. ``[citations] suffixes`` answered that by taking user-facing prose out
of the policy's reach, which keeps the notation out and gives up the coverage
with it.

**This is the other answer, and it keeps both.** A document that cannot carry a
stamp is declared here, and its entry carries the date instead::

    [[resource]]
    path = "README.md"
    note = "the project's front page"
    confirmed = "2026-09-11"

    the entry     when every citation in that document was verified
    the document  the citations themselves, written plainly

Every citation in a declared document is dated by its entry. Nothing is
exempted: a citation in a document that is neither stamped nor listed is the
finding it was before, and a *new* user-facing document that starts citing
things is one the catch asks about.

**The unit is the file, and the alternative was measured before it was
rejected.** Citation-level entries would copy all 32 of this repository's
user-facing citations into a registry, and target-level 19 of them -- a second
carrier of facts the documents already state, which is the duplication this
package exists to report. The cost of the coarser unit is stated in
:class:`Resource` rather than discovered later.

**An entry with no date covers nothing.** Declaring a document is saying where
its date will live, not that anybody has checked it; until a run confirms it,
its citations are undated exactly as they were. The residue that creates is
cleared by ``kinemata confirm --write``, which is the point -- a date written by
hand says nothing, and this list would be the easiest place in the project to
write one.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from .adapters.bibliography import confirmed_date

#: What an entry may say. Anything else is refused rather than ignored, for the
#: reason a bibliography entry's keys are: ``confirm`` written for ``confirmed``
#: would leave a document declared, never dated, and reported as though nobody
#: had ever checked it -- a finding whose cause is a typo two files away.
RESOURCE_KEYS = frozenset({"path", "note", "confirmed"})

#: The table a resource file declares its entries under.
RESOURCE_TABLE = "resource"


class ResourceError(Exception):
    """A resource list that cannot mean what it says.

    Raised rather than skipped, the same call every loader here makes. A list
    that silently dropped an unreadable entry would leave the citations in that
    document reported as undated, and the reader would go looking for the fault
    in the document.
    """


@dataclass(frozen=True)
class Resource:
    """One user-facing document, and the day its citations were verified.

    ``confirmed`` is the whole of what this carries, and it is deliberately a
    date rather than a stamp: section 5.9 settled that a project records *the
    day* a source was verified, and a second time format for the same fact would
    eventually disagree with the first about one of them.

    **The accepted cost, stated here rather than found later.** A citation added
    to the document after the last confirmation sits under a date that predates
    it. The date is a record of a verification that happened, not the thing
    keeping the citations true -- ``claims`` settles every one of them on every
    run, and a newly added dead path in a README is a finding that morning
    whatever this entry says. What the coarse unit costs is precision about
    *when*, not coverage.
    """

    path: str
    note: str
    #: The day every citation in this document was last confirmed, or ``None``
    #: when no run has confirmed it yet.
    confirmed: date | None = None

    @property
    def dated(self) -> bool:
        return self.confirmed is not None


def _entry(record: Any, index: int, where: str, root: Path,
           seen: dict[str, int]) -> Resource:
    place = f"{where}: resource {index}"
    if not isinstance(record, Mapping):
        raise ResourceError(
            f"{place} is not a table. A resource declares `path` and `note`, "
            "and carries `confirmed` once a run has verified it."
        )
    unknown = set(record) - RESOURCE_KEYS
    if unknown:
        raise ResourceError(
            f"{place} ({record.get('path', '?')}) declares "
            f"{', '.join(sorted(unknown))}, which means nothing here "
            f"(known: {', '.join(sorted(RESOURCE_KEYS))})."
        )
    missing = [field for field in ("path", "note") if not record.get(field)]
    if missing:
        raise ResourceError(
            f"{place} ({record.get('path', '?')}) is missing "
            f"{', '.join(missing)}. An entry needs the document it dates and a "
            "note saying why that document cannot carry the date itself."
        )

    # Normalized the way the walk spells a path, so a declaration written
    # :shown:`./Example.md` covers the same file the scan reports as
    # :shown:`Example.md`. A spelling that fails to match would be an entry that
    # reads as coverage and provides none. `PurePosixPath` drops the leading `.`
    # component and leaves a dotted *name* alone, which a character strip would
    # not.
    path = PurePosixPath(str(record["path"]).strip()).as_posix()
    if path in seen:
        raise ResourceError(
            f"{place}: {path} is already declared as resource {seen[path]}. One "
            "document has one date; two entries for it would let a confirmation "
            "run write one of them and leave the other reading as a record."
        )
    if not (root / path).is_file():
        raise ResourceError(
            f"{place}: no such file: {path}. A resource nothing can read covers "
            "no citations while reading in this list as though it did -- and a "
            "rename is exactly when that happens."
        )
    seen[path] = index

    confirmed = None
    if record.get("confirmed"):
        # Re-raised in this module's own vocabulary. The rule is the
        # bibliography's and stays there -- one reading of what a `confirmed`
        # field may say -- but a caller catching `ResourceError` around a
        # resource file would otherwise see a bad date escape as something else
        # entirely and refuse to load for a reason it could not name.
        try:
            confirmed = confirmed_date(record["confirmed"], place)
        except ValueError as exc:
            raise ResourceError(str(exc)) from exc

    return Resource(path=path, note=str(record["note"]), confirmed=confirmed)


def declared(
    records: Sequence[Mapping[str, Any]], *, root: str | Path, where: str
) -> tuple[Resource, ...]:
    """Every entry in a resource list, or a refusal naming the bad one.

    :param records: one mapping per entry, as the file declares them.
    :param root: the project root every declared path is checked against.
    :param where: the file these came from, for messages.

    **An empty list raises.** A declared resource file with nothing in it takes
    the citation policy's coverage question and answers it with silence: every
    user-facing citation stays a finding, the reader sees a declaration that
    looks like the fix, and nothing says the two are unconnected.
    """
    root = Path(root)
    seen: dict[str, int] = {}
    built = [
        _entry(record, index, where, root, seen)
        for index, record in enumerate(records)
    ]
    if not built:
        raise ResourceError(
            f"{where} declares no resources. A list with nothing in it dates no "
            "citation while reading in the config as though the policy had been "
            f"answered -- remove the declaration or write a [[{RESOURCE_TABLE}]]."
        )
    return tuple(built)


def coverage(resources: Iterable[Resource]) -> dict[str, date]:
    """Document -> the date its citations carry. Undated entries are absent.

    The map the citation policy is handed, and the reason it is a map rather
    than the entries themselves: :mod:`kinemata.provenance` must not learn what
    a resource list is, for the same reason it must not learn what a registry
    is. A project that declares none still gets the whole policy.
    """
    return {
        resource.path: resource.confirmed
        for resource in resources
        if resource.confirmed is not None
    }
