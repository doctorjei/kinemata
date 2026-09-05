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
from pathlib import Path
from typing import Any

from .adapters.constants import PythonConstants
from .adapters.mapping import MappingRegistry
from .adapters.patterns import CodePatterns
from .adapters.substitutions import Substitutions
from .bypass import git_ignored
from .claims import Counted
from .contract import BaseRegistry

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
    #: Numbers the documentation states, and the commands that settle them.
    #: Empty unless declared: no project spawns a process it did not ask for.
    counts: tuple[Counted, ...] = ()


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
    if not declarations:
        raise ConfigError(f"{path}: no [[registry]] declared")

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
        counts=_build_counts(raw.get("count", []), path),
    )


def _build_counts(declarations: list[dict[str, Any]], path: Path) -> tuple[Counted, ...]:
    """``[[count]]`` tables, refused rather than skipped when incomplete.

    A half-declared count is the worst outcome available: it looks configured
    and settles nothing.
    """
    built: list[Counted] = []
    for index, spec in enumerate(declarations):
        missing = [key for key in ("pattern", "command", "extract") if not spec.get(key)]
        if missing:
            raise ConfigError(
                f"{path}: [[count]] {index} is missing {', '.join(missing)}"
            )
        built.append(
            Counted(
                pattern=str(spec["pattern"]),
                command=tuple(str(part) for part in spec["command"]),
                extract=str(spec["extract"]),
                label=str(spec.get("label", "count")),
                directory=str(spec.get("directory", ".")),
            )
        )
    return tuple(built)
