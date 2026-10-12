"""AST boundaries and their rule-owned ratchets.

A boundary names a static source policy, rather than trying to recover imports or
calls from text.  It intentionally resolves only lexical imports and aliases:
dynamic attribute access and instance/data-flow dispatch are reported as
unjudged, never guessed into a green result.
"""

from __future__ import annotations

import ast
import fnmatch
import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Literal

from .bypass import _walk as _project_files
from .exclusion import excluded

RATCHET_DIRECTORY = Path(".kinemata") / "ratchets"
#: 2 keys a finding by its enclosing scope rather than its line, and carries a
#: multiplicity per key. Version 1 was unreleased and is refused rather than
#: migrated: its records are keyed on line numbers, which is the defect.
RATCHET_VERSION = 2
BOUNDARY_KINDS = ("imports", "calls")
TYPE_CHECKING_POLICIES = ("include", "ignore")
#: What a finding at module level is scoped to. Spelled rather than empty so a
#: module-level record and a function-level one never share a key by accident.
MODULE_SCOPE = "<module>"
_RULE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9_-]*\Z")


class BoundaryError(Exception):
    """A boundary declaration or its rule-owned evidence cannot be honored."""


@dataclass(frozen=True)
class Ratchet:
    """The required expiry for one optional boundary evidence artifact."""

    until: date


@dataclass(frozen=True)
class Boundary:
    """One import-layer or resolved-call policy declared in configuration."""

    name: str
    kind: Literal["imports", "calls"]
    only: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    imports: tuple[str, ...] = ()
    allow: tuple[str, ...] = ()
    calls: tuple[str, ...] = ()
    homes: tuple[str, ...] = ()
    type_checking: Literal["include", "ignore"] = "include"
    ratchet: Ratchet | None = None

    def semantic_fingerprint(self) -> str:
        """Fingerprint the policy, never its accepted findings or expiry."""
        declared = {
            "name": self.name,
            "kind": self.kind,
            "only": self.only,
            "exclude": self.exclude,
            "imports": self.imports,
            "allow": self.allow,
            "calls": self.calls,
            "homes": self.homes,
            "type_checking": self.type_checking,
        }
        return _fingerprint(declared)

    def artifact_path(self, root: Path) -> Path:
        return root / RATCHET_DIRECTORY / f"{self.name}.json"


@dataclass(frozen=True)
class ImportSite:
    path: str
    line: int
    module: str
    symbol: str | None
    type_checking: bool
    scope: str = MODULE_SCOPE

    @property
    def target(self) -> str:
        return f"{self.module}.{self.symbol}" if self.symbol else self.module


@dataclass(frozen=True)
class CallSite:
    path: str
    line: int
    target: str
    expression: str
    scope: str = MODULE_SCOPE


@dataclass(frozen=True)
class Unsupported:
    path: str
    line: int
    expression: str
    reason: str


@dataclass(frozen=True)
class Finding:
    """A source-located policy violation with a stable rule-local identity."""

    rule: str
    kind: str
    path: str
    line: int
    subject: str
    detail: str
    scope: str = MODULE_SCOPE

    @property
    def fingerprint(self) -> str:
        """Identify this finding across commits.

        ⚑ **The line number is deliberately absent**, and an adopter found out
        why the day this shipped: adding **one comment line** at the top of a
        module shifted every accepted import below it, so 37 of 110 records
        stopped matching and the rule failed. Re-recording on every unrelated
        edit is how a ratchet gets waved through.

        This is :class:`kinemata.baseline.Accepted`'s contract, deliberately: it
        keys on scope, subject, path and the matched spelling, and says why in
        its own docstring. **The enclosing scope replaces the line** rather than
        going with it — a lazy import inside ``def resolve`` stays inside
        ``resolve`` however far the code above it moves, while a module-level
        import and the same import inside a function are still two sites.
        """
        return _fingerprint({
            "rule": self.rule,
            "kind": self.kind,
            "path": self.path,
            "scope": self.scope,
            "subject": self.subject,
            "detail": self.detail,
        })

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.subject} {self.detail}"


