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
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from .bypass import GIT_DIR, _tree, _walk, git_ignored

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
#: ``%`` joined them after a Windows ``%APPDATA%\\httpie\\config.json`` in
#: httpie's documentation was reported as a dead path in httpie's own tree.
EXTERNAL_PREFIXES = ("~", "/", "#", "@", "$", "%")

#: A backslash means this is not a path *here*: a Windows path, which cannot be
#: resolved against this tree either way, or a token like ``\o/`` that only
#: looks like one. Both were reported on a foreign project, and both belong with
#: the prefixes above -- cases this cannot settle rather than cases it failed.
WINDOWS_SEPARATOR = "\\"

#: A bare ``Word.suffix`` whose stem is capitalized the way a class is.
#: ``Response.json`` is an attribute reference in requests' changelog, read as a
#: file because ``.json`` is a known suffix. Filenames in these trees are
#: lowercase (``config.json``) or shouted (``README.md``), neither of which
#: matches.
ATTRIBUTE_REFERENCE = re.compile(r"^[A-Z][a-z0-9]+\.[A-Za-z0-9]+$")

#: Suffixes the rule above does **not** apply to. It shipped costing a
#: capitalized document name -- ``Introduction.md``, ``Changelog.md`` -- which
#: is a spelling projects actually use, while an attribute called ``md`` is one
#: nobody writes. The collision is real only where the tail is also a plausible
#: method name, and ``json`` is the case that produced it. Narrowing the rule by
#: suffix keeps the catch and drops the cost.
ATTRIBUTE_EXEMPT_SUFFIXES = (".md", ".rst", ".txt")

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
#: A web address, whether it sits in a link target, in backticks, or bare in
#: prose. All three spellings appear in this project's own documents.
_URL = re.compile(r"https?://[^\s)>\]\"'`]+")

#: Status codes that settle a URL as gone. Everything else that is not a success
#: is ambiguous from here -- see :func:`_reach`.
DEAD_STATUS = frozenset({404, 410})

#: The server refusing the *method*, not the resource. Worth a second ask.
HEAD_REFUSED = frozenset({405, 501})

#: Sent because a default Python user agent is refused by enough sites to turn
#: real answers into unknowns.
USER_AGENT = "kinemata-claims/1.0 (documentation link check)"

EXTERNAL_TIMEOUT = 10.0


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
    #: What each cited URL answered: ``True`` alive, ``False`` gone, ``None``
    #: asked and unanswerable. The whole map is ``None`` when nothing was asked,
    #: which is the same distinction ``commits`` draws.
    reachable: dict[str, bool | None] | None = None

    def resolves(self, claim: str) -> bool:
        """Is this path in the tree, however the document chose to anchor it?

        Documents anchor paths differently and both are honest:
        ``src/pkg/cli.py`` from the root, ``pkg/cli.py`` from inside ``src``, or
        a bare ``cli.py`` naming a module the reader can find. A checker that
        demands one spelling reports correct prose, which is the fastest way to
        be ignored.
        """
        target = claim.strip().rstrip("/.,;:")
        # `./name` anchors to the document's own directory. Stripping it lets
        # the fallbacks below answer: httpie's packaging README names
        # `./get_release_artifacts.sh`, the file sits beside it, and this
        # reported it dead because the prefix survived into every lookup.
        if target.startswith("./"):
            target = target[2:]
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
    #: Claims held open by a declared promise: the document describes something
    #: the project intends to produce, and it does not exist yet. Reported on
    #: every run, never a failure -- that is what declaring it bought.
    deferred: list[Claim] = field(default_factory=list)
    #: Promises the tree has since kept. A **failure**, and the only kind here
    #: that fires on something going right: the declaration is now false, and
    #: an exemption list nobody prunes is an allowlist with a good story.
    kept: list[str] = field(default_factory=list)
    #: Promises no document cites any more -- the usual cause is a rename, which
    #: fails loudly as a new dead claim while the old entry silently protects
    #: nothing. A failure, because the entry is now junk in a list a reader has
    #: to trust.
    uncovered: list[str] = field(default_factory=list)
    #: Promises whose deferral has lapsed. The only signal for work that was
    #: canceled or never started: the document still cites the path, so coverage
    #: cannot tell, and nothing else ever goes red.
    overdue: list[str] = field(default_factory=list)

    @property
    def failed(self) -> bool:
        return bool(self.broken or self.blocked or self.kept
                    or self.uncovered or self.overdue)

    def text(self) -> str:
        out = [f"  {claim}" for claim in self.broken]
        for kind in self.blocked:
            out.append(f"  BLOCKED: {kind}")
        for promise in self.kept:
            out.append(
                f"  KEPT: {promise} exists now -- remove the promise"
            )
        for promise in self.uncovered:
            out.append(
                f"  UNCITED: {promise} is promised, and no document names it -- "
                "renamed, or the entry outlived its claim"
            )
        for promise in self.overdue:
            out.append(
                f"  LAPSED: {promise} -- decide again: extend the date, or drop "
                "the promise and let what it covered come back"
            )
        for kind in self.unavailable:
            out.append(f"  NOT CHECKED: {kind}")
        return "\n".join(out)


