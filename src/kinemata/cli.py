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

The difference between the last two is the exit code and where they run, not
the analysis. That is deliberate: two mechanisms that could disagree eventually
will.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import CONFIG_NAMES, ConfigError, Settings, find_config, load
from .claims import verify
from .literals import clusters
from .projection import project
from .report import DEFAULT_MAX_SITES, review


def _settings(args: argparse.Namespace) -> Settings:
    path = Path(args.config) if args.config else find_config()
    if path is None:
        raise ConfigError(
            f"no {CONFIG_NAMES[0]} found (searched upward from the current directory)"
        )
    return load(path)


def _target(args: argparse.Namespace, settings: Settings) -> Path:
    """Where to scan.

    A relative path resolves against the **project root**, not the working
    directory. Otherwise ``kinemata check src`` run from a parent directory
    silently scans a different tree and reports a clean or bogus result -- which
    it did, on the first run of this command.
    """
    if not args.path:
        return settings.root
    given = Path(args.path)
    return given if given.is_absolute() else settings.root / given


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


def _run_review(args: argparse.Namespace) -> tuple[int, int]:
    """Shared body of review and check. Returns (strong, weak) counts."""
    settings = _settings(args)
    strong = weak = 0

    for registry in settings.registries:
        if args.registry and registry.name != args.registry:
            continue
        report = review(
            registry,
            _target(args, settings),
            suffixes=registry.suffixes or settings.suffixes,
            exclude=settings.exclude,
            max_sites=_max_sites(args, settings),
        )
        strong += len(report.strong)
        weak += len(report.weak)

        body = report.text(verbose=args.verbose)
        if body.strip():
            if len(settings.registries) > 1:
                print(f"# {registry.name}")
            print(body)

    return strong, weak


def cmd_review(args: argparse.Namespace) -> int:
    strong, weak = _run_review(args)
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


def cmd_undeclared(args: argparse.Namespace) -> int:
    """The opposite question to ``review``: what wants a declaration.

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


def cmd_claims(args: argparse.Namespace) -> int:
    """Falsify what the documentation asserts about the tree.

    Gates, unlike ``undeclared``. A missing file is a fact, not a judgment.

    Prints the number of claims checked even when everything resolves, because
    "all resolve" and "nothing was looked at" read identically otherwise -- and
    this project has already shipped one check that passed by examining nothing.
    """
    settings = _settings(args)
    found = verify(
        _target(args, settings),
        suffixes=settings.claim_suffixes,
        exclude=settings.exclude,
        historical=settings.historical,
    )
    body = found.text()
    if body.strip():
        print(body)
    if found.broken:
        print(
            f"\nFAIL: {len(found.broken)} of {found.checked} documentation "
            f"claim(s) do not resolve.",
            file=sys.stderr,
        )
        return 1
    if not args.quiet:
        print(f"{found.checked} documentation claim(s) checked, all resolve.")
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    strong, _ = _run_review(args)
    if strong:
        print(f"\nFAIL: {strong} bypass(es) of declared things.", file=sys.stderr)
        return 1
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

    und = sub.add_parser("undeclared", parents=[common],
                         help="advisory: repeated text with no declared home")
    und.add_argument("path", nargs="?", help="limit the scan to this path")
    und.set_defaults(func=cmd_undeclared)

    clm = sub.add_parser("claims", parents=[common],
                         help="gate: fail on a documentation claim that does not resolve")
    clm.add_argument("path", nargs="?", help="limit the scan to this path")
    clm.set_defaults(func=cmd_claims)

    chk = sub.add_parser("check", parents=[common],
                         help="gate: fail on a strong bypass")
    chk.add_argument("path", nargs="?", help="limit the scan to this path")
    chk.set_defaults(func=cmd_check)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for attr in ("path", "strict"):
        if not hasattr(args, attr):
            setattr(args, attr, None)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