@dataclass(frozen=True)
class BoundaryResult:
    rule: Boundary
    findings: tuple[Finding, ...] = ()
    unsupported: tuple[Unsupported, ...] = ()
    blocked: tuple[str, ...] = ()
    files: tuple[str, ...] = ()

    @property
    def vacuous(self) -> bool:
        return not self.files

    @property
    def unjudged(self) -> bool:
        """Did part of the scan fail to measure anything at all?

        **This governs the *writer*, not the gate.** A run that could not measure
        must not author the evidence file, because an exemption written from a
        scan that examined nothing is exactly the failure the ratchet exists to
        prevent -- so ``--record`` and ``--prune`` refuse while this holds.

        It deliberately does **not** make the gate fail, and that split is the
        measured part. A call on a receiver this resolver cannot follow is **not
        evidence of a violation**. Failing on it makes the mechanism unusable
        rather than honest: on an adopter's tree a fully resolvable family of
        module functions produced **59** real findings beside **71** sites with
        an unknown receiver, because ``tmp.replace`` shares its last segment with
        ``os.replace`` and ``str.replace`` is everywhere; a ``Path.write_text``
        policy produced **191** such sites and **0** findings, a rule that could
        never pass, which teaches its reader to delete it.

        So the gate counts and prints them the way ``negated:`` and ``set-valued:``
        count theirs -- the coverage is partial and the number is on every run --
        while the writer still refuses, because an unmeasured call cannot earn an
        accepted finding.
        """
        return bool(self.blocked or self.vacuous or self.unsupported)

    @property
    def scope_fingerprint(self) -> str:
        """The actual file coverage, for a readable record of what was examined."""
        return _fingerprint({"files": self.files})

    def lost(self, recorded: Iterable[str]) -> tuple[str, ...]:
        """Files a previous run examined that this one does not.

        **A data change, not a declaration change, and reported rather than
        failed.** Adding a module must not block a gate, and neither must
        deleting one; the records on a file that went away are simply stale and
        an explicit ``--prune`` drops them. Narrowing is caught by the
        declaration instead -- :meth:`Boundary.semantic_fingerprint` carries
        ``only`` and ``exclude`` -- so this half exists to *say* what left the
        population rather than hold an opaque hash over it and fail on a routine
        commit, which is what it did at first: every new module in a covered
        package blocked the gate.
        """
        examined = set(self.files)
        return tuple(sorted(set(recorded) - examined))


@dataclass(frozen=True)
class Artifact:
    """One rule's independently versioned accepted-finding set."""

    owner: str
    kind: str
    rule: str
    files: tuple[str, ...]
    until: date
    #: Fingerprint -> how many of them. **The count because identical sites
    #: recur**: a module may import the same name in two functions, or the same
    #: literal three times over, and a set cannot tell a second occurrence from
    #: the first. Recording the multiplicity is what makes the next one an
    #: increase instead of an indistinguishable duplicate -- the same reason
    #: :class:`kinemata.baseline.Accepted` carries a ``count``.
    findings: Mapping[str, int]

    def validate(self, boundary: Boundary) -> None:
        if self.owner != boundary.name:
            raise BoundaryError(
                f"ratchet {boundary.artifact_path(Path('.'))}: owner {self.owner!r} "
                f"does not match boundary {boundary.name!r}"
            )
        if self.kind != boundary.kind:
            raise BoundaryError(
                f"ratchet for {boundary.name!r}: kind {self.kind!r} does not match "
                f"the declared {boundary.kind!r} policy"
            )
        if self.rule != boundary.semantic_fingerprint():
            raise BoundaryError(
                f"ratchet for {boundary.name!r}: its rule fingerprint differs from "
                "the declared policy; re-record deliberately rather than accepting a "
                "weakened or changed rule. `only` and `exclude` are part of this "
                "fingerprint, so a narrowed source scope is refused here too"
            )
        if boundary.ratchet is None or self.until != boundary.ratchet.until:
            raise BoundaryError(
                f"ratchet for {boundary.name!r}: its expiry does not match the "
                "declaration; re-record with the declared date"
            )
        if self.until < date.today():
            raise BoundaryError(
                f"ratchet for {boundary.name!r} expired on {self.until}; drive it "
                "down or re-record after a deliberate review"
            )


def _fingerprint(value: object) -> str:
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def _matches_module(name: str, pattern: str) -> bool:
    """Match a declared module family without text-substring surprises."""
    if pattern.endswith(".*"):
        return name.startswith(pattern[:-1])
    return name == pattern or name.startswith(f"{pattern}.")


def _matches_call(name: str, pattern: str) -> bool:
    return fnmatch.fnmatchcase(name, pattern)


