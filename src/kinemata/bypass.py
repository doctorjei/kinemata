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
  scanned ``project/workset.py`` alone and missed eight sites in six other
  modules (``42ece129``). A catch scoped to one module is not a catch.
* **It runs where the agent cannot reach it.** In CI, host-side. A check an
  agent can edit or skip is a reminder, not a catch.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator, Sequence

from .contract import BaseRegistry, Entry
from .prose import FILTERS, LITERAL_EXTRACTORS, STRING_FILTERS

#: Directories never worth scanning: not source, or not the project's.
SKIP_DIRS = frozenset(
    {
        ".git", ".venv", "venv", "node_modules", "__pycache__", ".mypy_cache",
        ".pytest_cache", ".ruff_cache", "build", "dist", ".tox", ".eggs",
    }
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


def _walk(root: Path, suffixes: Sequence[str]) -> Iterator[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix not in suffixes:
            continue
        if SKIP_DIRS & set(path.parts):
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

        table = STRING_FILTERS if strings_only else (FILTERS if code_only else {})
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


def unused(
    registry: BaseRegistry,
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".py",),
    exclude: Iterable[str] = (),
) -> list[str]:
    """Declared entries nothing *mentions*. **A review list, never a cut list.**

    ⚠ **This detects mention, not use, and the difference matters.**

    Validated against a labeled incident and it failed. kanibako-cli commit
    ``d8037cf5`` records that three declared keys "had no reader at all -- a set
    was accepted, persisted and read back, and nothing moved". This function
    missed all three, because each appears in the project's own declaring
    machinery: a key-name list and a key-to-path table. Those are mentions, not
    readers, and no amount of text matching tells them apart.

    Every declared entry is mentioned somewhere by construction -- that is what
    declaring *is* -- so without ``exclude`` this check is close to vacuous on
    precisely the registries it is meant to serve.

    :param exclude: path fragments holding the declaring machinery (key tables,
        inventories, the manifest itself). **Required in practice.** With the
        three declaring modules excluded, the incident above is found.

    Finding a real *reader* means tracing a value from resolution into
    behavior. That is dataflow analysis and deliberately out of scope here: a
    mechanism that claimed to do it syntactically would be lying about its reach.

    Why it survives as a review list rather than a gate: an entry can be real and
    unreferenced. "Supreme Law" is defined in canon and referenced nowhere in
    canon, because its consumer is a conversation. Auto-deleting on this signal
    destroys deliberate declarations.
    """
    root = Path(root)
    exclusions = tuple(exclude)
    entries = list(registry.entries())
    referenced: set[str] = set()

    for path in _walk(Path(root), suffixes):
        rel = str(path.relative_to(root))
        if any(fragment in rel for fragment in exclusions):
            continue
        text = path.read_text(errors="ignore")
        for found in registry.detect(text):
            # A reference inside the entry's own definition is not a use.
            entry = next((e for e in entries if e.id == found), None)
            if entry is not None and _is_home(rel, entry):
                continue
            referenced.add(found)

    return [e.id for e in entries if e.id not in referenced]
