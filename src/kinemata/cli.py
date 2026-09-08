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
from pathlib import Path

from .baseline import Baseline, BaselineError, record
from .bypass import Bypass, crossings, strays
from .claims import verify
from .config import CONFIG_NAMES, ConfigError, Settings, find_config, load
from .context import measure
from .gates import enforced
from .literals import clusters
from .projection import project
from .report import DEFAULT_MAX_SITES, Report, review


def _settings(args: argparse.Namespace) -> Settings:
    path = Path(args.config) if args.config else find_config()
    if path is None:
        raise ConfigError(
            f"no {CONFIG_NAMES[0]} found (searched upward from the current directory)"
        )
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


def _max_sites(args: argparse.Namespace, settings: Settings) -> int | None:
    if args.max_sites is not None:
        return None if args.max_sites < 0 else args.max_sites
    if settings.max_sites is not None:
        return settings.max_sites
    return DEFAULT_MAX_SITES


def cmd_ids(args: argparse.Namespace) -> int:
    settings = _settings(args)
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


def cmd_review(args: argparse.Namespace) -> int:
    settings, reports = _run_review(args)
    _print_reports(settings, reports, verbose=args.verbose)
    strong = sum(len(report.strong) for _, report in reports)
    weak = sum(len(report.weak) for _, report in reports)
    if not strong and not weak:
        if not args.quiet:
            print("Nothing already declared looks re-derived here.")
        return 0
    if not args.quiet:
        print()
        print(
            f"{strong} thing(s) already exist that this code spells out. "
            f"Route through them rather than re-deriving."
        )
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
    found = verify(
        _target(args, settings),
        suffixes=settings.claim_suffixes,
        exclude=settings.exclude,
        historical=settings.historical,
        counts=settings.counts,
        resolve_in=settings.resolve_in,
        commits_in=settings.commits_in,
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

    if found.failed or inventory.failed:
        parts = []
        if found.broken:
            parts.append(
                f"{len(found.broken)} of {found.checked} claim(s) do not resolve"
            )
        if found.blocked:
            parts.append(f"{len(found.blocked)} declared check(s) could not run")
        if inventory.absent:
            parts.append(f"{len(inventory.absent)} declared gate(s) do not run")
        print(f"\nFAIL: {'; '.join(parts)}.", file=sys.stderr)
        return 1
    if not args.quiet:
        print(f"{found.checked} documentation claim(s) checked, all resolve.")
    return 0


def cmd_context(args: argparse.Namespace) -> int:
    """Weigh what a session loads against its declared ceiling.

    Gates, because a ceiling exists to be enforced. Running it with nothing
    declared is a configuration error rather than a pass: a command that
    measures an empty set and exits 0 is the inert signal again.
    """
    settings = _settings(args)
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

    # Printed on every run that has a baseline at all, and **not suppressed by
    # --quiet**: an exemption list nobody reads the size of is how an allowlist
    # rots. The number is the point of printing it.
    if baseline.exists:
        note = f"\nbaseline: {baseline.size} accepted finding(s) in {baseline.path.name}"
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
    baseline = Baseline.load(settings.baseline)
    split = baseline.split(findings)

    if args.record:
        fresh = record(settings.baseline, findings)
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
        kept = record(settings.baseline, split.accepted)
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

    base = sub.add_parser("baseline", parents=[common],
                          help="the ratchet: findings accepted as pre-existing")
    base.add_argument("path", nargs="?", help="limit the scan to this path")
    base.add_argument("--record", action="store_true",
                      help="accept every current finding, replacing the baseline")
    base.add_argument("--prune", action="store_true",
                      help="drop records whose finding is no longer present")
    base.set_defaults(func=cmd_baseline)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for attr in ("path", "strict", "record", "prune"):
        if not hasattr(args, attr):
            setattr(args, attr, None)
    try:
        return args.func(args)
    except (ConfigError, BaselineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
