"""Bypass detection: the catch for duplication.

A registry entry is a thing with a single source of truth that code is required
to route through. A *bypass* is a site that re-derived the thing instead --
spelling a constant's value as a literal, hardcoding what an accessor would have
read, inlining an operation a helper already performs.

The mechanism is deliberately syntactic. Each entry declares the spelling that
means it was bypassed; this module finds those spellings outside the entry's own
definition. It does **not** try to decide whether two pieces of code do the same
job -- that is semantic, and a mechanism claiming to do it would be lying about
its own reach.

Two properties, both learned from corpus evidence:

* **Scope is the whole tree, never one module.** kanibako-cli's own tripwire
  scanned ``project/workset.py`` [0TMVXHC-Pa0004] alone and missed eight sites
  in six other modules (``42ece129`` [0TMVXHC-Cm0001]). A catch scoped to one
  module is not a catch.
* **It runs where the agent cannot reach it.** In CI, host-side. A check an
  agent can edit or skip is a reminder, not a catch.
"""

from __future__ import annotations

import os
import re
import subprocess
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .contract import BaseRegistry, Entry, undeclared
from .prose import (
    FILTERS,
    LITERAL_EXTRACTORS,
    PROSE_FILTERS,
    STRING_FILTERS,
    UNFENCED_FILTERS,
)

#: Which filter table each ``match_mode`` selects. A mode is a row here, so
#: adding one does not mean editing the branch that picks it.
MODE_FILTERS = {
    "prose": PROSE_FILTERS,
    "code": FILTERS,
    "strings": STRING_FILTERS,
    # Everything a document says, minus what it merely shows. For a registry
    # whose matches are *citations*, where an illustration of the notation is
    # indistinguishable from a use of it -- this project's own specification of
    # the citation form was the closed-world catch's only finding.
    "unfenced": UNFENCED_FILTERS,
    # No filtering at all. A row rather than a fallback, because ``raw`` was
    # already being passed by name and worked only because an unknown mode
    # happens to land on a table with no entry for the suffix -- a mode that
    # works by accident is one nobody can rely on.
    "raw": {},
}

#: Git's directory. Named on its own because two checks must look *for* it to
#: decide whether the tree is a repository, and a second spelling of it there
#: would be exactly the duplication this package exists to catch.
GIT_DIR = ".git"

#: Directories never worth scanning: not source, or not the project's.
SKIP_DIRS = frozenset(
    {
        GIT_DIR, ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", "build", "dist", ".tox", ".eggs",
    }
)


