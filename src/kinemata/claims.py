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

**And, like every other gate here, it ratchets.** A documentation gate that only
works on a clean documentation tree is a gate almost nobody can turn on -- the
argument :mod:`kinemata.baseline` already makes about code, unchanged when the
subject is prose. It is not hypothetical in this repository: ``[claims]
suffixes`` cannot include ``.py`` here because arming it leaves **10 unresolved
claims**, every one a genuine citation of outside evidence -- three paths into
other projects and seven commit hashes in corpus repositories that are
gitignored here and absent from a clean clone. Nobody can make those resolve and
no marker would be honest about them, so without a ratchet the only two states
available were "check the docstrings and be permanently red" and "do not check
the docstrings".

:meth:`Verification.findings` is what closes that: broken claims leave here as
:class:`kinemata.bypass.Bypass` records, which is what the ratchet already knows
how to fingerprint. The reason is :mod:`kinemata.provenance`'s and is quoted
rather than re-argued -- a second finding type would mean a second ratchet, and
two ratchets eventually disagree about what a project has accepted.
"""

from __future__ import annotations

import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath

from . import stamps
from .bypass import GIT_DIR, Bypass, _tree, _walk, git_ignored
from .prose import DOCUMENTATION_FILTERS, ILLUSTRATION, ILLUSTRATION_FILTERS

#: The name these findings travel under, so a baseline record says which check
#: accepted it. Not a registry -- prose is not declared data -- but the ratchet
#: tags every finding with the thing that produced it, and inventing a second
#: tagging scheme for one check is how two spellings of one idea start. Same
#: argument, same shape, as :data:`kinemata.provenance.PROVENANCE_REGISTRY`.
CLAIMS_REGISTRY = "claims"

#: How a broken claim names itself in a baseline record. Prefixed, so a reader
#: scanning the file can tell an accepted dead reference from an accepted
#: duplication at a glance -- the two are driven down by different people doing
#: different work.
#:
#: Deliberately **not** spelled ``FINDING_PREFIX``, which is what the same
#: constant is called in ``provenance``: that module imports from this one, and
#: two identically named constants across an import edge is the one-letter
#: neighbor problem with more letters.
CLAIM_PREFIX = "claim:"

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
#:
#: ``neither``, ``dead`` and ``former`` were added 2026-09-09 from an adopting
#: project's run: each produced a finding on prose that says, in plain English,
#: that the path is not there. Their case was a sentence reporting that a cited
#: test file and its test name both stopped existing -- the document was right
#: and this reported it anyway. ``formerly`` was already here and the bare
#: adjective was not, which is the shape a hand-written word list fails in.
NEGATION = re.compile(
    r"\b(no|not|never|neither|nor|without|absent|missing|removed|deleted|"
    r"dropped|gone|dead|"
    r"initially|formerly|former|previously|was|were|had|used to|instead of|"
    r"rather than|"
    # The vocabulary of describing a change. A changelog naming what a file
    # used to be called is a record, not a claim that the old name still works.
    r"stale|renamed|retired|superseded|replaced|corrected|obsolete|old)\b",
    re.I,
)

#: Names that mark an example rather than a file in this tree. ``src/pkg/x.py``
#: in a docstring is teaching a shape, not asserting a path.
#:
#: Two shapes joined it 2026-09-09, both from an adopter's findings. A stem that
#: is literally the word *file* is the most generic stand-in a document can
#: write, and a run of three or more n's is how a document spells "any number
#: goes here" -- a requirement identifier written as R-n-n-n names a form, not a
#: document. Neither has a word boundary to hang the list on, so they are
#: alternatives rather than entries in it.
PLACEHOLDER = re.compile(
    r"\b(pkg|foo|bar|baz|qux|example|examples?/your|OWNER|REPO|YOUR|myproj|"
    r"nosuch|placeholder|somewhere|your[-_]?\w*)\b"
    r"|(?:^|/)file\.[a-z0-9]+$"
    r"|n{3,}",
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
#: capitalized document name -- :shown:`Introduction.md`, :shown:`Changelog.md`
#: -- which is a spelling projects use, while an attribute called ``md`` is one
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
#:
#: **A closed list of fourteen is wrong for most repositories**, and silently:
#: an adopter's run on 2026-09-09 came back four claims of twenty-seven and
#: looked nearly green on a repository whose only two content files are a
#: container definition and a terminal multiplexer configuration -- cited five
#: times in backticks, and invisible here because one carries a dotted project
#: name for a suffix and the other ends in .conf. The scan was structurally
#: unable to see what that repository is about.
#:
#: So a project may **extend** this through ``[claims] file_suffixes``. Extend
#: rather than replace: the default set is not a preference this project holds,
#: it is the floor below which the check reports nothing, and a knob that
#: replaced it would let one added suffix silently turn off the other fourteen.
FILE_SUFFIXES = frozenset({
    ".py", ".md", ".toml", ".yaml", ".yml", ".cfg", ".json", ".txt", ".sh",
    ".ini", ".rst", ".lock", ".in", ".mk",
})

#: An inline code span, with the run of backticks that opens it matched by an
#: equal run closing it -- the same rule :data:`kinemata.prose.CODE_SPAN`
#: applies, for the same reason.
#:
#: A single-backtick pattern read a reStructuredText inline literal by accident.
#: Doubled backticks are the normal spelling for one, and the *inner* pair of a
#: doubled delimiter is itself a markdown span, so the path between them fell
#: out. That worked, and this project does not keep behavior that works by
#: coincidence: it holds only while nobody writes a run of three, and the
#: argument made everywhere else here is that precision belongs to declared
#: syntax rather than to what a regex happens to do.
#:
#: The token is group 2; group 1 is the delimiter.
_BACKTICKED = re.compile(r"(`+)([^`\s]+)\1")
#: The bracket text is captured as well as the target, so that
#: :func:`_link_claims` can tell a link from something that merely precedes a
#: parenthesis. It is group 1; the target is group 2.
_LINK = re.compile(r"\[([^\]]*)\]\(([^)#\s]+)[^)]*\)")
#: A short hash in an inline code span. Delimiter run matched deliberately, for
#: the reason :data:`_BACKTICKED` gives: this project's own docstrings spell a
#: cited commit as a doubled literal.
_SHA = re.compile(r"(`+)([0-9a-f]{7,12})\1")
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


class ClaimsError(Exception):
    """A claims declaration that cannot be honored.

    The same refusal ``config`` raises for a registry pointed at a file that is
    not there, raised from here because only the caller of :func:`verify` knows
    the root a relative declaration is measured from: the scanned tree is not
    always the config's own root, so validating at load time would settle the
    wrong path.
    """


@dataclass(frozen=True)
class Claim:
    """One falsifiable assertion a document makes about the tree."""

    kind: str
    text: str
    path: str
    line: int
    #: The whole line the claim was read from, which is what a baseline record
    #: fingerprints. Carried rather than re-read: the line a reader would edit
    #: is the reduced one -- fences and illustrations already blanked -- and
    #: fingerprinting the raw file would key a record on text this check does
    #: not look at.
    source: str = ""

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.kind} does not resolve: {self.text}"

    @property
    def entry_id(self) -> str:
        return f"{CLAIM_PREFIX}{self.kind}"

    def finding(self) -> Bypass:
        """This claim as the ratchet already knows how to record one.

        **The kind is the entry and the cited target is the antipattern.** A
        bypass names a declared entry and the spelling that went around it; a
        claim names a sort of assertion and the target that did not resolve, and
        those are the same two questions -- *what kind of thing is this* and
        *which one*. ``provenance`` mapped them the same way and a third mapping
        for a third finding type would make the baseline file unreadable by
        pattern.

        The line number rides along for the report and is absent from the
        fingerprint; :meth:`kinemata.baseline.Accepted.key` is where that is
        argued. What is in the fingerprint is the line's *text*, so a record
        survives an edit above it and does not survive the sentence itself being
        rewritten -- the same boundary every other finding here is held to.

        **A counted claim's antipattern carries the true value as well as the
        claimed one**, because that is what ``_verify_counts`` puts in the
        claim's text, and the consequence is deliberate rather than tolerated:
        accepting :shown:`**590 tests** (actually 597)` accepts a stated
        disagreement, so when the oracle starts saying 600 the record goes stale
        and the claim comes back as new. The alternative is a record that keeps
        a wrong number quiet through every later change to the thing it is wrong
        about, which is an exemption that outlives what somebody looked at.
        """
        return Bypass(
            entry_id=self.entry_id,
            antipattern=self.text,
            path=self.path,
            line=self.line,
            # Falls back to the claim itself for a claim with no line behind it.
            # `_verify_counts` had none until it was given one, and a fingerprint
            # keyed on the empty string would have made every count claim in a
            # file collide into one record.
            text=self.source or self.text,
        )


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

        **Known cost, held deliberately: a path that exists only in an ignored
        copy still resolves.** The filesystem is asked before the index, and the
        index is the only half that drops what git ignores. So a build tree, a
        vendored copy or any other ignored duplicate keeps a path alive here
        after the real one is deleted -- reported by an adopting project on
        2026-09-09, where a stale packaging copy would have concealed a defect
        they had already found by hand.

        It is held because the two cases are one case from here. The behavior
        was put in for a gitignored corpus directory sitting in the tree,
        several megabytes of it, which notes describe truthfully; suppressing
        that reported honest prose as dead. Ignored-and-present is the whole
        signal available, and it says "deliberately kept out of version control"
        for the corpus and "left over from a build" for the copy with equal
        confidence. Separating them needs something this does not have -- a
        notion of which ignored trees shadow tracked ones -- and guessing would
        trade a quiet miss for a loud false report on prose that is correct.
        """
        target = claim.strip().rstrip("/.,;:")
        # `./name` anchors to the document's own directory. Stripping it lets
        # the fallbacks below answer: httpie's packaging README names
        # `./get_release_artifacts.sh` [0TMVXHC-Pa0005], the file sits beside
        # it, and this reported it dead because the prefix survived into every
        # lookup.
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
    #: Claims a bibliography says are about **another project's tree**: the
    #: citation stands beside a reference key whose entry names a foreign
    #: source. Reported on every run, never a failure -- the same bargain a
    #: promise strikes, and for the same reason. The alternative shapes were
    #: both worse: leaving them broken makes the gate permanently red over
    #: honest citations, and dropping the readable target so no claim is
    #: extracted hides the evidence in a second file, against section 5.6.
    #:
    #: Counted in the report, the way a promise and an illustration are, and
    #: for the same reason: a suppression nobody can see the size of is an
    #: allowlist with a good story. The sites are not repeated there because
    #: this is the one suppression that already has a resolver -- the key is
    #: declared, so ``kinemata cite --where`` lists every place it is cited
    #: and ``unused`` names an entry nothing cites any more.
    foreign: list[Claim] = field(default_factory=list)
    #: Claims that did not fail and were not confirmed either: the oracle was
    #: off, absent, or unable to answer. **Never a failure** -- that is
    #: :attr:`ClaimKind.settled`'s whole argument, and gating on weather is what
    #: the three-way reading exists to avoid.
    #:
    #: ``unavailable`` already names the *oracle* that could not answer; this
    #: names the **claims** that went unconfirmed because of it, which is the
    #: half a reader cannot reconstruct from the other: one unreachable address
    #: cited from four documents is one line there and four sites here.
    #:
    #: Read by :mod:`kinemata.confirm`, which needs the opposite reading: a
    #: document with an unsettled claim in it is one this run cannot date.
    unsettled: list[Claim] = field(default_factory=list)
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
    #: Declared configuration that ran and settled nothing. **Not a failure**,
    #: and deliberately: a suffix that legitimately matches no file is a normal
    #: state, so gating on it would make the check red for a reason its reader
    #: cannot always fix. Kept here as well as printed so a caller can assert on
    #: it, and left out of :meth:`text` on purpose -- these already went to
    #: stderr, and repeating them on stdout prints each one twice.
    warnings: list[str] = field(default_factory=list)
    #: Spans a document marked as shown rather than asserted. **Never a
    #: failure, and counted rather than listed.** Nothing reports fenced spans,
    #: for the reason :func:`kinemata.prose.outside_fenced_blocks` gives: a
    #: fence is incidental markup, so a list of them is correct by construction
    #: and the reader's action is none. The illustration role is the opposite --
    #: a deliberate declaration that a span is not a claim, the same shape as a
    #: promise -- and a suppression nobody can count is an allowlist with a good
    #: story. The number is the reading; the sites are not.
    shown: int = 0

    @property
    def declarations_failed(self) -> bool:
        """Failures the ratchet must never absorb, because they have no site.

        A broken claim is a thing at a path on a line, which is what a baseline
        record fingerprints. These four are about the *declarations* -- an
        oracle that would not run, a promise the tree has kept, a promise
        nothing cites any more, a promise past its date -- and none of them has
        a site to key a record on.

        That is the mechanical reason. The deciding one is that accepting an
        overdue promise would build the one thing a ratchet must not have: a
        deferral that never lapses. ``Promise`` refuses a value meaning "never"
        and ``Baseline`` refuses a list with no date, and a route by which one
        could be baselined into silence would undo both of them at once.
        """
        return bool(self.blocked or self.kept or self.uncovered or self.overdue)

    @property
    def failed(self) -> bool:
        """Every failure, before any baseline is consulted.

        The unratcheted truth, and it stays that way: a caller that wants the
        gate's answer asks the baseline, and a caller that wants to know what is
        actually wrong with the tree asks this. ``review`` and ``check`` draw
        the same line for the same reason -- an advisory scan that hid known
        problems would be lying about the tree.
        """
        return bool(self.broken) or self.declarations_failed

    def findings(self) -> list[tuple[str, Bypass]]:
        """Broken claims, tagged the way the ratchet expects them.

        Only the broken ones: see :attr:`declarations_failed` for what is
        deliberately not here.
        """
        return [(CLAIMS_REGISTRY, claim.finding()) for claim in self.broken]

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


