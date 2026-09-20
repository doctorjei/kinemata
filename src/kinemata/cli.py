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
    command that changes it. **Both gates read it** -- ``check`` for the code it
    scans and ``claims`` for the documentation it scans -- and each is scoped to
    its own half, because one list serving two gates is the point and a command
    reporting on a check it never ran is not. ``review`` deliberately ignores it:
    the ratchet governs the gate, not the advice, and an advisory scan that hid
    known problems would be lying about the tree.

The difference between the last two is the exit code and where they run, not
the analysis. That is deliberate: two mechanisms that could disagree eventually
will.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Iterable
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from . import stamps
from .adapters.bibliography import EXTERNAL, Bibliography, undeclared_key
from .baseline import Baseline, BaselineError, Split, record
from .bypass import (
    SKIP_DIRS,
    Bypass,
    Stray,
    _tree,
    crossings,
    is_strays_scope,
    strays,
    strays_scope,
    unused,
)
from .citations import citations, index
from .claims import CLAIMS_REGISTRY, ClaimsError, Verification, verify
from .config import CONFIG_NAMES, ConfigError, Settings, find_config, load
from .confirm import ConfirmError, apply, dating, plan, redate
from .context import measure
from .contract import BaseRegistry, Entry
from .exclusion import audit, excluded, relative_paths
from .gates import WORKFLOW_DIR, enforced, uncovered
from .literals import clusters
from .parity import RELATION_SAYS, Disagreement, Divergence, Parity
from .parity import survey as parity_survey
from .probe import Mismatch, Probed
from .probe import survey as probe_survey
from .projection import project
from .prose import ILLUSTRATION_ROLE, python_unreadable_literals
from .provenance import (
    PROVENANCE_REGISTRY,
    ProvenanceError,
    Survey,
    declared_elsewhere,
    survey,
)
from .report import DEFAULT_MAX_SITES, Report, review
from .resources import coverage
from .shape import Shaped, Violation
from .shape import survey as shape_survey
from .stamps import StampError


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
    settings = load(path)
    # Printed by every command, because a notice is about the declarations
    # rather than about one scan. **Not suppressed by ``--quiet``**, the same
    # rule the exemption, gate and promise counts follow: this is what the
    # config says, not one of a check's findings.
    for message in settings.notices:
        print(f"warning: {message}", file=sys.stderr)
    return settings


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


def _scope(args: argparse.Namespace, settings: Settings) -> tuple[Path, Path | None]:
    """The tree paths are reported against, and the part of it to read.

    A relative path resolves against the **project root**, not the working
    directory. Otherwise ``kinemata check src`` run from a parent directory
    silently scans a different tree and reports a clean or bogus result -- which
    it did, on the first run of this command.

    **Containment decides which of two things a path argument means**, the way
    ``[context]`` splits a contained ``include`` from a declared ``external``:

    * **inside the project** -- a narrowing. The root stays the project's, and
      only that subtree is read. It has to stay the project's, because every
      path a run reports or matches is spelled relative to it.
    * **outside it** -- another tree, which is a real thing to ask for, and
      keeps the meaning a path argument has always had.

    🛑 **The subtree case used to collapse the two and was wrong twice**,
    measured on a scratch tree (2026-09-19) rather than reasoned about: a tree
    green from its root went red under ``kinemata check src``, reporting its own
    accepted findings as new, and the project's ``exclude`` stopped applying
    because :shown:`src/vendor/` cannot match :shown:`vendor/lib.py` -- so a
    narrowing quietly *widened* what was reported. :func:`kinemata.bypass._walk` carries
    the mechanism; the help text promising *limit the scan to this path* is what
    made it a defect rather than a second feature.

    The announcement is wired here rather than into each command because this is
    the one place every scanning command passes through; a command added later
    inherits it instead of having to remember it. It announces what is **read**,
    a narrowing being the thing a symlink would lead out of.
    """
    if not args.path:
        _announce(settings.root)
        return settings.root, None
    given = Path(args.path)
    target = given if given.is_absolute() else settings.root / given
    try:
        inside = bool(target.resolve().relative_to(settings.root.resolve()).parts)
    except ValueError:
        inside = False
    _announce(target)
    return (settings.root, target) if inside else (target, None)


def _target(args: argparse.Namespace, settings: Settings) -> Path:
    """What every path this run reports is relative to."""
    return _scope(args, settings)[0]


def _within(args: argparse.Namespace, settings: Settings) -> Path | None:
    """The part of the tree to read, when a run is narrowed to one.

    Derived from :func:`_scope` beside :func:`_target` rather than worked out
    again here: two readings of one argument is how the root and the narrowing
    came to disagree in the first place.
    """
    return _scope(args, settings)[1]


def _note_unfitted(settings: Settings) -> None:
    """Say that a declared registry bound to nothing, then carry on.

    This command does not need a registry, so a broken one is not its failure --
    but staying silent would leave a reader thinking the whole config is doing
    what it says. `check` still refuses, so nothing is lost from CI.
    """
    for message in settings.unfitted:
        print(f"note: {message}", file=sys.stderr)


def _max_sites(args: argparse.Namespace, settings: Settings) -> int | None:
    """The suppression threshold: the flag, then the config, then the default.

    **Negative means *off* in both spellings, and for one of them it did not.**
    The flag has said "negative disables suppression" since it existed, and the
    config value was handed to :func:`kinemata.report.review` untouched -- whose
    test is ``count > max_sites``, so a negative threshold made every
    antipattern noisy, suppressed every finding, and exited 0. One dial, two
    spellings, and the declared one silently switched the check off.

    Normalized once at the end rather than per source, which is what let the two
    drift: the flag's branch carried the rule and the config's branch was three
    lines away from it.
    """
    declared = args.max_sites if args.max_sites is not None else settings.max_sites
    if declared is None:
        return DEFAULT_MAX_SITES
    return None if declared < 0 else declared


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


def _run_review(
    args: argparse.Namespace, *, registry_required: bool = True
) -> tuple[Settings, list[tuple[str, Report]], Survey | None]:
    """Shared body of review, check and baseline: one scan per registry.

    Returns the reports rather than printing them, because ``check`` has to put
    the findings through the baseline before deciding what is worth showing.

    **The citation catch rides here rather than in a command of its own**, and
    that is the whole of its adoption story. Armed on a tree that has never
    dated a citation it reports every citation in the tree, so it needs the
    ratchet -- and the ratchet is fed from exactly this function, by ``check``
    which splits against the baseline and by ``baseline`` which records it. A
    separate command would have meant a second baseline, and two exemption
    lists eventually disagree about what a project accepted.

    The survey comes back beside the reports because what it *could not judge*
    is not a finding and has nowhere else to be said. A run that silently
    declined to look at part of a tree reads like a run that found nothing.

    :param registry_required: whether the caller has any other source of
        findings. ``baseline`` does -- it adds the documentation claims -- and
        a project that declares ``[claims]`` and nothing else is exactly the
        adoption case the ratchet was extended for, so refusing to record its
        baseline would have shipped the feature with no way to turn it on.
    """
    settings = _settings(args)
    # A registry is required only when a registry is what would do the work.
    # The citation catch rides this function and is not registry-shaped, so a
    # project declaring the policy and nothing else was refused here -- told to
    # declare a registry to run a check that never consults one, which is the
    # required fiction `_needs_registries` exists to have removed.
    if not settings.provenance:
        if registry_required:
            _needs_registries(settings, "scan for")
        elif settings.unfitted:
            # The other half of that refusal, which a caller with its own
            # findings still needs: a registry whose adapter recognized nothing
            # scans for nothing, and recording a baseline from it would write an
            # exemption list that is short for a reason nobody was told.
            raise ConfigError(" ".join(settings.unfitted))
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
                within=_within(args, settings),
                max_sites=_max_sites(args, settings),
            ),
        ))

    found: Survey | None = None
    if settings.provenance and args.registry in (None, PROVENANCE_REGISTRY):
        found = _survey(args, settings)
        reports.append((
            PROVENANCE_REGISTRY,
            # Every undated citation is strong: a missing stamp is a fact about
            # the document, not a guess about a namespace, and the weak tier
            # exists for the latter.
            Report(bypasses=tuple(hit for _, hit in found.findings()),
                   scanned=found.scanned),
        ))
    return settings, reports, found


def _survey(args: argparse.Namespace, settings: Settings) -> Survey:
    """Every citation the citation policy reaches.

    Scoped by `[citations] suffixes`, which defaults to the claims scope and is
    declared separately when a project wants stamps out of its user-facing
    prose. The two questions differ: a dead path in a README is a defect wherever
    it appears, while a stamp beside it is apparatus a reader has to learn to
    skip.
    """
    return survey(
        _target(args, settings),
        suffixes=settings.citation_suffixes,
        file_suffixes=settings.claim_file_suffixes,
        exclude=settings.exclude,
        within=_within(args, settings),
        historical=settings.historical,
        recorded=_entries_carrying(settings, "confirmed"),
        covered=coverage(settings.resources),
    )


