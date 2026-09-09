"""Command line: the same finding, delivered two ways.

One scan, two consumers -- the split this project is organized around:

``kinemata ids``
    The standing reminder. What already exists, small enough to load.

``kinemata review``
    The targeted reminder. What you are about to duplicate. **Exit 0 always**:
    it advises, and an agent may act on it or not. Meant to run in-box, before
    or during the work.

``kinemata check``
    The catch. Same scan, non-zero exit on a strong finding. Meant to run
    host-side or in CI, **where an agent cannot edit or skip it**. A check the
    agent controls is a reminder wearing a catch's clothes.

``kinemata context``
    The other budget. ``ids`` bounds the registry's own projection, which is the
    smallest thing an agent reads; this bounds the instruction layer, which is
    where context overwhelm actually happens. Gates.

``kinemata baseline``
    The ratchet's control surface: what a project has accepted, and the one
    command that changes it. ``check`` reads the baseline; nothing else does.
    ``review`` deliberately ignores it -- the ratchet governs the gate, not the
    advice, and an advisory scan that hid known problems would be lying about
    the tree.

The difference between the last two is the exit code and where they run, not
the analysis. That is deliberate: two mechanisms that could disagree eventually
will.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

from .baseline import Baseline, BaselineError, record
from .bypass import Bypass, crossings, strays, unused
from .claims import verify
from .config import CONFIG_NAMES, ConfigError, Settings, find_config, load
from .context import measure
from .contract import BaseRegistry
from .gates import WORKFLOW_DIR, enforced
from .literals import clusters
from .projection import project
from .report import DEFAULT_MAX_SITES, Report, review


def _settings(args: argparse.Namespace) -> Settings:
    """The config to run against, announced when it came from somewhere else.

    ``find_config`` walks upward, which is convenience in one place and a
    blindness leak in another: a role meant to see one subtree, running a gate
    inside it, silently picks up the parent's config and everything that config
    points at. Found on a real run, where the workaround was a second config
    file -- a second carrier of the same declarations.

    The walk is kept, because narrowing it to a repository boundary would have
    broken the one integration this project has done against a tree that is not
    a repository. What changes is that an **inherited** config says so. The
    ordinary case -- a config in this directory, or one named with ``-c`` --
    stays quiet, so the line means something when it appears.
    """
    path = Path(args.config) if args.config else find_config()
    if path is None:
        raise ConfigError(
            f"no {CONFIG_NAMES[0]} found (searched upward from the current directory)"
        )
    if not args.config and path.parent != Path.cwd().resolve():
        print(f"warning: using config from {path}, above the current directory",
              file=sys.stderr)
    return load(path)


#: Roots already announced in this run. A root scanned once per registry would
#: otherwise report the same crossing once per registry.
_ANNOUNCED: set[Path] = set()


def _announce(target: Path) -> None:
    """Say so when the scan leaves the tree it was pointed at.

    The walk follows symlinked directories on purpose -- refusing to scanned an
    assembled tree as empty and called it clean. The cost is that a root can be
    a name for material living somewhere else, and a reader who assumed the root
    bounds the scan would never learn otherwise. **Not suppressed by
    ``--quiet``:** this is the scope of the check, not one of its findings.
    """
    if target in _ANNOUNCED:
        return
    _ANNOUNCED.add(target)
    for crossing in crossings(target):
        print(f"warning: scan follows {crossing}, outside the tree given",
              file=sys.stderr)


def _target(args: argparse.Namespace, settings: Settings) -> Path:
    """Where to scan, announcing anything the scan reaches outside it.

    A relative path resolves against the **project root**, not the working
    directory. Otherwise ``kinemata check src`` run from a parent directory
    silently scans a different tree and reports a clean or bogus result -- which
    it did, on the first run of this command.

    The announcement is wired here rather than into each command because this is
    the one place every scanning command passes through; a command added later
    inherits it instead of having to remember it.
    """
    if not args.path:
        target = settings.root
    else:
        given = Path(args.path)
        target = given if given.is_absolute() else settings.root / given
    _announce(target)
    return target


def _note_unfitted(settings: Settings) -> None:
    """Say that a declared registry bound to nothing, then carry on.

    This command does not need a registry, so a broken one is not its failure --
    but staying silent would leave a reader thinking the whole config is doing
    what it says. `check` still refuses, so nothing is lost from CI.
    """
    for message in settings.unfitted:
        print(f"note: {message}", file=sys.stderr)


def _max_sites(args: argparse.Namespace, settings: Settings) -> int | None:
    if args.max_sites is not None:
        return None if args.max_sites < 0 else args.max_sites
    if settings.max_sites is not None:
        return settings.max_sites
    return DEFAULT_MAX_SITES


def _needs_registries(settings: Settings, doing: str) -> None:
    """Refuse a registry-shaped command on a config that declares none.

    The loader accepts such a config now, because a project may want ``claims``
    or ``context`` alone and inventing a registry to satisfy a loader is a
    fiction in a tool arguing that declarations should be true. The refusal
    moves here rather than disappearing: scanning nothing and exiting 0 is the
    inert signal, and it reads exactly like a clean tree.
    """
    if settings.unfitted:
        # Deferred from load, not forgiven. A registry whose adapter recognized
        # nothing would scan for nothing and pass, so the command that would do
        # the scanning is exactly where this has to stop.
        raise ConfigError(" ".join(settings.unfitted))
    if not settings.registries:
        raise ConfigError(
            f"no [[registry]] declared, so there is nothing to {doing}. "
            "Declare one, or run a command that does not need one -- `claims` "
            "and `context` check a config that declares no registry at all."
        )


def cmd_ids(args: argparse.Namespace) -> int:
    settings = _settings(args)
    _needs_registries(settings, "project")
    over_budget = False
    for registry in settings.registries:
        if args.registry and registry.name != args.registry:
            continue
        rendered = project(registry)
        if len(settings.registries) > 1 and not args.quiet:
            print(f"# {registry.name} ({rendered.count} entries, {rendered.size} B)")
        print(rendered.text, end="")
        for violation in rendered.violations:
            print(f"warning: {violation}", file=sys.stderr)
            over_budget = True
    return 1 if (over_budget and args.strict) else 0


def _run_review(args: argparse.Namespace) -> tuple[Settings, list[tuple[str, Report]]]:
    """Shared body of review, check and baseline: one scan per registry.

    Returns the reports rather than printing them, because ``check`` has to put
    the findings through the baseline before deciding what is worth showing.
    """
    settings = _settings(args)
    _needs_registries(settings, "scan for")
    reports: list[tuple[str, Report]] = []

    for registry in settings.registries:
        if args.registry and registry.name != args.registry:
            continue
        reports.append((
            registry.name,
            review(
                registry,
                _target(args, settings),
                suffixes=registry.suffixes or settings.suffixes,
                exclude=settings.exclude,
                max_sites=_max_sites(args, settings),
            ),
        ))

    return settings, reports


def _print_reports(
    settings: Settings, reports: list[tuple[str, Report]], *, verbose: bool
) -> None:
    for name, report in reports:
        body = report.text(verbose=verbose)
        if body.strip():
            if len(settings.registries) > 1:
                print(f"# {name}")
            print(body)


def _strong(reports: list[tuple[str, Report]]) -> list[tuple[str, Bypass]]:
    """Every gating finding, tagged with the registry that produced it.

    The registry name travels with the finding because a baseline record has to
    say which registry accepted it -- two registries can declare the same entry
    id, and a reviewer reading the file needs to know which one is exempted.
    """
    return [(name, hit) for name, report in reports for hit in report.strong]


def _silent(settings: Settings) -> tuple[int, int]:
    """How many declared entries nothing can be reported about, and of how many.

    An entry with no antipattern is in the projection and invisible to the
    scan: a reader sees it declared and reasonably concludes the check covers
    it. Measured on httpie, which declares ``HTTP_GET = 'GET'`` and
    ``HTTP_POST = 'POST'`` on adjacent lines while a lexer writes both as
    literals two lines apart -- ``check`` reports POST and says nothing about
    GET, because three characters is under the minimum value length.

    **The threshold is not the defect and does not move**; it was measured, and
    lowering it matches everything. The defect was that the silence had no
    voice, which is the same failure as an exemption list nobody prints.
    """
    total = quiet = 0
    for registry in settings.registries:
        for entry in registry.entries():
            total += 1
            if not entry.antipatterns:
                quiet += 1
    return quiet, total


def _report_silent(settings: Settings) -> None:
    """Printed by both scanning commands, and not suppressed by ``--quiet`` --
    the same rule the exemption, gate and promise counts follow."""
    quiet, total = _silent(settings)
    if quiet:
        print(
            f"silent: {quiet} of {total} declared entry(s) carry no antipattern, "
            "so no re-derivation of them can be reported. Usually a value too "
            "short or too generic to match on."
        )


def cmd_review(args: argparse.Namespace) -> int:
    settings, reports = _run_review(args)
    _print_reports(settings, reports, verbose=args.verbose)
    strong = sum(len(report.strong) for _, report in reports)
    weak = sum(len(report.weak) for _, report in reports)
    if not strong and not weak:
        if not args.quiet:
            print("Nothing already declared looks re-derived here.")
        _report_silent(settings)
        return 0
    if not args.quiet:
        print()
        print(
            f"{strong} thing(s) already exist that this code spells out. "
            f"Route through them rather than re-deriving."
        )
    _report_silent(settings)
    return 0  # advisory, always


def cmd_clusters(args: argparse.Namespace) -> int:
    """The opposite question to ``review``: what wants a declaration.

    Called ``undeclared`` until 2026-09-08, when the name went to the
    closed-world catch it had been shadowing. The two questions are genuinely
    different: this one finds *text* that repeats with no declared home, which
    is a judgment; the catch finds an *identifier* a closed registry does not
    declare, which is an error.

    Advisory, and it stays advisory. ``review`` and ``check`` answer whether a
    *declared* thing was re-derived, which is a violation. This answers whether
    text repeats with no declared home, which is a judgment -- the same text in
    two places may be two ideas that happen to coincide. It reports the fork and
    lets a reader take it.
    """
    settings = _settings(args)
    known: set[str] = set()
    for registry in settings.registries:
        for entry in registry.entries():
            known.add(entry.id)
            value = entry.extra.get("value")
            if isinstance(value, str):
                known.add(value)

    found = clusters(
        _target(args, settings),
        suffixes=settings.suffixes,
        exclude=settings.exclude,
        declared=known,
    )
    body = found.text(verbose=args.verbose)
    total = len(found.composed) + len(found.strong)
    if not body.strip():
        if not args.quiet:
            print("No repeated text without a declared home.")
        return 0
    print(body)
    if not args.quiet:
        print()
        print(
            f"{total} piece(s) of text repeat with nothing declaring them. "
            f"Declare one, or leave them apart on purpose."
        )
    return 0  # advisory, always


def cmd_undeclared(args: argparse.Namespace) -> int:
    """Catch A: an identifier the tree uses and a closed registry does not declare.

    This is the operation ``design.md`` §5 calls the catch — the one that raises
    rather than advises, and the reason a registry is a mechanism rather than a
    convention. It had **no command for the whole life of the project**: the
    function existed, was tested, and was reachable from nothing, while the name
    ``undeclared`` belonged to an advisory scan over repeated text. Wired
    2026-09-08.

    **Closed gates; open advises.** A legacy codebase cannot close on day one,
    so an open registry routes undeclared identifiers to a review list and exits
    0. Closing is the ratchet.

    **Refuses when no registry can answer.** Only a registry that recognizes its
    own identifiers can say what is undeclared, and today that is a mapping
    registry with a ``syntax``. Pointing this at a project whose registries
    cannot answer and exiting 0 would report "nothing undeclared" about a
    question nobody asked -- the inert signal this project exists to catch.
    """
    settings = _settings(args)
    _needs_registries(settings, "check against")
    target = _target(args, settings)

    answered: list[tuple[object, list[object]]] = []
    for registry in settings.registries:
        try:
            found = strays(
                registry,
                target,
                suffixes=settings.suffixes,
                exclude=settings.exclude,
            )
        except NotImplementedError:
            continue  # cannot recognize an identifier; reported below
        answered.append((registry, found))

    if not answered:
        raise ConfigError(
            "no declared registry can recognize its own identifiers, so none "
            "can say what is undeclared. This needs a registry with an "
            "identifier syntax (today: kind = \"yaml-mapping\" with `syntax`). "
            "Running anyway would report nothing and mean nothing."
        )

    failed = 0
    for registry, found in answered:
        closed = getattr(registry, "closed", False)
        label = "closed" if closed else "open"
        if not found:
            if not args.quiet:
                print(f"# {registry.name} ({label}): no undeclared identifiers.")
            continue
        print(f"# {registry.name} ({label})")
        for stray in found:
            print(f"  {stray}")
        if closed:
            failed += len(found)

    if failed:
        print(
            f"\nFAIL: {failed} use(s) of an identifier no closed registry "
            "declares. Declare it, or open the registry deliberately.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_unused(args: argparse.Namespace) -> int:
    """Declared entries nothing in the tree mentions. **Advisory, always.**

    Never a gate, and this is not timidity. An entry can be real and
    unreferenced: "Supreme Law" is declared in kanibako's canon and referenced
    nowhere in it, because its consumer is a conversation rather than a
    document. Every disuse detector inherits that blind spot, so this one emits
    a review list and a human takes the decision.

    **Registries that cannot answer are named, not dropped.** Two refuse: one
    with no ``machinery`` and no ``home``, because every declared entry is
    mentioned by whatever declares it; and one whose entries are declared to be
    absent, where the whole list comes back and every line of it is the
    convention being kept. Reporting the registries that answered while staying
    silent about the rest would put a clean line in front of a reader with no way
    to know the check skipped half the project.
    """
    settings = _settings(args)
    _needs_registries(settings, "look for unused entries in")
    target = _target(args, settings)

    answered: list[tuple[BaseRegistry, list[str]]] = []
    refused: list[str] = []
    for registry in settings.registries:
        try:
            found = unused(
                registry,
                target,
                suffixes=registry.suffixes or settings.suffixes,
                exclude=settings.exclude,
            )
        except ValueError as exc:
            refused.append(str(exc))
            continue
        answered.append((registry, found))

    if not answered:
        raise ConfigError(
            "no declared registry can say what is unused. "
            + " ".join(refused)
        )

    total = 0
    for registry, found in answered:
        if not found:
            if not args.quiet:
                print(f"# {registry.name}: every declared entry is mentioned.")
            continue
        print(f"# {registry.name}")
        for identifier in found:
            print(f"  {identifier}")
        total += len(found)

    for message in refused:
        print(f"skipped: {message}", file=sys.stderr)

    if total and not args.quiet:
        print()
        print(
            f"{total} declared entry(s) nothing mentions outside the files that "
            "declare them. **A review list, never a cut list** -- this detects "
            "mention, not use, and an entry whose consumer is not a file in "
            "this tree looks identical to one nobody wants."
        )
    return 0  # advisory, always


def cmd_claims(args: argparse.Namespace) -> int:
    """Falsify what the project asserts about itself: in prose, and in CI.

    Gates, unlike ``undeclared``. A missing file is a fact, not a judgment.

    Prints the number of claims checked even when everything resolves, because
    "all resolve" and "nothing was looked at" read identically otherwise -- and
    this project has already shipped one check that passed by examining nothing.

    The gate inventory rides here rather than in a command of its own. A check
    that verifies other checks are wired up is worthless if nothing guarantees
    *it* runs, and adding a fifth command would have created exactly that
    regress. Folded into an existing gate, it runs wherever that gate does.
    """
    settings = _settings(args)
    _note_unfitted(settings)
    found = verify(
        _target(args, settings),
        suffixes=settings.claim_suffixes,
        exclude=settings.exclude,
        historical=settings.historical,
        counts=settings.counts,
        resolve_in=settings.resolve_in,
        commits_in=settings.commits_in,
        promised=settings.promised,
        external=settings.external,
        timeout=settings.external_timeout,
    )
    inventory = enforced(settings.root, settings.gates)

    body = "\n".join(part for part in (found.text(), inventory.text()) if part.strip())
    if body.strip():
        print(body)

    # Printed whenever any gate is declared, and not suppressed by --quiet: a
    # declaration list that shrinks to nothing is the one failure this check
    # cannot fail on, so the number has to be in front of a reader.
    if inventory.declared:
        print(f"gates: {len(inventory.verified)} of {inventory.declared} "
              f"declared check(s) run in {', '.join(inventory.searched) or 'nothing'}")

    # Same rule as the gate count and the exemption count, for the same reason:
    # a promise is a claim nobody is checking, so the number of them is not
    # optional reading. A project that stops noticing its deferrals has an
    # allowlist.
    if settings.promised:
        print(f"promises: {len(settings.promised)} declared, "
              f"{len(found.deferred)} claim(s) held open")

    if found.failed or inventory.failed:
        parts = []
        if found.broken:
            parts.append(
                f"{len(found.broken)} of {found.checked} claim(s) do not resolve"
            )
        if found.kept:
            parts.append(
                f"{len(found.kept)} promised path(s) now exist and are still declared"
            )
        if found.uncovered:
            parts.append(
                f"{len(found.uncovered)} promised path(s) no document cites"
            )
        if found.overdue:
            parts.append(f"{len(found.overdue)} promised path(s) past their date")
        if found.blocked:
            parts.append(f"{len(found.blocked)} declared check(s) could not run")
        if inventory.absent:
            parts.append(f"{len(inventory.absent)} declared gate(s) do not run")
        print(f"\nFAIL: {'; '.join(parts)}.", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"{found.checked} documentation claim(s) checked, all resolve.")
    return 0


#: The starter config. Documentation-only by default, because that is the
#: cheapest adoption and needs no knowledge of which adapters exist: it declares
#: `[claims]`, which checks every path, link and commit the prose asserts.
#: Everything requiring a decision is commented out with the decision named.
STARTER_CONFIG = '''\
# Written by `kinemata init`. Every section below is optional except that the
# file must declare at least one check -- a config nothing can fail is not a
# configuration.

[project]
root = "."
exclude = ["build/", "dist/"]

# Falsify what the documentation says about this tree: paths that do not exist,
# links that do not resolve, commits that are not in history. Needs no registry.
[claims]
suffixes = [".md"]
# historical = ["archives/"]   # a record of what was true is not a stale claim
# promised = []                # paths a design will produce; fails once they exist

# A registry is one declared place per fact, and `check` fails on code that
# re-derives one. Declare the constants module you already have:
#
# [[registry]]
# name = "constants"
# kind = "python-constants"
# modules = ["src/pkg/constants.py"]
#
# Adopting on a codebase that already fails: run `kinemata baseline --record`
# once, locally, and commit the file. Never from CI.

# A ceiling on what a session loads. No default: measure what you carry today,
# declare that, then drive it down.
#
# [context]
# include = ["README.md", "docs/**/*.md"]
# budget = 0
'''

#: Gate rows matching the workflow ``init --ci`` writes. Kept beside it because
#: ``claims`` verifies the pair: if the two drift, our own gate fails.
STARTER_GATES = '''
# Checks this project requires, verified against the file meant to run them.
# A deleted or commented-out step fails `kinemata claims`.
[[gate]]
command = "kinemata claims"
note = "documentation, and this inventory"

[[gate]]
command = "kinemata check"
note = "code that re-derives a declared fact"
'''

#: Through ``WORKFLOW_DIR`` rather than spelled again: `kinemata clusters`
#: reported the second spelling the moment this was written.
WORKFLOW_PATH = f"{WORKFLOW_DIR}/kinemata.yml"

STARTER_WORKFLOW = '''\
# Written by `kinemata init --ci`.
#
# A workflow file lives in the repo, so an agent with write access can edit it:
# on its own this is a reminder, not a catch. Branch protection with this job as
# a REQUIRED status check is what promotes it, because a deleted job then blocks
# the merge instead of passing silently. See examples/ci-github-actions.yml in
# kinemata for the longer argument.

name: kinemata

on:
  push:
    branches: [main]
  pull_request:

jobs:
  kinemata:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.13"
      - name: Install the checker
        run: pip install "kinemata @ git+https://github.com/doctorjei/kinemata@main"
      - name: Documentation claims
        run: kinemata claims
      - name: Gate on strong bypasses
        run: kinemata check
'''


def cmd_init(args: argparse.Namespace) -> int:
    """Write a config a project can run today, and optionally the CI to run it.

    **The friction this answers was measured, not imagined.** Gating one real
    artifact set by hand took a config written from scratch against knowledge of
    which adapters exist, ten count tables, and a registry declared only to
    satisfy a loader rule that no longer exists. The first minute of adoption
    should not require reading the source.

    It refuses to overwrite. A scaffold that silently replaces a config someone
    tuned would be the worst possible first impression for a tool whose argument
    is that declarations should be true.
    """
    root = Path(args.path or ".").resolve()
    written: list[Path] = []

    config = root / CONFIG_NAMES[0]
    workflow = root / WORKFLOW_PATH
    for existing in (config, workflow if args.ci else None):
        if existing is not None and existing.exists():
            raise ConfigError(
                f"{existing} already exists. Delete it or edit it by hand -- "
                "this writes a starting point, it does not merge into one."
            )

    body = STARTER_CONFIG + (STARTER_GATES if args.ci else "")
    config.write_text(body)
    written.append(config)

    if args.ci:
        workflow.parent.mkdir(parents=True, exist_ok=True)
        workflow.write_text(STARTER_WORKFLOW)
        written.append(workflow)

    for path in written:
        print(f"wrote {path.relative_to(root)}")
    print("\nRun `kinemata claims` now; it needs no registry. Then declare a "
          "registry and run `kinemata check`.")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Weigh what a session loads against its declared ceiling.

    Gates, because a ceiling exists to be enforced. Running it with nothing
    declared is a configuration error rather than a pass: a command that
    measures an empty set and exits 0 is the inert signal again.
    """
    settings = _settings(args)
    _note_unfitted(settings)
    if settings.context is None:
        raise ConfigError(
            "no [context] declared: nothing says what a session loads. "
            "Declare include globs and a budget, or do not run this."
        )

    found = measure(
        settings.root,
        settings.context.include,
        ceiling=settings.context.budget,
        strip=settings.context.strip,
    )
    print(found.text(verbose=args.verbose))
    if found.failed:
        print(
            f"\nFAIL: what a session loads is {found.over} B over its ceiling.",
            file=sys.stderr,
        )
        return 1
    return 0