def git_ignored(root: str | Path) -> tuple[str, ...]:
    """Paths git is told to ignore: not this project's material.

    Every scan here asks the same question -- does this file belong to the
    project being checked? -- and ``.gitignore`` is where a project already
    answers it. Pointing a registry at prose made the cost visible: the spelling
    check reported sixteen violations, thirteen of them inside other authors'
    documents that only sit in the tree as test corpora.

    Empty when git cannot answer, which over-reports rather than under-reports.
    """
    root = Path(root)
    if not (root / GIT_DIR).exists():
        return ()
    result = subprocess.run(
        ["git", "-C", str(root), "ls-files", "--others", "--ignored",
         "--exclude-standard", "--directory"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode != 0:
        return ()
    return tuple(
        line.strip().rstrip("/") for line in result.stdout.splitlines() if line.strip()
    )


@dataclass(frozen=True)
class Bypass:
    """One site that spelled a thing out instead of routing through it."""

    entry_id: str
    antipattern: str
    path: str
    line: int
    text: str

    #: ``"strong"`` when a whole string literal IS the thing -- the literal
    #: someone should have written the constant for. ``"weak"`` when it merely
    #: occurs inside a longer literal, which is often a different namespace
    #: that happens to share characters. Only strong signals should gate CI;
    #: weak ones are worth a look. (Same split, same reason, as the brief's
    #: hunk-proximity strengths in §6.1.)
    strength: str = "strong"

    def __str__(self) -> str:
        return (
            f"{self.path}:{self.line}: {self.antipattern!r} bypasses "
            f"{self.entry_id} -- {self.text.strip()[:70]}"
        )


def _is_home(path: str, entry: Entry) -> bool:
    """Is this file where the entry is defined?

    Compared by path *suffix*, in both directions, because the two strings are
    anchored differently: ``home`` is recorded relative to the project root
    (``src/pkg/constants.py``) while the scan reports relative to whatever it
    was pointed at (``pkg/constants.py`` when scanning ``src/``). A plain
    substring test silently fails that case and reports every definition as a
    bypass of itself.
    """
    scanned = PurePosixPath(path.replace("\\", "/")).parts
    for fragment in entry.home:
        declared = PurePosixPath(fragment.replace("\\", "/")).parts
        if not declared:
            continue
        shorter, longer = sorted((scanned, declared), key=len)
        if longer[-len(shorter):] == shorter:
            return True
    return False


@dataclass(frozen=True)
class Crossing:
    """A symlinked directory the walk followed out of the tree it was given."""

    path: str
    target: str

    def __str__(self) -> str:
        return f"{self.path} -> {self.target}"


def _crossing(here: Path, root: Path, base: Path) -> Crossing | None:
    """Was this directory reached by a link that leaves ``root``?

    Only the top of a linked subtree is itself a symlink, so a crossing is
    reported once per link rather than once per directory beneath it.
    """
    if here == root or not here.is_symlink():
        return None
    target = here.resolve()
    if target.is_relative_to(base):
        return None
    return Crossing(path=here.relative_to(root).as_posix(), target=str(target))


def _tree(root: Path) -> Iterator[tuple[Path, list[str], Crossing | None]]:
    """Every directory under ``root``, sorted, with its file names.

    **``Path.rglob`` does not enter a symlinked directory, and every check in
    this package was built on it.** Measured 2026-09-08: a tree reached through
    a symlink yielded **0** files where the real path yielded **130**. A project
    whose source is reached that way was scanned as empty and every gate
    reported clean -- a catch reporting a clean tree because it could not see
    the tree, which is the worst way this package can fail.

    So the walk follows symlinked directories, and pays the two costs:

    * **Loops.** Not hypothetical: measured on a self-referential link, both
      ``os.walk(followlinks=True)`` and ``glob`` expand it about forty times
      before the OS refuses, reporting three files 120 times. Each directory is
      entered once, keyed on its real identity, which also collapses two links
      to the same tree into one visit.
    * **Scope.** A link can leave the project. It is followed and *announced*:
      the third element of each yield is a :class:`Crossing` when this directory
      was reached that way. Following is right -- a tree assembled from symlinks
      is a real layout, and one carrier reached from several places is the
      arrangement this project recommends -- but a scan reading files outside
      the root it was given should say so rather than let the reader assume the
      root bounds it.

    ``SKIP_DIRS`` are pruned before descending rather than filtered after, which
    is also what keeps the walk out of ``.venv``'s thousands of files.
    """
    base = root.resolve()
    try:
        top = root.stat()
    except OSError:
        return
    seen = {(top.st_dev, top.st_ino)}

    for parent, dirnames, filenames in os.walk(root, followlinks=True):
        here = Path(parent)
        filenames.sort()
        keep: list[str] = []
        for name in sorted(dirnames):
            if name in SKIP_DIRS:
                continue
            try:
                stat = (here / name).stat()  # follows the link, by design
            except OSError:
                continue  # broken link, or a directory we may not read
            identity = (stat.st_dev, stat.st_ino)
            if identity in seen:
                continue
            seen.add(identity)
            keep.append(name)
        dirnames[:] = keep
        yield here, filenames, _crossing(here, root, base)


def crossings(root: str | Path) -> list[Crossing]:
    """Every symlinked directory the walk follows out of ``root``.

    Separate from the scans so the fact can be reported once per run rather than
    once per registry, and so a caller that only wants to know the scope of a
    scan does not have to read every file to find out.
    """
    return [found for _, _, found in _tree(Path(root)) if found is not None]


def _walk(root: Path, suffixes: Sequence[str]) -> Iterator[Path]:
    for here, filenames, _ in _tree(root):
        for name in filenames:
            path = here / name
            if path.suffix not in suffixes:
                continue
            if not path.is_file():  # a broken link is not a file to read
                continue
            yield path


def scan(
    registry: BaseRegistry,
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".py",),
    exclude: Iterable[str] = (),
    code_only: bool | None = None,
    strings_only: bool | None = None,
) -> list[Bypass]:
    """Every bypass of ``registry``'s entries under ``root``.

    :param exclude: path fragments to skip -- tests that deliberately spell a
        literal, generated files, vendored code.
    :param code_only: strip comments and docstrings before matching. On by
        default: the same literal in prose is documentation, and reporting it is
        how the mechanism gets ignored. Measured on kanibako-cli, this is the
        difference between 8 real sites and 50 hits.
    :param strings_only: match only inside string literals. Use when the
        antipattern is a *value*: without it, ``box_data`` also matches the
        identifier ``box_data``, and those lines usually use the constant
        correctly.
    """
    root = Path(root)
    exclusions = tuple(exclude)

    # The registry chooses its own matching mode; an explicit argument wins.
    # Each parameter is resolved independently, so passing one does not silently
    # overwrite the other -- which it did, making an explicit code_only=False
    # behave as though the registry's mode had been requested.
    mode = getattr(registry, "match_mode", "strings")
    # With neither argument given, the mode picks its own table -- ``prose``
    # blanks inline code spans, ``unfenced`` blanks what a document shows. That
    # is what the two-way code/strings axis below cannot express, and reading
    # the table by name gives every mode the same answer here that ``strays``
    # gives, rather than leaving a new row to work in one caller and not the
    # other. For the four modes the axis does express, the two agree.
    from_mode = strings_only is None and code_only is None
    if strings_only is None:
        strings_only = mode == "strings"
    if code_only is None:
        code_only = mode != "raw"

    compiled: list[tuple[Entry, str, re.Pattern[str]]] = []
    for entry in registry.entries():
        for pattern in entry.antipatterns:
            compiled.append((entry, pattern, re.compile(pattern)))
    if not compiled:
        return []

    found: list[Bypass] = []
    for path in _walk(root, suffixes):
        rel = str(path.relative_to(root))
        if any(fragment in rel for fragment in exclusions):
            continue
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue
        extractor = LITERAL_EXTRACTORS.get(path.suffix) if strings_only else None
        if extractor is not None:
            literals = extractor(source)
            for entry, pattern, rx in compiled:
                if _is_home(rel, entry):
                    continue
                for number, content, line_text in literals:
                    if rx.fullmatch(content):
                        strength = "strong"
                    elif rx.search(content):
                        strength = "weak"
                    else:
                        continue
                    found.append(
                        Bypass(
                            entry_id=entry.id,
                            antipattern=pattern,
                            path=rel,
                            line=number,
                            text=line_text,
                            strength=strength,
                        )
                    )
            continue

        table = MODE_FILTERS.get(mode, FILTERS) if from_mode else (
            STRING_FILTERS if strings_only else (FILTERS if code_only else {})
        )
        source_filter = table.get(path.suffix)
        if source_filter is not None:
            source = source_filter(source)
        lines = source.splitlines()
        for entry, pattern, rx in compiled:
            if _is_home(rel, entry):
                continue
            for number, text in enumerate(lines, start=1):
                if rx.search(text):
                    found.append(
                        Bypass(
                            entry_id=entry.id,
                            antipattern=pattern,
                            path=rel,
                            line=number,
                            text=text,
                        )
                    )
    return found


@dataclass(frozen=True)
class Stray:
    """One use of an identifier the registry does not declare."""

    path: str
    line: int
    identifier: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.identifier}"


