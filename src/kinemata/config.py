"""Declaring registries without writing Python.

A mechanism nobody can turn on is not a mechanism. This reads a ``kinemata.toml``
so adopting the tool is a config file, not a subclass.

TOML because ``tomllib`` is stdlib: the core takes no dependency. A registry
whose source is YAML pulls PyYAML in only when that source is declared.

Example::

    [project]
    root = "."
    exclude = ["tests/", "build/"]

    [[registry]]
    name = "constants"
    kind = "python-constants"
    modules = ["src/pkg/constants.py"]

    [[registry]]
    name = "keys"
    kind = "yaml-mapping"
    source = "keyspace-manifest.yaml"
    section = "keys"
    clause_field = "spec"
    syntax = '\\b[a-z_]+(?:\\.[a-z_]+)+\\b'
    closed = true
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .adapters.constants import PythonConstants
from .adapters.mapping import MappingRegistry
from .adapters.patterns import CodePatterns
from .adapters.substitutions import Substitutions
from .baseline import BASELINE_NAME
from .bypass import git_ignored
from .claims import EXTERNAL_TIMEOUT, Counted, Promise
from .context import STRIPPERS
from .contract import BaseRegistry
from .gates import Gate

CONFIG_NAMES = ("kinemata.toml", ".kinemata.toml")


class ConfigError(Exception):
    """A registry declaration that cannot be honored.

    Raised rather than skipped. A misconfigured registry that silently scans
    nothing is the inert-signal failure: green, and checking nothing.
    """


#: Files whose claims about the tree are worth falsifying, and the fragments
#: that mark a record as superseded. Defaults rather than requirements: a
#: project with no ``[claims]`` table still gets its markdown checked.
DEFAULT_CLAIM_SUFFIXES = (".md",)


@dataclass(frozen=True)
class ContextBudget:
    """The declared instruction layer and what it may weigh."""

    include: tuple[str, ...]
    budget: int
    strip: tuple[str, ...] = ()


@dataclass
class Settings:
    root: Path
    registries: list[BaseRegistry] = field(default_factory=list)
    exclude: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = (".py",)
    max_sites: int | None = None
    claim_suffixes: tuple[str, ...] = DEFAULT_CLAIM_SUFFIXES
    #: Path fragments holding superseded records. An archive cites paths and
    #: commits that were real when written; checking it for currency reports
    #: the archive for being an archive.
    historical: tuple[str, ...] = ()
    #: Sibling trees a documentation claim may resolve against.
    resolve_in: tuple[str, ...] = ()
    #: Further repositories whose commits the documentation may cite.
    commits_in: tuple[str, ...] = ()
    #: May `claims` leave the machine to settle a URL? Off by default, and the
    #: number of links it therefore skips is printed rather than assumed.
    external: bool = False
    external_timeout: float = EXTERNAL_TIMEOUT
    #: Paths a design says it will produce. Held open while absent, and failing
    #: once they exist, once nothing cites them, or once their date has passed --
    #: three ways of noticing that the list has outlived the work it describes.
    promised: tuple[Promise, ...] = ()
    #: Numbers the documentation states, and the commands that settle them.
    #: Empty unless declared: no project spawns a process it did not ask for.
    counts: tuple[Counted, ...] = ()
    #: Where accepted findings are recorded. Always a path, even when no file is
    #: there yet -- ``baseline --record`` has to know where to write the first
    #: one, and a project that has never recorded is the normal starting state.
    baseline: Path = field(default_factory=lambda: Path(BASELINE_NAME))
    #: Checks the project declares must run, verified against the files meant to
    #: run them. Empty unless declared: a project that has not said which checks
    #: are required has not made a claim to falsify.
    gates: tuple[Gate, ...] = ()
    #: What a session loads, and what it may weigh. ``None`` when the project has
    #: not declared a ``[context]`` table -- distinct from a ceiling of zero.
    context: ContextBudget | None = None


def find_config(start: str | Path = ".") -> Path | None:
    """Nearest config, searching upward. Returns ``None`` if there is none."""
    current = Path(start).resolve()
    for directory in (current, *current.parents):
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _build_constants(spec: dict[str, Any], root: Path) -> BaseRegistry:
    modules = spec.get("modules")
    if not modules:
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: python-constants needs 'modules'"
        )
    paths = [root / m for m in modules]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: module(s) not found: {missing}"
        )
    registry = PythonConstants(
        paths,
        root=root,
        min_length=spec.get("min_length", 4),
        include_private=spec.get("include_private", False),
        closed=spec.get("closed", False),
    )
    registry.name = spec.get("name", "constants")
    return registry


def _build_yaml_mapping(spec: dict[str, Any], root: Path) -> BaseRegistry:
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - depends on env
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: kind 'yaml-mapping' needs PyYAML"
        ) from exc

    source = spec.get("source")
    if not source:
        raise ConfigError(f"registry {spec.get('name', '?')!r}: needs 'source'")
    path = root / source
    if not path.is_file():
        raise ConfigError(f"registry {spec.get('name', '?')!r}: no such file: {path}")

    document = yaml.safe_load(path.read_text()) or {}
    section = spec.get("section")
    if section:
        if section not in document:
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: section {section!r} not in {source}"
            )
        document = document[section]

    return MappingRegistry(
        document,
        name=spec.get("name", "keys"),
        clause_field=spec.get("clause_field"),
        syntax=spec.get("syntax"),
        closed=spec.get("closed", False),
        budget=spec.get("budget"),
        line_budget=spec.get("line_budget"),
    )


def _build_code_patterns(spec: dict[str, Any], root: Path) -> BaseRegistry:
    declarations = spec.get("entry")
    if not declarations:
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: code-patterns needs at least "
            "one [[registry.entry]] table"
        )
    try:
        return CodePatterns(declarations, name=spec.get("name", "patterns"),
                            closed=spec.get("closed", False))
    except ValueError as exc:
        raise ConfigError(f"registry {spec.get('name', '?')!r}: {exc}") from exc


def _build_substitutions(spec: dict[str, Any], root: Path) -> BaseRegistry:
    """Forbidden spellings, inline or from their own file.

    A file, because a style convention runs to dozens of pairs and burying them
    in the project config hides the rest of it. Inline, because a project with
    three retired names should not need a second file to say so.
    """
    words = spec.get("words")
    source = spec.get("source")
    if words and source:
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: give 'words' or 'source', not both"
        )
    if source:
        path = root / source
        if not path.is_file():
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: no such file: {path}"
            )
        try:
            words = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: cannot read {path}: {exc}"
            ) from exc
        words = words.get("words", words)
    if not words:
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: substitutions needs 'words' "
            "or a 'source' file holding them"
        )
    try:
        return Substitutions(
            words,
            name=spec.get("name", "substitutions"),
            closed=spec.get("closed", False),
            case_sensitive=spec.get("case_sensitive", False),
            boundary=spec.get("boundary", "prose"),
        )
    except ValueError as exc:
        raise ConfigError(f"registry {spec.get('name', '?')!r}: {exc}") from exc


BUILDERS = {
    "python-constants": _build_constants,
    "yaml-mapping": _build_yaml_mapping,
    "code-patterns": _build_code_patterns,
    "substitutions": _build_substitutions,
}


def load(path: str | Path) -> Settings:
    """Read a ``kinemata.toml`` into ready-to-use registries."""
    path = Path(path)
    try:
        raw = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"cannot read {path}: {exc}") from exc

    project = raw.get("project", {})
    root = (path.parent / project.get("root", ".")).resolve()

    declarations = raw.get("registry", [])
    # **A config that asks for no check at all is the error** -- not one that
    # declares no registry. The rule used to demand a `[[registry]]`, aimed at
    # the failure where an empty registry reads exactly like a clean tree; but
    # that failure is an empty registry, not an absent one. A project adopting
    # `claims` or `context` alone had to invent a registry to satisfy the
    # loader, and a required fiction is a bad first impression from a tool whose
    # whole argument is that declarations should be true. Measured on the one
    # real integration: one `[[registry]]` existed solely to get past this line.
    #
    # Commands that need a registry refuse individually instead, which is the
    # shape `context` and `undeclared` already use.
    if not any((declarations, raw.get("count"), raw.get("gate"),
                raw.get("claims") is not None, raw.get("context") is not None)):
        raise ConfigError(
            f"{path}: declares no check at all. A config needs at least one of "
            "[[registry]], [[count]], [[gate]], [claims] or [context] -- "
            "otherwise every command it configures would pass by doing nothing."
        )

    registries: list[BaseRegistry] = []
    for spec in declarations:
        kind = spec.get("kind")
        builder = BUILDERS.get(kind)
        if builder is None:
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: unknown kind {kind!r} "
                f"(known: {', '.join(sorted(BUILDERS))})"
            )
        registry = builder(spec, root)
        # Applied here rather than in each builder: every kind of registry can
        # be pointed at a different file set, and three copies of one line is
        # the thing this package exists to report.
        if "suffixes" in spec:
            registry.suffixes = tuple(spec["suffixes"])
        if "machinery" in spec:
            registry.machinery = tuple(spec["machinery"])
        # Every declaration above can be individually valid and still produce a
        # registry with nothing in it -- the modules exist and parse, they just
        # hold nothing this adapter recognizes. That check passes, reports
        # nothing, and reads exactly like compliance.
        #
        # Found by dogfooding: this project declared `python-constants` over
        # three of its own modules for six commits. It has no module-level
        # string constants at all, so the projection was empty and `check`
        # exited 0 the whole time. The wrong adapter, not a clean tree.
        if not spec.get("allow_empty", False) and not any(True for _ in registry.entries()):
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: kind {kind!r} produced no "
                "entries, so it would scan for nothing and pass. Point it at a "
                "source it can read, or set allow_empty = true if it is "
                "deliberately empty while being bootstrapped."
            )
        # A registry declared `closed` promises that an undeclared identifier is
        # an error -- a promise it can only keep if it can recognize an
        # identifier at all. Every kind accepts `closed`; only `yaml-mapping`
        # implements recognition, so the other three could be declared closed
        # and would answer nothing, which reads exactly like a clean tree.
        #
        # `__post_init_check__` existed to ask, and was called from nowhere for
        # the mechanism's whole life. Called here because this is the one place
        # a registry is built from configuration.
        try:
            registry.__post_init_check__()
        except NotImplementedError as exc:
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: kind {kind!r} cannot be "
                f"closed. {exc}"
            ) from exc

        registries.append(registry)

    claims = raw.get("claims", {})
    # What git ignores is not this project's material, and every check here asks
    # that same question. Answered once, in the one place settings come from.
    exclude = tuple(project.get("exclude", ())) + git_ignored(root)
    return Settings(
        root=root,
        registries=registries,
        exclude=exclude,
        suffixes=tuple(project.get("suffixes", (".py",))),
        max_sites=project.get("max_sites"),
        claim_suffixes=tuple(claims.get("suffixes", DEFAULT_CLAIM_SUFFIXES)),
        historical=tuple(claims.get("historical", ())),
        resolve_in=tuple(claims.get("resolve_in", ())),
        commits_in=tuple(claims.get("commits_in", ())),
        external=bool(claims.get("external", False)),
        external_timeout=float(claims.get("external_timeout", EXTERNAL_TIMEOUT)),
        promised=_promised(raw.get("promise"), claims, path),
        counts=_build_counts(raw.get("count", []), path,
                             _commands(raw.get("command"), path)),
        baseline=root / project.get("baseline", BASELINE_NAME),
        gates=_build_gates(raw.get("gate", []), path),
        context=_build_context(raw.get("context"), path),
    )


#: What a promise may say. Anything else is refused rather than ignored: a
#: misspelled key would drop the date silently and leave a deferral that expires
#: never, which is the whole failure this field exists to prevent.
PROMISE_KEYS = frozenset({"path", "what", "until", "note", "by"})

#: How to spell one, quoted in every refusal so the fix is on screen.
PROMISE_FORM = '[[promise]] with `until = "YYYY-MM-DD"` and either `path` or `what`'


def _promise(entry: Any, path: Path) -> Promise:
    """One deferral and the date it lapses.

    **Two kinds, one table.** ``path`` defers a claim about a file the project
    intends to produce, and the tree can end it three ways. ``what`` defers
    anything else -- a question left open, a threshold not yet measured, a
    finding reviewed and set aside -- and only the date can end that. The second
    kind exists because every deferral in a project has this shape, and a tool
    that dates only the ones it can see for itself leaves the rest as good
    intentions in prose.

    **Both fields are required and no value means "never".** A deferral that
    cannot lapse is an ignore list with a better name. If the work has no
    schedule the date is still answerable: it is when somebody looks at this
    again, not when the work ships.
    """
    if not isinstance(entry, dict):
        raise ConfigError(
            f"{path}: a promise is a table, not {entry!r}. Write {PROMISE_FORM}."
        )
    unknown = set(entry) - PROMISE_KEYS
    if unknown:
        raise ConfigError(
            f"{path}: promise {entry.get('path') or entry.get('what') or entry!r} "
            f"declares {', '.join(sorted(unknown))}, which means nothing here "
            f"(known: {', '.join(sorted(PROMISE_KEYS))})."
        )
    if bool(entry.get("path")) == bool(entry.get("what")):
        raise ConfigError(
            f"{path}: promise {entry!r} needs exactly one of `path` (a file the "
            "project will produce) or `what` (anything else being deferred)."
        )
    if not entry.get("until"):
        raise ConfigError(
            f"{path}: promise {entry.get('path') or entry.get('what')!r} names "
            f"no date it lapses. Write {PROMISE_FORM} -- there is no value "
            "meaning never."
        )
    until = entry["until"]
    # `date`, because TOML parses a bare 2026-12-01 into one; a quoted string is
    # the likelier spelling and both should work.
    if not isinstance(until, date):
        try:
            until = date.fromisoformat(str(until))
        except ValueError as exc:
            raise ConfigError(
                f"{path}: promise {entry.get('path') or entry.get('what')!r} is "
                f"deferred until {until!r}, which is not a date. Write it as "
                "YYYY-MM-DD."
            ) from exc
    try:
        return Promise(
            until=until,
            path=str(entry["path"]) if entry.get("path") else None,
            what=str(entry["what"]) if entry.get("what") else None,
            note=str(entry.get("note", "")),
            by=str(entry.get("by", "")),
        )
    except ValueError as exc:
        raise ConfigError(f"{path}: {exc}") from exc


def _promised(raw: Any, claims: dict[str, Any], path: Path) -> tuple[Promise, ...]:
    """The ``[[promise]]`` tables -- or a refusal.

    Every entry here suppresses something, so a malformed one suppresses nothing
    while looking like it does.
    """
    if claims.get("promised") is not None:
        raise ConfigError(
            f"{path}: [claims] promised has moved to [[promise]] tables, which "
            "defer a `what` as well as a `path`. Write "
            f"{PROMISE_FORM}."
        )
    if raw is None:
        return ()
    if not isinstance(raw, (list, tuple)):
        raise ConfigError(
            f"{path}: promises are declared as [[promise]] tables, not "
            f"{type(raw).__name__}."
        )
    return tuple(_promise(entry, path) for entry in raw)


def _build_context(spec: dict[str, Any] | None, path: Path) -> ContextBudget | None:
    """The ``[context]`` table, refused rather than half-honored.

    There is deliberately **no default ceiling**. No number is right for every
    project, and a default would be a number nobody chose being enforced as
    though somebody had. Measure first, set the ceiling at what you already
    carry, then drive it down.
    """
    if spec is None:
        return None
    include = spec.get("include")
    budget = spec.get("budget")
    missing = [key for key, value in (("include", include), ("budget", budget))
               if not value]
    if missing:
        raise ConfigError(
            f"{path}: [context] is missing {', '.join(missing)}. A budget with "
            "nothing to weigh, or a set with no ceiling, checks nothing."
        )
    strip = tuple(str(name) for name in spec.get("strip", ()))
    unknown = [name for name in strip if name not in STRIPPERS]
    if unknown:
        raise ConfigError(
            f"{path}: [context] strip has unknown transform(s) {unknown} "
            f"(known: {', '.join(sorted(STRIPPERS))})"
        )
    return ContextBudget(
        include=tuple(str(pattern) for pattern in include),
        budget=int(budget),
        strip=strip,
    )


def _build_gates(declarations: list[dict[str, Any]], path: Path) -> tuple[Gate, ...]:
    """``[[gate]]`` tables. A gate with no command declares nothing.

    Refused rather than skipped, for the same reason a half-declared count is:
    it looks configured and settles nothing, which is the inert signal wearing
    the shape of a check.
    """
    built: list[Gate] = []
    for index, spec in enumerate(declarations):
        command = spec.get("command")
        if not command:
            raise ConfigError(f"{path}: [[gate]] {index} is missing 'command'")
        built.append(
            Gate(
                command=str(command),
                where=tuple(str(item) for item in spec.get("where", ())),
                note=str(spec.get("note", "")),
            )
        )
    return tuple(built)


def _commands(raw: Any, path: Path) -> dict[str, tuple[str, ...]]:
    """The ``[command]`` table: an oracle named once, used by several counts.

    **Written because this package's own config format forced the antipattern
    it exists to catch.** ``[[count]]`` binds one command to one number and TOML
    cannot share a value, so a real integration ended up with eight inline
    programs of which only four were distinct -- one 25-line oracle copied three
    times, differing in the file it was pointed at. ``kinemata check`` cannot
    see that: a config is not source.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise ConfigError(
            f"{path}: [command] must be a table of name = [argv], not "
            f"{type(raw).__name__}."
        )
    declared: dict[str, tuple[str, ...]] = {}
    for name, argv in raw.items():
        if isinstance(argv, str) or not isinstance(argv, (list, tuple)) or not argv:
            raise ConfigError(
                f"{path}: [command] {name!r} must be a non-empty list of "
                "arguments, the way a shell would receive them."
            )
        declared[name] = tuple(str(part) for part in argv)
    return declared


