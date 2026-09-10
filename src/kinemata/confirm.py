"""Recording that a citation was confirmed, in the document that carries it.

A stamp says when a citation was last confirmed. **Advanced by hand it says
nothing**: nothing prevents the date moving without the check ever running,
which is a reminder wearing a catch's clothes. And at real volume it cannot be
done by hand at all -- this project's own working notes carry citations in the
hundreds. So the checker writes what it verified, which is what section 7 of
``docs/citations.md`` settles.

This is the one place the package writes into prose, so the boundary is drawn
tightly and stated here rather than left to be inferred:

* **The gate only ever reports.** ``check``, ``claims``, ``context`` and
  ``undeclared`` write nothing, and nothing here is reachable from any of them.
  A check that rewrites the tree it is judging can make itself pass, which is
  the failure this project exists to catch.
* **An explicit command writes.** :func:`plan` is read-only and is what the
  command does unless asked for more; :func:`apply` is the only thing here that
  touches a file, and only ``kinemata confirm --write`` reaches it.
* **Only what this run confirmed.** A stamp records a check that happened, never
  one that should have. A citation the run could not settle keeps the date it
  has -- and is named in the report, because a silent skip would leave a reader
  believing the whole tree was confirmed.

**The oracles are the ones ``claims`` already uses, read the other way round.**
``claims`` is a gate, so it treats a claim as false only when something said so:
a timeout is not a dead link, and a gate that goes red on weather teaches its
reader to skim it. A writer has to invert that reading. "Could not tell" is not
confirmation, so anything short of a settled yes leaves the stamp alone. The
oracles themselves are shared rather than rebuilt -- two mechanisms that could
disagree about whether a path exists eventually will.

**Only a keyed citation is written, and that is the whole of the association
this module assumes.** The key lives *inside* the token, so what a stamp
annotates needs no inference: the key names a bibliography entry and the entry
names the target. A stamp carrying a type alone -- ``[0TMQDKB-Pa]`` -- says when
*something* was looked at, and nothing here can tell what, so it is left alone.
General stamp-to-citation association is deliberately unbuilt, and this is not
it.

**The edit is seven characters wide.** A key is only ever written as part of a
stamp, so a keyed citation always carries a timestamp already: there is nothing
to insert and nothing to move. The timestamp is overwritten in place, the
replacement is the same length as what it replaces, and every other byte of the
document -- line endings, trailing spaces, the final newline, the order of
anything -- is the byte it was.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from . import stamps
from .adapters.bibliography import INTERPRETED, Bibliography, undeclared_key
from .bypass import _walk, git_ignored
from .claims import EXTERNAL_TIMEOUT, Tree, _index, _known_commits, _normalize, _reach_all
from .contract import Entry


class ConfirmError(Exception):
    """A write that cannot be made safely, refused rather than made anyway.

    Raised only from :func:`apply`, and only when the document no longer looks
    the way the plan read it. Writing regardless would put a date on text
    nothing in this run examined.
    """


#: What a run can say about one citation, in the order a summary reads them.
#: Declared as a table because the report, the counts and the write path all ask
#: about the same set, and three private spellings of one vocabulary is how two
#: of them come to disagree.
CONFIRMED = "confirmed"
CURRENT = "current"
UNSETTLED = "unsettled"
GONE = "gone"
REFUSED = "refused"

VERDICTS: tuple[str, ...] = (CONFIRMED, CURRENT, UNSETTLED, GONE, REFUSED)

#: How each verdict reads in a summary line. ``current`` is spelled out because
#: "1 current" invites the wrong reading -- it is the one verdict that means
#: *nothing was done and nothing is wrong*.
SUMMARY: dict[str, str] = {
    CONFIRMED: "confirmed",
    CURRENT: "already confirmed today",
    UNSETTLED: "unsettled",
    GONE: "gone",
    REFUSED: "refused",
}


@dataclass(frozen=True)
class Settler:
    """One interpreted type code, and the oracle that settles it.

    A table rather than a chain of tests on the code, for the reason
    ``claims.CLAIM_KINDS`` is one: a fourth interpreted code should cost a row.

    ``settle`` answers ``True`` (the target is there), ``False`` (something said
    it is not) or ``None`` (nothing could tell), and carries the sentence a
    reader needs for the last two. **The three-way answer is the point.** Two
    would force "could not tell" into one of the other buckets, and either
    choice is wrong: called false it fills the report with findings nobody can
    act on, called true it writes a date for a check that never happened.
    """

    code: str
    settle: Callable[[str, Tree], tuple[bool | None, str]]
    #: Which oracle this code needs. Asked of the row rather than tested by
    #: name, so the gathering pass never learns a code and there is one place
    #: where a code is spelled at all.
    needs_index: bool = False
    needs_git: bool = False
    needs_network: bool = False


def _settle_path(target: str, tree: Tree) -> tuple[bool | None, str]:
    """A path in this tree, asked the way every other check here asks.

    Inherits ``Tree.resolves``'s known generosity: a path present only in an
    ignored copy still resolves. Held deliberately there, and not worth a second
    answer here -- a stricter rule in one command would mean this tool says a
    file exists and does not exist depending on which command asked.
    """
    if tree.resolves(target):
        return True, ""
    return False, f"no such path: {target}"


def _settle_commit(target: str, tree: Tree) -> tuple[bool | None, str]:
    if tree.commits is None:
        return None, "the history cannot answer here (not a git repository)"
    if target in tree.commits:
        return True, ""
    return False, f"the history does not know {target}"


def _settle_url(target: str, tree: Tree) -> tuple[bool | None, str]:
    """An address, which is the one kind that has to leave the machine.

    Off unless the project asked for it, exactly as ``claims`` has it: a
    documentation checker that reaches the network unasked is a surprise. Off
    is reported rather than passed over, because a run that quietly declined to
    ask reads on stdout like a run that asked and got a yes.
    """
    if tree.reachable is None:
        return None, "network checks are not enabled (set external = true under [claims])"
    verdict = tree.reachable.get(target)
    if verdict is True:
        return True, ""
    if verdict is False:
        return False, f"{target} is gone"
    return None, f"{target} gave no usable answer"


#: One row per code the tool interprets. Adding an interpreted code without an
#: oracle would leave a code the tool claims to act on and cannot, so the two
#: tables are checked against each other below rather than trusted to stay in
#: step.
SETTLERS: tuple[Settler, ...] = (
    Settler("Pa", _settle_path, needs_index=True),
    Settler("Cm", _settle_commit, needs_git=True),
    Settler("Wb", _settle_url, needs_network=True),
)

_BY_CODE: dict[str, Settler] = {settler.code: settler for settler in SETTLERS}

if set(_BY_CODE) != set(INTERPRETED):
    raise ImportError(
        "the interpreted type codes and the oracles that settle them have "
        f"drifted apart: {sorted(set(INTERPRETED) ^ set(_BY_CODE))}. An "
        "interpreted code is one whose behavior the tool depends on, so one "
        "with no oracle is a promise nothing keeps."
    )


@dataclass(frozen=True)
class Outcome:
    """One keyed citation, and what this run was able to say about it.

    ``at`` is the offset of the timestamp's first character within the line, not
    of the token: it is exactly the slice a write replaces, and recording the
    thing that will be written keeps the writer from computing the position a
    second time off a match that is free to disagree with the first.
    """

    path: str
    line: int
    key: str
    verdict: str
    #: What was confirmed, or why nothing was: the entry's target for a
    #: confirmation, the reason for everything else.
    detail: str = ""
    #: The timestamp as it stands, and what would replace it. Equal whenever
    #: nothing is to be written.
    old: str = ""
    new: str = ""
    at: int = 0

    @property
    def writes(self) -> bool:
        return self.verdict == CONFIRMED

    def __str__(self) -> str:
        if self.writes:
            return f"{self.line:>5}  {self.key}  {self.old} -> {self.new}  {self.detail}"
        return f"{self.line:>5}  {self.key}  {self.verdict}: {self.detail}"


@dataclass(frozen=True)
class Plan:
    """Everything a run found, and nothing it did.

    Separate from the writing on purpose, and not as a convenience: this is what
    ``kinemata confirm`` produces on its own, so the default behavior of the one
    writing command in the package is to describe the edit rather than make it.
    """

    root: Path
    #: The moment every confirmation in this plan records.
    when: datetime
    outcomes: tuple[Outcome, ...] = ()
    #: Documents left unread because they hold superseded records. Section 6:
    #: archived material is left alone on both axes, since a record cites what
    #: was true when it was written.
    archived: tuple[str, ...] = ()
    #: Documents that are not UTF-8. Named, never edited: a writer that guessed
    #: an encoding would corrupt the half of the file it did not understand.
    unreadable: tuple[str, ...] = ()

    @property
    def writes(self) -> tuple[Outcome, ...]:
        return tuple(outcome for outcome in self.outcomes if outcome.writes)

    def counts(self) -> dict[str, int]:
        tally = dict.fromkeys(VERDICTS, 0)
        for outcome in self.outcomes:
            tally[outcome.verdict] += 1
        return tally

    def text(self, *, verbose: bool = False, quiet: bool = False) -> str:
        """The plan as a person can check it: file, line, key, and what changes.

        A confirmation prints both timestamps because that is the whole of the
        edit; a reader comparing the report against ``git diff`` afterward should
        be reading the same two tokens in both.

        ``current`` citations are held back unless asked for. They are the
        common case in a tree that was confirmed yesterday, and a report whose
        bulk is lines saying nothing happened is one its reader skims.
        """
        out: list[str] = []
        if not quiet:
            shown = [
                outcome for outcome in self.outcomes
                if verbose or outcome.verdict != CURRENT
            ]
            current = ""
            for outcome in shown:
                if outcome.path != current:
                    current = outcome.path
                    out.append(current)
                out.append(str(outcome))
            if out:
                out.append("")
        tally = self.counts()
        total = sum(tally.values())
        parts = [f"{count} {SUMMARY[verdict]}"
                 for verdict, count in tally.items() if count]
        out.append(f"{total} keyed citation(s)" + (f": {', '.join(parts)}" if parts else ""))
        if self.archived:
            out.append(
                f"{len(self.archived)} document(s) left alone as superseded records"
            )
        for rel in self.unreadable:
            out.append(f"{rel} is not UTF-8 and was not read")
        return "\n".join(out)


@dataclass
class _Site:
    """One stamp as it was read, before anything was known about its key."""

    path: str
    line: int
    text: str
    stamp: stamps.Stamp
    #: The backticked span ending immediately before the token, if there is one.
    accompanied: str | None = None


@dataclass
class _Wanted:
    """The targets an oracle has to be asked about, gathered before it is built."""

    paths: bool = False
    urls: set[str] = field(default_factory=set)
    shas: set[str] = field(default_factory=set)


def _excluded(rel: str, fragments: Sequence[str]) -> bool:
    return any(fragment in rel for fragment in fragments)


def _accompanied(line: str, start: int) -> str | None:
    """The target spelled beside the stamp, when the sentence spells one.

    Section 5.6: a citation accompanies its target by default, and the
    redundancy is *checkable* -- the bibliography says where the key points, the
    sentence says where it points, and disagreement is a finding.

    **Narrow on purpose.** Only a code span ending immediately before the token,
    with at most one space between, is read as the accompanied target. Anything
    looser starts guessing which of a sentence's several backticked words the
    citation was about, and a writer that guesses wrong dates a check of one
    thing as a check of another.
    """
    before = line[:start]
    if before.endswith(" "):
        before = before[:-1]
    if not before.endswith("`"):
        return None
    opening = before.rfind("`", 0, len(before) - 1)
    if opening < 0:
        return None
    return before[opening + 1:-1] or None


def plan(
    root: str | Path,
    books: Iterable[Bibliography],
    *,
    suffixes: Sequence[str] = (".md",),
    exclude: Iterable[str] = (),
    historical: Iterable[str] = (),
    external: bool = False,
    timeout: float = EXTERNAL_TIMEOUT,
    when: datetime | None = None,
) -> Plan:
    """What a confirmation run would record, having verified all of it.

    Reads. Writes nothing, and is the whole of what ``kinemata confirm`` does
    without ``--write``.

    :param books: the declared bibliographies. A key resolves against its own
        project's bibliography and nothing else, so a run with none has nothing
        it could confirm.
    :param historical: path fragments holding superseded records, left unread.
    :param external: ask the network about ``Wb`` targets. Off by default, and
        with it off every address is reported unsettled rather than passed over.
    :param when: the moment to record. Injected so a test can hold the clock
        still; a run takes it from the system.

    **Gitignored documents are never touched**, whatever the project's exclude
    list says. A tree carrying somebody else's documents -- a corpus, a vendored
    copy -- is exactly where an unwanted edit does the most damage, and git is
    where the project already declared what is not its own.
    """
    root = Path(root)
    when = when or datetime.now(UTC)
    declared: dict[str, Entry] = {
        entry.id: entry for book in books for entry in book.entries()
    }
    exclusions = tuple(fragment.rstrip("/") for fragment in exclude if fragment)
    exclusions += git_ignored(root)
    archives = tuple(fragment for fragment in historical if fragment)

    sites: list[_Site] = []
    archived: list[str] = []
    unreadable: list[str] = []
    for path in sorted(_walk(root, tuple(suffixes))):
        rel = path.relative_to(root).as_posix()
        if _excluded(rel, exclusions):
            continue
        if _excluded(rel, archives):
            archived.append(rel)
            continue
        try:
            source = path.read_bytes().decode("utf-8")
        except OSError:
            continue
        except UnicodeDecodeError:
            unreadable.append(rel)
            continue
        # Split with the line endings kept, and split the same way the writer
        # will. Offsets are only meaningful against the text they were measured
        # in, and `read_text` would have translated a CRLF document into
        # something the file on disk does not say.
        for number, line in enumerate(source.splitlines(keepends=True), start=1):
            for stamp in stamps.find(line):
                if stamp.key is None:
                    continue
                sites.append(
                    _Site(rel, number, line, stamp,
                          _accompanied(line, stamp.span[0]))
                )

    tree = _oracle(root, sites, declared, external=external, timeout=timeout)
    outcomes = tuple(
        _judge(site, declared, tree, when) for site in sites
    )
    return Plan(root=root, when=when, outcomes=outcomes,
                archived=tuple(archived), unreadable=tuple(unreadable))


def _wanted(sites: Iterable[_Site], declared: dict[str, Entry]) -> _Wanted:
    """Which oracles this run actually needs, so the rest are never woken.

    A tree with no commit citation should not spawn git, and a tree with no
    address should not open a socket even when the project has asked for
    network checks.
    """
    wanted = _Wanted()
    for site in sites:
        entry = declared.get(stamps.canonical_key(site.stamp.key or ""))
        if entry is None:
            continue
        settler = _BY_CODE.get(str(entry.extra["type"]))
        if settler is None:
            continue
        target = str(entry.extra["target"])
        if settler.needs_index:
            wanted.paths = True
        if settler.needs_git:
            wanted.shas.add(target)
        if settler.needs_network:
            wanted.urls.add(target)
    return wanted


def _oracle(
    root: Path,
    sites: Iterable[_Site],
    declared: dict[str, Entry],
    *,
    external: bool,
    timeout: float,
) -> Tree:
    """Everything this run will be asked, asked once.

    The scanned tree only. ``claims`` can be pointed at sibling trees for notes
    that live beside the repository they describe; a writer declining to follow
    it there loses nothing it could have written -- an unresolved target is not
    confirmed either way -- and gains not having a second definition of where
    this project ends.
    """
    wanted = _wanted(sites, declared)
    files: set[str] = set()
    directories: set[str] = set()
    if wanted.paths:
        files, directories = _index(root, git_ignored(root))
    tree = Tree(root=root, files=files, directories=directories, roots=(root,))
    if wanted.shas:
        tree.commits = _known_commits([root], wanted.shas)
    if external:
        tree.reachable = _reach_all(wanted.urls, timeout)
    return tree


def _judge(
    site: _Site, declared: dict[str, Entry], tree: Tree, when: datetime
) -> Outcome:
    """One citation: what this run can say, and whether that is worth writing.

    The order is deliberate. A site this run should not touch at all is decided
    before its target is looked at, so a refusal reads as the refusal it is
    rather than as a verdict on the source. Currency is decided **last**, so a
    citation confirmed this morning whose target went missing this afternoon is
    reported as gone rather than skipped as current.
    """
    key = stamps.canonical_key(site.stamp.key or "")
    at = site.stamp.span[0] + 1
    body = site.text[at:at + stamps.STAMP_LENGTH]
    refused = _refusal(site, key, declared)
    if refused is not None:
        return Outcome(site.path, site.line, key, REFUSED, refused, body, body, at)

    entry = declared[key]
    code, target = str(entry.extra["type"]), str(entry.extra["target"])
    settler = _BY_CODE.get(code)
    if settler is None:
        return Outcome(
            site.path, site.line, key, UNSETTLED,
            f"nothing here settles type {code}, so no run can confirm it",
            body, body, at,
        )
    verdict, why = settler.settle(target, tree)
    if verdict is None:
        return Outcome(site.path, site.line, key, UNSETTLED, why, body, body, at)
    if verdict is False:
        return Outcome(site.path, site.line, key, GONE, why, body, body, at)
    if site.stamp.moment.date() == when.date():
        return Outcome(site.path, site.line, key, CURRENT, target, body, body, at)
    return Outcome(site.path, site.line, key, CONFIRMED, target,
                   body, stamps.encode(when), at)


def _refusal(site: _Site, key: str, declared: dict[str, Entry]) -> str | None:
    """Why this site is not one to write into, or ``None`` if it is.

    Three, and each is a case where the document and the tool disagree about
    what the citation is. Reported rather than repaired: the fixes are edits to
    a sentence, and a tool that reworded prose to make its own write legal would
    be doing something nobody asked it for.
    """
    if key not in declared:
        return undeclared_key(key)
    end = site.stamp.span[1]
    if site.text[end:end + 1] == "(":
        return (
            "section 3.3: an opening parenthesis follows the stamp, so a reader's "
            "renderer takes the stamp as link text and the parenthesized words as "
            "its target. Separate them before dating this."
        )
    target = str(declared[key].extra["target"])
    if site.accompanied is not None and \
            _normalize(site.accompanied) != _normalize(target):
        return (
            f"section 5.6: the sentence accompanies this key with "
            f"{site.accompanied!r} and the bibliography points it at {target!r}. "
            "One of them is wrong, and nothing here can tell which."
        )
    return None


def apply(made: Plan) -> tuple[tuple[str, int], ...]:
    """Write the confirmations in ``made``, and report what each file received.

    **The only function in this module that touches a file.** It writes the
    seven timestamp characters of the citations the plan confirmed, and nothing
    else: the replacement is the same width as what it replaces, so no offset
    later in the line moves and no byte outside those seven is rewritten. A file
    whose bytes would not change is not written at all.

    Refuses when the text at a recorded offset is no longer the text the plan
    read there. That means the document changed under the run, and the only
    alternatives are writing a date onto something nothing examined or searching
    for where the citation went -- which is the guess this module does not make.
    """
    written: list[tuple[str, int]] = []
    edits: dict[str, list[Outcome]] = {}
    for outcome in made.writes:
        edits.setdefault(outcome.path, []).append(outcome)

    for rel, outcomes in edits.items():
        path = made.root / rel
        original = path.read_bytes()
        try:
            text = original.decode("utf-8")
        except UnicodeDecodeError as exc:  # pragma: no cover - planned around
            raise ConfirmError(f"{rel} is not UTF-8; nothing was written") from exc
        lines = text.splitlines(keepends=True)
        for outcome in outcomes:
            line = lines[outcome.line - 1]
            if line[outcome.at:outcome.at + stamps.STAMP_LENGTH] != outcome.old:
                raise ConfirmError(
                    f"{rel}:{outcome.line} no longer reads the way it did when "
                    f"this run examined it ({outcome.key}). Nothing was written "
                    "to it. Run the check again."
                )
            lines[outcome.line - 1] = (
                line[:outcome.at] + outcome.new
                + line[outcome.at + stamps.STAMP_LENGTH:]
            )
        updated = "".join(lines).encode("utf-8")
        if updated == original:
            continue
        path.write_bytes(updated)
        written.append((rel, len(outcomes)))
    return tuple(written)