def _package_parts(root: Path, path: Path) -> list[str]:
    """The importable module parts of a source file, walking up its own packages.

    **Measured wrong the first time by the repository dogfooding this rule.**
    Joining the path relative to the *project* root spelled every module in a
    :shown:`src/` layout as :shown:`src.kinemata.boundary`, so the rule naming
    ``kinemata.baseline`` could not match the very import it forbids: the gate
    printed "policy holds" over a planted violation. A :shown:`src/` directory is
    not part of any module name, and neither is a build directory -- the packages
    themselves say where they begin, by carrying :shown:`__init__.py`.

    So this climbs while the parent is a package, and answers from the topmost
    package it reaches. A file outside any package keeps its project-relative
    spelling, which is the only name it can have.
    """
    directory = path.parent
    while (directory / "__init__.py").is_file() and directory != root:
        directory = directory.parent
    relative = path.relative_to(directory)
    parts = list(relative.parts)
    if parts[-1] == "__init__.py":
        parts.pop()
    else:
        parts[-1] = Path(parts[-1]).stem
    return [part for part in parts if part]


def _module_name(root: Path, path: Path) -> str:
    """The import module corresponding to a source file, where package data says."""
    return ".".join(_package_parts(root, path))


def _relative_module(module: str, level: int, name: str | None) -> str:
    package = module.split(".")[:-1]
    kept = len(package) - (level - 1)
    if kept < 0:
        return name or ""
    parts = package[:kept]
    if name:
        parts.extend(name.split("."))
    return ".".join(parts)


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    return (
        isinstance(test, ast.Attribute)
        and isinstance(test.value, ast.Name)
        and test.value.id == "typing"
        and test.attr == "TYPE_CHECKING"
    )


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except AttributeError:  # pragma: no cover - Python 3.11 guarantees unparse
        return type(node).__name__


