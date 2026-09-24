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
import re
import tomllib
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path, PurePosixPath
from typing import Any

from .adapters.bibliography import Bibliography, duplicate_keys
from .adapters.constants import PythonConstants
from .adapters.mapping import MappingRegistry
from .adapters.patterns import CodePatterns
from .adapters.substitutions import Substitutions
from .adapters.values import ValueRegistry
from .baseline import BASELINE_NAME
from .bypass import MODE_FILTERS, git_ignored
from .citations import DEFAULT_ACCOMPANY_MAX
from .claims import (
    CLAIMS_REGISTRY,
    EVERY,
    EXTERNAL_TIMEOUT,
    OCCURRENCES,
    ORACLE_TIMEOUT,
    Counted,
    Promise,
    _excluded,
)
from .context import STRIPPERS, escapes
from .contract import (
    BaseRegistry,
    Registry,
    Selected,
    closure_guard,
    field_path,
    member,
    missing_members,
    spell_path,
    strings,
    usable_boundary,
)
from .gates import Gate
from .interpose import Funnel
from .parity import AUTHORITIES, FORMATS, RELATIONS, Oracle, Translation
from .probe import ACCEPTED_SPELLINGS, OUTCOME_MODES, Outcome, Probe
from .provenance import DEFAULT_STALE_AFTER, PROVENANCE_REGISTRY
from .resources import (
    RESOURCE_TABLE,
    Resource,
    ResourceError,
)
from .resources import declared as declared_resources
from .shape import (
    SET_OPERATORS,
    Condition,
    Predicate,
    Rule,
    Shape,
    ShapeError,
    asked,
)
from .targets import TARGET_FORM as FUNNEL_FORM
from .targets import TargetError

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
    #: Patterns that deliberately leave the tree -- an assembled instruction
    #: file, a compiled artifact. Separate from ``include`` so that reaching
    #: off-tree is legible where it is declared rather than inferable from a
    #: glob. See :func:`~kinemata.context.escapes`.
    external: tuple[str, ...] = ()


@dataclass
class Settings:
    root: Path
    #: `Registry`, not `BaseRegistry`: the ``import`` kind admits a class the
    #: project wrote, and the protocol is what such a class is held to.
    registries: list[Registry] = field(default_factory=list)
    exclude: tuple[str, ...] = ()
    #: What ``[project] exclude`` said, without what git already ignores. Kept
    #: apart because only this half is auditable: a project wrote these lines
    #: and can be told they removed nothing, while reporting the same about a
    #: `.gitignore` entry would be noise about a file nobody was checking.
    declared_exclude: tuple[str, ...] = ()
    #: Did the config declare ``[claims]`` at all? Every other mechanism refuses
    #: when nothing declares it and this one defaulted, which is how an adopter
    #: recorded a claims baseline under a registry-only config's excludes, into
    #: a file nothing would ever read.
    claims_declared: bool = False

    @property
    def checks_claims(self) -> bool:
        """Does anything give ``kinemata claims`` something to check?

        **Several declarations feed one command**, which is why this is a
        property here rather than a condition spelled in the CLI: the
        documentation scope, the gate inventory, the count oracles, the
        deferrals and the citation policy.

        Two drafts got this wrong in opposite directions, both caught by this
        repository's own tests. Refusing on ``[claims]`` alone silently disarmed
        the gate inventory for any project declaring gates and no documentation.
        Then withholding the *default scope* from a config without ``[claims]``
        broke ``[[count]]`` and ``[[promise]]``, which match their patterns
        inside documents and so need a scope to read. The scope stays default;
        what is refused is running at all when nobody asked for anything.
        """
        return bool(
            self.claims_declared
            or self.gates
            or self.counts
            or self.promised
            or self.provenance
        )

    suffixes: tuple[str, ...] = (".py",)
    max_sites: int | None = None
    claim_suffixes: tuple[str, ...] = DEFAULT_CLAIM_SUFFIXES
    #: Which files the citation policy reads. Defaults to the claims scope --
    #: see :func:`_citation_suffixes` for why a project may want it narrower.
    citation_suffixes: tuple[str, ...] = DEFAULT_CLAIM_SUFFIXES
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
    #: How long any declared oracle subprocess may run before it is killed and
    #: reported unreachable. See :data:`kinemata.claims.ORACLE_TIMEOUT`.
    oracle_timeout: float = ORACLE_TIMEOUT
    #: Paths a design says it will produce. Held open while absent, and failing
    #: once they exist, once nothing cites them, or once their date has passed --
    #: three ways of noticing that the list has outlived the work it describes.
    promised: tuple[Promise, ...] = ()
    #: Values the documentation states, and the commands that settle them. A
    #: number is one kind of value and gets no special table; see
    #: :class:`kinemata.claims.Counted` for why the comparison is exact.
    #: Empty unless declared: no project spawns a process it did not ask for.
    counts: tuple[Counted, ...] = ()
    #: Registry-level oracles: what the project's code actually produces, set
    #: against what a registry declares. See :mod:`kinemata.parity`. Empty
    #: unless declared, for the reason above.
    parities: tuple[Oracle, ...] = ()
    #: Write funnels to watch while the project's own suite runs. See
    #: :mod:`kinemata.interpose`. Empty unless declared, and inert until the
    #: project loads the plugin: nothing here patches anything on its own.
    funnels: tuple[Funnel, ...] = ()
    #: Rules a declaration must satisfy about itself. See :mod:`kinemata.shape`.
    #: Empty unless declared -- the one mechanism here whose subject is the
    #: declaration rather than the code, so a project with none is not missing
    #: a check on its source.
    shapes: tuple[Shape, ...] = ()
    #: Probe corpora: what the project's own code must accept and refuse. See
    #: :mod:`kinemata.probe`. Empty unless declared, and a declared one runs the
    #: project's code -- which is the same contract every ``module:attribute``
    #: in this file already carries.
    probes: tuple[Probe, ...] = ()
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
    #: Documents whose citations are dated in a list instead of in the prose.
    #: Empty unless declared: a project that has not said which of its documents
    #: are user-facing has not asked for the distinction.
    resources: tuple[Resource, ...] = ()
    #: Where that list is declared. Carried because ``confirm`` writes it, and a
    #: writer that recomputed the path from the config would be a second answer
    #: to where the file is.
    resources_path: Path | None = None


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
    paths = [
        root / m
        for m in _strings(modules, f"registry {spec.get('name', '?')!r}: modules")
    ]
    missing = [str(p) for p in paths if not p.is_file()]
    if missing:
        raise ConfigError(
            f"registry {spec.get('name', '?')!r}: module(s) not found: {missing}"
        )
    where = f"registry {spec.get('name', '?')!r}"
    registry = PythonConstants(
        paths,
        root=root,
        min_length=spec.get("min_length", 4),
        include_private=_flag(spec, "include_private", where),
        closed=_flag(spec, "closed", where),
    )
    registry.name = spec.get("name", "constants")
    return registry


#: How many sibling keys a "not in the document" refusal lists back. Enough to
#: recognize the level you are standing on -- and to see a near-miss spelling
#: right beside the one you typed -- without pasting somebody's whole manifest
#: into an error.
SECTION_SIBLINGS = 8


def _spell(segments: Sequence[str]) -> str:
    """A path as the config would have written it, for an error to point at."""
    return " -> ".join(repr(segment) for segment in segments)


def _dotted_hint(level: Any, walked: Sequence[str], segment: str, key: str) -> str:
    """The list form, when splitting a failed segment on dots would have worked.

    **The rule it serves is unchanged: a string is one key however many dots it
    holds, and is never split.** ``extra`` keys legitimately contain them, so
    splitting on a guess would compare the wrong cell and *pass*, which is the
    normalization this package refuses everywhere.

    What was missing is that the existing refusal answers a question the reader
    is not asking. Listing what the level holds is right for a typo; somebody
    who wrote ``policy.seed_whitelists`` knows what they meant and is asking why
    their path did not descend. That question has an answer whenever the split
    would resolve, and printing it costs one walk that only ever runs on a path
    already headed for a refusal.
    """
    if "." not in segment:
        return ""
    parts = segment.split(".")
    cursor = level
    for part in parts:
        if not isinstance(cursor, dict) or part not in cursor:
            return ""
        cursor = cursor[part]
    spelled = ", ".join(f'"{part}"' for part in (*walked, *parts))
    return (
        f". A {key} that is a string is one key however many dots it holds and "
        f"is never split, because a key may legitimately contain one -- write "
        f"{key} = [{spelled}] to descend through them."
    )