def strays(
    registry: BaseRegistry,
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".py",),
    exclude: Iterable[str] = (),
) -> list[Stray]:
    """Identifiers used under ``root`` that ``registry`` does not declare.

    This walks the tree for :func:`~kinemata.contract.undeclared`, which is the
    closed-world catch — the operation that *raises* rather than advising, and
    the one that makes a registry a mechanism instead of a convention.

    **It only answers for a registry that can recognize its own identifiers**,
    which today means a mapping registry with a declared ``syntax``. Any other
    kind raises ``NotImplementedError`` from ``candidates()``, deliberately:
    a registry that cannot tell an identifier from ordinary text would answer
    "nothing is undeclared" about every tree it was ever pointed at.

    Matching is per line so a finding carries a location. A caller that wants
    one row per identifier can collapse them; a catch that reported a bare name
    with no site would be asking a reader to go and find it.

    **It honors the registry's ``match_mode``, for the same reason ``scan`` does
    and with the same evidence behind it.** A keyspace identifier appears in
    source as a *string literal*; the identifier syntax that recognizes it also
    matches every dotted attribute access in the language. Measured on
    kanibako-cli with the fixture's permissive syntax: matching raw lines gives
    **48,685** findings, string literals alone **7,266**. Neither is a usable
    gate — the residue is filenames like ``credentials.json``, not settings keys
    — which is the point. **The mode filter is necessary and not sufficient;
    what makes this catch usable is a registry declaring an identifier syntax
    narrow enough to mean something.** Same lesson ``design.md`` §7 records for
    ``detect``, reached again from the other side.
    """
    root = Path(root)
    exclusions = tuple(exclude)
    mode = getattr(registry, "match_mode", "strings")
    strings_only = mode == "strings"

    found: list[Stray] = []
    for path in _walk(root, tuple(suffixes)):
        rel = str(path.relative_to(root))
        if any(fragment in rel for fragment in exclusions):
            continue
        try:
            source = path.read_text(errors="ignore")
        except OSError:
            continue

        extractor = LITERAL_EXTRACTORS.get(path.suffix) if strings_only else None
        if extractor is not None:
            for number, content, _line in extractor(source):
                for identifier in undeclared(registry, content):
                    found.append(Stray(path=rel, line=number, identifier=identifier))
            continue

        table = MODE_FILTERS.get(mode, FILTERS)
        blank = table.get(path.suffix)
        text = blank(source) if blank else source
        for number, line in enumerate(text.splitlines(), 1):
            for identifier in undeclared(registry, line):
                found.append(Stray(path=rel, line=number, identifier=identifier))
    return found


