"""Literals that should have been declared, and never were.

Everything else in this package detects re-derivation of something *already
declared*. That leaves a gap: two new things duplicating each other, neither of
them in a registry. Nothing fires, because there is no entry to bypass.

A corpus pass over 196 consolidation commits found that
gap is not one failure but three, and that the largest *reachable* share of it
is this one -- values and messages spelled in several places with no declared
home:

* three resolver "no X named 'N'" messages harmonized into one format
* plugin env literals folded into declared settings defaults
* a partition token single-sourced so it could not drift from the channel
  partition keying the same value

Every one of those is a category the bypass scan already handles **once
something is declared**. The only failure was that nothing prompted the
declaration. So this module does not judge whether two literals mean the same
thing -- it reports that the same text is spelled in several places and lets a
reader decide, which is the same fork the rest of the design offers: reuse it,
or declare it.

**Two strengths, for the reason the bypass scan has two.** Byte-identical text
in several files is *strong*. Text that merely resembles other text is *weak*,
because resemblance is where a mechanism starts guessing. Only strong findings
are fit to gate.
"""

from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from .bypass import _walk
from .prose import ANNOTATION_STRINGS, LITERAL_EXTRACTORS, MESSAGE_SKELETONS

#: Literals shorter than this are not worth clustering. Short strings are
#: overwhelmingly flags, keys and punctuation that repeat legitimately; the
#: constants adapter uses a shorter floor because there the value is already
#: known to be canonical, which is exactly the assumption unavailable here.
MIN_LITERAL_LENGTH = 8

#: A literal in more than this many files is an idiom, not a missing
#: declaration -- ``"utf-8"``, a format string every module uses. Reported as
#: suppressed rather than dropped, for the reason frequency suppression is
#: reported in ``report.py``: a filter nobody can see is a filter nobody can
#: correct.
DEFAULT_MAX_FILES = 12

#: Below this Jaccard overlap of word sets, two literals are not near-duplicates.
#: Tuned to keep "no workset named %r" beside "no box named %r" while separating
#: unrelated sentences that share one or two common words.
DEFAULT_SIMILARITY = 0.6

#: Words too common in a codebase's prose to imply kinship. Derived by
#: frequency at scan time rather than hardcoded, so a project's own domain
#: vocabulary suppresses itself; this is only the floor.
_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_]{2,}")


@dataclass(frozen=True)
class Site:
    """One place a literal is spelled."""

    path: str
    line: int
    text: str


@dataclass(frozen=True)
class Cluster:
    """Literals that are the same text, or close to it, in several files."""

    value: str
    sites: tuple[Site, ...]
    strength: str = "strong"
    variants: tuple[str, ...] = ()

    @property
    def files(self) -> tuple[str, ...]:
        return tuple(sorted({site.path for site in self.sites}))

    def __str__(self) -> str:
        where = ", ".join(f"{s.path}:{s.line}" for s in self.sites[:4])
        more = "" if len(self.sites) <= 4 else f" (+{len(self.sites) - 4} more)"
        return f"{self.value!r} in {len(self.files)} files -- {where}{more}"


@dataclass
class Duplication:
    """What a clustering pass found, including what it chose not to report."""

    strong: list[Cluster] = field(default_factory=list)
    weak: list[Cluster] = field(default_factory=list)
    composed: list[Cluster] = field(default_factory=list)
    suppressed: list[tuple[str, int]] = field(default_factory=list)

    def text(self, verbose: bool = False) -> str:
        """Report, most precise tier first.

        ``composed`` leads because it is the tier that earned it: 6 findings on
        a 65k-line codebase, against 111 exact and 222 near. Putting the noisiest
        tier first is how a reader learns to stop reading.
        """
        out: list[str] = []

        def block(title: str, entries: list[Cluster]) -> None:
            if not entries:
                return
            out.append(f"{title} ({len(entries)})")
            for cluster in entries:
                out.append(f"  {cluster}")
                if cluster.variants:
                    for variant in cluster.variants:
                        out.append(f"      {variant!r}")

        block("composed from a path spelled elsewhere", self.composed)
        block("same text, several files", self.strong)
        if verbose:
            block("near-identical text, already drifted", self.weak)
        elif self.weak:
            out.append(f"near-identical text: {len(self.weak)} (use -v)")
        if verbose and self.suppressed:
            out.append("suppressed as idiom (too many files to be a missing declaration)")
            for value, count in self.suppressed:
                out.append(f"  {value!r} in {count} files")
        elif self.suppressed:
            out.append(f"suppressed as idiom: {len(self.suppressed)} (use -v)")
        return "\n".join(out)


def _words(value: str) -> frozenset[str]:
    return frozenset(m.group(0).lower() for m in _WORD.finditer(value))


def _is_worth_clustering(value: str, min_length: int) -> bool:
    """Reject text that repeats for reasons that are not duplication.

    A literal with no letters is punctuation or a format fragment. One with a
    single word is a flag or a key, and those legitimately recur.
    """
    if len(value) < min_length or "\n" in value:
        return False
    return len(_words(value)) >= 2


def _collect(
    root: Path,
    suffixes: Sequence[str],
    exclusions: Sequence[str],
    min_length: int,
) -> dict[str, list[Site]]:
    by_value: dict[str, list[Site]] = defaultdict(list)
    for path in _walk(root, suffixes):
        rel = str(path.relative_to(root))
        if any(fragment in rel for fragment in exclusions):
            continue
        extractor = LITERAL_EXTRACTORS.get(path.suffix)
        if extractor is None:
            continue
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue
        annotations = ANNOTATION_STRINGS.get(path.suffix, lambda _: set())(source)
        skeletons = MESSAGE_SKELETONS.get(path.suffix, lambda _: [])(source)
        for line, content, line_text in [*extractor(source), *skeletons]:
            if content in annotations:
                continue
            if _is_worth_clustering(content, min_length):
                by_value[content].append(Site(rel, line, line_text.strip()[:80]))
    return by_value