def _narrowed(args: argparse.Namespace) -> str | None:
    """Why this scan does not cover the whole project, if it does not.

    A baseline describes the project. Rewriting it from a scan of one registry
    or one directory would silently drop every record the scan could not have
    produced -- the exemption list would shrink, `check` would go red on code
    nobody touched, and the fix would look like re-recording again.
    """
    if args.registry:
        return f"--registry {args.registry}"
    if args.path:
        return f"a path argument ({args.path})"
    return None


def cmd_check(args: argparse.Namespace) -> int:
    """The gate, ratcheted: fail on findings the baseline does not cover.

    On a codebase with no baseline this is what it always was. On one with a
    baseline it fails on *increase*, which is the only way the gate can be
    adopted by a project that is already failing it -- kanibako-cli starts at
    111 strong findings, and a wall of red on day one gets the gate switched off.
    """
    settings, reports = _run_review(args)
    baseline = Baseline.load(settings.baseline)
    split = baseline.split(_strong(reports))

    new_by_registry: dict[str, list[Bypass]] = {}
    for name, hit in split.new:
        new_by_registry.setdefault(name, []).append(hit)

    # Weak signals ride along unfiltered: they never gated, so the baseline has
    # no business hiding them.
    filtered = [
        (name, Report(
            bypasses=tuple(new_by_registry.get(name, ())) + report.weak,
            suppressed=report.suppressed,
            scanned=report.scanned,
            entries=report.entries,
        ))
        for name, report in reports
    ]
    _print_reports(settings, filtered, verbose=args.verbose)
    _report_silent(settings)

    # Printed on every run that has a baseline at all, and **not suppressed by
    # --quiet**: an exemption list nobody reads the size of is how an allowlist
    # rots. The number is the point of printing it.
    if baseline.exists:
        note = (f"\nbaseline: {baseline.size} accepted finding(s) in "
                f"{baseline.path.name}, until {baseline.until}")
        if baseline.by:
            note += f" ({baseline.by})"
        # Under a narrowed scan the unscanned records are simply absent from the
        # findings, which is indistinguishable from fixed. Saying nothing beats
        # reporting a project's whole baseline as stale.
        if split.stale and not _narrowed(args):
            gone = sum(item.count for item in split.stale)
            note += (
                f"; {gone} no longer present "
                f"(`kinemata baseline --prune` drops them)"
            )
        print(note)

    # A lapsed baseline fails even with nothing new, because that is the whole
    # point of the date: the exemptions are still in force and nobody has looked
    # at them since the day somebody said they would.
    if baseline.exists and baseline.lapsed():
        print(
            f"\nFAIL: the baseline lapsed on {baseline.until}. Its "
            f"{baseline.size} exemption(s) are still in force and nobody has "
            "decided again. Drive them down, or re-record with a new --until.",
            file=sys.stderr,
        )
        return 1

    if split.new:
        label = "new bypass(es)" if baseline.exists else "bypass(es)"
        print(f"\nFAIL: {len(split.new)} {label} of declared things.", file=sys.stderr)
        return 1
    return 0


