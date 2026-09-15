"""What a project's ``exclude`` removes, and whether it removed what it meant.

**One carrier for one predicate.** ``any(fragment in rel for fragment in
exclusions)`` was spelled seven times across six modules, which is the
duplication category this package reports first: a rule enforced in several
places drifts, and this one already had -- :mod:`claims` strips a fragment's
trailing slash before matching and the scans do not, so ``exclude = ["tests/"]``
means two different things depending on which check is running. That difference
is **left exactly as it was** here; preparation stays with each caller and only
the matching moves. Changing it would silently alter what every existing config
removes, which is the failure this module exists to make visible.

**Fragments are substrings, and an anchored spelling is new.** A bare fragment
matches anywhere in a relative path, so ``exclude = ["tests/"]`` also removed an
adopter's :shown:`docs/plans/2026-03-07-smoke-tests-design.md`, and a denylist
could not express "this directory" at all: ``exclude = ["docs/"]`` would also
remove :shown:`api-docs/`, the tree such a config would exist to cover. A
**leading slash** now means *relative to the root, anchored*, so
:shown:`/docs/` removes :shown:`docs/` and leaves :shown:`api-docs/` alone.

The old spelling is unchanged rather than repaired, deliberately. Redefining a
trailing slash as "directory" would be a silent change to the meaning of every
config already written, including this repository's own -- the exact class of
defect being fixed. :func:`audit` is the other half: a project keeps the
spelling it has and gets told what it actually removed.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path


def matches(rel: str, fragment: str) -> bool:
    """Does one fragment remove this path?

    Anchored when it begins with ``/``: the rest must be the whole path or a
    leading directory of it. Otherwise the historical substring test, kept
    verbatim so that adding the anchored form changes nothing already written.
    """
    if fragment.startswith("/"):
        stem = fragment.strip("/")
        return bool(stem) and (rel == stem or rel.startswith(stem + "/"))
    return fragment in rel


def excluded(rel: str, fragments: Sequence[str]) -> bool:
    """Is this path removed by any of them?"""
    return any(matches(rel, fragment) for fragment in fragments)


def anchors(rel: str, fragment: str) -> bool:
    """Would this fragment still match if it were anchored?

    The discriminator :func:`audit` reports on. A fragment that matches only as
    a substring removed something its author was probably not naming -- which
    is a guess, and reported as an observation rather than as a finding.
    """
    stem = fragment.strip("/")
    return bool(stem) and (rel == stem or rel.startswith(stem + "/"))


def anchored_form(rel: str, fragment: str) -> str:
    """The anchored spelling that removes *rel*, or ``""`` if none does.

    :shown:`tests/` against :shown:`packages/agent-claude/tests/test_credentials.py`
    gives :shown:`/packages/agent-claude/tests/` -- the fragment names a real
    directory, just not one at the root. Against
    :shown:`docs/plans/smoke-tests-design.md` it gives ``""``: the match is
    inside a file's name, so **no** anchored spelling reaches it.

    ⚑ **Written because the two cases were being told the same thing, and for
    one of them it was false.** An adopter was advised to write ``/tests/`` for
    paths three directories down; anchoring is root-relative, so taking the
    advice would have stopped excluding three plugin test trees while the check
    went on exiting 0. Reported by them against the published release.
    """
    stem = fragment.strip("/")
    if not stem:
        return ""
    want = stem.split("/")
    parts = rel.split("/")
    # Segment-wise, so `tests` matches the directory and never `smoke-tests`.
    for start in range(len(parts) - len(want) + 1):
        if parts[start : start + len(want)] == want:
            return "/" + "/".join(parts[: start + len(want)]) + "/"
    return ""


@dataclass(frozen=True)
class Removed:
    """What one fragment did on one run."""

    fragment: str
    #: Every path it removed.
    paths: tuple[str, ...] = ()
    #: Those it removed only as a substring -- not the tree the name suggests.
    incidental: tuple[str, ...] = ()

    @property
    def anchored(self) -> bool:
        return self.fragment.startswith("/")

    @property
    def deeper(self) -> tuple[str, ...]:
        """Incidental paths where the fragment IS a directory, below the root.

        **The half the old remedy was wrong about.** These are removals an
        author plausibly meant, and root-anchoring silently ends every one.
        """
        return tuple(
            rel for rel in self.incidental if anchored_form(rel, self.fragment)
        )

    @property
    def within_a_name(self) -> tuple[str, ...]:
        """Incidental paths matched inside a name, which nothing anchored reaches.

        The half the old remedy was right about: an author who wrote
        :shown:`tests/` was not naming :shown:`docs/plans/smoke-tests-design.md`.
        """
        return tuple(
            rel for rel in self.incidental if not anchored_form(rel, self.fragment)
        )

    @property
    def anchored_forms(self) -> tuple[str, ...]:
        """The distinct anchored spellings that keep :attr:`deeper` removed.

        **Derived from the paths that actually matched, never from the
        fragment** -- deriving it from the fragment is what produced advice that
        reached none of the paths printed beside it.
        """
        return tuple(sorted({anchored_form(rel, self.fragment) for rel in self.deeper}))

    @property
    def inert(self) -> bool:
        """It removed nothing, so it is a line asserting something untrue.

        An adopter shipped three excludes that removed nothing at all, on a
        reason inherited from a comment nobody had measured. This repository
        shipped one too: ``deliverables/`` names a directory that has never
        existed here.
        """
        return not self.paths


@dataclass(frozen=True)
class Audit:
    """Every fragment, and what it removed."""

    removed: tuple[Removed, ...] = ()

    @property
    def inert(self) -> tuple[Removed, ...]:
        return tuple(item for item in self.removed if item.inert)

    @property
    def incidental(self) -> tuple[Removed, ...]:
        return tuple(item for item in self.removed if item.incidental)

    def lines(self) -> tuple[str, ...]:
        """One line per fragment worth remarking on, or nothing.

        Silent when every fragment removed the tree it names, because a report
        that speaks on a clean run trains its reader to skip it.

        ⚑ **The two kinds of incidental match get different advice, because one
        remedy was false for one of them.** A fragment matching a directory
        below the root and a fragment matching inside a file's name are not the
        same mistake: anchoring fixes the second and **silently ends** the
        first. Reported by an adopter who came within one edit of taking the
        advice and losing three test trees, against the published release.
        """
        said: list[str] = []
        for item in self.inert:
            said.append(
                f"exclude {item.fragment!r} removed 0 files: nothing in this "
                "tree matches it."
            )
        for item in self.incidental:
            if item.within_a_name:
                said.append(
                    f"exclude {item.fragment!r} removed "
                    f"{len(item.within_a_name)} path(s) by matching inside a "
                    f"name rather than a directory: "
                    f"{_shown(item.within_a_name)}. "
                    f"Write '/{item.fragment.strip('/')}/' to remove only the "
                    "tree of that name at the root."
                )
            if item.deeper:
                said.append(
                    f"exclude {item.fragment!r} removed {len(item.deeper)} "
                    f"path(s) from directories below the root: "
                    f"{_shown(item.deeper)}. "
                    f"Anchoring is ROOT-relative, so "
                    f"'/{item.fragment.strip('/')}/' would reach none of them "
                    f"-- to keep them, name each: "
                    f"{', '.join(repr(form) for form in item.anchored_forms)}."
                )
        return tuple(said)


def _shown(paths: Sequence[str], limit: int = 3) -> str:
    """The first few, and how many were not printed."""
    more = f" and {len(paths) - limit} more" if len(paths) > limit else ""
    return ", ".join(paths[:limit]) + more


def audit(
    paths: Iterable[str], fragments: Sequence[str], *, pruned: Sequence[str] = ()
) -> Audit:
    """What each fragment removed from a set of relative paths.

    Takes the paths rather than walking, so the caller that already walked the
    tree does not pay for a second one -- the reason :mod:`citations` reuses the
    scan's walk instead of writing a third.

    **Two narrowings, both measured on this repository rather than reasoned
    about.** The first draft reported :shown:`.venv/` as removing nothing, which
    is false in the way that matters: the directory is there, and the walk prunes
    it before descending. ``pruned`` names those, and a fragment naming one is a
    redundancy rather than a mistake, so it is not reported at all.

    The second draft reported :shown:`tests/` as removing 511 paths by substring,
    of which every one was already removed by ``corpus/``. A fragment is only
    remarked on for the paths **nothing else removes**: an over-broad match that
    changes no outcome is noise, and a report that speaks when nothing is wrong
    is one its reader learns to skip.
    """
    listed = list(paths)
    skip = {name.strip("/") for name in pruned}
    found: list[Removed] = []
    for fragment in fragments:
        if not fragment or fragment.strip("/") in skip:
            continue
        others = [
            _widest(other) for other in fragments if other and other is not fragment
        ]
        probe = _widest(fragment)
        hit = tuple(rel for rel in listed if matches(rel, probe))
        incidental = (
            ()
            if fragment.startswith("/")
            else tuple(
                rel
                for rel in hit
                if not anchors(rel, fragment) and not excluded(rel, others)
            )
        )
        found.append(Removed(fragment=fragment, paths=hit, incidental=incidental))
    return Audit(removed=tuple(found))


def _widest(fragment: str) -> str:
    """The fragment as the most aggressive consumer reads it.

    :mod:`claims` strips a trailing slash before matching and the scans do not,
    so one ``exclude`` line removes two different sets depending on which check
    is running. **That difference is a real defect and is deliberately not fixed
    here**, because repairing it would narrow what every existing config removes
    without anyone asking for it.

    The audit reports the wider reading. Over-reporting names a path some checks
    still read; under-reporting would have stayed silent about
    :shown:`docs/plans/2026-03-07-smoke-tests-design.md`, which is the removal
    that cost an adopter two claims and the whole reason this report exists.
    """
    return fragment if fragment.startswith("/") else fragment.rstrip("/")


def relative_paths(root: str | Path, walker: Iterable[Path]) -> tuple[str, ...]:
    """The walked paths as the exclusion test sees them."""
    base = Path(root)
    return tuple(str(path.relative_to(base)) for path in walker)
