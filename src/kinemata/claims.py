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
import sys
from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .bypass import GIT_DIR, SKIP_DIRS, _walk, git_ignored

#: How far back from a claim to look for a word that turns it into a mention.
#: Scoped rather than whole-line: an earlier version skipped the entire line and
#: silently stopped checking lines that also asserted something.
NEGATION_WINDOW = 45

#: Where a negated clause ends. Distance alone is not enough: in "there is no
#: ``a.py``, but the loader is ``b.py``" the negation sits 36 characters before
#: a claim it does not govern, and a window wide enough to catch real negations
#: swallows that one. The negation must be in the *same clause*.
#: Commas are deliberately absent. "Stale names (`a.toml`, `b.md`)" carries one
#: negation across a list, and treating the comma as a boundary reported every
#: item after the first. A contrastive conjunction genuinely ends the negation's
#: reach; a list separator does not.
CLAUSE_BOUNDARY = re.compile(r"[;:]|\bbut\b|\bhowever\b|\bwhereas\b|\bwhile\b", re.I)

#: Words that mean a path is being discussed rather than claimed to exist.
NEGATION = re.compile(
    r"\b(no|not|never|without|absent|missing|removed|deleted|dropped|gone|"
    r"initially|formerly|previously|was|were|had|used to|instead of|rather than|"
    # The vocabulary of describing a change. A changelog naming what a file
    # used to be called is a record, not a claim that the old name still works.
    r"stale|renamed|retired|superseded|replaced|corrected|obsolete|old)\b",
    re.I,
)

#: Names that mark an example rather than a file in this tree. ``src/pkg/x.py``
#: in a docstring is teaching a shape, not asserting a path.
PLACEHOLDER = re.compile(
    r"\b(pkg|foo|bar|baz|qux|example|examples?/your|OWNER|REPO|YOUR|myproj|"
    r"nosuch|placeholder|somewhere|your[-_]?\w*)\b",
    re.I,
)

#: A one-letter stem is an example by convention -- `a.py`, `b.py`, `x.md`.
#: Prose explaining a rule quotes them constantly and asserts none of them.
EXAMPLE_STEM = re.compile(r"(^|/)[a-z]\.[a-z]+$")

#: Prefixes that put a path outside the tree, where this cannot verify it.
EXTERNAL_PREFIXES = ("~", "/", "#", "@", "$")

#: Characters that make a token a shape being described rather than a file.
PATTERN_CHARACTERS = "*?<>{}"

#: Link targets that address something other than a file in the tree. ``@``
#: prefixes a scheme some document sets use for tree-relative addressing.
LINK_PREFIXES = ("#", "mailto:", "@")

#: Marks a URL in either a path token or a link target.
SCHEME = "://"

#: Marks an SSH remote: ``git@github.com:owner/repo.git`` is an address.
REMOTE_MARKER = "@"

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
    #: Every tree a claim may resolve against, in order.
    roots: tuple[Path, ...] = ()

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
        # On disk beats the index. Exclusions say which documents to *read*;
        # they must not decide what exists. `corpus/` is gitignored and 39 MB of
        # it is sitting right there, so a note describing it is telling the
        # truth -- and reporting that is how a checker loses its reader.
        if any((base / target).exists() for base in self.roots or (self.root,)):
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
    #: Kinds absent because the tree cannot support them -- commit claims
    #: outside a repository. Named rather than dropped, but not a failure: the
    #: project did not ask for them.
    unavailable: list[str] = field(default_factory=list)
    #: Oracles the project **declared** and that could not be reached. A
    #: failure, because a declared check that silently does nothing is exactly
    #: the inert signal this package exists to prevent -- and in CI, "printed a
    #: note and exited 0" is indistinguishable from "passed".
    blocked: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.broken or self.blocked)

    def text(self) -> str:
        out = [f"  {claim}" for claim in self.broken]
        for kind in self.blocked:
            out.append(f"  BLOCKED: {kind}")
        for kind in self.unavailable:
            out.append(f"  NOT CHECKED: {kind}")
        return "\n".join(out)


# -- git, asked once and in one place ----------------------------------------


def _git(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments], capture_output=True, text=True, check=False
    )


def _is_repository(root: Path) -> bool:
    return (root / GIT_DIR).exists()


def _known_commits(roots: Sequence[Path], shas: Iterable[str]) -> set[str] | None:
    """Which of these hashes are in the repository. ``None`` if git cannot say.

    Searches every tree a claim may resolve against, not just the scanned one.
    Process notes that live beside a repository cite *its* commits, and the
    notes directory is usually not a repository itself -- so checking only the
    scanned root reports "not a git repository" and settles nothing. The dead
    hashes that prompted this were in exactly such a directory.
    """
    repositories = [base for base in roots if _is_repository(base)]
    if not repositories:
        return None
    known: set[str] = set()
    for sha in set(shas):
        if any(
            _git(repo, "cat-file", "-e", f"{sha}^{{commit}}").returncode == 0
            for repo in repositories
        ):
            known.add(sha)
    return known