def _walk(
    document: Any, section: Any, name: str, source: str, key: str = "section"
) -> Any:
    """Whatever a declared path of keys reaches, mapping or not.

    ``section`` is one key, as it has always been, or a list of them. **A list
    rather than a dotted string**, and that is the whole decision here: a dotted
    string reads better and cannot express a key containing a dot, at which
    point the loader is guessing which of two splits the project meant, over a
    file it did not write. This package refuses rather than guessing everywhere
    else. Dotted sugar can be layered on a list later; a list cannot be added
    *underneath* a dotted string without changing what an existing config means.

    A bare string is one segment, so no existing declaration changes meaning.

    **Every refusal names the segment that failed and what the level actually
    held.** "section not found" against a five-deep path is a refusal somebody
    has to go and locate by hand, which is the failure mode this package spends
    its error messages avoiding. ``key`` is the spelling the *author* used, so a
    ``toml-value`` registry is not told about a ``section`` it never wrote.

    **What is at the end is the caller's to judge**, which is the whole reason
    this is not :func:`_descend`: a mapping registry addresses a table and a
    value registry addresses a scalar, and both want these refusals on the way
    down. Splitting them was cheaper than a second walker that would have drifted
    from this one's messages.
    """
    if section is None or section == "":
        return document
    if isinstance(section, str):
        segments = [section]
    elif isinstance(section, (list, tuple)):
        segments = [str(segment) for segment in section]
    else:
        raise ConfigError(
            f"registry {name!r}: {key!r} is {type(section).__name__}; it "
            "takes one key, or a list of keys to descend through."
        )
    if not segments:
        raise ConfigError(
            f"registry {name!r}: {key!r} is an empty list, which addresses "
            "nothing. Name the keys to descend through, or drop the key."
        )

    walked: list[str] = []
    for segment in segments:
        where = f" under {_spell(walked)}" if walked else ""
        if not isinstance(document, dict):
            raise ConfigError(
                f"registry {name!r}: {_spell(walked)} in {source} is "
                f"{type(document).__name__}, not a mapping, so {segment!r} "
                "cannot be looked up inside it."
            )
        if segment not in document:
            held = list(document)
            shown = ", ".join(repr(sibling) for sibling in held[:SECTION_SIBLINGS])
            if len(held) > SECTION_SIBLINGS:
                shown += f", and {len(held) - SECTION_SIBLINGS} more"
            raise ConfigError(
                f"registry {name!r}: {key} segment {segment!r} is not in "
                f"{source}{where}. That level holds: {shown or 'nothing'}"
                f"{_dotted_hint(document, walked, segment, key)}"
            )
        document = document[segment]
        walked.append(segment)

    return document


def _descend(document: Any, section: Any, name: str, source: str) -> Any:
    """The mapping a registry addresses: :func:`_walk`, and a table at the end."""
    reached = _walk(document, section, name, source)
    # With nothing declared there is no path to name, and the top level has
    # always been handed on as it arrived. Tightening that here would be a
    # behavior change belonging to its own cause.
    if section is None or section == "":
        return reached
    if not isinstance(reached, dict):
        raise ConfigError(
            f"registry {name!r}: section {_spell(field_path(section))} in "
            f"{source} is {type(reached).__name__}, not a mapping. A mapping "
            "registry addresses a table of entries."
        )
    return reached


def _levels(
    document: Any, depth: int, prefix: tuple[str, ...], name: str, source: str
) -> Iterator[tuple[tuple[str, ...], Any]]:
    """Every leaf at exactly ``depth`` keys down, with the keys that reached it."""
    if depth == 0:
        yield prefix, document
        return
    if not isinstance(document, dict):
        where = _spell(prefix) if prefix else "the addressed section"
        raise ConfigError(
            f"registry {name!r}: {where} in {source} is "
            f"{type(document).__name__}, not a mapping, so it has no level to "
            "flatten. A matrix with one scalar row is a malformed matrix; "
            "skipping it would make the registry quietly smaller."
        )
    for key, value in document.items():
        yield from _levels(value, depth - 1, (*prefix, str(key)), name, source)


def _flatten(
    document: Any, depth: int, separator: str, name: str, source: str
) -> dict[str, Any]:
    """A nested table as one mapping of composite identifier to leaf.

    The adopter's `cells:` is a matrix -- an arriving kind, an occupant
    relation, an outcome token -- and a *cell* had no identifier, so no rule
    could speak about one. Composing the key path gives it one.

    **The leaf is handed on untouched**, so
    :meth:`~kinemata.adapters.mapping.MappingRegistry.entries` applies the rule
    it already has: a mapping leaf becomes ``extra``, a scalar becomes
    ``{"value": leaf}``. No new convention -- and the matrix case is the scalar
    one, so the outcome token lands where a ``[[shape]]`` rule reads it.
    """
    flat: dict[str, Any] = {}
    origins: dict[str, tuple[str, ...]] = {}
    for keys, leaf in _levels(document, depth, (), name, source):
        identifier = separator.join(keys)
        if identifier in origins:
            # Silent shadowing: one entry overwrites another and the registry
            # reports a smaller set that reads as correct, which is this
            # package's own subject. Both pairs are named because the fix is to
            # pick a separator absent from the keys, and you cannot pick one
            # without seeing which keys collided.
            raise ConfigError(
                f"registry {name!r}: flattening {source} with separator "
                f"{separator!r} gives {identifier!r} for both "
                f"{_spell(origins[identifier])} and {_spell(keys)}. One would "
                "silently shadow the other. Choose a separator that does not "
                "occur in the keys."
            )
        origins[identifier] = keys
        flat[identifier] = leaf
    return flat


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

    name = spec.get("name", "?")
    document = yaml.safe_load(path.read_text()) or {}
    document = _descend(document, spec.get("section"), name, source)

    depth = spec.get("flatten", 1)
    if isinstance(depth, bool) or not isinstance(depth, int) or depth < 1:
        raise ConfigError(
            f"registry {name!r}: 'flatten' is {depth!r}; it takes a positive "
            "whole number of key levels to compose into each identifier. 1 is "
            "the default and means one level, exactly as before."
        )
    separator = spec.get("separator")
    if depth > 1 and not separator:
        # No default, deliberately. Defaulting would mint identifiers whose
        # spelling the project never chose -- and the identifier is the thing
        # the baseline fingerprints, the oracle prints and the scan looks for.
        # A project that has to type it has read what it becomes.
        raise ConfigError(
            f"registry {name!r}: 'flatten' is {depth} but no 'separator' is "
            "declared, and there is no default. The separator spells every "
            "identifier this registry produces, so the project chooses it."
        )
    if separator is not None and depth == 1:
        raise ConfigError(
            f"registry {name!r}: 'separator' is declared but 'flatten' is 1, "
            "so nothing is composed and the separator does nothing. Declare "
            "'flatten' as well, or drop it."
        )
    if depth > 1:
        document = _flatten(document, depth, str(separator), name, source)

    return MappingRegistry(
        document,
        name=spec.get("name", "keys"),
        clause_field=spec.get("clause_field"),
        syntax=spec.get("syntax"),
        closed=_flag(spec, "closed", f"registry {name!r}"),
        budget=spec.get("budget"),
        line_budget=spec.get("line_budget"),
    )


#: What a ``toml-value`` accepts as an identifier, and it is deliberately the
#: same set :func:`kinemata.parity._rendered` accepts on the declared side of a
#: comparison: one place decides what a scalar looks like when a check has to
#: put it beside text a command printed. TOML's dates and times are absent for
#: that reason rather than a new one -- ``str`` of a ``datetime`` is a spelling
#: no oracle agrees with by accident.
VALUE_SCALARS = (str, int, float, bool)


def _scalars(reached: Any, name: str, source: str, where: str) -> list[str]:
    """One scalar, or a flat list of them, as the identifiers they will be.

    **A mapping is refused rather than read**, and the refusal lists what that
    level holds so an author who stopped one key short can finish the path --
    the remedy, not just the complaint. A nested list is refused for the reason
    :func:`kinemata.parity._declared_values` gives about containers: it has an
    internal order and a spelling no two sides agree on by accident, so
    rendering it would be a normalization that *passes*.
    """
    items = list(reached) if isinstance(reached, (list, tuple)) else [reached]
    if isinstance(reached, dict):
        held = list(reached)
        shown = ", ".join(repr(key) for key in held[:SECTION_SIBLINGS])
        if len(held) > SECTION_SIBLINGS:
            shown += f", and {len(held) - SECTION_SIBLINGS} more"
        raise ConfigError(
            f"registry {name!r}: {where} in {source} is a table, and this kind "
            f"reads the values themselves rather than the keys that hold them. "
            f"Name a key to descend into: that level holds {shown or 'nothing'}"
        )
    rendered: list[str] = []
    for item in items:
        if not isinstance(item, VALUE_SCALARS):
            raise ConfigError(
                f"registry {name!r}: {where} in {source} holds a "
                f"{type(item).__name__}, which has no spelling an oracle would "
                "print by accident. This kind reads a scalar, or a flat list "
                "of them."
            )
        rendered.append(str(item))
    return rendered