def unused(
    registry: BaseRegistry,
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".py",),
    exclude: Iterable[str] = (),
    machinery: Iterable[str] = (),
) -> list[str]:
    """Declared entries nothing *mentions*. **A review list, never a cut list.**

    ⚠ **This detects mention, not use, and the difference matters.**

    Validated against a labeled incident and it failed. kanibako-cli commit
    ``d8037cf5`` [0TMVXHC-Cm0002] records that three declared keys "had no
    reader at all -- a set was accepted, persisted and read back, and nothing
    moved". This function
    missed all three, because each appears in the project's own declaring
    machinery: a key-name list and a key-to-path table. Those are mentions, not
    readers, and no amount of text matching tells them apart.

    Every declared entry is mentioned somewhere by construction -- that is what
    declaring *is* -- so with nothing excluded this check is vacuous on precisely
    the registries it is meant to serve. **That configuration now raises.** It
    was the signature default for the life of the project while the docstring
    called exclusions "required in practice", which is a requirement nothing
    required: asking for nothing returned a clean-looking list measured at 0/3.

    Two ways to say where a declaration lives, and either satisfies this.
    ``home`` is per entry and says where *that* entry is defined; ``machinery``
    is per registry and names files that declare without using -- a key table,
    an inventory. The incident needs the second, because those keys' ``home`` is
    the manifest while the table that mentions them is a module.

    ⚠ **``exclude`` is not one of them, and that distinction is the whole
    refusal.** A project's ``exclude`` names build and test trees, and it is
    non-empty in every real project -- so accepting it as an answer would let
    the refusal pass everywhere while meaning nothing. Written that way first,
    and caught by running the command against this repository.

    :param exclude: trees not to read at all. Does not satisfy the requirement.
    :param machinery: declaring files, added to the registry's own.
    :raises ValueError: when nothing says where a declaration lives, or when the
        registry's entries are declared to be absent rather than used.

    Finding a real *reader* means tracing a value from resolution into
    behavior. That is dataflow analysis and deliberately out of scope here: a
    mechanism that claimed to do it syntactically would be lying about its reach.

    Why it survives as a review list rather than a gate: an entry can be real and
    unreferenced. "Supreme Law" is defined in canon and referenced nowhere in
    canon, because its consumer is a conversation. Auto-deleting on this signal
    destroys deliberate declarations.
    """
    root = Path(root)
    if not registry.mentions_are_uses:
        raise ValueError(
            f"registry {registry.name!r}: these entries are declared so that "
            "nothing says them, so an unmentioned one is the convention being "
            "kept. Every entry would be reported and every report would be a "
            "success."
        )
    declaring = tuple(machinery) + tuple(registry.machinery)
    entries = list(registry.entries())
    if not declaring and not any(entry.home for entry in entries):
        raise ValueError(
            f"registry {registry.name!r}: nothing says where these entries are "
            "declared, so every one of them is mentioned by its own declaring "
            "machinery and this check has nothing to report. Measured at 0/3 "
            "against a labeled incident in exactly this configuration. Declare "
            "`machinery` -- the files that declare rather than use these "
            "entries -- or give the entries a `home`."
        )
    exclusions = declaring + tuple(exclude)
    referenced: set[str] = set()

    # This walk consults no ``match_mode``, and ``unfenced`` is the one
    # exception rather than the start of a general rule. Applying ``code`` or
    # ``strings`` here would blank the code a constants registry's identifiers
    # are mentioned in and report every entry unmentioned -- measured, and the
    # reason `detect` documents for not doing this generally. ``unfenced`` is
    # different in kind: its matches are citations *in prose*, so what a
    # document merely shows is not a mention of anything, and the construct that
    # says so differs by language. `detect` blanks markdown fences on its own
    # behalf and will keep doing so for any caller; only a walk that reads
    # several languages knows which file it is holding.
    shows = (
        MODE_FILTERS["unfenced"]
        if getattr(registry, "match_mode", "strings") == "unfenced"
        else {}
    )

    for path in _walk(Path(root), suffixes):
        rel = str(path.relative_to(root))
        if any(fragment in rel for fragment in exclusions):
            continue
        text = path.read_text(errors="ignore")
        filtered = shows.get(path.suffix)
        if filtered is not None:
            text = filtered(text)
        for found in registry.detect(text):
            # A reference inside the entry's own definition is not a use.
            entry = next((e for e in entries if e.id == found), None)
            if entry is not None and _is_home(rel, entry):
                continue
            referenced.add(found)

    return [e.id for e in entries if e.id not in referenced]
