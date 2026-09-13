"""A budget on what a session actually loads.

``projection.py`` bounds the registry's own output, which is the smallest part of
what an agent reads. The instruction layer -- the harness file, a project's policy
documents, the docs a session is told to open -- is unbounded, and that is where
*overwhelmed with context* actually lives.

**The incident this was built from was measured, not imagined.** One agent
harness assembles a set of policy documents into the instruction file it loads,
on every load -- a **build output, regenerated each session, not a source**.
Session-start records of that output survive, so the size of what was actually
loaded is measured rather than estimated:

===========  =============
2026-09-02   12,973 B (four records, identical)
2026-09-05   21,357 B
2026-09-06   22,800 B
===========  =============

Seventy-six percent in four days, on a project that was itself building
mechanisms against context overwhelm, and nothing noticed. Growth is invisible
because each individual addition is defensible; only the total is a problem, and
nobody was looking at the total.

Those records are a **sample, not a census** -- not every session left one -- so
the series carries a direction and a rate rather than a starting size.

**This measures the sources and models the assembly, and that is not a
compromise.** The assembled file is transient: it exists only after the harness
has run, on a machine where it has run. A check that read it could not run in CI,
on a clean clone, or before the thing it is meant to prevent has already
happened. The sources are what persist and what a commit changes.

So: declare what a session loads, flatten it the way the harness does, and fail
over a declared ceiling.

**Globs, not file lists.** A file dropped into a declared directory has to be
counted by default. A list of filenames is an allowlist that silently omits
whatever arrives next, which is the same rot a baseline has.

**What this cannot do**, said here rather than discovered later:

* **Bytes are not attention.** This bounds size, never relevance. Twelve
  kilobytes of irrelevant material is worse than twenty of necessary material,
  and no byte count tells them apart.
* **It measures what you declare is loaded.** If the declaration drifts from what
  the harness reads, this measures the wrong thing precisely.
* **The flattening is a model of the assembly, and getting the *set* right is the
  hard half.** One real assembler compiles its instruction file by walking a
  reference graph **and** stripping comment blocks, over only the documents it
  deems critical. Modeling the stripping is easy; modeling *which files are in*
  is where a declaration goes wrong. Checked against that compiler by probing each
  source file's own lines for presence in its output: 23,287 B modeled against
  23,786 B produced, the **2.1%** residue being the compiler's generated
  scaffolding -- title, table of contents, section numbering.

  Note the direction. Once the set is right this **under**-counts, because a
  compiler adds structure of its own, so a ceiling wants headroom rather than
  trusting the total. The first attempt at this figure was wrong twice over and
  is worth recording as a method warning: it swept whole directories, counted
  deferred material that never loads, missed a file that does, and reported the
  difference as an error rate. **A set you did not verify is not a measurement.**

* **"What a session loads" is a decision, not a property of the tree**, and that
  is the sharpest limit here. Documentation systems worth bounding are usually
  built for *deferred* loading -- an entry point carrying pointers, with detail
  fetched only when a task needs it -- so most of the corpus may never reach a
  session, and which parts do can differ per session and per person. Declaring a
  set is declaring an **intent**: this is what we mean to be loaded up front. The
  check bounds that intent. It cannot see what an agent actually opened, and a
  declaration that quietly stops matching practice will bound the wrong thing
  precisely.
"""

from __future__ import annotations

import glob
import re
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

#: Transforms applied before measuring, declared by name in ``[context] strip``.
#: A table rather than a branch, so adding one does not mean editing the caller
#: -- the same reason ``CLAIM_KINDS`` is a table. Only entries with evidence
#: behind them belong here: this one exists because a real assembler removes HTML
#: comment blocks, which in one corpus held the original packaged text of every
#: document -- 44% of its bytes, none of it ever loaded.
STRIPPERS: dict[str, Callable[[str], str]] = {
    "html-comments": lambda text: re.sub(r"<!--.*?-->", "", text, flags=re.S),
}


@dataclass(frozen=True)
class Loaded:
    """One file in the declared set, before and after flattening."""

    path: str
    raw: int
    size: int
    #: Did this file resolve to somewhere outside the project tree?
    #:
    #: **Measured from the resolved path, not from the key that declared it.**
    #: ``[context] external`` may name an absolute path that lands back inside
    #: the root, and a report that called it off-tree because of which list
    #: asked for it would be stating something false about where the bytes are.
    #:
    #: ``external`` rather than a fresh word: ``[claims] external`` reaches past
    #: this tree to the network and the bibliography's ``EXTERNAL`` marks a
    #: source this project does not own. All three mean *beyond this
    #: repository*, which is overlap enough to reuse the term rather than teach
    #: a reader a second one.
    external: bool = False

    @property
    def stripped(self) -> int:
        return self.raw - self.size

    def __str__(self) -> str:
        note = f" ({self.stripped} B stripped)" if self.stripped else ""
        mark = "  [external]" if self.external else ""
        return f"{self.size:>7} B  {self.path}{note}{mark}"