# -- the network, asked once and in one place --------------------------------


def _ask(url: str, method: str, timeout: float) -> tuple[bool | None, int | None]:
    """One request. The verdict, and the status code that produced it."""
    request = urllib.request.Request(
        url, method=method, headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return (200 <= response.status < 400), response.status
    except urllib.error.HTTPError as exc:
        return (False if exc.code in DEAD_STATUS else None), exc.code
    except (urllib.error.URLError, OSError, ValueError):
        return None, None


def _reach(url: str, timeout: float = EXTERNAL_TIMEOUT) -> bool | None:
    """Is this address still there? ``None`` when that is not knowable.

    **Three outcomes, because two would be a lie.** A 404 or 410 is the site
    saying the page is gone. A success is a success. Everything else -- a
    timeout, a 5xx, and above all the 401, 403 or 429 a bot-hostile site returns
    to an unfamiliar client -- cannot tell a deleted page from a refused reader.
    Calling those dead would fill a gate with findings nobody can act on, and
    the reader would learn to skim it.

    ``HEAD`` first because a link check has no use for the body, then ``GET``
    when the server refuses the *method* rather than the resource.
    """
    verdict, status = _ask(url, "HEAD", timeout)
    if status in HEAD_REFUSED:
        verdict, _ = _ask(url, "GET", timeout)
    return verdict


def _reach_all(
    urls: Iterable[str], timeout: float, workers: int = 8
) -> dict[str, bool | None]:
    """Every distinct address, asked once. Order of the answers is irrelevant."""
    unique = sorted(set(urls))
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(unique))) as pool:
        verdicts = pool.map(lambda url: _reach(url, timeout), unique)
        return dict(zip(unique, verdicts, strict=True))


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
        if WINDOWS_SEPARATOR in token:
            continue
        if ATTRIBUTE_REFERENCE.match(token) and not token.endswith(
            ATTRIBUTE_EXEMPT_SUFFIXES
        ):
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


def _url_claims(line: str, previous: str = "") -> Iterator[str]:
    """Web addresses, wherever a document put them.

    Deliberately not restricted to markdown link targets. The dead
    OpenFastTrace link that motivated this kind was a bare URL in a list, and a
    checker that only reads ``[text](target)`` would have walked past it -- which
    is what happened for the whole life of the project.
    """
    seen: dict[str, None] = {}
    for match in _URL.finditer(line):
        # Trailing sentence punctuation belongs to the prose, not the address.
        seen.setdefault(match.group(0).rstrip(".,;:!?"), None)
    yield from seen


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


