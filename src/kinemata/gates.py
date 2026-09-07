"""Which checks must run, declared, so removing one is a visible change.

Every mechanism in this package can be turned off by deleting one line from a CI
workflow, and nothing notices. That is not hypothetical -- it is the failure this
project has hit most often, three times in a week, each time in a different
disguise:

* a registry declared over the wrong adapter produced no entries, so ``check``
  scanned for nothing and exited 0 **for six commits**;
* ``doc-check.py``'s exclusion list grew until it reported a tree clean that its
  replacement finds eight issues in;
* two numbers stated in prose -- an adoption cost and a test count -- had no
  oracle covering them and were both wrong when finally measured.

The shape is always the same: **the check reports success while checking less
than it says.** Green and inert are indistinguishable from outside.

So the gates a project requires are *declared*, and the declaration is checked
against the files that are supposed to run them. Deleting a step from CI then
fails the build instead of quietly passing it, and the only way to make it pass
is to delete the declaration too -- which is a visible edit in the diff, not an
absence.

**By §1's test this is a reminder, not a catch.** An agent can edit the
declaration and the workflow in one commit. What it buys is that silent removal
becomes a *stated* removal; what makes the surviving gates real is branch
protection with the job as a required status check, which lives outside the repo.

**What it does not see**, stated because a checker that overstates its reach is
the problem it is trying to solve: a step present but disabled by ``if:``, a job
nobody triggers, or a command that runs and checks nothing. This verifies that
the text is there and uncommented. It does not parse YAML -- the core takes no
runtime dependencies -- and it cannot tell a live step from a decorative one.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

#: Where CI definitions live when a project does not say otherwise.
WORKFLOW_DIR = ".github/workflows"

#: Suffixes a workflow file may carry. Both spellings are current in the wild.
WORKFLOW_SUFFIXES = (".yml", ".yaml")


@dataclass(frozen=True)
class Gate:
    """A check the project declares must run, and where it must be found."""

    command: str
    #: Files that must contain it. Empty means every workflow under
    #: ``.github/workflows``. Satisfied by **any** of them, because a project
    #: may split its checks across jobs or files.
    where: tuple[str, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Absent:
    """A declared gate that nothing was found to run."""

    gate: Gate
    reason: str

    def __str__(self) -> str:
        tail = f" -- {self.gate.note}" if self.gate.note else ""
        return f"{self.gate.command!r} does not run: {self.reason}{tail}"


@dataclass(frozen=True)
class Inventory:
    """What was declared, what was found, and what was read to decide."""

    verified: tuple[Gate, ...] = ()
    absent: tuple[Absent, ...] = ()
    #: Files actually read. Reported because "found in none of them" and
    #: "there were none to read" are different failures.
    searched: tuple[str, ...] = ()

    @property
    def declared(self) -> int:
        return len(self.verified) + len(self.absent)

    @property
    def failed(self) -> bool:
        return bool(self.absent)

    def text(self) -> str:
        return "\n".join(f"  {item}" for item in self.absent)


def _uncommented(text: str) -> str:
    """The file with whole-line comments removed.

    Enough to keep a commented-out step from satisfying its own declaration,
    which is the way a gate most plausibly gets disabled: someone comments it
    out to unblock a merge and never restores it. Not a YAML parser, and not
    claiming to be one.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _workflows(root: Path) -> list[Path]:
    directory = root / WORKFLOW_DIR
    if not directory.is_dir():
        return []
    return sorted(
        path for path in directory.iterdir()
        if path.is_file() and path.suffix in WORKFLOW_SUFFIXES
    )


def enforced(root: str | Path, gates: tuple[Gate, ...]) -> Inventory:
    """Check each declared gate against the files meant to run it."""
    root = Path(root)
    verified: list[Gate] = []
    absent: list[Absent] = []
    searched: set[str] = set()

    for gate in gates:
        if gate.where:
            targets = [root / fragment for fragment in gate.where]
            missing = [str(p.relative_to(root)) for p in targets if not p.is_file()]
            if missing:
                absent.append(Absent(gate, f"declared in {', '.join(missing)}, "
                                           f"which does not exist"))
                continue
        else:
            targets = _workflows(root)
            if not targets:
                absent.append(
                    Absent(gate, f"no workflow files under {WORKFLOW_DIR}")
                )
                continue

        found = False
        for path in targets:
            searched.add(str(path.relative_to(root)))
            try:
                body = _uncommented(path.read_text(errors="ignore"))
            except OSError:
                continue
            if gate.command in body:
                found = True
                break

        if found:
            verified.append(gate)
        else:
            where = ", ".join(str(p.relative_to(root)) for p in targets)
            absent.append(Absent(gate, f"not found in {where}"))

    return Inventory(
        verified=tuple(verified),
        absent=tuple(absent),
        searched=tuple(sorted(searched)),
    )