# -- claim kinds, declared rather than spelled out in the loop ----------------


def _negated(line: str, start: int, end: int, previous: str = "") -> bool:
    """Is the claim at ``start`` being discussed rather than asserted?

    Two bounds, because each alone has failed. The window keeps a negation
    early in a long line from reaching a claim at the end of it. The clause
    boundary keeps a negation from reaching *past* the clause it belongs to --
    without it, "there is no ``a.py``, but the loader is ``b.py``" silently
    stops checking ``b.py``, which is the under-reporting failure wearing the
    over-reporting fix's clothes.
    """
    window = line[max(0, start - NEGATION_WINDOW):start]
    # Wrapped prose puts the negation on the line above: "there is no\n``x.py``"
    # is one sentence and two lines, and looking only at this one reports it.
    if start < NEGATION_WINDOW and previous:
        window = previous[-NEGATION_WINDOW:] + " " + window
    boundaries = list(CLAUSE_BOUNDARY.finditer(window))
    clause = window[boundaries[-1].end():] if boundaries else window
    if NEGATION.search(clause):
        return True
    # And it may follow: "`src/gone.py` is missing" negates just as plainly as
    # "no `src/gone.py`". Bounded by the clause for the same reason.
    # From *after* the claim. Starting at it lets a path spell its own
    # negation: `src/gone.py` contains "gone", and reported itself exempt.
    ahead = line[end:end + NEGATION_WINDOW]
    boundary = CLAUSE_BOUNDARY.search(ahead)
    return bool(NEGATION.search(ahead[:boundary.start()] if boundary else ahead))


def _path_claims(line: str, previous: str = "") -> Iterator[str]:
    for match in _BACKTICKED.finditer(line):
        token = match.group(1)
        if SCHEME in token or token.startswith(EXTERNAL_PREFIXES):
            continue
        if any(character in token for character in PATTERN_CHARACTERS):
            continue
        # A remote, not a path: `git@host:owner/repo.git`.
        if REMOTE_MARKER in token:
            continue
        # A token with no extension and no trailing slash is only a path claim
        # if it turns out to be one. `doctorjei/kinemata` is a repository slug
        # and `owner/project` is a sentence; reporting them teaches readers to
        # skim the report. The cost is a dead *directory* reference going
        # unnoticed, which is the direction worth losing in.
        if not token.endswith("/") and PurePosixPath(token).suffix not in FILE_SUFFIXES:
            continue
        if PLACEHOLDER.search(token) or EXAMPLE_STEM.search(token):
            continue
        if _negated(line, match.start(), match.end(), previous):
            continue  # discussed, not asserted
        yield token


def _link_claims(line: str, previous: str = "") -> Iterator[str]:
    for match in _LINK.finditer(line):
        target = match.group(1)
        if SCHEME in target or target.startswith(LINK_PREFIXES):
            continue
        yield target


def _commit_claims(line: str, previous: str = "") -> Iterator[str]:
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
class Counted:
    """A number the documentation states, and the command that settles it.

    The only claim kind whose oracle is outside the tree, and the only one that
    is **opt-in**: settling it means running a command from a config file. That
    is a real trust decision -- a repository whose config can run commands is a
    repository you are already trusting -- so nothing runs unless a project
    declares it, and a project that declares none never spawns a process.

    Worth the cost because the failure is common and invisible: this project's
    notes claimed 74 tests through three separate sessions in which the true
    number went 76, 88, 103.
    """

    #: Group 1 is the claimed number.
    pattern: str
    command: tuple[str, ...]
    #: Group 1 is the true number, read from the command's output.
    extract: str
    label: str = "count"
    #: Where to run, relative to the scanned root. Documents and the thing they
    #: describe are not always in one tree: process notes may live beside a
    #: repository rather than inside it, and the oracle belongs with the code.
    directory: str = "."


def counted_claims(text: str, spec: Counted) -> Iterator[tuple[int, str]]:
    """The numbers a line states, however the pattern chose to capture them.

    The first *matching* group, not group 1. A count claim is naturally written
    as alternation -- "**103 tests**" or "103 tests pass" -- and every branch
    but the one that matched captures ``None``. Reading group 1 blindly crashes
    on the second phrasing, which is how this was found.
    """
    for match in re.finditer(spec.pattern, text):
        number = next((group for group in match.groups() if group), None)
        if number is None:
            continue
        yield int(number), match.group(0)