def cmd_baseline(args: argparse.Namespace) -> int:
    """Show what is accepted; ``--record`` and ``--prune`` change it.

    Showing is the default because recording is how the gate goes quiet. A
    command that silences findings should never be the thing that happens when
    somebody types the noun to see what it means.
    """
    if args.record and args.prune:
        print("error: --record and --prune do different things; pick one",
              file=sys.stderr)
        return 2

    scope = _narrowed(args)
    if scope and (args.record or args.prune):
        print(
            f"error: refusing to rewrite the baseline from a scan limited by "
            f"{scope}. Every record the scan could not produce would be dropped.",
            file=sys.stderr,
        )
        return 2

    settings, reports = _run_review(args)
    findings = _strong(reports)
    try:
        baseline = Baseline.load(settings.baseline)
    except BaselineError:
        # `--record` replaces the file, so refusing to read the old one would
        # make the instruction it prints impossible to follow -- which is what
        # happened the first time a dateless baseline met the date requirement.
        # Anything else still refuses: a baseline you cannot read must not be
        # treated as an empty one while it is still exempting findings.
        if not args.record:
            raise
        print(f"warning: {settings.baseline.name} could not be read; recording "
              "a fresh one over it", file=sys.stderr)
        baseline = Baseline(path=settings.baseline)
    split = baseline.split(findings)

    if args.record:
        if not args.until:
            raise BaselineError(
                "--record needs --until YYYY-MM-DD: the date this list stops "
                "being accepted without somebody deciding again. A baseline is "
                "an allowlist, and one that cannot lapse is a decision nobody "
                "revisits."
            )
        try:
            until = date.fromisoformat(args.until)
        except ValueError as exc:
            raise BaselineError(
                f"--until {args.until!r} is not a date. Write it as YYYY-MM-DD."
            ) from exc
        fresh = record(settings.baseline, findings, until=until,
                       by=args.by or "", note=args.note or "")
        delta = fresh.size - baseline.size
        fresh.save()
        change = f" ({delta:+d} against the previous baseline)" if baseline.exists else ""
        print(f"Recorded {fresh.size} accepted finding(s){change} in {settings.baseline}.")
        if delta > 0:
            # Growth is the failure mode. Say so at the moment it happens, since
            # the alternative is noticing it in a diff nobody reads closely.
            print(f"{delta} finding(s) newly accepted. Every one is now exempt "
                  f"from `check` until it is fixed and the baseline re-recorded.")
        return 0

    if args.prune:
        kept = record(settings.baseline, split.accepted, until=baseline.until,
                      by=baseline.by, note=baseline.note)
        dropped = baseline.size - kept.size
        kept.save()
        print(f"Dropped {dropped} record(s) no longer present; "
              f"{kept.size} accepted finding(s) remain.")
        return 0

    if not baseline.exists:
        print(f"No baseline recorded ({settings.baseline} does not exist).")
        print(f"`kinemata baseline --record` would accept {len(findings)} finding(s).")
        return 0

    print(f"{baseline.path}: {baseline.size} accepted finding(s).")
    if split.new:
        print(f"{len(split.new)} finding(s) not accepted -- `check` fails on these.")
    if scope:
        print(f"Scan limited by {scope}; nothing here is a statement about the rest.")
    elif split.stale:
        dropped = sum(item.count for item in split.stale)
        print(f"{dropped} accepted finding(s) no longer present "
              f"-- `--prune` drops them.")
        if args.verbose:
            for item in split.stale:
                print(f"    {item}")
    if args.verbose:
        for item in sorted(baseline.accepted, key=lambda r: r.key):
            print(f"    {item}")
    return 0