def _build_toml_value(spec: dict[str, Any], root: Path, path: Path) -> BaseRegistry:
    """Scalars a TOML file declares, as the identifiers themselves.

    ``tomllib`` is stdlib, so this adds no dependency and no extra -- which is
    what makes it the right home for the case that forced it. The version a
    Python project declares lives in :shown:`pyproject.toml` by definition --
    any project's, which is why that is an illustration rather than a path here
    -- and
    putting it on the declared side of a ``disjoint`` parity is how a tree
    claims it is not sitting on a version the index already has.
    """
    name = str(spec.get("name", "?"))
    source = spec.get("source")
    if not source:
        raise ConfigError(f"registry {name!r}: needs 'source'")
    file = root / str(source)
    if not file.is_file():
        raise ConfigError(f"registry {name!r}: no such file: {file}")
    declared = spec.get("path")
    if declared is None or declared == "" or declared == []:
        raise ConfigError(
            f"registry {name!r}: needs 'path', the keys naming the value this "
            "registry declares -- a list, or one key. Without it the whole "
            "document is the value, which is never a scalar."
        )
    try:
        document = tomllib.loads(file.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(
            f"registry {name!r}: {source} is not readable as TOML ({error})"
        ) from error

    reached = _walk(document, declared, name, str(source), key="path")
    values = _scalars(reached, name, str(source), _spell(field_path(declared)))
    return ValueRegistry(
        values,
        name=spec.get("name", "values"),
        syntax=spec.get("syntax"),
        closed=_flag(spec, "closed", f"registry {name!r}"),
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
        return CodePatterns(
            declarations,
            name=spec.get("name", "patterns"),
            closed=_flag(spec, "closed", f"registry {spec.get('name', '?')!r}"),
        )
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
    at = f"registry {spec.get('name', '?')!r}"
    try:
        return Substitutions(
            words,
            name=spec.get("name", "substitutions"),
            closed=_flag(spec, "closed", at),
            case_sensitive=_flag(spec, "case_sensitive", at),
            boundary=spec.get("boundary", "prose"),
        )
    except ValueError as exc:
        raise ConfigError(f"registry {spec.get('name', '?')!r}: {exc}") from exc


#: What a bibliography's own file may declare. Refused rather than ignored, for
#: the reason an entry's keys are: ``[entries]`` written for ``[[entry]]`` would
#: load a bibliography with nothing in it, and a key that resolves to nothing is
#: worse than a key nobody wrote.
BIBLIOGRAPHY_KEYS = frozenset({"entry", "types"})

#: Appended when the table that swallowed the key is an array-of-tables, because
#: refusing the key is only half an answer: the reader wrote it under a heading
#: that looks unrelated to the one it belongs to, and TOML's rule is what put it
#: there.
ABSORBED = (
    " An array-of-tables takes every bare key written after it, so a key meant "
    "for an enclosing table has to be moved above the first one."
)


def _reject_unknown(
    spec: dict[str, Any], known: frozenset[str], where: str, *, absorbs: bool = False
) -> None:
    """Refuse a key this table cannot mean, naming what it could have been.

    **Written because a key nothing reads is indistinguishable from a check that
    is switched off.** An adopter wrote two ``[[gate]]`` tables between
    ``suffixes`` and ``historical`` inside ``[claims]``; TOML gave ``historical``
    to the second gate, the suppression stopped applying, and the only symptom
    was a claim denominator moving between two runs of the same command. No
    error, no warning, and a config that read correctly to every human who
    looked at it.

    One function rather than a refusal per table: the same three lines were
    spelled five times here, all of them in the citation family, and every table
    added since had quietly decided that an unknown key means nothing at all.
    Which is the duplication this package exists to report.
    """
    unknown = set(spec) - known
    if not unknown:
        return
    raise ConfigError(
        f"{where} declares {', '.join(sorted(unknown))}, which means nothing "
        f"here (known: {', '.join(sorted(known))})."
        + (ABSORBED if absorbs else "")
    )


def _flag(
    spec: Mapping[str, Any],
    key: str,
    where: str,
    *,
    default: bool = False,
    because: str = "",
) -> bool:
    """One on-or-off key, refused when it is not a boolean.

    **A quoted flag is the config-file form of a normalization that passes.**
    Measured on this loader: a registry declaring ``closed = "false"`` loaded as
    **closed**, because every non-empty string is true -- so a project reads the
    opposite of what its own line says, and with ``syntax`` declared it arms the
    closed-world gate while doing it. ``exact`` and ``external`` coerced the same
    way, each of them narrowing or widening a check silently.

    One reader rather than a check per flag, on the rule
    :func:`_reject_unknown` is written under. It is *not* folded into that
    function: which keys are flags is a property of the table, not of the
    vocabulary -- ``[claims] external`` is a boolean and ``[context] external``
    is a list of patterns -- so the caller that knows what it is reading says so.

    ``because`` is appended for a key whose *being* a flag is the thing a reader
    doubts, rather than its spelling.
    """
    if key not in spec:
        return default
    value = spec[key]
    if not isinstance(value, bool):
        raise ConfigError(
            f"{where}: {key} is on or off and {value!r} is neither. TOML spells "
            f"a boolean as true or false without quotes, and a quoted one is a "
            f"string -- which is read as ON however it is spelled." + because
        )
    return value


#: What each table may declare. ⚑ ``[claims] promised`` is listed as **known**
#: and then refused by :func:`_promised` with a migration message: a retired key
#: needs the answer that says where it went, and a generic refusal here would
#: reach it first and say only that it is unknown.
PROJECT_KEYS = frozenset(
    {"root", "exclude", "suffixes", "max_sites", "baseline"}
)
CLAIMS_KEYS = frozenset(
    {
        "suffixes", "file_suffixes", "historical", "resolve_in", "commits_in",
        "external", "external_timeout", "oracle_timeout", "promised",
    }
)
CONTEXT_KEYS = frozenset({"include", "external", "budget", "strip"})
GATE_KEYS = frozenset({"command", "where", "note"})
COUNT_KEYS = frozenset(
    {
        "command", "run", "args", "directory", "pattern", "extract", "label",
        "occurrence",
    }
)
PARITY_KEYS = frozenset(
    {
        "command", "run", "args", "directory", "registry", "extract", "field",
        "authority", "translate", "translate_identifier", "relation", "ordered",
        "format",
    }
)
SHAPE_KEYS = frozenset({"registry", "rule"})
INTERPOSE_KEYS = frozenset({"registry", "target", "identify", "record"})
#: What a ``[[probe]]`` may declare. ``refusal`` and ``accepted`` belong to one
#: outcome mode each and are refused under the other, so the table is checked
#: twice: once for a key that means nothing anywhere, once for one that means
#: nothing *here*.
PROBE_KEYS = frozenset(
    {"name", "target", "cases", "outcome", "refusal", "accepted", "exact"}
)

#: Every table a ``kinemata.toml`` may declare. ⚑ **The root was the last table
#: that absorbed silently, and the worst one to.** A top-level ``[[gates]]`` --
#: the plural typo -- loaded without complaint and declared no gates at all, so
#: the inventory that says *these checks must still run* was never declared
#: rather than declared wrong. `declared_checks` below catches only the
#: degenerate case where a config declares nothing whatsoever, which a config
#: with one registry and a misspelled gate array is not.
ROOT_KEYS = frozenset(
    {
        "project", "registry", "count", "parity", "shape", "interpose", "gate",
        "probe", "claims", "context", "citations", "promise", "command",
    }
)

#: What any ``[[registry]]`` may declare whatever its kind: its own name, the
#: kind itself, and the contract attributes :func:`load` sets on the instance
#: after the builder has run.
REGISTRY_KEYS = frozenset(
    {
        "name", "kind", "closed", "allow_empty", "suffixes", "machinery",
        "match_mode", "boundary", "where", "defer_to",
    }
)

#: What each kind adds to those. **Differenced per kind rather than unioned**,
#: because ``section`` on a ``python-constants`` registry means exactly as
#: little as a key no kind has ever declared, and a flat union would accept it
#: while reporting nothing.
#:
#: ``import`` is deliberately absent: everything :data:`IMPORT_KEYS` does not
#: name is handed to the project's own class as a keyword argument, so refusing
#: an unrecognized key here would refuse the parameterization that naming a
#: class exists to allow. That kind checks its own vocabulary, through the
#: constructor.
KIND_KEYS = {
    "python-constants": frozenset({"modules", "include_private", "min_length"}),
    "yaml-mapping": frozenset(
        {
            "source", "section", "clause_field", "syntax", "budget",
            "line_budget", "flatten", "separator",
        }
    ),
    "toml-value": frozenset(
        {"source", "path", "syntax", "budget", "line_budget"}
    ),
    "code-patterns": frozenset({"entry"}),
    "substitutions": frozenset({"source", "words", "case_sensitive"}),
    "bibliography": frozenset({"source", "interpreted", "standardized"}),
}

#: A rule's own keys: its name, its optional guard, and whichever claim it
#: spells plus that claim's companion. The claim spellings are read from
#: :data:`SHAPE_CLAIMS` rather than restated, so a new operator cannot be
#: accepted by one table and refused by the other.
RULE_KEYS = frozenset({"name", "when", "field", "are"})


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

    _reject_unknown(document, BIBLIOGRAPHY_KEYS, f"registry {name!r}: {source}")

    try:
        return Bibliography(
            document.get("entry", ()),
            name=spec.get("name", "sources"),
            home=str(source),
            types=document.get("types"),
            interpreted=spec.get("interpreted"),
            standardized=spec.get("standardized"),
            closed=_flag(spec, "closed", f"registry {name!r}"),
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
    "toml-value": _build_toml_value,
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


def _max_sites(project: dict[str, Any], path: Path) -> int | None:
    """``[project] max_sites``, refused when it is not a count.

    The threshold is compared with ``count > max_sites``, so anything that is
    not a whole number either crashes inside the report with a ``TypeError``
    from three modules away, or -- for ``true``, which Python compares as 1 --
    quietly becomes a threshold of one and suppresses nearly everything. A
    suppression dial is the wrong place to guess.
    """
    if "max_sites" not in project:
        return None
    declared = project["max_sites"]
    if isinstance(declared, bool) or not isinstance(declared, int):
        raise ConfigError(
            f"{path}: [project] max_sites is {declared!r}, which is not a "
            "number of sites. Give a whole number, or a negative one to turn "
            "suppression off."
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

    # Before anything is read out of it, because every question below is asked
    # of a table this pass may find nothing declares. A misspelled array of
    # tables does not fail a check -- it removes one, and `declared_checks`
    # notices only when the config has nothing left at all.
    _reject_unknown(raw, ROOT_KEYS, f"{path}: document root")

    project = raw.get("project", {})
    _reject_unknown(project, PROJECT_KEYS, f"{path}: [project]")
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
        "[[parity]]": bool(raw.get("parity")),
        "[[shape]]": bool(raw.get("shape")),
        "[[interpose]]": bool(raw.get("interpose")),
        "[[probe]]": bool(raw.get("probe")),
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
        # After the kind is known, so the answer is the vocabulary of the kind
        # the project actually named, and before the builder runs, so a
        # misspelled `sourc` is reported as a misspelling rather than as a
        # bibliography that needs a `source` the reader can see they wrote.
        if kind in KIND_KEYS:
            _reject_unknown(
                spec, REGISTRY_KEYS | KIND_KEYS[kind],
                f"{path}: [[registry]] {spec.get('name', '?')!r} of kind {kind!r}",
                absorbs=True,
            )
        registry = builder(spec, root, path)
        # Applied here rather than in each builder: every kind of registry can
        # be pointed at a different file set, and three copies of one line is
        # the thing this package exists to report.
        if "suffixes" in spec:
            registry.suffixes = _strings(
                spec["suffixes"], f"{path}: registry {registry.name!r} suffixes"
            )
        if "machinery" in spec:
            registry.machinery = _strings(
                spec["machinery"], f"{path}: registry {registry.name!r} machinery"
            )
        if "defer_to" in spec:
            registry.defer_to = _deferral(spec["defer_to"], f"{path}: registry {registry.name!r}")
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
        # Last of the cross-kind attributes, and the only one that changes what
        # the registry *contains* rather than how it is read -- so it runs after
        # everything a selector might be asked about has been set, and before
        # the emptiness check below, which is what catches a selector that kept
        # nothing.
        if "where" in spec:
            registry = _selected(registry, spec, path)
        # Every declaration above can be individually valid and still produce a
        # registry with nothing in it -- the modules exist and parse, they just
        # hold nothing this adapter recognizes. That check passes, reports
        # nothing, and reads exactly like compliance.
        #
        # Found by dogfooding: this project declared `python-constants` over
        # three of its own modules for six commits. It has no module-level
        # string constants at all, so the projection was empty and `check`
        # exited 0 the whole time. The wrong adapter, not a clean tree.
        empty_is_declared = _flag(
            spec, "allow_empty", f"registry {registry.name!r}"
        )
        if not empty_is_declared and not any(True for _ in registry.entries()):
            unfitted.append(
                f"registry {registry.name!r}: kind {kind!r} produced no "
                "entries, so it would scan for nothing and pass. Point it at a "
                "source it can read, or set allow_empty = true if it is "
                "deliberately empty while being bootstrapped."
            )
            continue
        # A registry declared `closed` promises that an undeclared identifier is
        # an error -- a promise it can only keep if it can recognize an
        # identifier at all. Every kind accepts `closed`, and a kind without
        # `candidates()` could be declared closed and would answer nothing,
        # which reads exactly like a clean tree.
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
                f"registry {registry.name!r}: kind {kind!r} cannot be "
                f"closed. {exc}"
            ) from exc

        registries.append(registry)

    _check_deferrals(registries, path)

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
    _reject_unknown(claims, CLAIMS_KEYS, f"{path}: [claims]")
    # What git ignores is not this project's material, and every check here asks
    # that same question. Answered once, in the one place settings come from.
    declared_exclude = _strings(project.get("exclude", ()), f"{path}: [project] exclude")
    exclude = declared_exclude + git_ignored(root)
    claim_suffixes = _strings(
        claims.get("suffixes", DEFAULT_CLAIM_SUFFIXES), f"{path}: [claims] suffixes"
    )
    citation_suffixes = _citation_suffixes(
        raw.get("citations"), claim_suffixes, path
    )
    listed, resources_path = _resources(
        raw.get("citations"), root, claim_suffixes, citation_suffixes, exclude, path
    )
    return Settings(
        root=root,
        registries=registries,
        exclude=exclude,
        declared_exclude=declared_exclude,
        claims_declared=raw.get("claims") is not None,
        suffixes=_strings(project.get("suffixes", (".py",)), f"{path}: [project] suffixes"),
        max_sites=_max_sites(project, path),
        claim_suffixes=claim_suffixes,
        citation_suffixes=citation_suffixes,
        claim_file_suffixes=_claim_file_suffixes(claims, path),
        historical=_strings(claims.get("historical", ()), f"{path}: [claims] historical"),
        resolve_in=_strings(claims.get("resolve_in", ()), f"{path}: [claims] resolve_in"),
        commits_in=_strings(claims.get("commits_in", ()), f"{path}: [claims] commits_in"),
        external=_flag(claims, "external", f"{path}: [claims]"),
        external_timeout=float(claims.get("external_timeout", EXTERNAL_TIMEOUT)),
        oracle_timeout=float(claims.get("oracle_timeout", ORACLE_TIMEOUT)),
        promised=_promised(raw.get("promise"), claims, path),
        counts=_build_counts(raw.get("count", []), path,
                             _commands(raw.get("command"), path)),
        parities=_build_parities(raw.get("parity", []), path,
                                 _commands(raw.get("command"), path),
                                 [built.name for built in registries]),
        funnels=_build_funnels(raw.get("interpose", []), path,
                               [built.name for built in registries]),
        shapes=_build_shapes(raw.get("shape", []), path,
                             [built.name for built in registries]),
        probes=_build_probes(raw.get("probe", []), path),
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
        resources=listed,
        resources_path=resources_path,
        context=_build_context(raw.get("context"), path),
    )


#: What a ``[citations]`` table may say.
CITATION_KEYS = frozenset(
    {"accompany_max", "provenance", "resources", "stale_after", "suffixes"}
)

#: What a resource file may declare at the top level.
RESOURCE_FILE_KEYS = frozenset({RESOURCE_TABLE})


def _resources(
    spec: dict[str, Any] | None,
    root: Path,
    claim_suffixes: tuple[str, ...],
    citation_suffixes: tuple[str, ...],
    exclude: tuple[str, ...],
    path: Path,
) -> tuple[tuple[Resource, ...], Path | None]:
    """``[citations] resources`` -- the list that dates user-facing documents.

    A file of its own, never inline, for the reason a bibliography is: it is the
    file a reader of a citation goes looking for and the file a confirmation run
    writes, and a config touched by every run is a config nobody reviews.

    **Refused when the catch is off**, the call ``suffixes`` and ``stale_after``
    both make. Nothing dates anything with the policy off, so the list would sit
    in the config reading as a decision and covering nothing.

    **Refused when a declared document is somewhere the checks cannot see it**,
    and this is the one that earns its keep. A resource the citation policy does
    not read covers no citation; a resource ``claims`` does not read cannot be
    confirmed at all, because the confirmation oracle *is* ``claims`` -- and it
    would be dated on every run, having had nothing to falsify it. That is a
    green entry certifying a document nobody checked, which is the precise
    shape of inert signal this package exists to refuse.
    """
    table = _citations(spec, path)
    if "resources" not in table:
        return (), None
    if not _provenance(spec, path):
        raise ConfigError(
            f"{path}: [citations] declares resources but not provenance = true. "
            "The list dates citations that would otherwise need a stamp, and "
            "with the stamp requirement off there is nothing for it to answer."
        )
    declared = table["resources"]
    if not isinstance(declared, str) or not declared:
        raise ConfigError(
            f"{path}: [citations] resources is the file the list is declared in "
            f"and {declared!r} is not one."
        )
    source = root / declared
    if not source.is_file():
        raise ConfigError(f"{path}: [citations] resources: no such file: {source}")
    try:
        document = tomllib.loads(source.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(
            f"{path}: [citations] resources: cannot read {source}: {exc}"
        ) from exc
    _reject_unknown(document, RESOURCE_FILE_KEYS, f"{path}: {declared}")
    try:
        listed = declared_resources(
            document.get(RESOURCE_TABLE, ()), root=root, where=str(declared)
        )
    except ResourceError as exc:
        raise ConfigError(str(exc)) from exc

    for resource in listed:
        suffix = PurePosixPath(resource.path).suffix
        if suffix not in citation_suffixes:
            raise ConfigError(
                f"{path}: {declared} declares {resource.path}, which the "
                f"citation policy does not read ([citations] suffixes = "
                f"{list(citation_suffixes)}). Its citations are not findings, "
                "so dating them buys nothing and the entry reads as coverage."
            )
        if suffix not in claim_suffixes:
            raise ConfigError(
                f"{path}: {declared} declares {resource.path}, which the claims "
                f"check does not read ([claims] suffixes = {list(claim_suffixes)}). "
                "Confirmation asks whether everything a document cites still "
                "holds, and a document nothing extracts claims from would be "
                "dated by every run for having nothing to falsify it."
            )
        if _excluded(resource.path, exclude):
            raise ConfigError(
                f"{path}: {declared} declares {resource.path}, which "
                "[project] exclude (or git) keeps out of every scan here. "
                "Nothing reads it, so nothing can date it honestly."
            )
    return listed, source


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
    _reject_unknown(spec, CITATION_KEYS, f"{path}: [citations]")
    return spec


def _provenance(spec: dict[str, Any] | None, path: Path) -> bool:
    """``[citations] provenance`` -- does every citation need a stamp here?

    A flag rather than a list of kinds. Asked which citation kinds would be
    exempt, the answer settled on 2026-09-10 was: which ones wouldn't. Section
    6 spells out why a commit hash is not the exception it looks like -- a hash
    is content identity, history gets rewritten, and without a stamp *true when
    written* and *wrong when written* are the same text.
    """
    return _flag(
        _citations(spec, path),
        "provenance",
        f"{path}: [citations]",
        because=(
            " There is no list of exempt citation kinds to name here: section 6 "
            "of docs/citations.md admits none."
        ),
    )


def _citation_suffixes(
    spec: dict[str, Any] | None, claim_suffixes: tuple[str, ...], path: Path
) -> tuple[str, ...]:
    """``[citations] suffixes`` -- which files the stamp requirement reads.

    **Defaults to the claims scope, and exists because the two are not the same
    question.** A documentation claim is checked wherever a document makes one,
    including the first page a reader of the project sees. A citation stamp is
    apparatus: it says when a developer's checker last confirmed a reference,
    and in user-facing prose it is a token the reader has to learn to ignore.
    Without this knob the only way to keep stamps out of a README was to drop
    the README from claims entirely, which throws away the check that catches a
    dead path in the most-read file in the repository.

    Narrowing it is therefore not a suppression: the citations in the files
    left out are not exempted findings, they are **not findings**, because the
    project has said the policy does not reach there. That is the difference
    between this and a baseline record, and it is why it is a scope rather than
    an ignore list.

    Refused when the catch is off, the same call ``stale_after`` makes: a scope
    for a policy nobody declared is a line in a config file that reads as a
    decision and changes nothing.
    """
    table = _citations(spec, path)
    if "suffixes" not in table:
        return claim_suffixes
    if not _provenance(spec, path):
        raise ConfigError(
            f"{path}: [citations] declares suffixes but not provenance = true. "
            "Scoping a policy that is off narrows nothing, and reads in this "
            "file as though a decision had been made."
        )
    declared = table["suffixes"]
    if not isinstance(declared, list) or not declared:
        raise ConfigError(
            f"{path}: [citations] suffixes is a non-empty list of file "
            f"extensions and {declared!r} is not one. An empty list would turn "
            "the policy off while leaving it declared."
        )
    for suffix in declared:
        if not isinstance(suffix, str) or not suffix.startswith("."):
            raise ConfigError(
                f"{path}: [citations] suffixes holds {suffix!r}, which is not "
                "a file extension. Extensions carry their dot, so that they "
                "match what the walk compares them against."
            )
    return tuple(declared)


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
    suffixes = _strings(claims.get("file_suffixes", ()), f"{path}: [claims] file_suffixes")
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
    _reject_unknown(
        entry,
        PROMISE_KEYS,
        f"{path}: promise {entry.get('path') or entry.get('what') or entry!r}",
        absorbs=True,
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
    _reject_unknown(spec, CONTEXT_KEYS, f"{path}: [context]")
    include = spec.get("include")
    budget = spec.get("budget")
    missing = [key for key, value in (("include", include), ("budget", budget))
               if not value]
    if missing:
        raise ConfigError(
            f"{path}: [context] is missing {', '.join(missing)}. A budget with "
            "nothing to weigh, or a set with no ceiling, checks nothing."
        )
    strip = _strings(spec.get("strip", ()), f"{path}: [context] strip")
    unknown = [name for name in strip if name not in STRIPPERS]
    if unknown:
        raise ConfigError(
            f"{path}: [context] strip has unknown transform(s) {unknown} "
            f"(known: {', '.join(sorted(STRIPPERS))})"
        )
    # `include` is contained; `external` is the escape, and each refuses the
    # other's patterns. Until 2026-09-13 an absolute path, or a parent-directory
    # escape, in `include` worked -- by accident of two library behaviors rather
    # than by contract -- so a config could weigh anything on the filesystem
    # with nothing in the file saying so. The capability is kept, because an
    # adopter had a measured use for it -- an assembled instruction file living
    # outside any repository, which is the one thing a ceiling most wants to
    # see; what changed is that it has to be asked for by name.
    #
    # Symmetrically refused, because a one-way rule would leave `external`
    # accepting contained patterns and quietly labeling in-tree bytes "outside".
    include = _strings(include, f"{path}: [context] include")
    external = _strings(spec.get("external", ()), f"{path}: [context] external")
    leaving = [pattern for pattern in include if escapes(pattern)]
    if leaving:
        raise ConfigError(
            f"{path}: [context] include must stay inside the project: "
            f"{leaving} is absolute or escapes the tree. Declare it in "
            "[context] external, which exists for an assembled file kept "
            "outside the tree."
        )
    staying = [pattern for pattern in external if not escapes(pattern)]
    if staying:
        raise ConfigError(
            f"{path}: [context] external is for patterns that leave the tree, "
            f"and {staying} does not. Declare it in [context] include."
        )
    return ContextBudget(
        include=include,
        budget=int(budget),
        strip=strip,
        external=external,
    )


def _build_gates(declarations: list[dict[str, Any]], path: Path) -> tuple[Gate, ...]:
    """``[[gate]]`` tables. A gate with no command declares nothing.

    Refused rather than skipped, for the same reason a half-declared count is:
    it looks configured and settles nothing, which is the inert signal wearing
    the shape of a check.
    """
    built: list[Gate] = []
    for index, spec in enumerate(declarations):
        _reject_unknown(spec, GATE_KEYS, f"{path}: [[gate]] {index}", absorbs=True)
        command = spec.get("command")
        if not command:
            raise ConfigError(f"{path}: [[gate]] {index} is missing 'command'")
        built.append(
            Gate(
                command=str(command),
                where=_strings(spec.get("where", ()), f"{path}: [[gate]] {index} where"),
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


def _strings(value: Any, what: str) -> tuple[str, ...]:
    """:func:`kinemata.contract.strings`, refused as a config error."""
    try:
        return strings(value, what)
    except ValueError as exc:
        raise ConfigError(str(exc)) from None


def _deferral(raw: Any, where: str) -> tuple[str, ...]:
    """A ``defer_to`` list: registry names, refused when it is anything else.

    Read through :func:`_strings`, and an empty list refused on top, because a
    deferral to nobody is a key that does nothing.
    """
    names = _strings(raw, f"{where} defer_to")
    if not names or not all(names):
        raise ConfigError(
            f"{where}: defer_to must be a non-empty list of registry names, "
            f"not {raw!r}."
        )
    return names


def _check_deferrals(registries: Sequence[Registry], path: Path) -> None:
    """Every ``defer_to`` names a registry that can be deferred to, from one that
    could defer.

    Asked once every registry is built, since a deferral may name one declared
    later in the file. **Each refusal is a deferral that would do nothing** --
    the inert declaration this loader refuses everywhere else: a name nothing
    answers to, a registry deferring to itself, one that recognizes no
    identifiers and so never has a candidate to hand over, and a target none of
    whose entries declares a value, which no candidate could ever match.
    """
    by_name = {registry.name: registry for registry in registries}
    for registry in registries:
        targets = member(registry, "defer_to")
        if not targets:
            continue
        where = f"{path}: registry {registry.name!r}"
        try:
            member(registry, "candidates")("")
        except NotImplementedError:
            raise ConfigError(
                f"{where} declares defer_to but recognizes no identifiers of its "
                "own, so it never has a candidate to defer. Deference applies to "
                "`kinemata undeclared`, which needs candidates()."
            ) from None
        for target in targets:
            if target == registry.name:
                raise ConfigError(f"{where} defers to itself.")
            if target not in by_name:
                raise ConfigError(
                    f"{where} defers to {target!r}, which no loaded registry is "
                    f"called (loaded: {', '.join(sorted(by_name))})."
                )
            if not any(entry.antipatterns for entry in by_name[target].entries()):
                raise ConfigError(
                    f"{where} defers to {target!r}, none of whose entries "
                    "declares a value -- so no candidate could ever match one, "
                    "and the deferral would do nothing."
                )


def _argv(raw: Any, where: str, key: str) -> tuple[str, ...]:
    """One inline argument list, refused rather than iterated when it is a string.

    TOML has no argv type, so ``command = "python -m tool"`` is the natural
    thing to write and a string is iterable: it became one argument per
    character and the run died on ``"p"``. The report named the *oracle* as
    unrunnable, so a config defect was diagnosed as the project's command being
    missing -- and a blocked parity oracle makes ``baseline --record`` refuse,
    which turns the typo into a disarmed writer as well.

    ⚑ **``[[gate]]`` spells ``command`` as a string on purpose**, so the key's
    name does not say which form it takes. That is why this is checked per site
    rather than inferred.

    :func:`_commands` is deliberately not a caller: the ``[command]`` table also
    requires a *non-empty* list, where an inline ``command`` reports emptiness
    alongside the other keys a declaration is missing. Same predicate, different
    contract -- the rule ``targets.py`` records about ``_build_import``.
    """
    if raw is None:
        return ()
    if isinstance(raw, str) or not isinstance(raw, (list, tuple)):
        raise ConfigError(
            f"{where} declares {key} as {type(raw).__name__}; it takes a list "
            "of arguments, the way a shell would receive them: "
            f"{key} = [\"python\", \"-m\", \"tool\"]. A string is iterable, so "
            "this would run as one argument per character."
        )
    return tuple(str(part) for part in raw)


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
        _reject_unknown(spec, COUNT_KEYS, f"{path}: [[count]] {index}", absorbs=True)
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
            argv = _argv(spec.get("command"), f"{path}: [[count]] {index}", "command")

        missing = [key for key in ("pattern", "extract") if not spec.get(key)]
        if not argv:
            missing.append("command")
        if missing:
            raise ConfigError(
                f"{path}: [[count]] {index} is missing {', '.join(missing)}"
            )
        argv += _argv(spec.get("args"), f"{path}: [[count]] {index}", "args")
        occurrence = str(spec.get("occurrence", EVERY))
        if occurrence not in OCCURRENCES:
            # Named rather than defaulted, on the rule the unknown `strip`
            # transform follows: a misspelling that fell back to "every" would
            # quietly re-check the history this key exists to stop reading.
            raise ConfigError(
                f"{path}: [[count]] {index} declares occurrence "
                f"{occurrence!r}; known: {', '.join(sorted(OCCURRENCES))}"
            )
        built.append(
            Counted(
                pattern=str(spec["pattern"]),
                command=argv,
                extract=str(spec["extract"]),
                label=str(spec.get("label", "count")),
                directory=str(spec.get("directory", ".")),
                occurrence=occurrence,
            )
        )
    return tuple(built)


def _build_parities(
    declarations: list[dict[str, Any]],
    path: Path,
    commands: dict[str, tuple[str, ...]] | None,
    registries: list[str],
) -> tuple[Oracle, ...]:
    """``[[parity]]`` tables, refused rather than skipped when incomplete.

    A parity declaration naming a registry that does not exist is refused here
    rather than at the command, because the two failures look identical from
    the outside and only one of them is the project's mistake: a run that
    reports nothing because the name was misspelled is indistinguishable from a
    project whose declaration and code agree.
    """
    known = commands or {}
    built: list[Oracle] = []
    claimed: dict[str, int] = {}
    for index, spec in enumerate(declarations):
        _reject_unknown(spec, PARITY_KEYS, f"{path}: [[parity]] {index}", absorbs=True)
        if spec.get("command") and spec.get("run"):
            raise ConfigError(
                f"{path}: [[parity]] {index} declares both 'command' and 'run'; "
                "one names the oracle inline, the other names a declared one."
            )
        if spec.get("run"):
            name = str(spec["run"])
            if name not in known:
                raise ConfigError(
                    f"{path}: [[parity]] {index} runs {name!r}, which no "
                    f"[command] declares (known: {', '.join(sorted(known)) or 'none'})"
                )
            argv: tuple[str, ...] = known[name]
        else:
            argv = _argv(spec.get("command"), f"{path}: [[parity]] {index}", "command")

        missing = [key for key in ("registry", "extract") if not spec.get(key)]
        if not argv:
            missing.append("command")
        if missing:
            raise ConfigError(
                f"{path}: [[parity]] {index} is missing {', '.join(missing)}"
            )
        target = str(spec["registry"])
        if target not in registries:
            raise ConfigError(
                f"{path}: [[parity]] {index} names registry {target!r}, which "
                f"no [[registry]] declares "
                f"(known: {', '.join(sorted(registries)) or 'none'})"
            )
        # One registry, one oracle. Two declarations would compare membership
        # twice, so one disagreement would be reported and recorded as two --
        # and a baseline whose counts are inflated by the config's shape is one
        # nobody can audit against a scan.
        if target in claimed:
            raise ConfigError(
                f"{path}: [[parity]] {index} names registry {target!r}, which "
                f"[[parity]] {claimed[target]} already does. One registry, one "
                "oracle: to check a second fact about the same data model, "
                "declare a second [[registry]] view of it."
            )
        claimed[target] = index

        value_field = _field_spelling(
            spec.get("field"), f"{path}: [[parity]] {index}"
        )
        authority = str(spec.get("authority", ""))
        if authority and authority not in AUTHORITIES:
            raise ConfigError(
                f"{path}: [[parity]] {index} declares authority {authority!r}; "
                f"it must be one of {', '.join(AUTHORITIES)}."
            )
        # Required with a field and optional without, because the membership
        # directions name their own side -- "produced, declared by nothing" says
        # what to do -- while a value divergence is two strings and nothing
        # saying which one is the claim.
        if value_field and not authority:
            raise ConfigError(
                f"{path}: [[parity]] {index} compares the "
                f"{spell_path(value_field)!r} field "
                "but declares no authority. Say which side is the claim -- "
                f"{' or '.join(AUTHORITIES)} -- because a divergence with no "
                "authoritative side is a finding nobody can act on."
            )

        relation = str(spec.get("relation", "equal"))
        if relation not in RELATIONS:
            raise ConfigError(
                f"{path}: [[parity]] {index} declares relation {relation!r}; "
                f"it must be one of {', '.join(RELATIONS)}."
            )
        # A value comparison pairs identifiers both sides carry. Under
        # `disjoint` there are none by construction, and under a containment the
        # pairing is defined only over the intersection -- a claim nothing has
        # asked for, and a capability with no reader is one this project
        # declines rather than ships.
        if value_field and relation != "equal":
            raise ConfigError(
                f"{path}: [[parity]] {index} claims relation {relation!r} and "
                f"also compares the {spell_path(value_field)!r} field. A value "
                "comparison needs identifiers on both sides, which is the thing "
                "this relation is about. Declare one or the other."
            )

        # Without a field there is one side to translate and `translate`
        # already reaches it, so a second key naming that side is a declaration
        # saying the same thing twice -- and refusing beats picking a winner,
        # since either choice makes the other line inert.
        if spec.get("translate_identifier") is not None and not value_field:
            raise ConfigError(
                f"{path}: [[parity]] {index} declares 'translate_identifier' "
                "and compares no field, so it already translates its "
                "identifiers through 'translate'. Use one key: "
                "'translate_identifier' is for a parity that compares values "
                "as well, where 'translate' is spent on those."
            )

        # Refused rather than ignored where there is nothing to order:
        # membership compares identifiers, which are a set on both sides by
        # construction. A key that quietly means nothing is a check its author
        # believes is running.
        ordered = _flag(spec, "ordered", f"{path}: [[parity]] {index}")
        if ordered and not value_field:
            raise ConfigError(
                f"{path}: [[parity]] {index} declares 'ordered' and compares no "
                "field. Order is a property of a declared cell, and membership "
                "is a set on both sides -- name the 'field' whose order is the "
                "claim, or drop the key."
            )

        fmt = str(spec.get("format", "text"))
        if fmt not in FORMATS:
            raise ConfigError(
                f"{path}: [[parity]] {index} declares format {fmt!r}; it must be "
                f"one of {', '.join(FORMATS)}."
            )
        # Each refused rather than ignored: a key that quietly means nothing is
        # a check its author believes is running.
        if fmt == "json":
            clash = (
                "compares no field, and json is how a field's values are spelled"
                if not value_field
                else "declares 'translate', a rewrite of text, which data does "
                "not have" if spec.get("translate") is not None
                else "declares 'ordered', and a JSON list is already compared "
                "in order" if ordered
                else ""
            )
            if clash:
                raise ConfigError(
                    f"{path}: [[parity]] {index} declares format 'json' and {clash}."
                )

        argv += _argv(spec.get("args"), f"{path}: [[parity]] {index}", "args")
        built.append(
            Oracle(
                registry=target,
                command=argv,
                extract=str(spec["extract"]),
                directory=str(spec.get("directory", ".")),
                field=value_field,
                authority=authority,
                translate=_build_translation(spec.get("translate"), path, index),
                translate_identifier=_build_translation(
                    spec.get("translate_identifier"), path, index,
                    "translate_identifier",
                ),
                relation=relation,
                ordered=ordered,
                format=fmt,
            )
        )
    return tuple(built)


def _build_funnels(
    declarations: list[dict[str, Any]], path: Path, registries: list[str]
) -> tuple[Funnel, ...]:
    """``[[interpose]]`` tables, refused rather than skipped when incomplete.

    **The shape of a target is checked here and the target is not resolved.**
    Resolving it means importing the project's own modules, which belongs
    inside the project's own test session rather than inside every ``kinemata
    check`` -- and a module that imports there and not here would otherwise
    make a config unloadable for a reason having nothing to do with the file.
    :func:`kinemata.targets.resolve` does the rest, and its failure is the
    session's.
    """
    built: list[Funnel] = []
    watched: dict[str, int] = {}
    for index, spec in enumerate(declarations):
        _reject_unknown(
            spec, INTERPOSE_KEYS, f"{path}: [[interpose]] {index}", absorbs=True
        )
        missing = [
            key for key in ("registry", "target", "identify") if not spec.get(key)
        ]
        if missing:
            raise ConfigError(
                f"{path}: [[interpose]] {index} is missing {', '.join(missing)}"
            )
        target = str(spec["target"])
        for key in ("target", "identify"):
            module, _, attribute = str(spec[key]).partition(":")
            if not module.strip() or not attribute.strip():
                raise ConfigError(
                    f"{path}: [[interpose]] {index} names {spec[key]!r} as {key}, "
                    f"which is not a target. Write {FUNNEL_FORM}."
                )
        # One patch per callable. Two declarations would wrap it twice, so a
        # single call would be counted twice and the second uninstall would
        # restore the first wrapper rather than the original -- leaving the
        # project's own class patched after the run, which is the one property
        # this mechanism puts above the others.
        if target in watched:
            raise ConfigError(
                f"{path}: [[interpose]] {index} watches {target!r}, which "
                f"[[interpose]] {watched[target]} already watches. One patch "
                "per callable."
            )
        watched[target] = index
        name = str(spec["registry"])
        if name not in registries:
            raise ConfigError(
                f"{path}: [[interpose]] {index} names registry {name!r}, which "
                f"no [[registry]] declares "
                f"(known: {', '.join(sorted(registries)) or 'none'})"
            )
        built.append(
            Funnel(
                registry=name,
                target=target,
                identify=str(spec["identify"]),
                record=str(spec.get("record", "")),
            )
        )
    return tuple(built)


@dataclass(frozen=True)
class _Claim:
    """What a config must carry beside one ``[[shape.rule]]`` operator."""

    #: Another key the operator is meaningless without.
    companion: str = ""
    #: Whether the claim has to name the field it reads. Required wherever the
    #: alternative would be a silent default: ``matches`` with no field would
    #: read as "some obvious field" to everybody and as "the entry's id" to this
    #: code, so the id gets its own spelling instead.
    needs_field: bool = False
    #: The :mod:`kinemata.shape` operator this spelling builds, when the two
    #: differ. ``id_matches`` is the one case, and it exists so that no operator
    #: has two spellings in a config.
    operator: str = ""


#: Every operator a ``[[shape.rule]]`` may claim with. A table rather than a
#: chain of ``if``s, the way :data:`kinemata.claims.CLAIM_KINDS` is: a reader
#: auditing what a config can say should find one list, and a new operator
#: cannot be added without deciding what it requires.
#:
#: ⚑ **This table and shape's two operator tables are asserted equal, both ways,
#: by a case that exists for nothing else.** A spelling this layer accepts and
#: that layer cannot evaluate would be a config refused at the wrong end -- or
#: worse, accepted and then blocked at every run.
SHAPE_CLAIMS: dict[str, _Claim] = {
    "present": _Claim(),
    "absent": _Claim(),
    "equals": _Claim(needs_field=True),
    "choices": _Claim(needs_field=True),
    "matches": _Claim(needs_field=True),
    "each_matches": _Claim(needs_field=True),
    "each_value_matches": _Claim(needs_field=True),
    "contains": _Claim(needs_field=True),
    "id_matches": _Claim(operator="matches"),
    "exists": _Claim(),
    "keys_of": _Claim(companion="are"),
    "exhausts": _Claim(companion="field"),
    "holds": _Claim(),
}

#: Which spellings compile a pattern at load. An unusable one would otherwise
#: make every entry in a group violate a rule that is itself broken -- the
#: reasoning :func:`_build_translation` states for the same decision.
SHAPE_PATTERNS = ("matches", "each_matches", "each_value_matches", "id_matches")


def _shape_condition(
    spec: dict[str, Any], where: str, *, allow_set: bool
) -> Condition | Predicate:
    """One guard or claim, or a refusal naming what is wrong with it.

    ``in spec`` rather than truthiness throughout: ``equals = false`` and
    ``equals = 0`` are claims a declaration really makes, and reading them as
    "no operator given" would silently drop the rule.
    """
    spelled = [name for name in SHAPE_CLAIMS if name in spec]
    if not spelled:
        raise ConfigError(
            f"{where} claims nothing. Give it one of "
            f"{', '.join(sorted(SHAPE_CLAIMS))}."
        )
    if len(spelled) > 1:
        raise ConfigError(
            f"{where} claims {len(spelled)} things at once "
            f"({', '.join(sorted(spelled))}). One claim per rule: a finding "
            "that could mean either of two mistakes is one nobody can act on, "
            "and the baseline would record it under a single fingerprint."
        )
    spelling = spelled[0]
    claim = SHAPE_CLAIMS[spelling]
    if spelling == "holds":
        target = str(spec["holds"])
        module, _, attribute = target.partition(":")
        if not module.strip() or not attribute.strip():
            raise ConfigError(
                f"{where} names {target!r} as its predicate, which is not a "
                f"target. Write {FUNNEL_FORM}."
            )
        return Predicate(target=target)

    operator = claim.operator or spelling
    if operator in SET_OPERATORS and not allow_set:
        raise ConfigError(
            f"{where} guards with {spelling!r}, which asks about the whole set "
            "rather than about one entry, so it could not select a group."
        )
    if claim.companion and claim.companion not in spec:
        raise ConfigError(f"{where} claims {spelling!r} without {claim.companion!r}")
    field_name: str | tuple[str, ...] = _field_spelling(spec.get("field"), where)
    if claim.needs_field and not field_name:
        raise ConfigError(
            f"{where} claims {spelling!r} without naming a field. Add "
            f"field = \"...\", or use id_matches to claim something about the "
            "entry's own identifier."
        )

    argument: Any = spec[spelling]
    if spelling in ("present", "absent"):
        # These name their subject in the argument rather than in `field`, so a
        # path spelling arrives here instead: `present = ["default", "primary"]`
        # asks for an arm of a map. Checked by the same builder so one rule
        # governs both slots.
        argument = _field_spelling(argument, where)
    if spelling == "choices":
        # Refused when it is not a list, but its items keep their type: a
        # declared `choices = [1, 2]` compares integers, and text would not.
        _strings(argument, f"{where} choices")
        argument = tuple(argument)
    if spelling == "keys_of":
        # The two entry ids ride in the same two slots every other operator
        # uses, so `shape` needs no third field: `keys_of` names the entry whose
        # keys are read and `are` names the one whose values they must be.
        field_name, argument = str(spec["keys_of"]), spec["are"]
    elif spelling == "exhausts":
        field_name, argument = _field_spelling(spec["field"], where), spec["exhausts"]

    if spelling in SHAPE_PATTERNS:
        try:
            re.compile(str(argument))
        except re.error as error:
            raise ConfigError(
                f"{where} claims {spelling} {argument!r}, which is not a usable "
                f"pattern ({error})"
            ) from error

    return Condition(operator=operator, argument=argument, field=field_name)


#: Which key each outcome mode requires, and therefore which the other refuses.
#: A table rather than a chain of ``if``s, for :data:`SHAPE_CLAIMS`' reason: a
#: third mode must not be able to arrive without its discriminator.
_OUTCOME_DISCRIMINATORS = {"raises": "refusal", "returns": "accepted"}


def _build_probes(
    declarations: list[dict[str, Any]], path: Path
) -> tuple[Probe, ...]:
    """``[[probe]]`` tables, refused rather than skipped when incomplete.

    **The shapes of ``target``, ``cases`` and ``refusal`` are checked here and
    none of them is resolved**, which is :func:`_build_funnels`' split and its
    reason: importing a project's own modules belongs inside a run, not inside
    every ``kinemata check``.

    ⚑ **Each outcome mode's discriminator is required and the other mode's is
    refused.** A ``refusal`` beside ``outcome = "returns"`` is a reader's
    evidence that the config means something it does not, and this package has
    already paid once for a key that meant nothing being taken for a check that
    was switched on.
    """
    built: list[Probe] = []
    claimed: dict[str, int] = {}
    for index, spec in enumerate(declarations):
        where = f"{path}: [[probe]] {index}"
        _reject_unknown(spec, PROBE_KEYS, where, absorbs=True)
        missing = [key for key in ("name", "target", "cases") if not spec.get(key)]
        if missing:
            raise ConfigError(f"{where} is missing {', '.join(missing)}")

        name = str(spec["name"]).strip()
        if name in claimed:
            raise ConfigError(
                f"{where} is named {name!r}, which [[probe]] {claimed[name]} "
                "already is. Names are how a baseline record says which probe "
                "it belongs to, so two of one name would share a scope."
            )
        claimed[name] = index

        for key in ("target", "cases"):
            module, _, attribute = str(spec[key]).partition(":")
            if not module.strip() or not attribute.strip():
                raise ConfigError(
                    f"{where} names {spec[key]!r} as {key}, which is not a "
                    f"target. Write {FUNNEL_FORM}."
                )

        mode = str(spec.get("outcome", "")).strip()
        if mode not in OUTCOME_MODES:
            raise ConfigError(
                f"{where} declares outcome {mode or '(nothing)'!r}, which is "
                f"not how an answer can be read here "
                f"(known: {', '.join(OUTCOME_MODES)}). There is deliberately no "
                "escape to a project predicate: a project supplying the reading "
                "of an outcome is supplying the verdict."
            )
        required = _OUTCOME_DISCRIMINATORS[mode]
        forbidden = next(
            value for key, value in _OUTCOME_DISCRIMINATORS.items() if key != mode
        )
        if not spec.get(required):
            raise ConfigError(
                f'{where} declares outcome "{mode}" and no {required}. It is '
                "required rather than defaulted: a probe that inherited one "
                "would be reading the project's answers by a convention nobody "
                "chose."
            )
        if spec.get(forbidden):
            raise ConfigError(
                f'{where} declares outcome "{mode}" and {forbidden}, which '
                f'only outcome "{"raises" if mode == "returns" else "returns"}" '
                "reads. Nothing here would use it."
            )

        refusal = str(spec.get("refusal", "")).strip()
        accepted = str(spec.get("accepted", "")).strip()
        exact = _flag(spec, "exact", where)
        if exact and mode != "raises":
            raise ConfigError(
                f'{where} declares exact beside outcome "{mode}", which has no '
                "exception type to be exact about. It narrows refusal matching "
                'and belongs with outcome "raises".'
            )
        if mode == "raises":
            module, _, attribute = refusal.partition(":")
            if not module.strip() or not attribute.strip():
                raise ConfigError(
                    f"{where} names {refusal!r} as refusal, which is not a "
                    f"target. Write {FUNNEL_FORM}, naming the exception type "
                    "that means the input was refused."
                )
        elif accepted not in ACCEPTED_SPELLINGS:
            raise ConfigError(
                f"{where} declares accepted {accepted!r}, which is not one of "
                f"{', '.join(ACCEPTED_SPELLINGS)}. The value's type is not "
                "inferred: a callable returning 0 for success and one returning "
                "0 errors are the same bytes and the opposite meaning."
            )

        built.append(
            Probe(
                name=name,
                target=str(spec["target"]).strip(),
                cases=str(spec["cases"]).strip(),
                outcome=Outcome(
                    mode=mode, refusal=refusal, accepted=accepted, exact=exact
                ),
            )
        )
    return tuple(built)


def _build_shapes(
    declarations: list[dict[str, Any]], path: Path, registries: list[str]
) -> tuple[Shape, ...]:
    """``[[shape]]`` tables, refused rather than skipped when incomplete.

    A shape declaration naming a registry that does not exist is refused here
    for the reason :func:`_build_parities` gives: a run reporting nothing
    because a name was misspelled looks exactly like a declaration in good
    shape.
    """
    built: list[Shape] = []
    claimed: dict[str, int] = {}
    for index, spec in enumerate(declarations):
        _reject_unknown(spec, SHAPE_KEYS, f"{path}: [[shape]] {index}", absorbs=True)
        name = str(spec.get("registry", ""))
        if not name:
            raise ConfigError(f"{path}: [[shape]] {index} is missing registry")
        if name not in registries:
            raise ConfigError(
                f"{path}: [[shape]] {index} names registry {name!r}, which no "
                f"[[registry]] declares "
                f"(known: {', '.join(sorted(registries)) or 'none'})"
            )
        # One registry, one block. Two would let the same rule name be declared
        # twice under one scope, and the baseline could not tell their records
        # apart -- the argument `[[parity]]` makes about a second oracle.
        if name in claimed:
            raise ConfigError(
                f"{path}: [[shape]] {index} names registry {name!r}, which "
                f"[[shape]] {claimed[name]} already does. One registry, one "
                "block: add the rule to that block."
            )
        claimed[name] = index

        declared_rules = spec.get("rule", [])
        if not declared_rules:
            raise ConfigError(
                f"{path}: [[shape]] {index} declares no [[shape.rule]], so it "
                "would check nothing about "
                f"{name!r} while looking like it does."
            )
        rules: list[Rule] = []
        seen: dict[str, int] = {}
        for position, raw_rule in enumerate(declared_rules):
            where = f"{path}: [[shape.rule]] {position} of [[shape]] {index}"
            _reject_unknown(
                raw_rule, RULE_KEYS | frozenset(SHAPE_CLAIMS), where, absorbs=True
            )
            rule_name = str(raw_rule.get("name", "")).strip()
            if not rule_name:
                raise ConfigError(
                    f"{where} is missing name. Every rule carries one: a reader "
                    "of this config cannot see a predicate's body, and the name "
                    "is what tells them what the rule claims."
                )
            if rule_name in seen:
                raise ConfigError(
                    f"{where} is named {rule_name!r}, which rule {seen[rule_name]} "
                    "already uses. The baseline scope is built from the name, so "
                    "two rules sharing one is an exemption list nobody can audit."
                )
            seen[rule_name] = position
            guard = raw_rule.get("when")
            rules.append(
                Rule(
                    name=rule_name,
                    claim=_shape_condition(raw_rule, where, allow_set=True),
                    guard=(
                        None
                        if guard is None
                        else _shape_guard(guard, f"{where}'s when")
                    ),
                )
            )
        built.append(Shape(registry=name, rules=tuple(rules)))
    return tuple(built)


def _selected(registry: BaseRegistry, spec: dict[str, Any], path: Path) -> BaseRegistry:
    """``[[registry]] where`` -- the same registry, narrowed to a group.

    **The vocabulary is a ``[[shape]]`` guard, reused rather than invented.** It
    is already the seam for *"which entries is this rule about"*, and a second
    operator table would eventually disagree with the first.

    **Why it lives on the registry and not on the check that wanted it.** The
    motivating case is a parity whose oracle answers for 10 of 99 declared rows,
    paying an ``unproduced`` tail for the other 89. Putting the selector on
    ``[[parity]]`` would have made membership's *"and there is nothing else"*
    subset-relative for everyone and broken the uniqueness of
    ``parity:<registry>:<direction>``, so two narrowed parities' ``--prune``
    would delete each other's records. Here the registry **is** the set,
    membership keeps its meaning, and every other mechanism -- the scan,
    ``undeclared``, ``shape``, ``unused`` -- sees the same narrowing.
    """
    name = spec.get("name", "?")
    at = f"{path}: [[registry]] {name!r} where"
    if _flag(spec, "closed", f"registry {name!r}"):
        raise ConfigError(
            f"registry {name!r} declares both 'closed' and 'where'. A closed "
            "registry answers 'nothing declares this identifier', and over a "
            "subset every identifier belonging to an excluded row would be a "
            "finding that is wrong. Close the whole view, or narrow it."
        )
    guard = _shape_guard(spec["where"], at)
    try:
        keep = asked(guard)
    except (ShapeError, TargetError) as exc:
        raise ConfigError(f"{at} cannot be evaluated: {exc}") from exc
    narrowed = Selected(registry, keep)
    if not any(True for _ in narrowed.entries()):
        # Refused rather than reported, and refused here rather than left to the
        # emptiness notice below, which `allow_empty` can switch off: a selector
        # that kept nothing makes every mechanism reading this registry vacuous
        # at once. The two causes are told apart because the fixes are opposite.
        if any(True for _ in registry.entries()):
            raise ConfigError(
                f"{at} ({guard}) kept none of the entries {name!r} declares, so "
                "every check reading this view would pass by looking at nothing."
            )
        raise ConfigError(
            f"registry {name!r} produced no entries at all, so its 'where' "
            f"({guard}) has nothing to narrow."
        )
    return narrowed


def _field_spelling(declared: object, where: str) -> str | tuple[str, ...]:
    """A ``field``: one key, or a path into an entry written as a list.

    **A list descends and a string never does**, however many dots it holds.
    The alternative -- splitting ``"default.primary"`` -- would guess, and
    ``extra`` keys legitimately contain dots: the first adopter's own
    identifiers are spelled ``workset.boxes``. A guess that is wrong here does
    not fail, it compares the wrong cell and passes, which is the failure this
    package refuses by name. See :func:`kinemata.contract.field_path`.
    """
    if declared is None:
        return ""
    if isinstance(declared, str):
        return declared
    if isinstance(declared, (list, tuple)):
        if not declared:
            raise ConfigError(
                f"{where} declares an empty 'field'. A path with no keys "
                "reaches the entry itself, which is not a value to compare."
            )
        bad = [part for part in declared if not isinstance(part, str) or not part]
        if bad:
            raise ConfigError(
                f"{where} declares a 'field' path with {bad!r} in it; every "
                "step is the name of a key, so each must be a non-empty string."
            )
        return tuple(declared)
    raise ConfigError(
        f"{where} declares 'field' as {type(declared).__name__}; it takes a "
        'key ("default") or a path into the entry (["default", "primary"]).'
    )


def _shape_guard(declared: object, where: str) -> Condition | Predicate:
    """A guard: a table of operators, or a target naming a predicate."""
    if isinstance(declared, str):
        return _shape_condition({"holds": declared}, where, allow_set=False)
    if isinstance(declared, dict):
        return _shape_condition(dict(declared), where, allow_set=False)
    raise ConfigError(
        f"{where} is a {type(declared).__name__}. A guard is either a table of "
        f"operators or a {FUNNEL_FORM.split(' = ')[1]} naming a predicate."
    )


def _build_translation(
    declared: object, path: Path, index: int, key: str = "translate"
) -> Translation | None:
    """One translation a ``[[parity]]`` declares, or a refusal.

    Compiled here rather than at the comparison, unlike ``extract``: an
    unusable ``extract`` makes a run fail loudly as blocked, while an unusable
    translation would make every comparison in it wrong. A project's mistake
    belongs where a project's mistakes are refused.

    ``key`` names the one being built, so a refusal about
    ``translate_identifier`` does not point at the other key's spelling.
    """
    if declared is None:
        return None
    where = f"{path}: [[parity]] {index}'s {key}"
    if not isinstance(declared, dict):
        raise ConfigError(f"{where} must be a table, not a {type(declared).__name__}")
    table, pattern = declared.get("map"), declared.get("pattern")
    if table is not None and pattern is not None:
        raise ConfigError(
            f"{where} declares both 'map' and 'pattern'; a declaration carries "
            "at most one translation, and two would be a pipeline nobody can "
            "read off the config."
        )
    if table is not None:
        if not isinstance(table, dict) or not table:
            raise ConfigError(
                f"{where} declares an empty or non-table 'map'. A map that "
                "translates nothing is a comparison pretending to have one."
            )
        return Translation(
            table={str(key): str(value) for key, value in table.items()}
        )
    if pattern is not None:
        # Never defaulted: an empty replacement is a legitimate translation, so
        # a missing one is a typo that would silently delete text.
        if "replacement" not in declared:
            raise ConfigError(
                f"{where} declares a 'pattern' with no 'replacement'. Say what "
                'the pattern becomes, even if that is "".'
            )
        try:
            re.compile(str(pattern))
        except re.error as error:
            raise ConfigError(f"{where} has an unusable pattern ({error})") from error
        return Translation(
            pattern=str(pattern), replacement=str(declared["replacement"])
        )
    raise ConfigError(
        f"{where} declares neither 'map' nor 'pattern', so it says nothing "
        "about how the two sides differ."
    )