def _build_counts(
    declarations: list[dict[str, Any]],
    path: Path,
    commands: dict[str, tuple[str, ...]] | None = None,
) -> tuple[Counted, ...]:
    """``[[count]]`` tables, refused rather than skipped when incomplete.

    A half-declared count is the worst outcome available: it looks configured
    and settles nothing.

    A count names its oracle inline with ``command``, or by ``run`` against the
    ``[command]`` table, and ``args`` appends to either. Naming one that was
    never declared raises rather than defaulting, for the same reason an unknown
    ``strip`` transform does: the alternative is a count that silently settles
    nothing.
    """
    known = commands or {}
    built: list[Counted] = []
    for index, spec in enumerate(declarations):
        if spec.get("command") and spec.get("run"):
            raise ConfigError(
                f"{path}: [[count]] {index} declares both 'command' and 'run'; "
                "one names the oracle inline, the other names a declared one."
            )
        if spec.get("run"):
            name = str(spec["run"])
            if name not in known:
                raise ConfigError(
                    f"{path}: [[count]] {index} runs {name!r}, which no "
                    f"[command] declares (known: {', '.join(sorted(known)) or 'none'})"
                )
            argv: tuple[str, ...] = known[name]
        else:
            argv = tuple(str(part) for part in spec.get("command", ()))

        missing = [key for key in ("pattern", "extract") if not spec.get(key)]
        if not argv:
            missing.append("command")
        if missing:
            raise ConfigError(
                f"{path}: [[count]] {index} is missing {', '.join(missing)}"
            )
        argv += tuple(str(part) for part in spec.get("args", ()))
        built.append(
            Counted(
                pattern=str(spec["pattern"]),
                command=argv,
                extract=str(spec["extract"]),
                label=str(spec.get("label", "count")),
                directory=str(spec.get("directory", ".")),
            )
        )
    return tuple(built)
