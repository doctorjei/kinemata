"""Documentation as a registry of claims, and the same catch pointed at prose.

A document asserts facts about the tree it ships with: this file exists, that
link resolves, this commit is the one that made the change. Each is a claim with
a source of truth somewhere else in the repository, which makes it falsifiable --
and a falsifiable claim nobody falsifies is how documentation rots while
reporting itself correct.

The evidence for building it is this project's own. In one working session,
``docs/design.md`` documented a method named ``enumerate()`` for three commits
after the code had settled on ``entries()``; the README's first screen carried a
spelling the convention forbids; and two commit hashes were cited in notes after
a rebase had removed them from the tree. All three were invisible to a careful
reader and obvious to a checker.

**Two failures this had to be built around**, both learned the expensive way:

* **Over-reporting.** The first prototype produced 23 findings, none real, most
  of them prose that *discusses* a path rather than asserting one. "There is no
  ``~/.ssh`` in this box" is a true sentence about an absent file, and reading it
  as a claim teaches readers to ignore the report.
* **Then silent under-reporting**, introduced by the fix for the first. Skipping
  any line containing a negation word disabled the check on lines that also made
  a real claim, and the tool reported clean while checking less than it said.
  Negation is scoped to the text immediately before the claim for that reason.

Kinds are declared in ``CLAIM_KINDS`` rather than spelled out in the loop, so
adding one is a table entry and the loop never learns their names.

Unlike ``undeclared``, this **gates**. A missing file is a fact, not a judgment.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable, Iterator, Sequence

from .bypass import GIT_DIR, SKIP_DIRS, _walk

#: How far back from a claim to look for a word that turns it into a mention.
#: Scoped rather than whole-line: an earlier version skipped the entire line and
#: silently stopped checking lines that also asserted something.
NEGATION_WINDOW = 45

#: Where a negated clause ends. Distance alone is not enough: in "there is no
#: ``a.py``, but the loader is ``b.py``" the negation sits 36 characters before
#: a claim it does not govern, and a window wide enough to catch real negations
#: swallows that one. The negation must be in the *same clause*.
CLAUSE_BOUNDARY = re.compile(r"[,;:]|\bbut\b|\bhowever\b|\bwhereas\b|\bwhile\b", re.I)

#: Words that mean a path is being discussed rather than claimed to exist.
NEGATION = re.compile(
    r"\b(no|not|never|without|absent|missing|removed|deleted|dropped|gone|"
    r"initially|formerly|previously|was|were|had|used to|instead of|rather than)\b",
    re.I,
)

#: Names that mark an example rather than a file in this tree. ``src/pkg/x.py``
#: in a docstring is teaching a shape, not asserting a path.
PLACEHOLDER = re.compile(
    r"\b(pkg|foo|bar|baz|qux|example|examples?/your|OWNER|REPO|YOUR|myproj|"
    r"nosuch|placeholder|somewhere|your[-_]?\w*)\b",
    re.I,
)

#: Prefixes that put a path outside the tree, where this cannot verify it.
EXTERNAL_PREFIXES = ("~", "/", "#", "@", "$")

#: Characters that make a token a shape being described rather than a file.
PATTERN_CHARACTERS = "*?<>{}"

#: Link targets that address something other than a file in the tree.
LINK_PREFIXES = ("#", "mailto:")

#: Marks a URL in either a path token or a link target.
SCHEME = "://"

#: Extensions that make a bare filename a claim about a file. Without an
#: allowlist, ``config.data`` and ``system.agent`` read as filenames.
FILE_SUFFIXES = frozenset({
    ".py", ".md", ".toml", ".yaml", ".yml", ".cfg", ".json", ".txt", ".sh",
    ".ini", ".rst", ".lock", ".in", ".mk",
})

_BACKTICKED = re.compile(r"`([^`\s]+)`")
_LINK = re.compile(r"\[[^\]]*\]\(([^)#\s]+)[^)]*\)")
_SHA = re.compile(r"`([0-9a-f]{7,12})`")


@dataclass(frozen=True)
class Claim:
    """One falsifiable assertion a document makes about the tree."""

    kind: str
    text: str
    path: str
    line: int

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} does not resolve: {self.text}"


@dataclass
class Tree:
    """What the claims are checked against."""

    root: Path
    files: set[str] = field(default_factory=set)
    directories: set[str] = field(default_factory=set)
    commits: set[str] | None = None

    def resolves(self, claim: str) -> bool:
        """Is this path in the tree, however the document chose to anchor it?

        Documents anchor paths differently and both are honest:
        ``src/pkg/cli.py`` from the root, ``pkg/cli.py`` from inside ``src``, or
        a bare ``cli.py`` naming a module the reader can find. A checker that
        demands one spelling reports correct prose, which is the fastest way to
        be ignored.
        """
        target = claim.strip().rstrip("/.,;:")
        if not target:
            return True
        everything = self.files | self.directories
        if target in everything:
            return True
        suffix = "/" + target
        if any(known.endswith(suffix) for known in everything):
            return True
        prefix = target + "/"
        if any(known.startswith(prefix) for known in everything):
            return True
        if "/" not in target:
            return any(PurePosixPath(known).name == target for known in self.files)
        return False


@dataclass
class Verification:
    broken: list[Claim] = field(default_factory=list)
    checked: int = 0
    #: Claim kinds that could not be checked at all, named rather than dropped.
    #: A checker that quietly stops checking is worse than no checker.
    unavailable: list[str] = field(default_factory=list)

    def text(self) -> str:
        out = [f"  {claim}" for claim in self.broken]
        for kind in self.unavailable:
            out.append(f"  NOT CHECKED: {kind}")
        return "\n".join(out)


# -- git, asked once and in one place ----------------------------------------


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True
    )


def _is_repository(root: Path) -> bool:
    return (root / GIT_DIR).exists()


def _git_ignored(root: Path) -> set[str]:
    """Paths git is told to ignore: other projects' material, not our claims.

    Returns empty when git cannot answer, which over-reports rather than
    under-reports -- the safe direction, and the same choice ``prose.py`` makes
    for a file it cannot parse.

    Not optional in practice. Without it this project's own run reported 147
    broken paths, every one of them inside a gitignored brief belonging to
    another author.
    """
    if not _is_repository(root):
        return set()
    result = _git(root, "ls-files", "--others", "--ignored",
                  "--exclude-standard", "--directory")
    if result.returncode != 0:
        return set()
    return {line.strip().rstrip("/") for line in result.stdout.splitlines() if line.strip()}


def _known_commits(root: Path, shas: Iterable[str]) -> set[str] | None:
    """Which of these hashes are in the repository. ``None`` if git cannot say."""
    if not _is_repository(root):
        return None
    known: set[str] = set()
    for sha in set(shas):
        if _git(root, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0:
            known.add(sha)
    return known


# -- claim kinds, declared rather than spelled out in the loop ----------------


def _negated(line: str, start: int) -> bool:
    """Is the claim at ``start`` being discussed rather than asserted?

    Two bounds, because each alone has failed. The window keeps a negation
    early in a long line from reaching a claim at the end of it. The clause
    boundary keeps a negation from reaching *past* the clause it belongs to --
    without it, "there is no ``a.py``, but the loader is ``b.py``" silently
    stops checking ``b.py``, which is the under-reporting failure wearing the
    over-reporting fix's clothes.
    """
    window = line[max(0, start - NEGATION_WINDOW):start]
    boundaries = list(CLAUSE_BOUNDARY.finditer(window))
    clause = window[boundaries[-1].end():] if boundaries else window
    return bool(NEGATION.search(clause))


def _path_claims(line: str) -> Iterator[str]:
    for match in _BACKTICKED.finditer(line):
        token = match.group(1)
        if SCHEME in token or token.startswith(EXTERNAL_PREFIXES):
            continue
        if any(character in token for character in PATTERN_CHARACTERS):
            continue
        if "/" not in token and PurePosixPath(token).suffix not in FILE_SUFFIXES:
            continue
        if PLACEHOLDER.search(token):
            continue
        if _negated(line, match.start()):
            continue  # discussed, not asserted
        yield token


def _link_claims(line: str) -> Iterator[str]:
    for match in _LINK.finditer(line):
        target = match.group(1)
        if SCHEME in target or target.startswith(LINK_PREFIXES):
            continue
        yield target


def _commit_claims(line: str) -> Iterator[str]:
    for match in _SHA.finditer(line):
        yield match.group(1)


def _resolve_path(text: str, tree: Tree, document: Path) -> bool:
    return tree.resolves(text.split(":", 1)[0])


def _resolve_link(text: str, tree: Tree, document: Path) -> bool:
    anchored = (document.parent / text).resolve()
    try:
        relative = anchored.relative_to(tree.root.resolve()).as_posix()
    except ValueError:
        return True  # outside the tree; not ours to falsify
    return tree.resolves(relative)


def _resolve_commit(text: str, tree: Tree, document: Path) -> bool:
    return tree.commits is None or text in tree.commits


@dataclass(frozen=True)
class ClaimKind:
    """One sort of falsifiable assertion, and how to settle it."""

    name: str
    extract: Callable[[str], Iterator[str]]
    resolve: Callable[[str, Tree, Path], bool]
    #: Kinds that report the tree's *current* state are wrong to run over
    #: superseded records: an archive cites what was true when it was written.
    current_only: bool = True
    #: This kind cannot be settled from the file tree alone. The loop asks the
    #: row rather than testing its name, so a fourth kind needing git costs a
    #: field and no edit here.
    needs_git: bool = False
    #: What to report when the kind cannot be checked. Named, never dropped.
    when_unavailable: str = ""


#: Adding a kind is a row here. The verification loop never learns their names.
CLAIM_KINDS: tuple[ClaimKind, ...] = (
    ClaimKind("path", _path_claims, _resolve_path),
    ClaimKind("link", _link_claims, _resolve_link),
    ClaimKind(
        "commit", _commit_claims, _resolve_commit,
        needs_git=True,
        when_unavailable="commit hashes (not a git repository)",
    ),
)


def _excluded(rel: str, exclusions: Sequence[str]) -> bool:
    return any(fragment in rel for fragment in exclusions)


def _index(root: Path, exclusions: Sequence[str]) -> tuple[set[str], set[str]]:
    files: set[str] = set()
    directories: set[str] = set()
    for path in root.rglob("*"):
        if SKIP_DIRS & set(path.parts):
            continue
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, exclusions):
            continue
        (directories if path.is_dir() else files).add(rel)
    return files, directories


def verify(
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".md",),
    exclude: Iterable[str] = (),
    historical: Iterable[str] = (),
    kinds: Sequence[ClaimKind] = CLAIM_KINDS,
) -> Verification:
    """Falsify every claim the prose makes about this tree.

    :param historical: path fragments holding superseded records. An archive
        cites paths and commits that were real when written; checking it for
        currency reports the archive for being an archive.
    """
    root = Path(root)
    archives = tuple(fragment for fragment in historical if fragment)
    exclusions = tuple(fragment.rstrip("/") for fragment in exclude if fragment)
    exclusions += tuple(_git_ignored(root))

    files, directories = _index(root, exclusions)
    tree = Tree(root=root, files=files, directories=directories)

    found = Verification()
    pending: list[tuple[ClaimKind, str, Claim]] = []

    for path in _walk(root, suffixes):
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, exclusions):
            continue
        historic = _excluded(rel, archives)
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue

        for number, line in enumerate(source.splitlines(), start=1):
            for kind in kinds:
                if historic and kind.current_only:
                    continue
                for text in kind.extract(line):
                    pending.append((kind, text, Claim(kind.name, text, rel, number)))

    tree.commits = _known_commits(
        root, (text for kind, text, _ in pending if kind.needs_git)
    )
    if tree.commits is None:
        found.unavailable.extend(
            kind.when_unavailable
            for kind in kinds
            if kind.needs_git and kind.when_unavailable
        )

    for kind, text, claim in pending:
        found.checked += 1
        if not kind.resolve(text, tree, root / claim.path):
            found.broken.append(claim)

    found.broken.sort(key=lambda c: (c.path, c.line))
    return found
