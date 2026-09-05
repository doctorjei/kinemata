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

from .config import ConfigError, Settings, find_config, load
from .projection import project
from .report import DEFAULT_MAX_SITES, review


def _settings(args: argparse.Namespace) -> Settings:
    path = Path(args.config) if args.config else find_config()
    if path is None:
        raise ConfigError(
            "no kinemata.toml found (searched upward from the current directory)"
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
            suffixes=settings.suffixes,
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
    common.add_argument("-c", "--config", help="path to kinemata.toml")
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