def _resolve_url(text: str, tree: Tree, document: Path) -> bool:
    """A URL is false only when something said so.

    Not asked, or asked and unanswerable, both resolve. A link check that
    reported every timeout as a dead link would be red on a bad network day,
    and a gate that is red for reasons the reader cannot fix is a gate the
    reader learns to skip.
    """
    if tree.reachable is None:
        return True
    return tree.reachable.get(text) is not False


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
    #: This kind cannot be settled without leaving the machine. Opt-in, and off
    #: by default: a documentation checker that reaches the network unasked is a
    #: surprise, and in an air-gapped CI it fails with nothing wrong.
    needs_network: bool = False
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
    # A URL is a claim about the world rather than about the tree, and it was
    # the one claim in these documents nothing could falsify: `_link_claims`
    # skips any target carrying a scheme, so a dead OpenFastTrace link sat in
    # `CONVENTIONS.md` until a reader noticed it. Off unless asked.
    ClaimKind("url", _url_claims, _resolve_url, needs_network=True),
)


@dataclass(frozen=True)
class Promise:
    """Something deferred, and the date the deferral lapses.

    **Two kinds, one shape.** A promise names either a ``path`` the project
    intends to produce, or -- with ``what`` -- anything else it has decided not
    to settle yet: a question left open, a threshold not yet measured, a finding
    reviewed and set aside. The second kind exists because every deferral in a
    real project is this shape, and a tool that dates only the ones it can see
    for itself leaves the rest as good intentions in prose.

    **``until`` is required, and there is no value meaning "never".** A deferral
    that cannot lapse is an ignore list with a better name: if the work is
    canceled or simply never starts, nothing is ever red again.

    ``until`` is **not a delivery date** and nothing here treats it as one. It
    is the date this deferral stops holding by itself, after which somebody
    decides again -- extend it, which is a visible edit somebody makes, or drop
    it and let the thing it was covering come back. The point is the decision
    recurring, not the estimate being right.

    A ``path`` promise has three ways to end, because the tree can answer for
    it: the path exists, nothing cites it any more, or the date passed. A
    ``what`` promise has only the date, because nothing else can tell.
    """

    until: date
    path: str | None = None
    what: str | None = None
    #: Why this was deferred, in the words of whoever deferred it. Free text,
    #: like the field `[[gate]]` carries: a declaration a later reader cannot
    #: account for is one they will not touch, so it outlives its reason.
    note: str = ""
    #: Who deferred it. **Required whenever there is a note**, because an
    #: unsigned note is a reason with nobody behind it -- and the reader who
    #: has to decide whether a deferral still holds needs to know whose call it
    #: was. A deferral is somebody's decision or it is drift.
    by: str = ""

    def __post_init__(self) -> None:
        if bool(self.path) == bool(self.what):
            raise ValueError(
                "a promise names a `path` or a `what`, not both and not neither"
            )
        if self.note and not self.by:
            raise ValueError(
                f"the note on {self.label!r} is unsigned: give `by` as well, "
                "so a later reader knows whose decision this was"
            )

    @property
    def label(self) -> str:
        return self.path or self.what or ""

    def described(self) -> str:
        if not self.note:
            return f"{self.label} ({self.by})" if self.by else self.label
        return f"{self.label} -- {self.note} ({self.by})"


#: Kinds a project may declare as promised. A file can be intended and absent;
#: a commit cannot -- a hash that does not exist yet cannot be cited honestly,
#: so allowing it would only buy a way to defer a wrong citation.
PROMISABLE = frozenset({"path", "link"})


