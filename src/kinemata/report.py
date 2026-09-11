"""Turning a raw scan into something worth reading.

`scan` is deliberately dumb: it reports every match. That is right for a
mechanism and wrong for a report, because an antipattern can be a *domain word*
rather than a duplication signal.

Measured on kanibako-cli at HEAD, deriving antipatterns from constant values
produces 1,537 matches. Three constants account for 1,054 of them::

    KIND_WORKSET  = 'workset'    419 matches
    KANIBAKO_PATH = 'kanibako'   386 matches
    KIND_PROJECT  = 'project'    249 matches

Nobody "bypassed" the word *workset* 419 times in a program about worksets. By
contrast every genuine bypass found in the ``42ece129`` [0TMVXHC-Cx0001]
validation matched 6 sites or fewer. Frequency separates the two cleanly.

**Suppression is reported, never silent.** A check that quietly stops checking
is the inert-signal failure: it reports success while doing nothing. The report
says what it stopped looking at and why, so the reader can either accept it or
author a narrower pattern by hand.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .bypass import Bypass, scan
from .contract import BaseRegistry

#: An antipattern matching more sites than this is treated as a domain word.
#: Calibrated on kanibako-cli, where real bypasses ran to 6 sites and the
#: noisiest domain words to 419. Tune it per project; the gap is usually wide.
DEFAULT_MAX_SITES = 20


@dataclass(frozen=True)
class Suppressed:
    """An antipattern that matched too widely to be a duplication signal."""

    entry_id: str
    antipattern: str
    matches: int

    def __str__(self) -> str:
        return (
            f"{self.entry_id}: {self.antipattern!r} matched {self.matches} sites "
            f"-- treated as a domain word, not checked"
        )


@dataclass(frozen=True)
class Report:
    """What a scan found, and what it declined to look at."""

    bypasses: tuple[Bypass, ...] = ()
    suppressed: tuple[Suppressed, ...] = ()
    scanned: int = 0
    entries: int = 0

    @property
    def strong(self) -> tuple[Bypass, ...]:
        """Whole-literal matches. These are what should gate CI."""
        return tuple(b for b in self.bypasses if b.strength == "strong")

    @property
    def weak(self) -> tuple[Bypass, ...]:
        """Matches inside a longer literal -- often a different namespace."""
        return tuple(b for b in self.bypasses if b.strength == "weak")

    @property
    def clean(self) -> bool:
        """No strong signals. Weak ones are reported but do not gate."""
        return not self.strong

    def by_entry(self, only: str | None = None) -> dict[str, list[Bypass]]:
        source = self.bypasses if only is None else tuple(
            b for b in self.bypasses if b.strength == only
        )
        grouped: dict[str, list[Bypass]] = {}
        for hit in source:
            grouped.setdefault(hit.entry_id, []).append(hit)
        return grouped

    def text(self, *, verbose: bool = False) -> str:
        lines: list[str] = []
        grouped = self.by_entry(only="strong")

        for entry_id in sorted(grouped, key=lambda k: (-len(grouped[k]), k)):
            hits = grouped[entry_id]
            lines.append(f"{entry_id}  ({len(hits)} site{'s' if len(hits) > 1 else ''})")
            for hit in hits:
                lines.append(f"    {hit.path}:{hit.line}  {hit.text.strip()[:64]}")

        if self.weak:
            lines.append("")
            if verbose:
                lines.append("Weak (value inside a longer literal -- check the namespace):")
                for hit in self.weak:
                    lines.append(f"    {hit.path}:{hit.line}  {hit.entry_id}")
            else:
                lines.append(f"({len(self.weak)} weak signal(s); --verbose to list)")

        if self.suppressed and verbose:
            lines.append("")
            lines.append("Not checked (matched too widely to be a signal):")
            for item in sorted(self.suppressed, key=lambda s: -s.matches):
                lines.append(f"    {item}")
        elif self.suppressed:
            lines.append("")
            lines.append(
                f"({len(self.suppressed)} antipattern(s) suppressed as domain "
                f"words; --verbose to list)"
            )

        return "\n".join(lines)


def review(
    registry: BaseRegistry,
    root: str | Path,
    *,
    suffixes: Sequence[str] = (".py",),
    exclude: Sequence[str] = (),
    strings_only: bool | None = None,
    max_sites: int | None = DEFAULT_MAX_SITES,
) -> Report:
    """Scan, then drop antipatterns that matched too widely to mean anything.

    :param max_sites: suppression threshold; ``None`` disables suppression.
    """
    raw = scan(
        registry,
        root,
        suffixes=suffixes,
        exclude=exclude,
        strings_only=strings_only,
    )

    entries = len(list(registry.entries()))
    scanned = len({hit.path for hit in raw})

    if max_sites is None:
        return Report(bypasses=tuple(raw), scanned=scanned, entries=entries)

    counts = Counter((hit.entry_id, hit.antipattern) for hit in raw)
    noisy = {key for key, count in counts.items() if count > max_sites}

    kept = tuple(h for h in raw if (h.entry_id, h.antipattern) not in noisy)
    suppressed = tuple(
        Suppressed(entry_id=entry_id, antipattern=pattern, matches=counts[(entry_id, pattern)])
        for entry_id, pattern in sorted(noisy)
    )
    return Report(
        bypasses=kept,
        suppressed=suppressed,
        scanned=scanned,
        entries=entries,
    )