#: Stands for the interpreter kinemata is running under. A config file cannot
#: name it -- ``python`` on PATH is whatever the system installed, which is not
#: where the project's dev dependencies live, and a command that cannot run
#: reports nothing while looking configured.
INTERPRETER = "{python}"


def actual_count(spec: Counted, root: Path) -> int | None:
    """Run the oracle. ``None`` when it cannot be reached -- never a pass."""
    command = [
        sys.executable if part == INTERPRETER else part for part in spec.command
    ]
    try:
        result = subprocess.run(
            command, cwd=str(root / spec.directory), capture_output=True, text=True,
            check=False,
        )
    except (OSError, ValueError):
        return None
    found = re.search(spec.extract, result.stdout + result.stderr)
    return int(found.group(1)) if found else None


@dataclass(frozen=True)
class ClaimKind:
    """One sort of falsifiable assertion, and how to settle it."""

    name: str
    extract: Callable[..., Iterator[str]]
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
    """Everything present, minus what belongs to somebody else.

    Only ``git_ignored`` narrows this. A project's ``exclude`` says which files
    to *read as documents*; letting it also decide what exists reported
    `temp/scripts/harvest.sh` as missing while the file sat there.
    """
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
    counts: Sequence[Counted] = (),
    resolve_in: Iterable[str] = (),
    commits_in: Iterable[str] = (),
) -> Verification:
    """Falsify every claim the prose makes about this tree.

    :param historical: path fragments holding superseded records. An archive
        cites paths and commits that were real when written; checking it for
        currency reports the archive for being an archive.
    :param commits_in: further repositories whose commits may be cited. Notes
        that review another project name its commits, and settling those
        against only this repository reports honest citations as dead.
    :param resolve_in: further trees a claim may resolve against. Process notes
        that live beside a repository rather than inside it describe *that*
        tree, and resolving them only against their own is how a correct
        reference reads as a dead one.
    """
    root = Path(root)
    archives = tuple(fragment for fragment in historical if fragment)
    exclusions = tuple(fragment.rstrip("/") for fragment in exclude if fragment)
    exclusions += git_ignored(root)

    files, directories = _index(root, git_ignored(root))
    roots = [root]
    for other in resolve_in:
        elsewhere = (root / other).resolve()
        if elsewhere.is_dir():
            roots.append(elsewhere)
            more_files, more_directories = _index(elsewhere, git_ignored(elsewhere))
            # Indexed twice: bare, and under the tree's own name. Notes beside a
            # repository call it by name -- `workspace/docs/design.md` -- and
            # indexing only the inside of that tree reports the reference dead.
            label = elsewhere.name
            files |= more_files | {f"{label}/{rel}" for rel in more_files}
            directories |= more_directories | {f"{label}/{rel}" for rel in more_directories}
    tree = Tree(root=root, files=files, directories=directories, roots=tuple(roots))

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

        previous = ""
        for number, line in enumerate(source.splitlines(), start=1):
            for kind in kinds:
                if historic and kind.current_only:
                    continue
                for text in kind.extract(line, previous):
                    pending.append((kind, text, Claim(kind.name, text, rel, number)))
            previous = line

    commit_roots = roots + [
        (root / other).resolve() for other in commits_in
    ]
    tree.commits = _known_commits(
        commit_roots, (text for kind, text, _ in pending if kind.needs_git)
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

    _verify_counts(root, suffixes, exclusions, archives, counts, found)
    found.broken.sort(key=lambda c: (c.path, c.line))
    return found


def _verify_counts(
    root: Path,
    suffixes: Sequence[str],
    exclusions: Sequence[str],
    archives: Sequence[str],
    counts: Sequence[Counted],
    found: Verification,
) -> None:
    """Numbers the prose states, against what the oracle actually reports."""
    for spec in counts:
        truth = actual_count(spec, root)
        if truth is None:
            # Declared and unreachable is a failure, not a note. The project
            # asked for this check; a broken oracle means it is not running.
            found.blocked.append(
                f"{spec.label}: {' '.join(spec.command)} produced no number"
            )
            continue
        for path in _walk(root, suffixes):
            rel = path.relative_to(root).as_posix()
            if _excluded(rel, exclusions) or _excluded(rel, archives):
                continue
            try:
                source = path.read_text(errors="ignore")
            except OSError:
                continue
            for number, line in enumerate(source.splitlines(), start=1):
                for claimed, text in counted_claims(line, spec):
                    found.checked += 1
                    if claimed != truth:
                        found.broken.append(
                            Claim(spec.label, f"{text} (actually {truth})", rel, number)
                        )