def _relative(path: Path, root: Path) -> str:
    """A path as the project spells it, falling back to what it is.

    Every other line this command prints names a file the way the tree does, and
    a bare basename would be the one place a reader has to guess which directory
    it meant.
    """
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return str(path)


def _report_resources(settings: Settings, found: Survey | None) -> None:
    """How much of this tree's provenance rests on the resource list.

    Printed whenever a list is declared, and not suppressed by ``--quiet`` --
    the rule the baseline size, the gate count and the illustration count all
    follow. A citation the policy stopped reporting because four entries in a
    file date it reads, in silence, exactly like a citation carrying a stamp.

    **A declared document that dates no citation is named**, for the same reason
    ``unused`` names a declared entry nothing mentions: it may be a document
    that has not started citing anything yet, and it may be a rename that left
    the entry pointing somewhere harmless. Never a failure, because only the
    reader can tell those apart.
    """
    if found is None or not settings.resources:
        return
    dating = {seen.path for seen in found.listed}
    where = (_relative(settings.resources_path, settings.root)
             if settings.resources_path else "the list")
    print(f"resources: {len(found.listed)} citation(s) in "
          f"{len(dating)} document(s) dated by {where}")
    idle = [resource.path for resource in settings.resources
            if resource.path not in dating]
    if idle:
        print(f"  {len(idle)} declared resource(s) date no citation: "
              f"{', '.join(sorted(idle))}")


def _report_unassociated(found: Survey | None) -> None:
    """What the citation catch declined to judge, and why.

    Not suppressed by ``--quiet``, the same rule the baseline size and the gate
    count follow. Silence about a citation the tool could not place is
    indistinguishable from a citation it placed and found dated, and the whole
    argument for the narrow association rule is that a wrong accusation costs
    more than a missed one -- which is only true while the misses are counted.
    """
    if found is None:
        return
    if found.ambiguous:
        print(
            f"unjudged: {len(found.ambiguous)} citation(s) appear more than "
            "once on their line and the occurrences disagree about carrying a "
            "stamp. Which one the sentence asserts cannot be recovered, so "
            "nothing is reported for them."
        )
    if found.unlocatable:
        print(
            f"unjudged: {len(found.unlocatable)} citation(s) could not be "
            "placed on the line that produced them."
        )
    if found.archived:
        print(
            f"{len(found.archived)} document(s) left alone as superseded "
            "records; a record cites what was true when it was written."
        )


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


def _strays(
    args: argparse.Namespace, settings: Settings, target: Path
) -> list[tuple[object, list[Stray]]]:
    """Catch A's scan, per registry that can answer.

    Shared by ``undeclared`` and ``baseline`` for the reason ``_run_review`` is
    shared by ``check`` and ``baseline``: the command that writes the exemption
    list has to run every check that feeds it, and a source it did not run is a
    set of records ``--prune`` deletes in silence.

    **Returns an empty list rather than refusing when nothing can answer.** The
    refusal belongs to ``undeclared``, whose whole output would otherwise be a
    clean closed world nobody asked about; ``baseline`` legitimately runs on a
    project where no registry recognizes its own identifiers and simply has no
    strays to record.
    """
    answered: list[tuple[object, list[Stray]]] = []
    for registry in settings.registries:
        if args.registry and registry.name != args.registry:
            continue
        try:
            found = strays(
                registry,
                target,
                # The registry's own file set wins, as it already does for
                # `review` and `unused`. This command was the one that ignored
                # it, which had no visible effect only because nothing closable
                # declared its own suffixes: a bibliography does, and pointing
                # a closed one at the project's `.py` default would find no
                # citations anywhere and report a clean closed world.
                suffixes=registry.suffixes or settings.suffixes,
                exclude=settings.exclude,
                within=_within(args, settings),
            )
        except NotImplementedError:
            continue  # cannot recognize an identifier; reported by the caller
        answered.append((registry, found))
    return answered


def _gating_strays(
    answered: Iterable[tuple[object, list[Stray]]]
) -> list[tuple[str, Bypass]]:
    """The half of Catch A that can fail a build, tagged with its scope.

    **Closed registries only**, which is the same rule ``_strong`` applies to
    weak signals and for the same reason: an open registry advises and exits 0,
    so ratcheting its findings would record exemptions against a check that was
    never going to fail. Open one deliberately and its findings arrive here.
    """
    return [
        (strays_scope(registry.name), stray.finding())
        for registry, found in answered
        if getattr(registry, "closed", False)
        for stray in found
    ]


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