def _normalize(text: str) -> str:
    """One spelling of a claim, so a promise and a claim compare as written.

    Mirrors what resolution already strips: the trailing punctuation prose
    leaves on a path, and the ``:line`` suffix a citation carries.
    """
    return text.split(":", 1)[0].strip().rstrip("/.,;:")


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
    # Shares ``_tree`` with the scans, and for the same reason: this index was
    # built on ``rglob``, which does not enter a symlinked directory, so a
    # document citing a path reached that way was reported as a dead claim.
    for here, filenames, _ in _tree(root):
        if here != root:
            rel = here.relative_to(root).as_posix()
            if not _excluded(rel, exclusions):
                directories.add(rel)
        for name in filenames:
            rel = (here / name).relative_to(root).as_posix()
            if not _excluded(rel, exclusions):
                files.add(rel)
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
    promised: Iterable[Promise] = (),
    today: date | None = None,
    external: bool = False,
    timeout: float = EXTERNAL_TIMEOUT,
) -> Verification:
    """Falsify every claim the prose makes about this tree.

    :param historical: path fragments holding superseded records. An archive
        cites paths and commits that were real when written; checking it for
        currency reports the archive for being an archive.
    :param promised: paths a design says it will produce, spelled as the
        document spells them. **A design document cannot be gated without
        this.** Every path it names is a claim, and the ones describing the
        work itself are false until the work lands, so the gate runs red
        permanently -- which teaches its reader to skim a red gate -- or the
        project fabricates a stub that satisfies the check by letter. Measured
        on a real design set: 6 of 52 claims, all of that class.

        Declared rather than inferred from the prose. A future-tense heuristic
        over English was the obvious alternative and is the same shape as this
        module's negation heuristic, which silently skipped whole lines
        carrying a real claim -- and a suppression that reads clean is the
        failure this package exists to catch. A declared list is a decision
        somebody made, in a file a reviewer can read, countable on every run.

        Matched by exact spelling for the same reason: a promise of
        ``docs/plan.md`` that also silenced every other ``plan.md`` in the tree
        would suppress claims nobody chose to defer. Two spellings mean two
        entries.
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
    # A path promise is keyed by its normalized spelling so a claim can match
    # it; a `what` promise has nothing to match and only the date can end it.
    promises: list[tuple[str, Promise]] = []
    open_questions: list[Promise] = []
    for promise in promised:
        if promise.what:
            open_questions.append(promise)
            continue
        key = _normalize(promise.path or "")
        if key and key not in {seen for seen, _ in promises}:
            promises.append((key, promise))
    promised_paths = {key for key, _ in promises}

    covered: set[str] = set()

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

    cited = {text for kind, text, _ in pending if kind.needs_network}
    if external:
        tree.reachable = _reach_all(cited, timeout)
        # Named one at a time rather than counted. An unanswerable address is
        # the one case where a reader may want to open it themselves, and a
        # bare number gives them nothing to open.
        found.unavailable.extend(
            f"{url} (asked, no usable answer)"
            for url, verdict in sorted(tree.reachable.items())
            if verdict is None
        )
    elif cited:
        # Counted, because silence here reads as "these documents cite nothing
        # external" -- which is the shape of inert signal this module exists to
        # refuse. Off is a decision; off and invisible is a blind spot.
        found.unavailable.append(
            f"{len(cited)} external link(s) (network checks not enabled; "
            "set external = true under [claims])"
        )

    for kind, text, claim in pending:
        found.checked += 1
        if kind.resolve(text, tree, root / claim.path):
            continue
        if kind.name in PROMISABLE and _normalize(text) in promised_paths:
            found.deferred.append(claim)
            covered.add(_normalize(text))
            continue
        found.broken.append(claim)

    # Three ways a promise stops being true, and only the first was checked when
    # this shipped: the work landed, nothing cites it any more, or the date the
    # project set has passed. The second and third are the silent ones.
    when = today or date.today()
    for key, promise in promises:
        if tree.resolves(promise.path or ""):
            found.kept.append(promise.described())
        elif key not in covered:
            found.uncovered.append(promise.described())
        elif promise.until < when:
            found.overdue.append(
                f"{promise.described()} (deferred until {promise.until.isoformat()})"
            )

    # An open question has no tree to answer for it. The date is the whole
    # mechanism, which is why `until` is required on every promise rather than
    # only on the ones nothing else can check.
    for promise in open_questions:
        if promise.until < when:
            found.overdue.append(
                f"{promise.described()} (deferred until {promise.until.isoformat()})"
            )

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