def _near_clusters(
    singles: dict[str, list[Site]],
    min_files: int,
    similarity: float,
) -> list[Cluster]:
    """Group remaining literals by word-set overlap.

    Candidate pairs come from an inverted index rather than an all-pairs sweep,
    and words carried by many literals are dropped from that index first. That
    is the same move frequency suppression makes in ``report.py``: a term common
    enough to link everything links nothing.
    """
    values = list(singles)
    if len(values) < 2:
        return []

    index: dict[str, list[int]] = defaultdict(list)
    for i, value in enumerate(values):
        for word in _words(value):
            index[word].append(i)

    # A word appearing across a large share of literals is vocabulary, not kinship.
    ceiling = max(3, len(values) // 10)
    candidates: dict[frozenset[int], None] = {}
    for holders in index.values():
        if len(holders) > ceiling:
            continue
        for a_pos, a in enumerate(holders):
            for b in holders[a_pos + 1:]:
                candidates[frozenset((a, b))] = None

    parent = list(range(len(values)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    joined = False
    for pair in candidates:
        a, b = tuple(pair)
        wa, wb = _words(values[a]), _words(values[b])
        union = wa | wb
        if not union or len(wa & wb) / len(union) < similarity:
            continue
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
            joined = True
    if not joined:
        return []

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(len(values)):
        groups[find(i)].append(i)

    clusters: list[Cluster] = []
    for members in groups.values():
        if len(members) < 2:
            continue
        sites = [s for i in members for s in singles[values[i]]]
        # Deliberately no distinct-file requirement, unlike the exact tier. Two
        # spellings of one message have *already* drifted, and that is the
        # finding whether or not they sit in the same module: kento-core
        # e84b9504 harmonized "Error: No {} named" against "Error: no instance
        # named" 28 lines apart in a single file.
        spellings = sorted(values[i] for i in members)
        clusters.append(
            Cluster(
                value=spellings[0],
                sites=tuple(sites),
                strength="weak",
                variants=tuple(spellings),
            )
        )
    return clusters


def _path_clusters(
    by_value: dict[str, list[Site]],
    min_files: int,
    min_length: int,
) -> list[Cluster]:
    """Paths built by composing a shorter path that is spelled out again.

    Equality is the wrong test for this failure and the corpus says so.
    kanibako-cli ``452f0451`` single-sourced ``/etc/kanibako`` and two files
    under it; the sites were ``Path("/etc/kanibako/config_base.yaml")`` in one
    module and ``Path("/etc/kanibako") / BASELINE_FILENAME`` in another. No two
    of those strings are equal. The commit's own words are that the directory
    was "spelled independently" -- independent spellings, not copies.

    So the relation to look for is *containment on a path boundary*: a literal
    that another literal extends by a ``/``. Requiring the boundary is what
    keeps this from matching every string that happens to share a prefix.
    """
    paths = {
        value: sites
        for value, sites in by_value.items()
        if "/" in value and len(value) >= min_length
    }
    found: list[Cluster] = []
    emitted: list[str] = []
    for short in sorted(paths, key=len):
        stem = short.rstrip("/")
        # Keep the outermost prefix only; a nested one repeats its finding.
        if any(stem.startswith(prior + "/") for prior in emitted):
            continue
        members = [short] + [
            other for other in paths if other != short and other.startswith(stem + "/")
        ]
        if len(members) < 2:
            continue
        sites = [site for member in members for site in paths[member]]
        if len({site.path for site in sites}) < min_files:
            continue
        emitted.append(stem)
        found.append(
            Cluster(
                value=short,
                sites=tuple(sites),
                strength="composed",
                variants=tuple(sorted(members)),
            )
        )
    return found


def clusters(
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".py",),
    exclude: Iterable[str] = (),
    declared: Iterable[str] = (),
    min_length: int = MIN_LITERAL_LENGTH,
    min_files: int = 2,
    max_files: int = DEFAULT_MAX_FILES,
    similarity: float = DEFAULT_SIMILARITY,
) -> Duplication:
    """Literals spelled in several files with no declared home.

    :param declared: values a registry already declares. Those are the bypass
        scan's business, and reporting them here would say the same thing twice
        in two voices -- the failure this project is named after.
    :param min_files: distinct files a literal must appear in. Two, by default:
        one file repeating itself is usually a local idiom, while the same text
        in two modules is what drifts when one of them is edited.
    """
    root = Path(root)
    known = set(declared)
    by_value = _collect(root, suffixes, tuple(exclude), min_length)

    found = Duplication()
    singles: dict[str, list[Site]] = {}
    for value, sites in by_value.items():
        if value in known:
            continue
        files = {site.path for site in sites}
        if len(files) > max_files:
            found.suppressed.append((value, len(files)))
            continue
        if len(files) >= min_files:
            found.strong.append(Cluster(value=value, sites=tuple(sites)))
        else:
            singles[value] = sites

    found.weak = _near_clusters(singles, min_files, similarity)
    found.composed = _path_clusters(
        {v: s for v, s in by_value.items() if v not in known},
        min_files,
        min_length,
    )
    found.composed.sort(key=lambda c: (-len(c.files), c.value))
    found.strong.sort(key=lambda c: (-len(c.files), c.value))
    found.weak.sort(key=lambda c: (-len(c.files), c.value))
    found.suppressed.sort(key=lambda pair: -pair[1])
    return found