def _common() -> argparse.ArgumentParser:
    """Flags accepted both before and after the subcommand.

    Without this, ``kinemata ids -r keys`` fails while ``kinemata -r keys ids``
    works -- an ordering rule nobody remembers and every user gets wrong.
    """
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-c", "--config", help=f"path to {CONFIG_NAMES[0]}")
    common.add_argument("-r", "--registry", help="limit to one registry by name")
    common.add_argument("-q", "--quiet", action="store_true")
    common.add_argument("-v", "--verbose", action="store_true",
                        help="list weak signals and suppressed antipatterns")
    common.add_argument("--max-sites", type=int, default=None,
                        help="suppress antipatterns matching more sites than this "
                             "(negative disables suppression)")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common()
    parser = argparse.ArgumentParser(
        prog="kinemata",
        parents=[common],
        description="One declared place per fact. Find what re-derives it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    ids = sub.add_parser("ids", parents=[common],
                         help="the projection: what already exists")
    ids.add_argument("--strict", action="store_true",
                     help="exit non-zero if a projection is over budget")
    ids.set_defaults(func=cmd_ids)

    rev = sub.add_parser("review", parents=[common],
                         help="advisory: what this code re-derives")
    rev.add_argument("path", nargs="?", help="limit the scan to this path")
    rev.set_defaults(func=cmd_review)

    clu = sub.add_parser("clusters", parents=[common],
                         help="advisory: repeated text with no declared home")
    clu.add_argument("path", nargs="?", help="limit the scan to this path")
    clu.set_defaults(func=cmd_clusters)

    und = sub.add_parser("undeclared", parents=[common],
                         help="gate: an identifier a closed registry does not "
                              "declare (advisory while the registry is open)")
    und.add_argument("path", nargs="?", help="limit the scan to this path")
    und.set_defaults(func=cmd_undeclared)

    unu = sub.add_parser("unused", parents=[common],
                         help="advisory: declared entries nothing mentions "
                              "(a review list, never a cut list)")
    unu.add_argument("path", nargs="?", help="limit the scan to this path")
    unu.set_defaults(func=cmd_unused)

    clm = sub.add_parser("claims", parents=[common],
                         help="gate: fail on a documentation claim that does not resolve")
    clm.add_argument("path", nargs="?", help="limit the scan to this path")
    clm.set_defaults(func=cmd_claims)

    chk = sub.add_parser("check", parents=[common],
                         help="gate: fail on a strong bypass the baseline does "
                              "not already accept")
    chk.add_argument("path", nargs="?", help="limit the scan to this path")
    chk.set_defaults(func=cmd_check)

    ctx = sub.add_parser("context", parents=[common],
                         help="gate: what a session loads, against its ceiling")
    ctx.set_defaults(func=cmd_context)

    ini = sub.add_parser("init", parents=[common],
                         help=f"write a starting {CONFIG_NAMES[0]}, and "
                              "optionally the CI to run it")
    ini.add_argument("path", nargs="?", help="where to write (default: here)")
    ini.add_argument("--ci", action="store_true",
                     help="also write a workflow, and declare it as a gate")
    ini.set_defaults(func=cmd_init)

    base = sub.add_parser("baseline", parents=[common],
                          help="the ratchet: findings accepted as pre-existing")
    base.add_argument("path", nargs="?", help="limit the scan to this path")
    base.add_argument("--record", action="store_true",
                      help="accept every current finding, replacing the baseline")
    base.add_argument("--prune", action="store_true",
                      help="drop records whose finding is no longer present")
    base.add_argument("--until", metavar="YYYY-MM-DD",
                      help="the date this list stops being accepted by itself")
    base.add_argument("--by", help="who accepted it; required with --note")
    base.add_argument("--note", help="why, in the words of whoever accepted it")
    base.set_defaults(func=cmd_baseline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for attr in ("path", "strict", "record", "prune", "until", "by", "note"):
        if not hasattr(args, attr):
            setattr(args, attr, None)
    try:
        return args.func(args)
    except (ConfigError, BaselineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