def _warn(found: Verification, message: str) -> None:
    """Say it once, on stderr, and keep it on the result.

    Not an exception and not a finding. Some declarations can do nothing for a
    legitimate reason, and the useful answer to those is a sentence in front of
    a reader rather than a red gate -- but the useless answer, and the one this
    package exists to refuse, is the byte-identical output an adopter got on
    2026-09-09 from a knob that matched nothing at all.
    """
    found.warnings.append(message)
    print(f"warning: {message}", file=sys.stderr)


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


def _path_claims(
    line: str, previous: str = "", file_suffixes: frozenset[str] = FILE_SUFFIXES
) -> Iterator[str]:
    for match in _BACKTICKED.finditer(line):
        token = match.group(2)
        if SCHEME in token or token.startswith(EXTERNAL_PREFIXES):
            continue
        if WINDOWS_SEPARATOR in token:
            continue
        # The last clause: a suffix the *project* declared is one it has already
        # said names a file, so the collision this rule guards against cannot
        # arise. Without it a container definition carrying a dotted project
        # name reads as an attribute of a class, and declaring its extension
        # bought nothing -- which is how an adopter's two content files stayed
        # invisible after the knob for them was added.
        if (
            ATTRIBUTE_REFERENCE.match(token)
            and not token.endswith(ATTRIBUTE_EXEMPT_SUFFIXES)
            and PurePosixPath(token).suffix in FILE_SUFFIXES
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
        if not token.endswith("/") and PurePosixPath(token).suffix not in file_suffixes:
            continue
        if PLACEHOLDER.search(token) or EXAMPLE_STEM.search(token):
            continue
        if _negated(line, match.start(), match.end(), previous):
            continue  # discussed, not asserted
        yield token


def _link_claims(
    line: str, previous: str = "", file_suffixes: frozenset[str] = FILE_SUFFIXES
) -> Iterator[str]:
    """Link targets, minus the one thing that is never link text.

    A citation stamp is a bracket group, so ``[0TMQDKB-Ty](see below)`` read as
    a link and reported ``see`` as a dead path. A space between the two
    prevented it, and relying on that was rejected: whitespace is invisible,
    survives editing poorly, and a rule that holds only while nobody deletes a
    character is not a rule. The extractor is taught the stamp's shape instead,
    so the behavior no longer depends on what follows -- which is this project's
    argument everywhere else, that precision belongs to declared syntax rather
    than to incidental formatting.
    """
    for match in _LINK.finditer(line):
        if stamps.CONTENT.fullmatch(match.group(1)):
            continue
        target = match.group(2)
        if SCHEME in target or target.startswith(LINK_PREFIXES):
            continue
        yield target


def _commit_claims(
    line: str, previous: str = "", file_suffixes: frozenset[str] = FILE_SUFFIXES
) -> Iterator[str]:
    for match in _SHA.finditer(line):
        sha = match.group(2)
        # Hex is a superset of decimal, so every seven-to-twelve digit number a
        # document quotes matched this. An adopter's byte count of eleven digits
        # was reported as a dead commit on 2026-09-09; git does not mint
        # all-decimal short hashes often enough for the catch to be worth the
        # class of finding it produces, and a number in prose is the commonest
        # backticked token there is.
        if sha.isdigit():
            continue
        yield sha


def _url_claims(
    line: str, previous: str = "", file_suffixes: frozenset[str] = FILE_SUFFIXES
) -> Iterator[str]:
    """Web addresses, wherever a document put them.

    Deliberately not restricted to markdown link targets. The dead
    OpenFastTrace link that motivated this kind was a bare URL in a list, and a
    checker that only reads :shown:`[text](target)` would have walked past it,
    which is what happened for the whole life of the project.

    **A token with no authority is not an address.** Prose that elides a URL --
    scheme, separator, then an ellipsis -- lost its dots to the punctuation
    strip below and became a bare scheme, which then got a real network request
    and a place in the report. Filtered on the empty authority rather than on
    the ellipsis: the ellipsis was how it was found, but anything the strip can
    reduce to a scheme has the same defect, and matching the symptom would leave
    the next spelling of it to be found the same way.
    """
    seen: dict[str, None] = {}
    for match in _URL.finditer(line):
        # Trailing sentence punctuation belongs to the prose, not the address.
        address = match.group(0).rstrip(".,;:!?")
        if not urllib.parse.urlsplit(address).netloc:
            continue
        seen.setdefault(address, None)
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


def _settled_commit(text: str, tree: Tree, document: Path) -> bool:
    """Did the history answer, or is there no history here to ask?"""
    return tree.commits is not None


def _settled_url(text: str, tree: Tree, document: Path) -> bool:
    """Did the address answer at all?

    False when the network check is off and false when the request came back
    unreadable -- a timeout, a 5xx, the 403 a bot-hostile host returns. Both are
    passes for the gate and neither is a confirmation.
    """
    return tree.reachable is not None and tree.reachable.get(text) is not None


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
    """A value the documentation states, and the command that settles it.

    The only claim kind whose oracle is outside the tree, and the only one that
    is **opt-in**: settling it means running a command from a config file. That
    is a real trust decision -- a repository whose config can run commands is a
    repository you are already trusting -- so nothing runs unless a project
    declares it, and a project that declares none never spawns a process.

    Worth the cost because the failure is common and invisible: this project's
    notes claimed 74 tests through three separate sessions in which the true
    number went 76, 88, 103.

    **A number is the special case; a value is the general one.** Everything
    else here is negative in polarity: a registry says a declared value must not
    be re-spelled outside its home, so a second spelling is a finding and
    agreement is silence. An adopting project inventoried 326 conformance checks
    against this tool on 2026-09-09 and could not express 291 of them, and the
    largest single structural reason was that polarity -- **125 test functions**
    across four manifest-parity suites assert the opposite shape, *this
    documented row equals what the code produces*. Under a negative mechanism
    that shape comes out inverted: agreement produces the finding and
    disagreement produces silence.

    This tree carries the same inversion. The projection budget is declared once
    in ``contract.py`` and three documents restate the number; raising the
    constant leaves every gate green while all three documents go stale, because
    until this settled values there was nothing that compared a documented value
    against the one the code holds.

    **The comparison is exact, and nothing is normalized.** A document saying
    "16 KB" is not settled by an oracle that emits the byte count, and that is a
    **known and accepted limit, not an oversight**: a project that wants both
    spellings checked declares two entries, each with its own ``pattern`` and
    its own ``extract``. No unit conversion, no numeric coercion between unlike
    spellings, no rounding, no fuzzy match -- because a normalization that is
    wrong does not fail, it *passes*, and a check that passes wrongly is the
    exact failure this package exists to prevent.

    **Edge whitespace is stripped from both sides, and nothing else is.** What
    sits at the ends of a capture belongs to the regex that captured it -- the
    newline a command's output ends in, a loosely written ``\\s*`` -- and is not
    something either the document or the oracle asserts; letting it decide the
    comparison would be silent wrongness of its own, in a check whose whole
    argument is against that. Interior spacing and surrounding punctuation are
    kept verbatim: ``a b`` and ``a  b`` are different spellings, and what falls
    inside the capture group is the declaration's decision rather than this
    comparison's.

    **There is one oracle form, the subprocess.** Reading the value out of the
    source with ``ast`` was considered and dropped: the constant that motivated
    this is an arithmetic expression rather than a literal, so
    ``ast.literal_eval`` cannot read the very value at issue.
    """

    #: The first matching group is the claimed value.
    pattern: str
    command: tuple[str, ...]
    #: Group 1 is the true value, read from the command's output.
    extract: str
    label: str = "count"
    #: Where to run, relative to the scanned root. Documents and the thing they
    #: describe are not always in one tree: process notes may live beside a
    #: repository rather than inside it, and the oracle belongs with the code.
    directory: str = "."


def counted_claims(text: str, spec: Counted) -> Iterator[tuple[str, str]]:
    """The values a line states, however the pattern chose to capture them.

    The first *matching* group, not group 1. A claim like this is naturally
    written as alternation -- :shown:`**103 tests**` or :shown:`103 tests pass`
    -- and every branch but the one that matched captures ``None``. Reading
    group 1 blindly crashes on the second phrasing, which is how this was
    found; this project's own test-count pattern now carries four branches.
    """
    for match in re.finditer(spec.pattern, text):
        value = next((group for group in match.groups() if group), None)
        if value is None:
            continue
        yield value.strip(), match.group(0)


#: Stands for the interpreter kinemata is running under. A config file cannot
#: name it -- ``python`` on PATH is whatever the system installed, which is not
#: where the project's dev dependencies live, and a command that cannot run
#: reports nothing while looking configured.
INTERPRETER = "{python}"


def actual_count(spec: Counted, root: Path) -> str | None:
    """Run the oracle. ``None`` when it cannot be reached -- never a pass.

    The value comes back as the text the oracle printed, stripped at the edges
    only; see :class:`Counted` for why nothing further is done to it.
    """
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
    return found.group(1).strip() if found else None


@dataclass(frozen=True)
class ClaimKind:
    """One sort of falsifiable assertion, and how to settle it."""

    name: str
    extract: Callable[..., Iterator[str]]
    resolve: Callable[[str, Tree, Path], bool]
    #: Kinds that report the tree's *current* state are wrong to run over
    #: superseded records: an archive cites what was true when it was written.
    #: A kind whose oracle is **outside** the tree does not get this: there is
    #: no "was true then" for it to appeal to, and switching it off inside an
    #: archive removes real findings rather than false ones.
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
    #: Did the oracle actually answer *yes*, or did it merely fail to say no?
    #: Absent for a kind whose oracle always answers -- a path is in the index
    #: or it is not.
    #:
    #: **The gate deliberately conflates the two and this is where the two come
    #: apart.** ``resolve`` treats a claim as false only when something said so,
    #: because a check that went red on a timeout would teach its reader to skim
    #: a red gate. That reading is right for gating and wrong for *writing*: a
    #: run that could not reach an address has not confirmed it, and
    #: :mod:`kinemata.confirm` must not date a document on the strength of a
    #: question nobody answered. One extra function per kind, rather than a
    #: second resolver that would eventually disagree with the first.
    settled: Callable[[str, Tree, Path], bool] | None = None


#: Adding a kind is a row here. The verification loop never learns their names.
CLAIM_KINDS: tuple[ClaimKind, ...] = (
    ClaimKind("path", _path_claims, _resolve_path),
    ClaimKind("link", _link_claims, _resolve_link),
    ClaimKind(
        "commit", _commit_claims, _resolve_commit,
        needs_git=True,
        when_unavailable="commit hashes (not a git repository)",
        settled=_settled_commit,
    ),
    # A URL is a claim about the world rather than about the tree, and it was
    # the one claim in these documents nothing could falsify: `_link_claims`
    # skips any target carrying a scheme, so a dead OpenFastTrace link sat in
    # `CONVENTIONS.md` until a reader noticed it. Off unless asked.
    #
    # And **not** current_only, which it was until 2026-09-09. That flag exempts
    # a record from being judged against the tree's present state, because an
    # archive cites what was true when it was written. A URL is not about the
    # tree, so there is nothing for the record to have been right about at the
    # time: a dead link in a changelog is a dead link, and the reader following
    # it gets the same nothing either way. Measured on an adopting project,
    # whose two historical fragments took 17 of its 36 URLs out of the check --
    # including both of the genuine 404s it had.
    ClaimKind("url", _url_claims, _resolve_url, current_only=False,
              needs_network=True, settled=_settled_url),
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


def _as_documentation(source: str, suffix: str) -> tuple[str, int]:
    """The part of a file that is prose, minus what that prose only shows.

    Both reductions in one place because they compose in one order and every
    reader of a declared document wants both. ``_verify_counts`` read the file
    raw, which was harmless here only by luck: a ``[[count]]`` pattern is a
    regex the *project* writes, and one that matches a number in a sentence will
    match the same number in a default value.

    Returns the reduced text and how many illustrations were blanked. The second
    caller drops the count deliberately -- both walks read the same files, so
    counting in each would report every illustration twice.
    """
    document = DOCUMENTATION_FILTERS.get(suffix)
    if document is not None:
        source = document(source)
    shown = ILLUSTRATION_FILTERS.get(suffix)
    if shown is None:
        return source, 0
    # Counted before blanking, from the same pattern that does the blanking:
    # afterwards there is nothing left to count.
    return shown(source), len(ILLUSTRATION.findall(source))


def _report_inert_suffixes(
    read: dict[str, int], yielded: dict[str, int], root: Path, found: Verification
) -> None:
    """Say which declared document suffix settled nothing, and which kind of nothing.

    ``[claims] suffixes`` reads as "scan these documents", and every extractor
    behind it is bound to markdown syntax: a backticked token, a bracket and
    parenthesis link, a backticked hex run. A format sharing none of it is read
    and contributes nothing. An adopter added a YAML suffix on 2026-09-09 and
    got byte-identical output: no extra claims, no note, and a green run that
    meant less than the one before it.

    reStructuredText is the near miss rather than the miss, and it is the one
    that matters here because Python docstrings are written in it: its inline
    literal is a doubled delimiter, whose inner pair *is* a markdown span, so
    the token inside was extracted by accident. The delimiter run is matched
    deliberately now -- see :data:`_BACKTICKED` -- and ``.py`` is reduced to its
    docstrings and comments before any extractor sees it.

    A warning rather than a failure, because a suffix matching no files is a
    thing a shared config legitimately does. The two messages are kept apart
    because the fixes are: nothing matched is usually a typo or a tree without
    those documents, while files matched and yielded nothing is the trap -- the
    documents were read and this could not see anything in them.
    """
    for suffix, count in read.items():
        if not count:
            _warn(
                found,
                f"claim suffix {suffix} matched no files under {root}. Nothing "
                "was read for it, so it settles nothing.",
            )
        elif not yielded[suffix]:
            _warn(
                found,
                f"claim suffix {suffix} matched {count} file(s) and yielded no "
                "claims. Every extractor here reads markdown syntax -- a "
                "backticked token, a bracket-and-parenthesis link -- so a "
                "document in another format is read and contributes nothing.",
            )


def verify(
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".md",),
    exclude: Iterable[str] = (),
    historical: Iterable[str] = (),
    kinds: Sequence[ClaimKind] = CLAIM_KINDS,
    counts: Sequence[Counted] = (),
    file_suffixes: Iterable[str] = (),
    resolve_in: Iterable[str] = (),
    commits_in: Iterable[str] = (),
    foreign: Callable[[Claim], bool] | None = None,
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
        :shown:`docs/plan.md` that also silenced every other :shown:`plan.md` in
        the tree would suppress claims nobody chose to defer. Two spellings mean
        two entries.
    :param file_suffixes: extensions that make a backticked bare filename a
        path claim, **added to** :data:`FILE_SUFFIXES` rather than replacing
        it. Without this the allowlist is fourteen names chosen here, and a
        repository whose content is a container definition and a shell
        configuration is one the check cannot see at all -- measured on an
        adopter, four claims of twenty-seven, looking nearly green.
    :param commits_in: further repositories whose commits may be cited. Notes
        that review another project name its commits, and settling those
        against only this repository reports honest citations as dead.

        **A path named here that is absent, or present and not a repository,
        raises** -- the same refusal ``resolve_in`` makes, for the same reason
        and one layer deeper. ``_known_commits`` keeps only the roots that are
        repositories, so either mistake used to vanish into that filter: the
        declaration contributed nothing and said nothing, and the run stayed
        green while every citation it was meant to settle was judged against
        this repository alone. The shape bites hardest where it is least
        visible -- a corpus checked out on a developer's machine and gitignored
        in CI settles the citations locally and silently stops settling them
        where the gate actually runs.
    :param foreign: asked of a claim this tree could not settle, and answers
        whether the project has *declared* it to be about somebody else's tree.
        A predicate rather than a bibliography, because this module must not
        learn what a registry is: documentation checking works on a repository
        that declares no registry at all, and wiring the two together here
        would make the claims gate need one. The caller that knows about both
        builds it -- :func:`kinemata.provenance.declared_foreign`.

        **The evidence this exists for is a docstring citing another
        repository.** This package's own source names commits and paths in the
        projects it was validated against; they are real citations of real
        artifacts, permanently unresolvable here because those trees are not
        this one. Left unhandled they are dead claims forever, which is a gate
        that can never go green over text nobody should change.
    :param resolve_in: further trees a claim may resolve against. Process notes
        that live beside a repository rather than inside it describe *that*
        tree, and resolving them only against their own is how a correct
        reference reads as a dead one.

        **A directory named here and not present raises.** It fails open
        otherwise, and open is invisible: an adopter compared a run declaring a
        missing sibling tree against a run declaring nothing and got identical
        bytes -- same findings, same exit code, no note. In CI, where the
        sibling is usually not checked out, that is every claim it was meant to
        settle going unchecked while the run reads clean. A warning was
        considered and rejected: the steady state this would have to tolerate is
        "the tree I resolve against is often absent", and a project in that
        state is asking for a check it is not getting.

        Note that these trees are also searched for cited commits, so declaring
        one turns on commit resolution against it. That is deliberate --
        ``_known_commits`` exists because notes beside a repository cite its
        history and their own directory is not a repository -- but it does mean
        a path knob has a second effect, which is why it is written down here.
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
        if not elsewhere.is_dir():
            raise ClaimsError(
                f"resolve_in names {other!r}, which is not a directory here "
                f"({elsewhere}). Every claim it was to settle would go "
                "unchecked and the run would still read clean."
            )
        roots.append(elsewhere)
        more_files, more_directories = _index(elsewhere, git_ignored(elsewhere))
        # Indexed twice: bare, and under the tree's own name. Notes beside a
        # repository call it by name -- :shown:`workspace/docs/design.md` -- and
        # indexing only the inside of that tree reports the reference dead.
        label = elsewhere.name
        files |= more_files | {f"{label}/{rel}" for rel in more_files}
        directories |= more_directories | {f"{label}/{rel}" for rel in more_directories}
    tree = Tree(root=root, files=files, directories=directories, roots=tuple(roots))

    found = Verification()
    pending: list[tuple[ClaimKind, str, Claim]] = []
    known_suffixes = FILE_SUFFIXES | {str(suffix) for suffix in file_suffixes}
    # Per declared document suffix, so a suffix that is present and inert can be
    # told apart from one that is present and working. Both halves are needed:
    # zero files and zero claims are different mistakes with different fixes.
    read: dict[str, int] = dict.fromkeys((str(s) for s in suffixes), 0)
    yielded: dict[str, int] = dict.fromkeys(read, 0)

    for path in _walk(root, suffixes):
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, exclusions):
            continue
        historic = _excluded(rel, archives)
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue
        read[path.suffix] += 1
        # A declared suffix says "read these as documents". For a source file
        # that is true of the docstrings and comments and false of everything
        # else, and the difference is not cosmetic: scanned whole, one line of
        # this package's own executable code reads as a markdown link and
        # reports its target as a dead path.
        source, illustrations = _as_documentation(source, path.suffix)
        found.shown += illustrations
        before = len(pending)

        previous = ""
        for number, line in enumerate(source.splitlines(), start=1):
            for kind in kinds:
                if historic and kind.current_only:
                    continue
                for text in kind.extract(line, previous, known_suffixes):
                    pending.append(
                        (kind, text, Claim(kind.name, text, rel, number, line))
                    )
            previous = line
        yielded[path.suffix] += len(pending) - before

    _report_inert_suffixes(read, yielded, root, found)

    commit_roots = list(roots)
    for other in commits_in:
        elsewhere = (root / other).resolve()
        # Refuse precisely what `_known_commits` would drop, so a declaration
        # that survives this loop is one that will actually be consulted.
        if not elsewhere.is_dir():
            raise ClaimsError(
                f"commits_in names {other!r}, which is not a directory here "
                f"({elsewhere}). Every commit it was to settle would be "
                "reported against this repository alone."
            )
        if not _is_repository(elsewhere):
            raise ClaimsError(
                f"commits_in names {other!r}, which is not a git repository "
                f"({elsewhere}). Naming it settles nothing and says nothing, "
                "which is the failure resolve_in was taught to refuse."
            )
        commit_roots.append(elsewhere)
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
    if external and not cited:
        # The mirror of the branch below, and it went unwritten while that one
        # was being argued for. Declared and reaching nothing reads exactly like
        # declared and checking twelve: the run is green either way and the
        # network was never touched. Measured here on 2026-09-11 -- excluding
        # two documents this project carries without authoring took the
        # population from five addresses to none, all five of which had been
        # somebody else's, so the check had been settling no link of this
        # project's at all while looking like a network gate.
        #
        # A warning rather than a failure, the same call `_report_inert_suffixes`
        # makes: a tree that legitimately cites no address is a normal tree.
        _warn(
            found,
            "[claims] external is on and no document cites an address, so the "
            "network check settles nothing. Green here means it found no links "
            "to check, not that the links check out.",
        )
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
            # Resolving is the gate's answer and not always the writer's: ask
            # the row whether anything actually said yes.
            if kind.settled is not None and \
                    not kind.settled(text, tree, root / claim.path):
                found.unsettled.append(claim)
            continue
        # Asked only once the tree has failed to settle it. A citation that
        # resolves here is about here, whatever a key beside it says -- so a
        # foreign declaration can never take a live claim out of the check.
        if foreign is not None and foreign(claim):
            found.foreign.append(claim)
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
    """Values the prose states, against what the oracle actually reports."""
    for spec in counts:
        truth = actual_count(spec, root)
        if truth is None:
            # Declared and unreachable is a failure, not a note. The project
            # asked for this check; a broken oracle means it is not running.
            found.blocked.append(
                f"{spec.label}: {' '.join(spec.command)} produced no value"
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
            # Counted claims read the same reduced text every other kind does.
            # A declared suffix means "these are documents", and honoring that
            # for paths while reading the same file raw for values would let a
            # value be shown in one sentence and asserted in the next.
            source, _ = _as_documentation(source, path.suffix)
            for number, line in enumerate(source.splitlines(), start=1):
                for claimed, text in counted_claims(line, spec):
                    found.checked += 1
                    if claimed != truth:
                        found.broken.append(
                            Claim(spec.label, f"{text} (actually {truth})",
                                  rel, number, line)
                        )