@dataclass(frozen=True)
class Measurement:
    """What the declared set weighs, against what it is allowed to weigh."""

    files: tuple[Loaded, ...] = ()
    ceiling: int = 0

    @property
    def size(self) -> int:
        return sum(item.size for item in self.files)

    @property
    def raw(self) -> int:
        return sum(item.raw for item in self.files)

    @property
    def over(self) -> int:
        return max(0, self.size - self.ceiling)

    @property
    def failed(self) -> bool:
        return self.size > self.ceiling

    @property
    def external(self) -> tuple[Loaded, ...]:
        """The files that resolved outside the project tree."""
        return tuple(item for item in self.files if item.external)

    def text(self, *, verbose: bool = False) -> str:
        lines = []
        if verbose:
            for item in sorted(self.files, key=lambda f: -f.size):
                lines.append(f"  {item}")
        headroom = self.ceiling - self.size
        summary = (
            f"{self.size} B loaded from {len(self.files)} file(s), "
            f"ceiling {self.ceiling} B"
        )
        summary += (
            f" -- OVER by {self.over} B" if self.failed else f", {headroom} B spare"
        )
        lines.append(summary)
        # Said on every run that has one, not only under `--verbose`. A ceiling
        # met partly with bytes that are not in the repository is a different
        # claim from one met entirely with bytes that are, and a reader
        # comparing this number against a clean clone needs to know which.
        #
        # Deliberately silent about *how* they got out. Most arrive through
        # `[context] external`, but a relative pattern can reach a symlinked
        # directory that leaves the tree, and naming the key here asserted a
        # declaration the run cannot see -- which it did, on the first symlink
        # this was pointed at.
        if self.external:
            weight = sum(item.size for item in self.external)
            lines.append(
                f"  ({weight} B of that from {len(self.external)} file(s) "
                "outside the project tree)"
            )
        if self.raw != self.size:
            lines.append(
                f"  ({self.raw - self.size} B stripped before measuring; "
                f"{self.raw} B on disk)"
            )
        return "\n".join(lines)


def flatten(text: str, strip: Sequence[str]) -> str:
    """Apply the declared transforms, in the order declared."""
    for name in strip:
        transform = STRIPPERS.get(name)
        if transform is None:
            raise KeyError(name)
        text = transform(text)
    return text


def escapes(pattern: str) -> bool:
    """Would this pattern reach outside the tree it is resolved against?

    A **syntactic** question on purpose, decidable when the config loads and
    verifiable by anyone reading the line: a pattern is an escape if it is
    absolute or carries a ``..`` segment. That is what separates ``include``
    from ``external``.

    It deliberately does not resolve anything. An absolute path can land back
    inside the root, and a check that resolved first would accept
    ``/home/me/project/docs`` in ``include`` on one machine and refuse it on
    another -- a config whose validity depends on where the tree is checked out.
    Whether a file is *actually* off-tree is answered per file, after
    resolution, and carried on :attr:`Loaded.external`.
    """
    if PurePosixPath(pattern).is_absolute() or PureWindowsPath(pattern).is_absolute():
        return True
    return ".." in PurePosixPath(pattern).parts


def measure(
    root: str | Path,
    include: Iterable[str],
    *,
    ceiling: int,
    strip: Sequence[str] = (),
    external: Iterable[str] = (),
) -> Measurement:
    """Weigh every file matching ``include``, flattened, against ``ceiling``.

    Each glob is resolved against ``root``. A file matched by two globs is
    counted once: the declaration says what is loaded, and loading a file twice
    is a property of the harness, not of the set.

    **Resolved with ``glob``, not ``Path.glob``, and the difference is the
    point.** ``Path.glob`` does not descend into a symlinked directory, so
    ``notebook/**/*.md`` weighed nothing at all behind a link -- an *under*-count
    in a ceiling check, which passes. Two traps came with the swap, both
    measured rather than assumed: the ``glob`` module skips names beginning with
    a dot unless told otherwise, which would have silently dropped a declared
    ``.claude/`` file; and it expands a symlink loop about forty deep, which
    counted three files 120 times. Hence ``include_hidden`` and a key on the
    real file rather than on the path that reached it.

    ``external`` is the same resolution for patterns that deliberately leave the
    tree. It is a separate list rather than more entries in ``include`` because
    reaching off-tree is a decision worth reading at the declaration site: an
    absolute path or a parent-directory escape used to work here **by accident**
    of ``Path.__truediv__`` discarding its left operand and ``glob`` resolving a
    parent segment without complaint, so a config could weigh a compiled
    artifact from anywhere on the filesystem and nothing in the file said so.
    The capability is kept -- an adopter had a real, measured use for it,
    weighing an assembled instruction file that lives outside any repository --
    and now has to be asked for: ``include`` refuses an escape and names this
    list.
    """
    root = Path(root)
    base = root.resolve()
    seen: dict[Path, str] = {}
    for pattern in [*include, *external]:
        for match in sorted(glob.glob(pattern, root_dir=root, recursive=True,
                                      include_hidden=True)):
            path = root / match
            if path.is_file():
                seen.setdefault(path.resolve(), match)

    files = []
    for path, relative in sorted(seen.items(), key=lambda item: item[1]):
        try:
            text = path.read_text(errors="ignore")
        except OSError:
            continue
        files.append(
            Loaded(
                path=relative,
                raw=len(text.encode("utf-8")),
                size=len(flatten(text, strip).encode("utf-8")),
                # From the resolved path rather than from the list that asked:
                # an absolute pattern in `external` can land back inside the
                # root, and the report has to say where the bytes are.
                external=not path.is_relative_to(base),
            )
        )
    return Measurement(files=tuple(files), ceiling=ceiling)
