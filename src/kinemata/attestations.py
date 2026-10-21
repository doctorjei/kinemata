"""Attestations: one finding at a time, declared correct, and why.

**Not the baseline, and the difference is the point.** A baseline accepts a
tree's existing debt so that only new findings fail; every record is due back
by its ``until``. Some findings are not debt at all: the text is right and the
heuristic that flagged it is wrong about this one instance. Recording those in
the baseline misdescribes them as something to fix, and they lapse with it.
Reported by ``yapyon`` 2026-10-17, whose bytes-literal spec writes the value
:shown:`badf00d0` -- a pure-hex code span, which ``claims`` reads as a commit.
Across every tree measured here, 1 such span in 80 was data and the other 79
were commits, so the rule is right and the instance is the exception.

So an attestation differs from a baseline record on exactly two things:

- it **states why the text is correct** -- the ``correct`` field, required and
  never blank, so an entry says what would have to change for it to be wrong,
  not merely that a finding was noisy;
- it **never lapses**, and instead **fails once its text is gone**: an
  attestation whose line was edited or deleted fails the run until it is
  removed, so the file cannot outlive what it vouched for -- the rule
  ``[[interpose]]`` applies to a marker that changed no verdict.

**Excusing nothing is not the same as its text being gone**, and only the
second fails. A run can be unable to produce the finding at all: unpacked from
an sdist there is no ``.git``, so no commit claim resolves or fails, and both of
this repository's own attestations excused nothing while the lines they vouch
for sat unchanged (2026-10-21). Failing there would turn a run that could not
check into a run that found something wrong. Such an attestation is reported
as **idle** instead; :func:`still_written` is the test.

An entry names a finding with the baseline record's own keys, so a record can
be moved across by adding ``correct``. It covers **every** finding with that
key, not one: identical text in one file is one statement, correct once.

The file is hand-written and nothing here writes it. It is the first kinemata
file in yapyon, read as a **record** -- literals only, nothing deferred -- and
it lives at :data:`ATTESTATIONS_PATH` beside the config.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import yapyon

from .baseline import normalize

#: Where a project's attestations live, relative to the directory holding its
#: config. Fixed rather than configurable: nobody has asked to move it, and a
#: key added later breaks nobody.
ATTESTATIONS_PATH = Path(".config") / "kinemata" / "attestations.yap"

#: What identifies a finding: the baseline record's keys, spelled as it spells
#: them on disk.
FINDING_KEYS = ("registry", "entry", "antipattern", "path", "text")

#: The field an entry cannot omit or leave blank.
CORRECT = "correct"

#: The one top-level key the file holds.
TOP = "attestations"


class AttestationError(Exception):
    """An attestations file that cannot be trusted.

    Refused, never skipped: a malformed entry that quietly excused nothing
    would leave a finding failing for reasons nobody could see, and one that
    quietly excused too much is an exemption nobody declared.
    """


@dataclass(frozen=True)
class Attestation:
    """One finding, declared correct."""

    registry: str
    entry_id: str
    antipattern: str
    path: str
    text: str
    correct: str

    @property
    def key(self) -> tuple[str, str, str, str, str]:
        """The baseline record's key, so the two match a finding identically."""
        return (self.registry, self.entry_id, self.antipattern, self.path,
                normalize(self.text))

    def __str__(self) -> str:
        return (f"{self.path}: {self.antipattern!r} ({self.registry}, "
                f"{self.entry_id}) -- {self.text[:60]}")


def load(path: Path) -> tuple[Attestation, ...]:
    """Every attestation ``path`` declares. A missing file declares none."""
    if not path.is_file():
        return ()
    try:
        document = yapyon.loads_record(path.read_text(encoding="utf-8"),
                                       source=str(path))
    except yapyon.AkanError as why:
        raise AttestationError(f"{path}: not a yapyon record: {why}") from why
    if not isinstance(document, dict) or set(document) != {TOP}:
        raise AttestationError(
            f"{path}: holds one key, {TOP!r}, a list of attestations"
        )
    entries = document[TOP]
    if not isinstance(entries, list):
        raise AttestationError(f"{path}: {TOP!r} is a list of attestations")
    found = tuple(_entry(path, index, raw) for index, raw in enumerate(entries))
    seen: dict[tuple[str, ...], int] = {}
    for index, attestation in enumerate(found):
        if attestation.key in seen:
            raise AttestationError(
                f"{path}: attestation {index + 1} repeats attestation "
                f"{seen[attestation.key] + 1}; one finding is attested once"
            )
        seen[attestation.key] = index
    return found


def _entry(path: Path, index: int, raw: object) -> Attestation:
    where = f"{path}: attestation {index + 1}"
    if not isinstance(raw, dict):
        raise AttestationError(f"{where} is not a mapping")
    wanted = (*FINDING_KEYS, CORRECT)
    unknown = sorted(set(raw) - set(wanted))
    missing = [key for key in wanted if key not in raw]
    if unknown or missing:
        problems = []
        if missing:
            problems.append(f"missing {', '.join(missing)}")
        if unknown:
            problems.append(f"unknown {', '.join(unknown)}")
        raise AttestationError(
            f"{where}: {'; '.join(problems)}. An attestation names a finding by "
            f"{', '.join(FINDING_KEYS)} and says why it is correct in {CORRECT!r}."
        )
    for key in wanted:
        if not isinstance(raw[key], str):
            raise AttestationError(f"{where}: {key!r} is a string")
    if not raw[CORRECT].strip():
        raise AttestationError(
            f"{where}: {CORRECT!r} is blank. Say why the flagged text is "
            "correct -- what would have to change for it to be wrong."
        )
    return Attestation(
        registry=raw["registry"],
        entry_id=raw["entry"],
        antipattern=raw["antipattern"],
        path=raw["path"],
        text=raw["text"],
        correct=raw[CORRECT],
    )


def still_written(attestation: Attestation, root: Path) -> bool:
    """Is the line this attestation vouches for still in its file?

    Compared the way a finding is keyed -- whitespace collapsed -- so an
    indentation change is the same line, and an edited word is not.
    """
    try:
        source = (root / attestation.path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    wanted = normalize(attestation.text)
    return any(normalize(line) == wanted for line in source.splitlines())


def keys(attestations: Iterable[Attestation]) -> dict[tuple[str, ...], Attestation]:
    """Each attestation by the key a finding is matched on."""
    return {attestation.key: attestation for attestation in attestations}