def _report_unreadable(settings: Settings) -> None:
    """How many lines a ``strings`` registry could not read, when any.

    **An f-string is dropped whole by the literal extractor**, so a registry
    matching on values is blind to every one of them and reports clean.
    ``prose.python_string_literals`` is the carrier for why, and the drop is
    deliberate; this is the other half the adopter who found it actually asked
    for -- *"a dropped literal that says it was dropped costs a reader
    nothing."*

    Not suppressed by ``--quiet``, on the rule the silent, exemption, gate and
    promise counts already follow: a count the reader did not ask for is the
    only way they learn the scope is smaller than it looks.
    """
    scoped = [
        registry for registry in settings.registries
        if getattr(registry, "match_mode", "strings") == "strings"
    ]
    if not scoped:
        return
    rows = 0
    files = 0
    for here, names, _ in _tree(settings.root):
        for name in names:
            path = here / name
            if path.suffix != ".py":
                continue
            rel = str(path.relative_to(settings.root))
            if excluded(rel, settings.declared_exclude):
                continue
            try:
                found = python_unreadable_literals(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
            if found:
                rows += len(found)
                files += 1
    if rows:
        print(
            f"unread: {rows} f-string(s) in {files} file(s) are not read as "
            "literals, so a `strings` registry cannot match inside them. Their "
            "interpolated parts are not literals; the whole token is skipped."
        )


def _report_exclusions(settings: Settings) -> None:
    """What ``[project] exclude`` actually removed, when that is a surprise.

    **An adopter lost two documentation claims to a fragment that read like a
    directory and matched as a substring**, and spent a day on three more that
    removed nothing at all -- both invisible, because a config saying something
    confidently while doing nothing looks exactly like a config that works. This
    repository shipped the same defect: ``deliverables/`` has never existed here.

    Not suppressed by ``--quiet``, on the rule the silent, exemption, gate and
    promise counts already follow: a count the reader did not ask for is the
    only way they learn the scope moved.
    """
    if not settings.declared_exclude:
        return
    walked = relative_paths(
        settings.root, (here / name for here, names, _ in _tree(settings.root)
                        for name in names)
    )
    report = audit(walked, settings.declared_exclude, pruned=tuple(SKIP_DIRS))
    for line in report.lines():
        print(line)


def cmd_review(args: argparse.Namespace) -> int:
    settings, reports, found = _run_review(args)
    _print_reports(settings, reports, verbose=args.verbose)
    strong = sum(len(report.strong) for _, report in reports)
    weak = sum(len(report.weak) for _, report in reports)
    if not strong and not weak:
        if not args.quiet:
            print("Nothing already declared looks re-derived here.")
        _report_silent(settings)
        _report_unreadable(settings)
        _report_exclusions(settings)
        _report_resources(settings, found)
        _report_unassociated(found)
        return 0
    if not args.quiet:
        print()
        print(
            f"{strong} thing(s) already exist that this code spells out. "
            f"Route through them rather than re-deriving."
        )
    _report_silent(settings)
    _report_unreadable(settings)
    _report_exclusions(settings)
    _report_resources(settings, found)
    _report_unassociated(found)
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
        within=_within(args, settings),
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
    0.

    **Ratcheted against the same baseline ``check`` and ``claims`` read**, as of
    2026-09-13. Until then "closing is the ratchet" was the whole of the
    adoption story, and it was the wrong shape: closing is a cliff, not a
    ratchet. A project with one pre-existing undeclared identifier had two
    options -- leave the registry open and get an advisory list nobody reads, or
    close it and fail every build until the last one was declared -- which is
    exactly the position the citation catch was in before it was given the same
    list. Now a closed registry can be adopted on a tree that does not yet
    satisfy it, and a *new* undeclared identifier fails.

    Only **closed** registries' findings are ratcheted: an open one exits 0
    anyway, so recording exemptions for it would be an allowlist against a
    check that was never going to fail.

    **Refuses when no registry can answer.** Only a registry that recognizes its
    own identifiers can say what is undeclared, and today that is a mapping
    registry with a ``syntax``. Pointing this at a project whose registries
    cannot answer and exiting 0 would report "nothing undeclared" about a
    question nobody asked -- the inert signal this project exists to catch.
    """
    settings = _settings(args)
    _needs_registries(settings, "check against")
    target = _target(args, settings)

    answered = _strays(args, settings, target)
    if not answered:
        raise ConfigError(
            "no declared registry can recognize its own identifiers, so none "
            "can say what is undeclared. This needs a registry with an "
            "identifier syntax (today: kind = \"yaml-mapping\" with `syntax`). "
            "Running anyway would report nothing and mean nothing."
        )

    # A `Bypass` is what the ratchet fingerprints; a `Stray` is what a reader
    # should be shown. Paired by identity through the split, exactly as `claims`
    # pairs its `Claim` objects: `split` hands back the very objects it was
    # given, which is what `id` keys on.
    gating = _gating_strays(answered)
    shown = [stray for registry, found in answered
             if getattr(registry, "closed", False) for stray in found]
    behind = {id(hit): stray for (_, hit), stray
              in zip(gating, shown, strict=True)}

    baseline = Baseline.load(settings.baseline)
    split = baseline.split(
        gating, scope=[strays_scope(registry.name) for registry, _ in answered]
    )
    exempt = {id(behind[id(hit)]) for _, hit in split.accepted}

    failed = 0
    for registry, found in answered:
        closed = getattr(registry, "closed", False)
        label = "closed" if closed else "open"
        # Accepted findings leave the listing but not the accounting below. A
        # reader of this output is looking for what to fix; a list that mixes
        # the exempt with the live teaches them to cross-reference the baseline
        # to tell which is which.
        live = [s for s in found if id(s) not in exempt] if closed else found
        if not live:
            if not args.quiet:
                print(f"# {registry.name} ({label}): no undeclared identifiers.")
            continue
        print(f"# {registry.name} ({label})")
        for stray in live:
            print(f"  {stray}")
        if closed:
            failed += len(live)

    # Printed for the reason `check` prints its own baseline size: a run that
    # silently applied part of an exemption list reads exactly like a clean one.
    if split.accepted and not args.quiet:
        until = f", until {baseline.until}" if baseline.until else ""
        print(f"\nbaseline: {len(split.accepted)} undeclared identifier(s) "
              f"accepted as pre-existing in {settings.baseline.name}{until}")
    _report_stale(split, quiet=args.quiet)

    if failed:
        print(
            f"\nFAIL: {failed} use(s) of an identifier no closed registry "
            "declares. Declare it, or open the registry deliberately.",
            file=sys.stderr,
        )
        return 1
    return 0


def _set_valued(result: Parity, args: argparse.Namespace) -> None:
    """Say when a value comparison was a *set* comparison.

    A list cell is compared as a set on purpose, so this is a disclosure and
    never a finding -- but it was the one suppression here that printed
    nothing, which is exactly what made a withdrawn path claim invisible in
    ``claims`` until 0.2.0.

    **A count and no identifiers**, deliberately, and the distinction is the
    one that release already drew: a negation is a suppression the tool
    *inferred* from prose nobody wrote for it, so the sites are the only way to
    judge it, while a list cell is a suppression the project **declared** by
    writing a list. Its author can see which rows those are; what they could
    not see is that order went unchecked.
    """
    if not result.set_valued or args.quiet:
        return
    count = len(result.set_valued)
    print(
        f"  set-valued: {count} declared cell(s) hold a list, compared as "
        "sets -- order is not part of the claim"
    )


def _parity(
    args: argparse.Namespace, settings: Settings, target: Path
) -> list[Parity]:
    """The parity run, shared by ``parity`` and ``baseline``.

    Shared for the reason ``_strays`` is: the command that writes the exemption
    list has to run every check that feeds it, or ``--prune`` deletes records
    for a source it never looked at.
    """
    specs = [
        spec for spec in settings.parities
        if not args.registry or spec.registry == args.registry
    ]
    return parity_survey(
        settings.registries, specs, target, settings.oracle_timeout
    )


def cmd_parity(args: argparse.Namespace) -> int:
    """Declared entries against the set the project's code actually produces.

    The positive twin of the registry scan: everywhere else a second spelling is
    the finding, and here a **disagreement** is. Both directions gate, because
    they are different mistakes -- a declaration that is short, and one that has
    outlived the code -- and a check reporting only one of them would leave the
    other looking settled.

    **Refuses when nothing declares an oracle** (exit 2), the way ``context``
    refuses a project with no ceiling. Running with no ``[[parity]]`` would
    print a clean sheet about a question nobody asked, which is the inert signal
    this package exists to prevent.

    **A blocked oracle fails.** Not a note: in CI, "printed a warning and exited
    0" is indistinguishable from a pass, and an oracle that cannot answer means
    the check is not running at all.

    ⚑ **A declaration naming a ``field`` compares values as well**, and does so
    *in addition to* membership rather than instead of it -- so *"and there is
    nothing else"* remains part of every value claim, and an oracle that printed
    nothing cannot read as agreement.
    """
    settings = _settings(args)
    if not settings.parities:
        print(
            "error: no [[parity]] declared: nothing says what this project's "
            "code actually produces. Declare a registry, an oracle command and "
            "an extract, or do not run this.",
            file=sys.stderr,
        )
        return 2

    results = _parity(args, settings, _target(args, settings))
    paired: list[tuple[str, Bypass, Disagreement | Divergence]] = []
    for result in results:
        for item in result.reports():
            paired.append((item.scope, item.finding(), item))

    baseline = Baseline.load(settings.baseline)
    split = baseline.split(
        [(scope, hit) for scope, hit, _ in paired],
        scope=[name for result in results for name in result.scopes()],
    )
    exempt = {id(hit) for _, hit in split.accepted}
    # Keyed off the pairing built above rather than by asking each result for
    # its disagreements again: those are fresh objects every call, so a second
    # ask would match nothing against the exemptions just resolved.
    live: dict[str, list[Disagreement | Divergence]] = {}
    for _, hit, item in paired:
        if id(hit) not in exempt:
            live.setdefault(item.registry, []).append(item)

    failed = 0
    for result in results:
        shown = live.get(result.registry, [])
        if result.blocked:
            print(f"# {result.registry}")
            print(f"  BLOCKED: {result.blocked}", file=sys.stderr)
            failed += 1
            continue
        if not shown:
            if not args.quiet:
                # What was compared, not only that it agreed: a value run and a
                # membership-only run print the same clean line otherwise, and
                # the difference is the whole reason one of them was declared.
                also = f", agreeing on {result.compared}" if result.compared else ""
                # And *which claim* held, for the same reason one step further
                # out: a containment and an equality both print "in agreement"
                # while meaning different things, and the weaker one is the one
                # a reader most needs told, since it is not closed-world.
                held = (
                    "in agreement"
                    if result.relation == "equal"
                    else RELATION_SAYS[result.relation]
                )
                print(
                    f"# {result.registry}: {result.declared} declared, "
                    f"{result.produced} produced, {held}{also}."
                )
                _set_valued(result, args)
            continue
        print(f"# {result.registry}")
        for item in shown:
            print(f"  {item}")
        _set_valued(result, args)
        failed += len(shown)

    if split.accepted and not args.quiet:
        until = f", until {baseline.until}" if baseline.until else ""
        print(f"\nbaseline: {len(split.accepted)} disagreement(s) accepted as "
              f"pre-existing in {settings.baseline.name}{until}")
    _report_stale(split, quiet=args.quiet)

    if failed:
        print(
            f"\nFAIL: {failed} disagreement(s) between a declaration and what "
            "the code produces.",
            file=sys.stderr,
        )
        return 1
    return 0


def _shape(args: argparse.Namespace, settings: Settings) -> list[Shaped]:
    """The shape run, shared by ``shape`` and ``baseline``.

    Shared for the reason ``_parity`` and ``_strays`` are: the command that
    writes the exemption list has to run every check that feeds it, or
    ``--prune`` deletes records for a source it never looked at.
    """
    declared = [
        item for item in settings.shapes
        if not args.registry or item.registry == args.registry
    ]
    return shape_survey(settings.registries, declared)


def cmd_shape(args: argparse.Namespace) -> int:
    """A declaration against the rules it states about itself.

    The one check here whose subject is the declaration rather than the code, so
    it reads no tree and takes no path. What it catches is a row edited into the
    wrong shape -- a missing flag, a value outside the declared vocabulary, an
    axis that stopped being a cross product -- which nothing else here can see,
    because every other mechanism compares the declaration to something and this
    asks whether the declaration is what it claims to be.

    **Refuses when nothing declares a rule** (exit 2), the way ``parity`` and
    ``context`` refuse. A clean sheet about a question nobody asked is the inert
    signal this package exists to prevent.

    ⚑ **A rule that selected no entries FAILS, and is reported as vacuous rather
    than as a violation** -- nothing was wrong with an entry, the rule found no
    entries to be wrong. It is not a finding the baseline can accept either: a
    run that judged nothing has not earned the right to have its records pruned.
    """
    settings = _settings(args)
    if not settings.shapes:
        print(
            "error: no [[shape]] declared: nothing says what shape this "
            "project's own declarations must be in. Declare a registry and at "
            "least one [[shape.rule]], or do not run this.",
            file=sys.stderr,
        )
        return 2

    results = _shape(args, settings)
    # One pass, keeping the violation beside the record built from it, for the
    # reason `cmd_parity` states: `finding()` returns a fresh object every call,
    # so asking a second time would match nothing against the exemptions just
    # resolved.
    paired: list[tuple[str, Bypass, Violation]] = [
        (item.scope, item.finding(), item)
        for result in results
        for item in result.violations
    ]

    baseline = Baseline.load(settings.baseline)
    split = baseline.split(
        [(scope, hit) for scope, hit, _ in paired],
        scope=[name for result in results for name in result.scopes()],
    )
    exempt = {id(hit) for _, hit in split.accepted}
    live: dict[str, list[Violation]] = {}
    for _, hit, item in paired:
        if id(hit) not in exempt:
            live.setdefault(item.registry, []).append(item)

    failed = 0
    for result in results:
        shown = live.get(result.registry, [])
        entries = max((item.examined for item in result.judged), default=0)
        if not shown and not result.blocked and not result.vacuous:
            if not args.quiet:
                # What ran, not only that it passed: a rule whose guard narrowed
                # to two entries is not a failure and is the thing a reader most
                # wants to see before trusting a clean line.
                print(
                    f"# {result.registry}: {len(result.judged)} rule(s) over "
                    f"{entries} entry(s), all satisfied."
                )
                for item in result.judged:
                    print(f"  {item.rule.name}: {item.examined} examined")
            continue
        print(f"# {result.registry}")
        for item in result.blocked:
            print(f"  BLOCKED {item.rule.name!r}: {item.blocked}", file=sys.stderr)
            failed += 1
        for item in result.vacuous:
            print(
                f"  VACUOUS {item.rule.name!r}: examined no entry, so it "
                "checked nothing",
                file=sys.stderr,
            )
            failed += 1
        for item in shown:
            print(f"  {item}")
        failed += len(shown)

    if split.accepted and not args.quiet:
        until = f", until {baseline.until}" if baseline.until else ""
        print(f"\nbaseline: {len(split.accepted)} violation(s) accepted as "
              f"pre-existing in {settings.baseline.name}{until}")
    _report_stale(split, quiet=args.quiet)

    if failed:
        print(
            f"\nFAIL: {failed} rule(s) a declaration does not satisfy.",
            file=sys.stderr,
        )
        return 1
    return 0


def _probe(args: argparse.Namespace, settings: Settings) -> list[Probed]:
    """The probe run, shared by ``probe`` and ``baseline``.

    Shared for ``_shape``'s reason: the command that writes the exemption list
    has to run every check that feeds it.
    """
    return probe_survey(settings.probes)


def cmd_probe(args: argparse.Namespace) -> int:
    """What a project's own code accepts and refuses, against what it declared.

    The one check here whose fact has no value on either side -- the answer is
    that a callable took an input or would not. It reads no tree and takes no
    path: the corpus comes from the project, and the target is named rather than
    discovered.

    **Refuses when nothing declares a probe** (exit 2), the way ``parity``,
    ``shape`` and ``context`` refuse.

    ⚑ **A corpus carrying one polarity FAILS and is reported as vacuous rather
    than as a violation.** Nothing was wrong with a case; the corpus cannot tell
    a discriminating callable from a constant one, which is the property it
    exists to demonstrate. It is not a finding the baseline can accept either --
    a run that could not discriminate has not earned the right to have its
    records pruned.
    """
    settings = _settings(args)
    if not settings.probes:
        print(
            "error: no [[probe]] declared: nothing says what this project's "
            "code must accept and refuse. Declare a target, a case supplier "
            "and an outcome, or do not run this.",
            file=sys.stderr,
        )
        return 2

    results = _probe(args, settings)
    # One pass, keeping the mismatch beside the record built from it: `finding()`
    # returns a fresh object every call, so asking twice would match nothing
    # against the exemptions just resolved. Same reason as `cmd_shape`.
    paired: list[tuple[str, Bypass, Mismatch]] = [
        (item.scope, item.finding(), item)
        for result in results
        for item in result.mismatches
    ]

    baseline = Baseline.load(settings.baseline)
    split = baseline.split(
        [(scope, hit) for scope, hit, _ in paired],
        scope=[name for result in results for name in result.scopes()],
    )
    exempt = {id(hit) for _, hit in split.accepted}
    live: dict[str, list[Mismatch]] = {}
    for _, hit, item in paired:
        if id(hit) not in exempt:
            live.setdefault(item.probe, []).append(item)

    # Counted apart, because they are different failures and one summary line
    # calling a vacuous corpus a "case the code answers otherwise" would name
    # the wrong defect to the one reader who has to fix it.
    mismatched = 0
    unanswered = 0
    for result in results:
        shown = live.get(result.probe, [])
        if not shown and not result.blocked and not result.vacuous:
            if not args.quiet:
                # What ran, not only that it passed. The two counts are the
                # whole guarantee, so printing the total alone would hide a
                # corpus drifting toward one side.
                print(
                    f"# {result.probe}: {result.examined} case(s), "
                    f"{result.accepting} accept / {result.refusing} refuse"
                )
            continue
        print(f"# {result.probe}")
        if result.blocked:
            print(f"  BLOCKED: {result.blocked}", file=sys.stderr)
            unanswered += 1
        elif result.vacuous:
            print(f"  VACUOUS: {result.why_vacuous()}", file=sys.stderr)
            unanswered += 1
        for item in shown:
            print(f"  {item}")
        mismatched += len(shown)

    if split.accepted and not args.quiet:
        until = f", until {baseline.until}" if baseline.until else ""
        print(f"\nbaseline: {len(split.accepted)} case(s) accepted as "
              f"pre-existing in {settings.baseline.name}{until}")
    _report_stale(split, quiet=args.quiet)

    if mismatched or unanswered:
        said = []
        if mismatched:
            said.append(f"{mismatched} case(s) the code does not answer as declared")
        if unanswered:
            said.append(f"{unanswered} probe(s) that did not answer")
        print(f"\nFAIL: {', '.join(said)}.", file=sys.stderr)
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
                within=_within(args, settings),
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


def _elsewhere_keys(settings: Settings) -> frozenset[str]:
    """Reference keys whose **type code** says the artifact is somebody else's.

    Read off the built registries rather than re-parsing the config, so a key
    the bibliography refused never reaches here. Asked of every registry by what
    its entries carry, not by class: a project that supplies its own adapter
    through ``kind = "import"`` and declares external evidence the same way gets
    the same behavior, which is what publishing the vocabulary means.

    **Keyed on the code rather than on a field's presence**, which is the change
    that made the codes worth minting. The predicate used to ask whether an
    entry carried ``foreign``, so a reader had to know that a field silently
    re-read ``Pa`` as a path in somebody else's tree. Now the code says it and
    the field only says where.
    """
    return frozenset(
        entry.id
        for registry in settings.registries
        for entry in registry.entries()
        if str(entry.extra.get("type", "")) in EXTERNAL
    )


def _entries_carrying(settings: Settings, field: str) -> frozenset[str]:
    """Reference keys whose entry declares ``field``.

    Today that is ``confirmed``: a source verified on a day, which is a record
    rather than a live pointer. Asked of every registry by what its entries
    carry rather than by class, so a project supplying its own adapter through
    ``kind = "import"`` gets the same behavior -- which is what publishing a
    field means.
    """
    return frozenset(
        entry.id
        for registry in settings.registries
        for entry in registry.entries()
        if entry.extra.get(field)
    )


def _verify(args: argparse.Namespace, settings: Settings) -> Verification:
    """Every claim the documents make, over the files the config declares.

    One body, two callers: ``claims`` gates on it and ``baseline`` records it.
    Held in one function for the reason ``_run_review`` is -- the gate and the
    thing that writes the gate's exemption list must not be able to disagree
    about what a finding is.

    This is also where the two halves of an external citation are joined, and
    the only place that knows both: a bibliography is a registry, a claim is
    prose, and neither module is allowed to import the other's world.
    """
    return verify(
        _target(args, settings),
        suffixes=settings.claim_suffixes,
        file_suffixes=settings.claim_file_suffixes,
        exclude=settings.exclude,
        within=_within(args, settings),
        historical=settings.historical,
        counts=settings.counts,
        resolve_in=settings.resolve_in,
        commits_in=settings.commits_in,
        elsewhere=declared_elsewhere(_elsewhere_keys(settings)),
        promised=settings.promised,
        external=settings.external,
        timeout=settings.external_timeout,
        oracle_timeout=settings.oracle_timeout,
    )


def _report_stale(split: Split, *, quiet: bool = False) -> None:
    """Say how many accepted records nothing matched, and why one is a rewrite.

    **One carrier for what four commands spelled identically.** ``undeclared``,
    ``parity``, ``shape`` and ``probe`` each held the same three lines, and the
    fifth and sixth renderings of the same fact -- ``check``'s and ``claims``'
    -- had already drifted to different punctuation and a different suppression
    rule, which is how a spelling repeated six times announces what it is going
    to do next. Found while :func:`_report_reworded` had to be called from six
    places for the same reason.

    The ``note`` forms are deliberately **not** folded in here. They embed this
    into a line they are already building, and unifying them would change what
    two commands print to no reader's benefit -- a cleanup that edits output is
    no longer a cleanup.
    """
    if split.stale and not quiet:
        gone = sum(item.count for item in split.stale)
        print(f"{gone} accepted record(s) no longer present "
              "-- `kinemata baseline --prune` drops them.")
    _report_reworded(split, quiet=quiet)


def _report_reworded(split: Split, *, quiet: bool = False) -> None:
    """Say which new findings are an accepted record with its line edited.

    *An accepted finding's text changed* and *a new claim does not resolve* are
    the same two lines of output today, and an adopter hit the first while
    believing the second (2026-09-19): repairing one finding meant reflowing a
    paragraph, which moved the words of a **neighboring** baselined line. Their
    run reddened with what presented as new, and the accepted count dropped by
    one with nothing said.

    **The verdict is unchanged and the ask was not a looser match** -- they said
    so, and a fingerprint that forgave a rewrite would hold an exemption open
    across the edit that changed what was exempted. This names the event.

    Printed under either narrowing -- ``--registry`` or a path -- where the raw
    stale count is suppressed because records outside the narrowing are absent
    rather than fixed. A pair is trustworthy anyway: it needs a **new finding at
    the same site**, so that site was scanned.

    ⚑ **It said nothing under a path argument for one commit**, because a path
    was the scan *root* then and no record written from the project root could
    match a finding reported relative to a subdirectory. :func:`_scope` is where
    that was fixed and carries what it cost.
    """
    if quiet or not split.reworded:
        return
    pairs = split.reworded
    # Self-contained rather than "N of them": this prints beside both the new
    # findings and the stale records, and a sentence that needs its neighbor to
    # say what it counts is one that reads wrong the first time it moves.
    # Spelled out rather than "finding(s) is/are", which the agreement makes
    # unreadable here in a way the other counts in this file do not have.
    head = (
        "1 new finding is an accepted record whose line was edited"
        if len(pairs) == 1
        else f"{len(pairs)} new findings are accepted records whose lines "
             "were edited"
    )
    print(f"{head}, not a new site -- re-record, or put the text back:")
    # Not `record`: that is the module-level function this file imports, and
    # shadowing it here is how a later edit in this function calls the wrong one.
    for accepted, _ in pairs:
        print(f"  {accepted}")


def _report_unscanned(split: Split) -> None:
    """Name the exemptions this command was not in a position to judge.

    Not suppressed by ``--quiet``, the same rule the baseline size and the gate
    count follow. One list serves every check and no command runs every check,
    so silence here would leave a reader of ``check``'s output believing they
    had seen the whole exemption list.
    """
    if not split.unscanned:
        return
    total = sum(item.count for item in split.unscanned)
    sources = sorted({item.registry for item in split.unscanned})
    print(
        f"{total} further accepted finding(s) belong to {', '.join(sources)}, "
        "which this command does not run; nothing here is a statement about them."
    )


def cmd_claims(args: argparse.Namespace) -> int:
    """Falsify what the project asserts about itself: in prose, and in CI.

    Gates, unlike ``undeclared``. A missing file is a fact, not a judgment.

    **Refuses when nothing declares ``[claims]``** (exit 2), the way ``parity``,
    ``shape``, ``context`` and ``undeclared`` do. This was the one mechanism here
    that defaulted instead, and the default was not harmless: an adopter's
    registry-only config ran a documentation scan nobody had scoped, under that
    config's excludes, and ``baseline --record`` wrote 356 findings into a file
    they would never read with a command they would never run. A scope nobody
    chose is not a safe default -- it is a second answer to a question the real
    claims config already answers differently.

    Prints the number of claims checked even when everything resolves, because
    "all resolve" and "nothing was looked at" read identically otherwise -- and
    this project has already shipped one check that passed by examining nothing.

    The gate inventory rides here rather than in a command of its own. A check
    that verifies other checks are wired up is worthless if nothing guarantees
    *it* runs, and adding a fifth command would have created exactly that
    regress. Folded into an existing gate, it runs wherever that gate does.

    **Ratcheted against the same baseline ``check`` reads, and still its own
    command with its own exit code.** Sharing the file was the requirement --
    two exemption lists eventually disagree about what a project accepted.
    Merging the two commands was considered and rejected on three counts, none
    of them about taste:

    * ``[claims] external`` reaches the network. ``check`` is what an agent runs
      in-box on every edit, and a gate that goes amber on a bad network day is
      one its reader learns to skim.
    * Four of the five things that fail here have no site to fingerprint -- see
      :attr:`kinemata.claims.Verification.declarations_failed` -- so this exit
      code is not reducible to "new findings", which is all ``check``'s is.
    * ``kinemata claims`` is declared in ``[[gate]]`` and verified against the
      workflow that runs it, by this very command. Folding it away would make
      that declaration false, and the inventory it carries is the thing that
      notices a deleted CI step.
    """
    settings = _settings(args)
    if not settings.checks_claims:
        print(
            "error: nothing here declares anything for this command to check: "
            "no [claims], no [[gate]], no [[count]] and no [[promise]]. "
            "Declare one, or do not run this.",
            file=sys.stderr,
        )
        return 2

    _note_unfitted(settings)
    found = _verify(args, settings)
    inventory = enforced(settings.root, settings.gates)

    baseline = Baseline.load(settings.baseline)
    # A `Bypass` is what the ratchet fingerprints; a `Claim` is what a reader
    # should be shown. Paired by position, because `findings()` is the one place
    # the tagging lives and re-spelling it here to get the pairing would be a
    # second copy of it. `strict` pins the parallelism rather than trusting it,
    # and the split returns these very objects, which is what `id` keys on.
    tagged = found.findings()
    behind = {id(hit): claim for (_, hit), claim
              in zip(tagged, found.broken, strict=True)}
    split = baseline.split(tagged, scope=(CLAIMS_REGISTRY,))
    gated = replace(found, broken=[behind[id(hit)] for _, hit in split.new])

    body = "\n".join(part for part in (gated.text(), inventory.text()) if part.strip())
    if body.strip():
        print(body)

    # Printed whenever any gate is declared, and not suppressed by --quiet: a
    # declaration list that shrinks to nothing is the one failure this check
    # cannot fail on, so the number has to be in front of a reader.
    if inventory.declared:
        print(f"gates: {len(inventory.verified)} of {inventory.declared} "
              f"declared check(s) run in {', '.join(inventory.searched) or 'nothing'}")
        # Same condition, deliberately: with no gates declared there is no
        # coverage sentence to be misleading, so nothing to correct. With gates,
        # a declared section no gate row runs would keep the line above green
        # while running nowhere -- the count measures declared gates, not
        # declared checks.
        declared = {
            "registry": bool(settings.registries),
            "parity": bool(settings.parities),
            "shape": bool(settings.shapes),
            "probe": bool(settings.probes),
            "context": settings.context is not None,
        }
        for spelling in uncovered(settings.gates, declared):
            print(f"ungated: {spelling} declares checks no [[gate]] row runs")

    # Same rule as the gate count and the exemption count, for the same reason:
    # a promise is a claim nobody is checking, so the number of them is not
    # optional reading. A project that stops noticing its deferrals has an
    # allowlist.
    if settings.promised:
        print(f"promises: {len(settings.promised)} declared, "
              f"{len(found.deferred)} claim(s) held open")

    # Same rule again: a span marked as an illustration is a span this stopped
    # checking because somebody said to, and suppression is reported here rather
    # than being silent. Counted, not listed -- see `Verification.shown`.
    if found.shown:
        print(f"illustrations: {found.shown} span(s) marked `:{ILLUSTRATION_ROLE}:` "
              "and not read as claims")

    # And again, for the suppression nobody declared. A negation in the same
    # clause withdraws a path claim, which is right far more often than not and
    # was the one suppression here that printed nothing at all. The reader needs
    # the size of it: "needs no edit" is a negation governing `edit` that exempts
    # every path within the window before it, and a run that lost claims that way
    # is indistinguishable from a clean one.
    if found.negated:
        print(f"negated: {found.negated} path claim(s) read as discussed rather "
              "than asserted, a negation being in the same clause")
        # The one part of it a reader cannot guess, and it is not a failure: a
        # markdown `|` is not a clause boundary, so a `No` in one cell of a row
        # withdraws a path named in another. Printed without -v because a table
        # is where a project keeps its path inventory, and a project with none
        # of this sees nothing.
        if found.across_cells:
            print(f"  {found.across_cells} of them across a table cell, where "
                  "the negation is in another cell of the same row")
        # Listed under -v, where an illustration is only ever counted. An
        # illustration is a suppression the author declared; this one the tool
        # inferred, from prose nobody wrote for it, and the author may not know
        # it happened. The count says how much came off the table; only the
        # sites say whether it should have.
        #
        # With the cause, since 2026-09-19. The sites alone left an adopter
        # reading 336 of them in their own files to find the seven that were
        # real; the word and the direction are what let a reader skip the
        # obvious ones without opening anything.
        if args.verbose:
            for entry in found.withdrawn:
                claim = entry.claim
                print(f"  {claim.path}:{claim.line}: {claim.text} -- {entry.cause}")

    # And again, for the suppression that is a declaration rather than a
    # marker: these citations were not checked here because the project said
    # they are somebody else's. `cite --where` resolves any one of them to its
    # sites, which is why the number is the reading and the list is not.
    if found.elsewhere:
        print(f"external evidence: {len(found.elsewhere)} citation(s) naming "
              "another repository, checked by the project that owns it")

    # Not a suppression this time but its neighbor: claims nothing falsified and
    # nothing confirmed either. `unavailable` above names the oracle that would
    # not answer; this says how much of the documentation is resting on it, and
    # an unreachable address cited from four files is four of these.
    if found.unsettled:
        print(f"unsettled: {len(found.unsettled)} claim(s) resolved because "
              "nothing contradicted them, not because an oracle confirmed them")

    # Same rule once more, and the one this command had no voice for until the
    # ratchet reached it: an exemption list nobody reads the size of is how an
    # allowlist rots. The number is the point of printing it.
    if baseline.exists:
        note = (f"\nbaseline: {len(split.accepted)} claim(s) accepted as "
                f"pre-existing in {baseline.path.name}, until {baseline.until}")
        if baseline.by:
            note += f" ({baseline.by})"
        if split.stale and not _narrowed(args):
            gone = sum(item.count for item in split.stale)
            note += (f"; {gone} no longer present "
                     f"(`kinemata baseline --prune` drops them)")
        print(note)
        _report_reworded(split)
        _report_unscanned(split)

    # A lapsed baseline fails here for the reason it fails `check`: the date is
    # the whole mechanism, and exemptions still in force that nobody has decided
    # again are what it is there to surface.
    #
    # Conditioned on this command having records in the list, which `check`'s
    # copy of this is not. That is not a softer rule, it is the same rule
    # addressed to the right reader: a lapse with no claim records in it is
    # already `check`'s red gate, and a second command going red for somebody
    # else's list teaches both readers that red means "look elsewhere".
    if baseline.exists and baseline.lapsed() and (split.accepted or split.stale):
        print(
            f"\nFAIL: the baseline lapsed on {baseline.until}, and "
            f"{len(split.accepted)} claim(s) here are still exempt under it. "
            "Drive them down, or re-record with a new --until.",
            file=sys.stderr,
        )
        return 1

    if gated.failed or inventory.failed:
        parts = []
        if gated.broken:
            label = "new claim(s)" if baseline.exists else "claim(s)"
            parts.append(
                f"{len(gated.broken)} of {found.checked} {label} do not resolve"
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
        # "All resolve" is not what green means once a baseline is in play, and
        # printing it anyway would be the tool telling its own lie of the kind
        # it exists to catch. The accepted ones are still broken; they are
        # accepted.
        if split.accepted:
            print(f"{found.checked} documentation claim(s) checked; "
                  f"{len(split.accepted)} accepted as pre-existing, "
                  "the rest resolve.")
        else:
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

# A claim deferred until a date, which is what stops a deferral from being an
# ignore list. `path` defers a file the project will produce; `what` defers
# anything else. Both need `until`.
#
# [[promise]]
# path  = "docs/report.md"
# until = "2026-12-01"

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


def _destination(path: str | None) -> Path:
    """Resolve where ``init`` writes, refusing a place it cannot write to.

    The first outside adopter reported this on 2026-09-09: a directory that did
    not exist got a raw ``FileNotFoundError`` traceback out of the write, from
    the first command anyone runs. A tool whose argument is that declarations
    should be true cannot look like it crashed on a typo.

    The three refusals are checked here rather than at each write because with
    ``--ci`` two files are produced in sequence: failing partway through would
    leave a half-scaffolded tree behind, which is the overwrite this command
    already refuses to do, arrived at by another road.
    """
    root = Path(path or ".").resolve()
    if not root.exists():
        raise ConfigError(
            f"{root} does not exist. Create it first -- this writes a config "
            "into a project, it does not create the project."
        )
    if not root.is_dir():
        raise ConfigError(
            f"{root} is not a directory. Name the project root to write into, "
            "not the file to write."
        )
    if not os.access(root, os.W_OK | os.X_OK):
        raise ConfigError(f"{root} is not writable.")
    return root


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
    root = _destination(args.path)
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
        external=settings.context.external,
    )
    print(found.text(verbose=args.verbose))
    if found.failed:
        print(
            f"\nFAIL: what a session loads is {found.over} B over its ceiling.",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_stamp(args: argparse.Namespace) -> int:
    """Mint a citation stamp, or read one back.

    The token is opaque by construction: seven characters buys compactness at
    the cost of legibility, and the trade only pays at second precision -- at
    day precision a plain date is three characters longer and needs no tooling
    at all. That cost is accepted rather than denied, and this is the tooling.

    **Minting emits the timestamp alone, without brackets and without a type.**
    The type says what kind of citation this annotates, which only the writer
    knows, and a default would be this command deciding a question section 5 of
    ``docs/citations.md`` leaves to the adopting project.

    Needs no config, and does not load one. Every other command here reads a
    declaration; this one is a codec, and a decoder that refused to run outside
    a configured project would be unusable in the place a stamp is most often
    met, which is somebody else's document.
    """
    if not args.token:
        print(stamps.encode(datetime.now(UTC)))
        return 0
    stamp = stamps.parse(args.token)
    moment = stamp.moment.isoformat()
    if stamp.type_code is None:
        print(moment)
        return 0
    line = f"{moment} type {stamp.type_code.capitalize()}"
    # The key is printed as well as the type rather than instead of it: the
    # type is the half a reader can act on without a bibliography, and this
    # command deliberately reads no configuration, so it cannot resolve the
    # other half. `kinemata cite` does that.
    if stamp.key is not None:
        line += f" key {stamps.canonical_key(stamp.key)}"
    print(line)
    return 0


def _bibliographies(settings: Settings, *, required: bool = True) -> list[Bibliography]:
    """The declared bibliographies, or a refusal naming what to declare.

    ``required`` is false for the one caller that has a second thing to date: a
    project may declare a resource list and no bibliography at all -- it has
    user-facing documents whose citations need confirming and writes no keyed
    citations of its own -- and refusing there would have made the list
    unusable without machinery it does not need. ``confirm`` still refuses when
    neither is declared, because then there is nothing to confirm.
    """
    found = [r for r in settings.registries if isinstance(r, Bibliography)]
    if not found and required:
        raise ConfigError(
            "no bibliography is declared, so no reference key resolves to "
            'anything. Declare one: a [[registry]] with kind = "bibliography" '
            "and a `source` file holding its entries."
        )
    return found


def _known(text: str, declared: dict[str, Entry]) -> str:
    """One key, canonically spelled, or a refusal.

    A citation naming a key no entry declares is a finding, not a lookup that
    returns nothing -- section 5.3 puts that failure and the duplicate key
    together as the two this scheme is built to catch. Answering with silence
    here would be the tool declining to report the thing it exists for.
    """
    key = stamps.reference_key(text)
    if key not in declared:
        raise ConfigError(undeclared_key(key))
    return key


def cmd_cite(args: argparse.Namespace) -> int:
    """Resolve a reference key, in either direction.

    **Forward** -- what a key points at -- is how a reader gets the readable
    form of a citation that stands alone, which is the whole reason a key may
    stand alone at all.

    **Reverse** (``--where``) is every place a key is cited, and it is what
    makes accompanying affordable: without it, moving a source means finding
    every mention by hand. Its output is bare ``file:line`` because it is meant
    to be fed to an editor or to ``sed`` -- a worklist, not a report.

    **With no argument**, every key and how often it is cited. A key nothing
    cites gets no separate machinery here; it is a declared entry nothing
    mentions, which ``kinemata unused`` already describes.
    """
    settings = _settings(args)
    _note_unfitted(settings)
    if args.where and args.keys:
        raise ConfigError(
            "give keys to resolve, or --where to find citations of one -- not "
            "both. The two directions answer different questions and print "
            "different things."
        )

    books = _bibliographies(settings)
    declared = {entry.id: entry for book in books for entry in book.entries()}

    if args.keys:
        for text in args.keys:
            entry = declared[_known(text, declared)]
            target = str(entry.extra["target"])
            print(f"{entry.id}  {target}  -- {entry.extra['note']}")
            if entry.extra.get("repository"):
                print(f"{' ' * len(entry.id)}  in {entry.extra['repository']}, "
                      "which is where it resolves")
            # The accompany threshold, reported and never enforced. Whether a
            # sentence reads better with its target spelled beside the key is a
            # judgment about that sentence; what a tool can offer is the
            # measurement the judgment needs.
            if args.verbose and len(target) > settings.accompany_max:
                print(f"{' ' * len(entry.id)}  {len(target)} characters, over "
                      f"the declared {settings.accompany_max}: long enough that "
                      "the key reads better standing alone")
        return 0

    suffixes = tuple(dict.fromkeys(
        suffix for book in books for suffix in (book.suffixes or settings.suffixes)
    ))
    found = index(citations(_target(args, settings), suffixes=suffixes,
                            exclude=settings.exclude))

    if args.where:
        key = _known(args.where, declared)
        here = found.get(key, [])
        for citation in here:
            print(citation)
        if not here and not args.quiet:
            # To stderr, so a worklist piped onward stays a worklist. An empty
            # answer and a key nobody cites read identically on stdout.
            print(f"note: nothing cites {key}", file=sys.stderr)
        return 0

    for key in sorted(declared):
        print(f"{key}  {len(found.get(key, ()))}")
    return 0


def cmd_confirm(args: argparse.Namespace) -> int:
    """Verify what the documents cite, and record the ones that held.

    **The one command here that writes into prose**, which is why it describes
    the edit by default and makes it only when asked. Section 7 of
    ``docs/citations.md`` draws the boundary: the gate only ever reports, an
    explicit command writes, and it writes only what it confirmed in that run.
    ``baseline`` already has this shape for the same reason -- a command whose
    normal mode changes a file somebody else has to review should say what it
    would do first.

    **It never gates, and exits 0 on any run that completed.** The exit code is
    what a project would wire into CI, and a check that rewrites the tree it is
    judging can make itself pass. Refusals and dead targets are in the report,
    which is where a writer's findings belong.

    **Two things get dated and they are read by different oracles.** A keyed
    citation is dated where it stands, and its key names the one source to
    settle. A user-facing document is dated in the resource list, and what has
    to hold is *everything it cites* -- which is the question ``claims``
    answers, so this runs the same verification that command does rather than a
    second opinion about the same tree.
    """
    settings = _settings(args)
    _note_unfitted(settings)
    books = _bibliographies(settings, required=not settings.resources)
    suffixes = tuple(dict.fromkeys(
        suffix for book in books for suffix in (book.suffixes or settings.suffixes)
    ))
    made = plan(
        _target(args, settings),
        books,
        suffixes=suffixes,
        exclude=settings.exclude,
        historical=settings.historical,
        external=settings.external,
        timeout=settings.external_timeout,
    )
    print(made.text(verbose=args.verbose, quiet=args.quiet))

    listing = None
    if settings.resources and settings.resources_path is not None:
        listing = dating(
            settings.resources,
            _verify(args, settings),
            source=settings.resources_path,
            when=made.when,
        )
        print()
        print(listing.text(verbose=args.verbose, quiet=args.quiet))

    pending = bool(made.writes) or bool(listing and listing.writes)
    if not args.write:
        if pending and not args.quiet:
            print("\nNothing written. Re-run with --write to record these "
                  "confirmations.")
        return 0

    written = apply(made)
    for rel, count in written:
        print(f"wrote {rel} ({count} stamp(s))")
    if listing is not None and listing.writes:
        entries = redate(listing)
        print(f"wrote {_relative(listing.source, settings.root)} "
              f"({entries} resource date(s))")
    elif not written:
        print("nothing to write")
    return 0


def cmd_stale(args: argparse.Namespace) -> int:
    """Citations nobody has confirmed lately. **Advisory, and exits 0 always.**

    Section 6 keeps provenance and staleness on separate axes, and this is the
    second one. Requiring a stamp is a catch: a missing stamp is a fact about
    the document. Whether a citation is old enough to deserve re-reading is a
    judgment about the world, and gating on the calendar means a build that
    goes red on a day nobody touched the repository.

    **Scoped to the kinds that leave the machine**, which today is addresses.
    A path or a commit is settled locally on every run, so a clock over them
    would restate what ``claims`` already answered this morning -- a review
    list whose every entry is either already a finding or already known good.
    An address costs a network request, which is why settling it is opt-in and
    why the date on it is the only record that it was ever settled at all. The
    scope is read off the claim table (:data:`kinemata.provenance.CLOCKED`),
    so a later kind that needs the network is clocked without an edit here.
    """
    settings = _settings(args)
    _note_unfitted(settings)
    if not settings.provenance:
        raise ConfigError(
            "the citation clock has nothing to measure here: [citations] "
            "provenance is not declared, so citations are not required to "
            "carry a stamp and the ones that do are an accident of who wrote "
            "them. Arm the catch first -- `kinemata baseline --record` accepts "
            "the population you already have."
        )
    found = _survey(args, settings)
    after = timedelta(days=settings.stale_after)
    now = datetime.now(UTC)
    past = found.stale(after=after, now=now)

    for seen in past:
        days = seen.age(now).days
        print(f"{seen.path}:{seen.line}  {seen.text}  ({days} days)")

    clocked = found.clocked()
    if past:
        print()
    print(f"{len(past)} of {len(clocked)} dated citation(s) not confirmed "
          f"within {settings.stale_after} day(s). `kinemata confirm` re-dates "
          "the ones that still resolve.")
    # The population the clock cannot see, counted rather than left out. A
    # review list is only meaningful next to the size of what it was drawn
    # from, which is the same argument the baseline's printed size rests on.
    blind = found.unclocked()
    if blind:
        print(f"{len(blind)} further citation(s) of the same kind carry no "
              "stamp at all, so the clock says nothing about them. They are "
              "`kinemata check`'s findings, not this list's.")
    _report_resources(settings, found)
    _report_unassociated(found)
    return 0  # advisory, always


def _gate_for(scope: str) -> str:
    """Which command fails on a record from this finding source.

    Three sources feed one exemption list, and naming the wrong one sends a
    reader to a green run. That already happened once with two: a reader told a
    dead reference was exempt from ``check`` went and looked at a command that
    was never going to report it.
    """
    if scope == CLAIMS_REGISTRY:
        return "`kinemata claims`"
    if is_strays_scope(scope):
        return "`kinemata undeclared`"
    return "`kinemata check`"


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

    **Scoped to what this command scans.** The same file holds ``claims``'
    exemptions and this command does not read documentation; unscoped, every
    accepted dead reference would be reported here as no longer present, by a
    command that never looked for it, under a line recommending ``--prune``.
    """
    settings, reports, found = _run_review(args)
    baseline = Baseline.load(settings.baseline)
    split = baseline.split(_strong(reports), scope=[name for name, _ in reports])

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
    _report_unreadable(settings)
    _report_exclusions(settings)
    _report_resources(settings, found)
    _report_unassociated(found)

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
        _report_reworded(split)
        _report_unscanned(split)

    # A lapsed baseline fails even with nothing new, because that is the whole
    # point of the date: the exemptions are still in force and nobody has looked
    # at them since the day somebody said they would.
    #
    # **Unconditional, and deliberately not symmetric with `claims`**, which
    # lapses only when the list actually exempts a claim. The asymmetry was
    # weighed on 2026-09-11 and kept. This command is the backstop: a scoped
    # scan reaches only the registries the config still declares, so records
    # belonging to a registry somebody deleted are reported as unscanned and
    # judged by nothing. Were this conditional too, those records would sit in
    # an exemption list that cannot expire -- which is precisely what `Promise`
    # and `Baseline` both refuse by construction.
    #
    # The cost is that a claims-only lapse turns this red for a list it does not
    # judge. Accepted, because a lapse is not weather: somebody dated a decision
    # and the date passed. The report above already says which records are this
    # command's business and which are not.
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

    **This is the one command that runs every check**, because it is the one
    command that writes the file. ``check`` and ``claims`` each cover their own
    half and are scoped accordingly; a ``--prune`` that covered only one half
    would delete the other's records on the strength of never having looked.

    ⚑ **And running a check is not the same as the check answering**, which is
    the other half of the same guarantee: a write is refused outright while any
    declared oracle is blocked. See the guard below for what that costs and why
    it is worth it.
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

    settings, reports, found = _run_review(args, registry_required=False)
    _report_unassociated(found)
    findings = _strong(reports)

    # **Every check that feeds the list, run by the one command that writes it.**
    # `--prune` rebuilds the file from what this scan produced, so a source it
    # did not run is a set of records silently deleted -- the same failure
    # `_narrowed` refuses a registry filter for, and skipping the documentation
    # scan here would be that failure with a runtime argument in front of it.
    # The cost is real and accepted: this now reaches the network and runs the
    # declared count oracles, exactly as `kinemata claims` does.
    #
    # Guarded the way the citation catch is, so `baseline -r claims` shows the
    # documentation half alone.
    stalled: list[str] = []
    # ⚑ And not at all when nothing declares claims work. `kinemata claims`
    # refuses such a config outright, so recording its findings would fill the
    # baseline from a scan the gate will never run -- which is how an adopter's
    # registry-only config accumulated 356 documentation findings in a file
    # nothing would ever read. The writer and the gate answer to one rule.
    if args.registry in (None, CLAIMS_REGISTRY) and settings.checks_claims:
        verified = _verify(args, settings)
        findings += verified.findings()
        stalled += verified.blocked

    # Catch A, for the same reason and with the same cost. Added 2026-09-13 when
    # the catch was ratcheted: a finding source the writing command does not run
    # is a set of records `--prune` deletes in silence, and this one is worse
    # than the documentation half because a dropped stray record re-fails a
    # *closed* registry -- the gate nobody can open again without editing the
    # config.
    #
    # `_strays` honors `--registry` like every other scan here, and `_narrowed`
    # has already refused `--record`/`--prune` if one was given.
    findings += _gating_strays(_strays(args, settings, _target(args, settings)))

    # Parity, for the third time and the same reason. Its oracles are declared
    # commands, so this is the second place `baseline` spawns a subprocess --
    # accepted knowingly, because a scan that does not run cannot author the
    # exemptions it is about to rewrite.
    for result in _parity(args, settings, _target(args, settings)):
        findings += result.findings()
        if result.blocked:
            stalled.append(f"{result.registry}: {result.blocked}")

    # Shape, for the fourth time and the same reason -- and it brings a second
    # way for a check not to have answered: a rule that examined no entry ran
    # without judging anything, so its records are exactly as unearned as a
    # blocked oracle's. Both stall the rewrite.
    for shaped in _shape(args, settings):
        findings += shaped.findings()
        stalled += [f"{shaped.registry}: {why}" for why in shaped.unjudged()]

    # Probe, for the fifth time and the same reason. It brings the third way a
    # check can run without answering: a corpus carrying one polarity called the
    # project's code and still could not tell a discriminating callable from a
    # constant one. **The rule generalizes past oracles** -- anything that can
    # look like it checked while checking nothing must stall the writer.
    for probed in _probe(args, settings):
        findings += probed.findings()
        if probed.blocked or probed.vacuous:
            stalled.append(probed.unjudged())

    # **A scan that could not run must not author the list.** Running every
    # check is only half the guarantee: an oracle that is not installed here
    # produces no findings, which is indistinguishable from a tree where it
    # found nothing -- and both `--record` and `--prune` rebuild the file from
    # what this run produced, so every record that oracle was covering is
    # deleted by a machine that merely lacks the command. Measured, not
    # reasoned about: a broken parity oracle dropped a recorded exemption and
    # reported it as no longer present.
    if stalled and (args.record or args.prune):
        print(
            "error: refusing to rewrite the baseline while a declared oracle "
            "cannot answer. Its records would be dropped as though the "
            "findings were fixed:",
            file=sys.stderr,
        )
        for why in stalled:
            print(f"  BLOCKED: {why}", file=sys.stderr)
        return 2

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
        # Asked before the write, because `exists` asks the filesystem and
        # `save` is about to create the file: read afterwards, a first recording
        # reports itself as "+11 against the previous baseline" there was none
        # of. Found while pasting this command's output into a report.
        existed = baseline.exists
        fresh.save()
        change = f" ({delta:+d} against the previous baseline)" if existed else ""
        print(f"Recorded {fresh.size} accepted finding(s){change} in {settings.baseline}.")
        if delta > 0:
            # Growth is the failure mode. Say so at the moment it happens, since
            # the alternative is noticing it in a diff nobody reads closely.
            #
            # Every gate named, not one. This list stopped being `check`'s alone
            # when documentation started riding it, and a reader told that a
            # dead reference is exempt from `check` would go look at a command
            # that was never going to report it. Catch A joined them 2026-09-13,
            # which is why this is now derived from the records rather than
            # spelled out -- a hand-written list of gates is the thing that went
            # stale the first time.
            named = ", ".join(sorted({_gate_for(name) for name, _ in split.new}))
            print(f"{delta} finding(s) newly accepted. Every one is now exempt "
                  f"from {named or '`kinemata check`'} until it is fixed and "
                  f"the baseline re-recorded.")
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
        # Named by the gate that would fail, not by one of them: this list feeds
        # two commands and telling a reader to look at `check` for a dead link
        # sends them to a green run.
        gates = sorted({_gate_for(name) for name, _ in split.new})
        print(f"{len(split.new)} finding(s) not accepted -- "
              f"{', '.join(gates)} fails on these.")
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


def _common(*, hold: bool) -> argparse.ArgumentParser:
    """Flags accepted both before and after the subcommand.

    Without this, ``kinemata ids -r keys`` fails while ``kinemata -r keys ids``
    works -- an ordering rule nobody remembers and every user gets wrong.

    ``hold`` is what makes it work in *both* directions, and its absence was a
    real defect. argparse parses a subcommand into a fresh namespace and copies
    every key of it over the outer one, so the subparser's own default silently
    overwrote a value given before the subcommand. Measured 2026-09-09 --
    ``kinemata -c canon.toml context`` reported "no [context] declared" while
    reading the *repository's* config, having discarded the path it was handed.
    A flag dropped in silence is worse than one rejected: the command still runs,
    against something else.

    So the subparsers hold their defaults (``SUPPRESS``, carrying only what was
    actually typed) and the top-level parser supplies the real ones. They must be
    two separate calls, because ``parents=`` shares `argparse.Action` objects by
    reference -- the first attempt at this fix set the defaults with
    ``set_defaults``, which walks those same shared actions and reassigns
    ``.default``, undoing the ``SUPPRESS`` it had just been given.
    """
    common = argparse.ArgumentParser(add_help=False)
    absent = argparse.SUPPRESS
    common.add_argument("-c", "--config", default=absent if hold else None,
                        help=f"path to {CONFIG_NAMES[0]}")
    common.add_argument("-r", "--registry", default=absent if hold else None,
                        help="limit to one registry by name")
    common.add_argument("-q", "--quiet", action="store_true",
                        default=absent if hold else False)
    common.add_argument("-v", "--verbose", action="store_true",
                        default=absent if hold else False,
                        help="list weak signals and suppressed antipatterns")
    common.add_argument("--max-sites", type=int, default=absent if hold else None,
                        help="suppress antipatterns matching more sites than this "
                             "(negative disables suppression)")
    return common


def build_parser() -> argparse.ArgumentParser:
    common = _common(hold=True)
    parser = argparse.ArgumentParser(
        prog="kinemata",
        parents=[_common(hold=False)],
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

    par = sub.add_parser("parity", parents=[common],
                         help="gate: a declaration and what the code actually "
                              "produces, set against each other")
    par.add_argument("path", nargs="?", help="limit the scan to this path")
    par.set_defaults(func=cmd_parity)

    # No `path`: this one reads the declaration, not the tree, so a path would
    # be an argument it could only ignore.
    shp = sub.add_parser("shape", parents=[common],
                         help="gate: a declaration against the rules it states "
                              "about its own shape")
    shp.set_defaults(func=cmd_shape)

    # No `path` either, and for a second reason on top of shape's: the corpus is
    # the project's to produce, so there is no tree here to narrow.
    prb = sub.add_parser("probe", parents=[common],
                         help="gate: what the project's code accepts and "
                              "refuses, against what it declared")
    prb.set_defaults(func=cmd_probe)

    unu = sub.add_parser("unused", parents=[common],
                         help="advisory: declared entries nothing mentions "
                              "(a review list, never a cut list)")
    unu.add_argument("path", nargs="?", help="limit the scan to this path")
    unu.set_defaults(func=cmd_unused)

    clm = sub.add_parser("claims", parents=[common],
                         help="gate: fail on a documentation claim the baseline "
                              "does not already accept")
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

    stm = sub.add_parser("stamp", parents=[common],
                         help="mint a citation stamp, or decode one")
    stm.add_argument("token", nargs="?",
                     help="a stamp to read (default: mint one for now)")
    stm.set_defaults(func=cmd_stamp)

    cit = sub.add_parser("cite", parents=[common],
                         help="resolve a reference key: what it points at, "
                              "where it is cited, or every key with its count")
    cit.add_argument("keys", nargs="*",
                     help="keys to resolve (default: every key and its "
                          "citation count)")
    cit.add_argument("--where", metavar="KEY",
                     help="every file:line citing this key, one per line")
    cit.set_defaults(func=cmd_cite)

    con = sub.add_parser("confirm", parents=[common],
                         help="verify what the documents cite, and date the "
                              "citations that held (writes only with --write)")
    con.add_argument("path", nargs="?", help="limit the run to this path")
    con.add_argument("--write", action="store_true",
                     help="record the confirmations in the documents themselves")
    con.set_defaults(func=cmd_confirm)

    sta = sub.add_parser("stale", parents=[common],
                         help="citations nobody has confirmed lately "
                              "(advisory; never gates)")
    sta.add_argument("path", nargs="?", help="limit the run to this path")
    sta.set_defaults(func=cmd_stale)

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
    for attr in ("path", "strict", "record", "prune", "until", "by", "note",
                 "token", "keys", "where"):
        if not hasattr(args, attr):
            setattr(args, attr, None)
    try:
        return args.func(args)
    except (ClaimsError, ConfigError, BaselineError, StampError,
            ConfirmError, ProvenanceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
