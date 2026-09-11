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

    [[registry]]
    name = "keyspace"
    kind = "import"
    target = "mypkg.registries:KeyspaceRegistry"

The kinds are a convenience, not the boundary. ``import`` names a class the
project wrote, for a data model none of the others fit; see
:func:`_build_import` for why it exists and what it refuses.

How a registry *matches* is declared beside what it holds -- ``suffixes``,
``machinery``, ``boundary`` and ``match_mode`` are read on any kind, including
``import``. The adapter's answer is the default; the project's is the
declaration. See :func:`_boundary` and :func:`_match_mode` for what forced each.
"""

from __future__ import annotations

import importlib
import inspect
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from .adapters.bibliography import Bibliography, duplicate_keys
from .adapters.constants import PythonConstants
from .adapters.mapping import MappingRegistry
from .adapters.patterns import CodePatterns
from .adapters.substitutions import Substitutions
from .baseline import BASELINE_NAME
from .bypass import MODE_FILTERS, git_ignored
from .citations import DEFAULT_ACCOMPANY_MAX
from .claims import CLAIMS_REGISTRY, EXTERNAL_TIMEOUT, Counted, Promise
from .context import STRIPPERS
from .contract import (
    BaseRegistry,
    Registry,
    closure_guard,
    missing_members,
    usable_boundary,
)
from .gates import Gate
from .provenance import DEFAULT_STALE_AFTER, PROVENANCE_REGISTRY

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

#: Names a registry may not take, because the baseline already files findings
#: under them for checks that are not registries. Derived from the modules that
#: own them rather than spelled again here -- a third non-registry check would
#: otherwise be reserved in one place and not the other, which is the shape of
#: drift this package reports.
RESERVED_NAMES = frozenset({CLAIMS_REGISTRY, PROVENANCE_REGISTRY})


@dataclass(frozen=True)
class ContextBudget:
    """The declared instruction layer and what it may weigh."""

    include: tuple[str, ...]
    budget: int
    strip: tuple[str, ...] = ()


@dataclass
class Settings:
    root: Path
    #: `Registry`, not `BaseRegistry`: the ``import`` kind admits a class the
    #: project wrote, and the protocol is what such a class is held to.
    registries: list[Registry] = field(default_factory=list)
    exclude: tuple[str, ...] = ()
    suffixes: tuple[str, ...] = (".py",)
    max_sites: int | None = None
    claim_suffixes: tuple[str, ...] = DEFAULT_CLAIM_SUFFIXES
    #: Extensions that make a backticked bare filename a path claim, **added
    #: to** the built-in set rather than replacing it. Declared because the
    #: built-in fourteen are wrong for most repositories and wrong invisibly:
    #: on one adopter's tree the only two content files -- a container
    #: definition carrying a dotted project name, and a `.conf` -- were cited
    #: five times and seen zero times, and the run looked nearly green.
    claim_file_suffixes: tuple[str, ...] = ()
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
    #: Values the documentation states, and the commands that settle them. A
    #: number is one kind of value and gets no special table; see
    #: :class:`kinemata.claims.Counted` for why the comparison is exact.
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
    #: Registries whose adapter recognized nothing in the source they name. Not
    #: dropped and not fatal at load: a registry-shaped command refuses with
    #: these, and `claims` or `context` runs while reporting them.
    #:
    #: `requests` declares its canonical things as code shapes and numbers and
    #: has no module-level string constants at all, so `python-constants` bound
    #: to nothing -- and refusing at load stopped its documentation from being
    #: checked as well. The adapter not fitting is a fact about the project, not
    #: a reason to withhold every other check.
    unfitted: tuple[str, ...] = ()
    #: Things worth saying at load that are not refusals -- today, a project
    #: type code that diverges from the standardized vocabulary. Distinct from
    #: ``unfitted``, which no registry-shaped command may run past: a notice
    #: never stops a command, so folding the two together would either silence
    #: this or turn a legibility remark into a broken build.
    notices: tuple[str, ...] = ()
    #: Longest citation target that still reads comfortably beside its key.
    #: Nothing enforces it; see :data:`kinemata.citations.DEFAULT_ACCOMPANY_MAX`
    #: for the measurement behind the default and for why it is a reminder.
    accompany_max: int = DEFAULT_ACCOMPANY_MAX
    #: Does every citation have to carry a stamp? **Off unless declared.**
    #: Section 6 admits no exemption by kind, so the only dial is the project:
    #: armed on a tree that has never dated a citation, this reports every
    #: citation in it, and a gate that fires on everything on day one is one
    #: somebody switches off. A project arms it and records a baseline, which
    #: is the adoption path the ratchet already exists for.
    provenance: bool = False
    #: Days a citation may go unconfirmed before ``kinemata stale`` surfaces
    #: it. Advisory and never a gate: section 6 keeps provenance and staleness
    #: on separate axes.
    stale_after: int = DEFAULT_STALE_AFTER


def find_config(start: str | Path = ".") -> Path | None:
    """Nearest config, searching upward. Returns ``None`` if there is none."""
    current = Path(start).resolve()
    for directory in (current, *current.parents):
        for name in CONFIG_NAMES:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _build_constants(spec: dict[str, Any], root: Path, path: Path) -> BaseRegistry:
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


def _build_yaml_mapping(spec: dict[str, Any], root: Path, path: Path) -> BaseRegistry:
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


def _build_code_patterns(spec: dict[str, Any], root: Path, path: Path) -> BaseRegistry:
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


def _build_substitutions(spec: dict[str, Any], root: Path, path: Path) -> BaseRegistry:
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


#: What a bibliography's own file may declare. Refused rather than ignored, for
#: the reason an entry's keys are: ``[entries]`` written for ``[[entry]]`` would
#: load a bibliography with nothing in it, and a key that resolves to nothing is
#: worse than a key nobody wrote.
BIBLIOGRAPHY_KEYS = frozenset({"entry", "types"})


def _build_bibliography(spec: dict[str, Any], root: Path, path: Path) -> BaseRegistry:
    """Declared sources, always from their own file.

    A file, and never inline -- which is where this parts company with
    ``substitutions``, whose three retired names do not deserve a second file. A
    bibliography is the one declaration a *reader* of a citation goes looking
    for, and burying it inside the checker's configuration puts it where they
    will not look. It is also the file a move edits, and a config touched every
    time a source moves is a config nobody reviews.
    """
    name = spec.get("name", "?")
    source = spec.get("source")
    if not source:
        raise ConfigError(
            f"registry {name!r}: bibliography needs 'source', the file its "
            "entries are declared in"
        )
    path = root / source
    if not path.is_file():
        raise ConfigError(f"registry {name!r}: no such file: {path}")
    try:
        document = tomllib.loads(path.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"registry {name!r}: cannot read {path}: {exc}") from exc

    unknown = set(document) - BIBLIOGRAPHY_KEYS
    if unknown:
        raise ConfigError(
            f"registry {name!r}: {source} declares {', '.join(sorted(unknown))}, "
            f"which means nothing here (known: {', '.join(sorted(BIBLIOGRAPHY_KEYS))})."
        )

    try:
        return Bibliography(
            document.get("entry", ()),
            name=spec.get("name", "sources"),
            home=str(source),
            types=document.get("types"),
            interpreted=spec.get("interpreted"),
            standardized=spec.get("standardized"),
            closed=spec.get("closed", False),
        )
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


#: Keys the loader consumes on an ``import`` registry. Everything else in the
#: table is handed to the class as a keyword argument, so a project can
#: parameterize its own adapter without this file learning its vocabulary --
#: which is the whole point of naming a class instead of a kind.
#:
#: ``boundary`` and ``match_mode`` are kept here, with ``suffixes`` and
#: ``machinery``, because they are contract attributes rather than anything a
#: kind invented: the loader sets them on the instance and they work on a
#: project's own class exactly as they do on a built-in one. The cost is that a
#: class taking its own constructor argument of either name will not receive it
#: -- which is why they are named in the refusal a bad key already raises, and
#: why such a class should read the attribute the loader sets instead.
IMPORT_KEYS = frozenset(
    {"name", "kind", "target", "suffixes", "machinery", "allow_empty",
     "boundary", "match_mode"}
)

#: How a target is spelled, quoted in every refusal so the fix is on screen.
#: One module, one attribute in it, both named outright.
TARGET_FORM = 'target = "package.module:ClassName"'


def _build_import(spec: dict[str, Any], root: Path, path: Path) -> Registry:
    """A registry class the project wrote, named from the project's own config.

    **The contract invited an override no config file could reach.**
    ``design.md`` §4.2 says ``declared()`` may be overridden when membership
    cannot be enumerated, and until 2026-09-09 acting on that meant importing
    kinemata as a library: ``BUILDERS`` was a fixed table of kinds, so
    ``[[registry]]`` could not name a class. The first outside audit -- kanibako,
    the project this tool was pitched to on the promise that *a project supplies
    an implementation of the role rather than adopting our data model* -- hit it
    on the one thing they most wanted to declare. Their keyspace is closed but
    not flat: membership is answered by six manifest sections, which is exactly
    the ``declared()`` override the table invites and exactly what the config
    surface could not express. A gap, not a boundary.

    **The target is explicit and never discovered.** No scan of the tree, no
    entry points, no guessing from a package name: one module and one attribute
    in it, so the code this config causes to run is readable in the diff that
    adds it. Discovery would put that decision somewhere nobody reviews.

    The class must be importable by the interpreter running kinemata. Nothing is
    put on ``sys.path`` here on the project's behalf -- a config that could
    inject import paths could shadow a stdlib module from a line of TOML, and
    "install the package" is a fix a person can carry out and verify.
    """
    name = spec.get("name", "?")
    target = spec.get("target")
    parts = target.split(":") if isinstance(target, str) else []
    if len(parts) != 2 or not all(part.strip() for part in parts):
        raise ConfigError(
            f"{path}: registry {name!r} names {target!r}, which is not a target. "
            f"Write {TARGET_FORM}."
        )
    module_name, attribute = (part.strip() for part in parts)

    try:
        module = importlib.import_module(module_name)
    # Importing runs the project's module, so anything at all can come back out
    # of it. Narrowing to ImportError would let the rest escape as a traceback
    # from inside somebody's package, which is what this refusal exists to
    # replace.
    except Exception as exc:
        raise ConfigError(
            f"{path}: registry {name!r} cannot import {module_name!r} for target "
            f"{target!r}: {type(exc).__name__}: {exc}. The package has to be "
            "importable by the interpreter running kinemata -- install it, or "
            "put it on PYTHONPATH."
        ) from exc

    if not hasattr(module, attribute):
        raise ConfigError(
            f"{path}: registry {name!r} names {attribute!r} for target "
            f"{target!r}, and {module_name!r} defines no such attribute."
        )
    obj = getattr(module, attribute)

    if not inspect.isclass(obj):
        raise ConfigError(
            f"{path}: registry {name!r} target {target!r} is a "
            f"{type(obj).__name__}, not a class. Name the registry class itself; "
            "kinemata constructs it."
        )

    arguments = {key: value for key, value in spec.items() if key not in IMPORT_KEYS}
    try:
        inspect.signature(obj).bind(**arguments)
    except TypeError as exc:
        raise ConfigError(
            f"{path}: registry {name!r} target {target!r} will not take the keys "
            f"declared with it ({', '.join(sorted(arguments)) or 'none'}): {exc}. "
            "Every key in the table except "
            f"{', '.join(sorted(IMPORT_KEYS))} is passed to the class as a "
            "keyword argument."
        ) from exc
    except ValueError:  # pragma: no cover - a callable with no readable signature
        # Asked rather than assumed, and a class that will not describe itself
        # still gets constructed below; the constructor is the real authority.
        pass

    try:
        registry = obj(**arguments)
    except Exception as exc:
        raise ConfigError(
            f"{path}: registry {name!r} target {target!r} raised while being "
            f"constructed: {type(exc).__name__}: {exc}"
        ) from exc

    absent = missing_members(registry)
    if absent:
        raise ConfigError(
            f"{path}: registry {name!r} target {target!r} is not a registry -- it "
            f"has no {', '.join(absent)}. Subclass kinemata.contract.BaseRegistry, "
            "which derives everything but entries()."
        )

    # The config's name wins where it is given, as it does for every other kind.
    # Unlike them there is something to fall back to: a project's own class
    # already carries a name, and overwriting it with a default nobody wrote
    # would rename the registry in every report for no reason.
    if spec.get("name"):
        registry.name = str(spec["name"])
    return registry


BUILDERS = {
    "python-constants": _build_constants,
    "yaml-mapping": _build_yaml_mapping,
    "code-patterns": _build_code_patterns,
    "substitutions": _build_substitutions,
    "bibliography": _build_bibliography,
    "import": _build_import,
}

#: Keys the pass in :func:`load` must leave alone because a builder has already
#: consumed them. Only keys that pass would otherwise apply belong here: a
#: builder's own vocabulary -- ``modules``, ``syntax``, ``case_sensitive`` --
#: needs no entry, since nothing reaches for it a second time.
#:
#: One entry, and it is the reason this is a table rather than a rule in prose:
#: ``substitutions`` reads ``boundary`` as *which rule builds its patterns* --
#: ``prose`` or ``identifier`` -- which is a different question from what may
#: abut a match, and one of its two answers is not a character class at all.
#: Applying both meanings to one key would refuse a config that has been valid
#: since the option existed.
#:
#: The two questions share a name deliberately: they are the same question asked
#: of the two matchers, and ``identifier`` means the same rule in both.
BUILDER_KEYS = {"substitutions": frozenset({"boundary"})}


def _match_mode(spec: dict[str, Any], path: Path) -> str:
    """``match_mode`` on any registry, checked against the table that reads it.

    Reported unreachable by the first outside audit on 2026-09-09: the loader
    passed ``suffixes`` and ``machinery`` through and nothing else, so a project
    could not ask for ``raw`` or override the adapter's ``code``/``strings``.

    Refused rather than defaulted, because an unknown mode used to *work*: it
    landed on a table with no entry for the suffix and so filtered nothing,
    which is ``raw`` reached by accident. A misspelling that quietly buys a mode
    nobody asked for is how a project ends up trusting a scan it never
    configured.
    """
    declared = spec["match_mode"]
    if not isinstance(declared, str) or declared not in MODE_FILTERS:
        raise ConfigError(
            f"{path}: registry {spec.get('name', '?')!r} asks for match_mode "
            f"{declared!r}, which selects no filter table "
            f"(known: {', '.join(sorted(MODE_FILTERS))})."
        )
    return declared


def _boundary(spec: dict[str, Any], path: Path) -> str:
    """``boundary`` on any registry whose builder does not claim the key.

    The other half of the same report. ``contract._BOUNDARY`` contains ``.``, so
    ``bootstrap.CHANNELS_PATH`` was invisible to ``detect()`` while bare
    ``CHANNELS_PATH`` was found; the fix made the boundary a registry attribute,
    and this makes it a *declaration*. The adapters' defaults are right for the
    data models they were written for and cannot be right for a model nobody
    here has seen.

    :func:`~kinemata.contract.usable_boundary` decides; this only says which
    registry and which file, because "unknown boundary" with neither is a
    refusal somebody has to go and locate.
    """
    try:
        return usable_boundary(spec["boundary"])
    except ValueError as exc:
        raise ConfigError(
            f"{path}: registry {spec.get('name', '?')!r}: {exc}"
        ) from exc


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
    # Spelled once and read twice from the same place. The condition and the
    # message used to be separate lists, and `[citations] provenance` -- a table
    # that fails a build -- was added to neither: a project declaring only the
    # citation policy was refused, and told to declare one of five things that
    # did not include the one it had. Same shape as the gate count that read
    # "four" until a fifth gate existed.
    #
    # `[citations]` counts only with `provenance` armed. The table's other key
    # is advisory -- `cite -v` reports it and nothing enforces it -- so a config
    # carrying that alone really does check nothing.
    declared_checks = {
        "[[registry]]": bool(declarations),
        "[[count]]": bool(raw.get("count")),
        "[[gate]]": bool(raw.get("gate")),
        "[claims]": raw.get("claims") is not None,
        "[context]": raw.get("context") is not None,
        "[citations] provenance": bool(
            (raw.get("citations") or {}).get("provenance")
        ),
    }
    if not any(declared_checks.values()):
        names = list(declared_checks)
        raise ConfigError(
            f"{path}: declares no check at all. A config needs at least one of "
            f"{', '.join(names[:-1])} or {names[-1]} -- "
            "otherwise every command it configures would pass by doing nothing."
        )

    registries: list[Registry] = []
    unfitted: list[str] = []
    for spec in declarations:
        # The baseline tags every record with the check that produced it, and
        # two of those names belong to checks that are not registries -- the
        # documentation scan and the citation catch. A registry answering to one
        # of them would put its records under a name a gate reads as somebody
        # else's and declines to judge, so the exemption would sit in the file
        # doing nothing while reading as an accepted finding.
        #
        # Refused rather than renamed or suffixed. Guessing what the project
        # meant is how a declaration stops saying what it says, and these are
        # the only two names in the file that are not the project's to choose.
        if spec.get("name") in RESERVED_NAMES:
            reserved = ", ".join(sorted(RESERVED_NAMES))
            raise ConfigError(
                f"{path}: registry {spec['name']!r} takes a name the baseline "
                f"reserves for a check that is not a registry ({reserved}). Its "
                "accepted findings would be filed under that check and no gate "
                "would judge them. Rename the registry."
            )
        kind = spec.get("kind")
        builder = BUILDERS.get(kind)
        if builder is None:
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: unknown kind {kind!r} "
                f"(known: {', '.join(sorted(BUILDERS))})"
            )
        registry = builder(spec, root, path)
        # Applied here rather than in each builder: every kind of registry can
        # be pointed at a different file set, and three copies of one line is
        # the thing this package exists to report.
        if "suffixes" in spec:
            registry.suffixes = tuple(spec["suffixes"])
        if "machinery" in spec:
            registry.machinery = tuple(spec["machinery"])
        # Matching behavior, same place and for the same reason. An adapter's
        # answer is a default: it knows what shape its own data model usually
        # has, and only the project knows what its identifiers are actually
        # spelled like or which files they live in. Set before anything asks the
        # registry a question, so no cached matcher is built from the class
        # default and then contradicted.
        if "match_mode" in spec:
            registry.match_mode = _match_mode(spec, path)
        if "boundary" in spec and "boundary" not in BUILDER_KEYS.get(kind, ()):
            registry.boundary = _boundary(spec, path)
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
            unfitted.append(
                f"registry {spec.get('name', '?')!r}: kind {kind!r} produced no "
                "entries, so it would scan for nothing and pass. Point it at a "
                "source it can read, or set allow_empty = true if it is "
                "deliberately empty while being bootstrapped."
            )
            continue
        # A registry declared `closed` promises that an undeclared identifier is
        # an error -- a promise it can only keep if it can recognize an
        # identifier at all. Every kind accepts `closed`; only `yaml-mapping`
        # implements recognition, so the other three could be declared closed
        # and would answer nothing, which reads exactly like a clean tree.
        #
        # `__post_init_check__` existed to ask, and was called from nowhere for
        # the mechanism's whole life. Called here because this is the one place
        # a registry is built from configuration -- through `closure_guard`,
        # which reaches a project-supplied class that satisfies the protocol
        # without inheriting the base.
        try:
            closure_guard(registry)
        except NotImplementedError as exc:
            raise ConfigError(
                f"registry {spec.get('name', '?')!r}: kind {kind!r} cannot be "
                f"closed. {exc}"
            ) from exc

        registries.append(registry)

    # **The key space is project-wide, not per file.** A project may keep more
    # than one bibliography, and only something holding all of them can see a
    # key that resolves to two different sources depending on which file was
    # read last. Each registry has already refused its own duplicates.
    collisions = duplicate_keys(registries)
    if collisions:
        raise ConfigError(
            f"{path}: {'; '.join(collisions)}. A reference key is unique across "
            "the whole project, so one of these is a second source wearing an "
            "existing key -- pick an unused number rather than renumbering."
        )

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
        claim_file_suffixes=_claim_file_suffixes(claims, path),
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
        unfitted=tuple(unfitted),
        notices=tuple(
            message
            for registry in registries
            for message in getattr(registry, "notices", ())
        ),
        accompany_max=_accompany_max(raw.get("citations"), path),
        provenance=_provenance(raw.get("citations"), path),
        stale_after=_stale_after(raw.get("citations"), path),
        context=_build_context(raw.get("context"), path),
    )


#: What a ``[citations]`` table may say.
CITATION_KEYS = frozenset({"accompany_max", "provenance", "stale_after"})


def _citations(spec: dict[str, Any] | None, path: Path) -> dict[str, Any]:
    """The ``[citations]`` table, shape-checked once.

    Three readers ask about this table, and each of them would otherwise have
    to decide again what an unknown key means. One place, one answer.
    """
    if spec is None:
        return {}
    if not isinstance(spec, dict):
        raise ConfigError(
            f"{path}: [citations] is a table, not {type(spec).__name__}."
        )
    unknown = set(spec) - CITATION_KEYS
    if unknown:
        raise ConfigError(
            f"{path}: [citations] declares {', '.join(sorted(unknown))}, which "
            f"means nothing here (known: {', '.join(sorted(CITATION_KEYS))})."
        )
    return spec


def _provenance(spec: dict[str, Any] | None, path: Path) -> bool:
    """``[citations] provenance`` -- does every citation need a stamp here?

    A flag rather than a list of kinds. Asked which citation kinds would be
    exempt, the answer settled on 2026-09-10 was: which ones wouldn't. Section
    6 spells out why a commit hash is not the exception it looks like -- a hash
    is content identity, history gets rewritten, and without a stamp *true when
    written* and *wrong when written* are the same text.
    """
    declared = _citations(spec, path).get("provenance", False)
    if not isinstance(declared, bool):
        raise ConfigError(
            f"{path}: [citations] provenance is on or off and {declared!r} is "
            "neither. There is no list of exempt citation kinds to name here: "
            "section 6 of docs/citations.md admits none."
        )
    return declared


def _stale_after(spec: dict[str, Any] | None, path: Path) -> int:
    """``[citations] stale_after`` -- the clock, in days.

    **Refused when the catch is off, rather than accepted and inert.** The
    clock measures how long since a citation was confirmed, and it can only see
    citations that carry a date. A project that has not required stamps has a
    population where some citations are dated and the rest are invisible, so
    the review list would be silently partial -- a check reporting a short list
    while most of the tree went unexamined is the inert-signal failure this
    package exists to refuse. Half a policy is refused, not run.
    """
    table = _citations(spec, path)
    declared = table.get("stale_after", DEFAULT_STALE_AFTER)
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        raise ConfigError(
            f"{path}: [citations] stale_after is a number of days and "
            f"{declared!r} is not one. Zero would call a citation stale the "
            "moment it was written, which is the opposite of a reminder."
        )
    if "stale_after" in table and not _provenance(spec, path):
        raise ConfigError(
            f"{path}: [citations] declares stale_after but not "
            "provenance = true. The clock only sees citations that carry a "
            "stamp, so with the stamp requirement off it would report on "
            "whichever citations happen to be dated and say nothing about the "
            "rest -- a short list that reads like a clean tree."
        )
    return declared


def _accompany_max(spec: dict[str, Any] | None, path: Path) -> int:
    """``[citations] accompany_max`` -- refused when it cannot mean anything.

    A threshold of zero or less would say that no target ever accompanies its
    key, which is the opposite of what section 5.6 settles: accompanying is the
    default, and standing alone is the exception a long target earns. Written as
    a refusal rather than a repair because a project meaning to raise the
    ceiling and typing a negative would silently get the reverse rule.
    """
    declared = _citations(spec, path).get("accompany_max", DEFAULT_ACCOMPANY_MAX)
    if not isinstance(declared, int) or isinstance(declared, bool) or declared < 1:
        raise ConfigError(
            f"{path}: [citations] accompany_max is a length in characters and "
            f"{declared!r} is not one. Measure your own targets and declare "
            "what still reads comfortably beside a token."
        )
    return declared


def _claim_file_suffixes(claims: dict[str, Any], path: Path) -> tuple[str, ...]:
    """``[claims] file_suffixes`` -- refused when it cannot mean anything.

    A suffix without its leading dot never matches: the check compares against
    what ``PurePosixPath.suffix`` returns, which always carries one. Written as
    a refusal rather than a quiet repair because the whole reason this knob
    exists is a check that was blind and looked green, and accepting a spelling
    that matches nothing would reproduce that inside the fix for it.
    """
    declared = claims.get("file_suffixes", ())
    if isinstance(declared, str) or not isinstance(declared, (list, tuple)):
        raise ConfigError(
            f"{path}: [claims] file_suffixes is a list of extensions, not "
            f"{type(declared).__name__}."
        )
    suffixes = tuple(str(item) for item in declared)
    wrong = [item for item in suffixes if not item.startswith(".") or item == "."]
    if wrong:
        raise ConfigError(
            f"{path}: [claims] file_suffixes {wrong} would match nothing -- an "
            'extension is compared with its dot, as ".conf" or ".kanibako".'
        )
    return suffixes


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
    and settles nothing. Equally true of the value form: ``pattern`` without
    ``extract`` is a documented value with no oracle, and a run that skipped it
    would report the same green as a run that settled it.

    **The table settles a value, and stays named ``[[count]]``.** A number is
    the special case, so a second table for the general one would be one job
    done twice -- which is the thing this package tells every project it scans
    not to do -- and renaming this one would break the configs of the adopter
    whose inventory asked for the generalization, mid-migration, for cosmetics.

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