class _Visitor(ast.NodeVisitor):
    """Sequential lexical alias collection plus import/call observations."""

    def __init__(self, path: str, module: str) -> None:
        self.path = path
        self.module = module
        self.scopes: list[dict[str, str]] = [{}]
        #: The enclosing def/class chain, which is what a finding keys on in
        #: place of its line -- stable however far the code above it moves.
        self.enclosing: list[str] = []
        self.type_checking = False
        self.imports: list[ImportSite] = []
        self.calls: list[CallSite] = []
        self.dynamic: list[Unsupported] = []

    @property
    def scope(self) -> str:
        return ".".join(self.enclosing) if self.enclosing else MODULE_SCOPE

    def _resolved(self, node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            for scope in reversed(self.scopes):
                if node.id in scope:
                    return scope[node.id]
            if node.id == "open":
                return "builtins.open"
            return None
        if isinstance(node, ast.Attribute):
            prefix = self._resolved(node.value)
            return f"{prefix}.{node.attr}" if prefix else None
        return None

    def _alias(self, target: ast.expr, value: ast.expr) -> None:
        if isinstance(target, ast.Name):
            resolved = self._resolved(value)
            if resolved:
                self.scopes[-1][target.id] = resolved

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self.imports.append(ImportSite(
                self.path, node.lineno, alias.name, None, self.type_checking, self.scope
            ))
            # A TYPE_CHECKING import is evidence for an import policy, but it is
            # not a runtime binding. Letting it resolve a later call would turn a
            # type-only name into a fabricated runtime dependency.
            if not self.type_checking:
                bound = alias.asname or alias.name.split(".")[0]
                self.scopes[-1][bound] = alias.name if alias.asname else bound

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        module = (
            _relative_module(self.module, node.level, node.module)
            if node.level else (node.module or "")
        )
        for alias in node.names:
            if alias.name == "*":
                # Star imports cannot identify a later bare call. The import still
                # belongs to an import-layer policy; no inferred aliases follow.
                self.imports.append(ImportSite(
                    self.path, node.lineno, module, "*", self.type_checking, self.scope
                ))
                continue
            self.imports.append(ImportSite(
                self.path, node.lineno, module, alias.name, self.type_checking, self.scope
            ))
            if not self.type_checking:
                self.scopes[-1][alias.asname or alias.name] = f"{module}.{alias.name}"

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        for target in node.targets:
            self._alias(target, node.value)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            self._alias(node.target, node.value)

    def visit_Call(self, node: ast.Call) -> None:
        resolved = self._resolved(node.func)
        expression = _expression(node.func)
        if resolved:
            self.calls.append(
                CallSite(self.path, node.lineno, resolved, expression, self.scope)
            )
        self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self.visit(node.test)
        prior = self.type_checking
        if _is_type_checking(node.test):
            self.type_checking = True
        for item in node.body:
            self.visit(item)
        self.type_checking = prior
        for item in node.orelse:
            self.visit(item)

    def _scoped(self, node: ast.AST, name: str | None = None) -> None:
        self.scopes.append({})
        self.enclosing.append(name or type(node).__name__)
        self.generic_visit(node)
        self.enclosing.pop()
        self.scopes.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._scoped(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._scoped(node, node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._scoped(node, "lambda")


def _files(root: Path, boundary: Boundary, exclude: Iterable[str] = ()) -> tuple[Path, ...]:
    """The project's own Python, read the way every other scan here reads it.

    **Walking ``rglob("*.py")`` was the first spelling and it read other people's
    code.** An importing boundary with no ``only`` picked up ``.venv/`` and any
    gitignored corpus, and reported their imports as violations of this project's
    layering. It also poisons :attr:`BoundaryResult.scope_fingerprint`: the
    coverage lock is supposed to move when the *declaration* narrows, and a
    vendored library upgrading would then read as this rule's coverage changing.

    So this asks the same question every other scan asks -- *does this file belong
    to the project being checked?* -- and takes the answer the project already
    declared. Measured on a scratch tree: two of two files under a rule naming one
    ``only``-less package were reported, one of them inside ``.venv/``.
    """
    fragments = (*exclude, *boundary.exclude)
    selected: list[Path] = []
    for path in sorted(_project_files(root, (".py",))):
        relative = path.relative_to(root).as_posix()
        if excluded(relative, fragments):
            continue
        if boundary.only and not any(
            excluded(relative, (fragment,)) for fragment in boundary.only
        ):
            continue
        selected.append(path)
    return tuple(selected)


def _imports(boundary: Boundary, found: Iterable[ImportSite]) -> list[Finding]:
    findings: list[Finding] = []
    for item in found:
        if item.type_checking and boundary.type_checking == "ignore":
            continue
        if not any(_matches_module(item.target, pattern) for pattern in boundary.imports):
            continue
        permitted = any(
            _matches_module(item.module, pattern) or _matches_module(item.target, pattern)
            for pattern in boundary.allow
        )
        if not permitted:
            suffix = f" import {item.target!r} is outside the declared surface"
            findings.append(Finding(
                boundary.name, boundary.kind, item.path, item.line, item.target,
                suffix, item.scope,
            ))
    return findings


def _calls(boundary: Boundary, found: Iterable[CallSite]) -> list[Finding]:
    findings: list[Finding] = []
    for item in found:
        if not any(_matches_call(item.target, pattern) for pattern in boundary.calls):
            continue
        if any(excluded(item.path, (home,)) for home in boundary.homes):
            continue
        findings.append(Finding(
            boundary.name,
            boundary.kind,
            item.path,
            item.line,
            item.target,
            f" call through {item.expression!r} is outside its declared home",
            item.scope,
        ))
    return findings


def _unsupported(
    boundary: Boundary, tree: ast.AST, path: str, resolved: Iterable[CallSite]
) -> list[Unsupported]:
    """Name dynamic forms that could otherwise disguise a selected call.

    A local call is not itself suspicious; an attribute on an unknown instance is.
    It is reported only where its method spelling belongs to this policy, keeping a
    call-home rule from becoming an inventory of the application's every function.
    """
    if boundary.kind != "calls":
        return []
    endings = {pattern.rsplit(".", 1)[-1] for pattern in boundary.calls}
    known = {(item.line, item.expression) for item in resolved if item.path == path}
    rows: list[Unsupported] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        expression = _expression(node.func)
        if node.func.attr not in endings or (node.lineno, expression) in known:
            continue
        if isinstance(node.func.value, (ast.Call, ast.Subscript)):
            reason = "dynamic receiver cannot be resolved statically"
        else:
            reason = "instance/data-flow receiver cannot be resolved statically"
        rows.append(Unsupported(path, node.lineno, expression, reason))
    return rows


def survey(root: Path, boundary: Boundary, exclude: Iterable[str] = ()) -> BoundaryResult:
    """Run one policy over exactly its declared source scope."""
    sources = _files(root, boundary, exclude)
    imports: list[ImportSite] = []
    calls: list[CallSite] = []
    unsupported: list[Unsupported] = []
    blocked: list[str] = []
    relative: list[str] = []
    for source in sources:
        path = source.relative_to(root).as_posix()
        relative.append(path)
        try:
            text = source.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=path)
        except (OSError, UnicodeDecodeError, SyntaxError) as exc:
            blocked.append(f"{path}: cannot parse Python source ({exc})")
            continue
        visitor = _Visitor(path, _module_name(root, source))
        visitor.visit(tree)
        imports.extend(visitor.imports)
        calls.extend(visitor.calls)
        unsupported.extend(_unsupported(boundary, tree, path, visitor.calls))
    if boundary.kind == "imports":
        findings = _imports(boundary, imports)
    else:
        findings = _calls(boundary, calls)
    return BoundaryResult(
        boundary,
        tuple(findings),
        tuple(unsupported),
        tuple(blocked),
        tuple(relative),
    )


def _shown_version(raw: object) -> object:
    return raw.get("version") if isinstance(raw, dict) else None


def _read_tally(raw: object, path: Path) -> Mapping[str, int]:
    """Fingerprint -> count, read strictly. A damaged tally is never an empty one."""
    if not isinstance(raw, dict) or not all(
        isinstance(key, str)
        and isinstance(value, int)
        and not isinstance(value, bool)
        and value > 0
        for key, value in raw.items()
    ):
        raise BoundaryError(
            f"{path}: boundary ratchet findings must map a fingerprint to a count; "
            "re-record it"
        )
    return dict(raw)


def _tally(findings: Iterable[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in findings:
        counts[item.fingerprint] = counts.get(item.fingerprint, 0) + 1
    return counts


def load_artifact(path: Path) -> Artifact:
    """Read one evidence file strictly; a damaged ratchet is never empty."""
    try:
        raw = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise BoundaryError(f"cannot read boundary ratchet {path}: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != RATCHET_VERSION:
        raise BoundaryError(
            f"{path}: boundary ratchet schema {_shown_version(raw)!r} "
            f"is not version {RATCHET_VERSION}; re-record it rather than editing by hand"
        )
    expected = {"version", "owner", "kind", "rule", "files", "until", "findings"}
    scalar = expected - {"version", "findings", "files"}
    if set(raw) != expected or not all(isinstance(raw[key], str) for key in scalar):
        raise BoundaryError(
            f"{path}: malformed boundary ratchet; re-record it rather than editing by hand"
        )
    if not isinstance(raw["files"], list) or not all(
        isinstance(item, str) for item in raw["files"]
    ):
        raise BoundaryError(f"{path}: boundary ratchet files must be paths; re-record it")
    tally = _read_tally(raw["findings"], path)
    try:
        until = date.fromisoformat(raw["until"])
    except ValueError as exc:
        raise BoundaryError(f"{path}: boundary ratchet expiry is not YYYY-MM-DD") from exc
    return Artifact(
        owner=raw["owner"], kind=raw["kind"], rule=raw["rule"],
        files=tuple(raw["files"]), until=until, findings=tally,
    )


def save_artifact(path: Path, result: BoundaryResult, findings: Iterable[Finding]) -> Artifact:
    """Write this rule's artifact and no other file or global baseline."""
    boundary = result.rule
    if boundary.ratchet is None:
        raise BoundaryError(f"boundary {boundary.name!r} declares no [boundary.ratchet]")
    artifact = Artifact(
        owner=boundary.name,
        kind=boundary.kind,
        rule=boundary.semantic_fingerprint(),
        files=result.files,
        until=boundary.ratchet.until,
        findings=_tally(findings),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "version": RATCHET_VERSION,
        "owner": artifact.owner,
        "kind": artifact.kind,
        "rule": artifact.rule,
        "files": list(artifact.files),
        "until": artifact.until.isoformat(),
        "findings": dict(sorted(artifact.findings.items())),
    }, indent=2) + "\n")
    return artifact


def inventory(root: Path, boundaries: Iterable[Boundary]) -> tuple[str, ...]:
    """Reject unmanaged, malformed, or wrong-owner sidecars on every full run."""
    declared = {rule.name: rule for rule in boundaries if rule.ratchet is not None}
    directory = root / RATCHET_DIRECTORY
    if not directory.exists():
        return ()
    if not directory.is_dir():
        return (f"{directory}: ratchet directory is not a directory",)
    errors: list[str] = []
    for path in sorted(directory.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            errors.append(f"{path}: unmanaged boundary ratchet artifact")
            continue
        try:
            artifact = load_artifact(path)
        except BoundaryError as exc:
            errors.append(str(exc))
            continue
        rule = declared.get(artifact.owner)
        if rule is None:
            errors.append(f"{path}: orphaned boundary ratchet for {artifact.owner!r}")
            continue
        if path != rule.artifact_path(root):
            errors.append(
                f"{path}: boundary ratchet owner {artifact.owner!r} has the wrong managed path"
            )
    return tuple(errors)


def validate_name(name: str) -> bool:
    return bool(_RULE_NAME.fullmatch(name))
