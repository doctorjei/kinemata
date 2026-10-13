"""A fenced code block that shows a signature, checked against the real one.

The narrowest of the identifier questions, and the only one this project
accepted: **a `def name(...)` line inside a fence is a claim about what
the code is**, where a prose mention is not. ``docs/introduction.md``
§ Known limits records why the broad form was declined -- a backticked
identifier is mostly not a symbol claim, so *every backticked identifier
resolves* is a guesser with an opt-out -- and the narrow form is where
that stops being true.

Reported by kanibako 2026-10-13, whose writers were comparing fenced
signatures against source by hand on every documentation lane. Their
own evidence for what counts: three lanes came back for wrong *default
values* (`= ""` where the code has `= UNSET`, `None` where it has
`GENERAL_SLOT`), which a comparison of names and order passes happily.
So a default's **value** is part of the claim, not decoration.

**Wrapping is not an edge case here; it is 16% of the population.**
Measured on the adopter's tree, 36 of 230 fenced signatures wrap across
lines::

    def _box_settings_files(
        mode: BoxMode, metadata_path: Path, ...
    ) -> BoxSettingsFiles:

Matching one line at a time reads half a signature and reports every one
as drift, and reading only whole lines misses a sixth of the corpus
**silently** -- which is the failure this package exists to refuse. So
:func:`fenced_signatures` accumulates until the parentheses balance.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterator
from dataclasses import dataclass, field

#: An opening or closing fence, as :data:`kinemata.prose.FENCE` reads one.
#: **Declared twice rather than imported**, because this module's subject is a
#: fence's *contents* and prose's is what a fence filters out; the two would
#: agree today and diverge the first time either is changed, which is the
#: second carrier this project is built to report.
FENCE = re.compile(r"^\s*(`{3,}|~{3,})")

#: The head of a definition. **The parameter list is not here**, because it may
#: run to several lines and only :func:`fenced_signatures` can see that far.
HEAD = re.compile(r"^\s*(?:async\s+)?(?P<kind>def|class)\s+(?P<name>[A-Za-z_]\w*)\s*\(")

#: A call, which is the same claim stated the other way: ``name(...)`` is
#: unambiguous where a bare mention is not, and a document that shows how a
#: function is called has made the same assertion about its parameters.
CALL = re.compile(r"^\s*(?:return\s+|=\s*|await\s+)?(?P<name>[a-z_]\w*)\s*\(")

#: Parameter names a document would never write, filtered so a Python keyword
#: or a call's first argument cannot read as a signature.
NOT_A_SIGNATURE = frozenset({
    "if", "elif", "while", "for", "switch", "assert", "return", "with", "and",
    "or", "not", "in", "is", "del", "yield", "raise", "except", "lambda",
    "print", "super", "range", "len", "str", "int", "bool", "dict", "list",
    "tuple", "set", "frozenset", "type", "isinstance", "getattr", "setattr",
})


@dataclass(frozen=True)
class Signature:
    """One signature as a document writes it, or as the code declares it.

    ``params`` is a name and a **rendered default**, because a wrong default
    value is the drift this was built for and a name-only comparison cannot
    see it. An empty default means the parameter has none, which is different
    from one that has the empty string.
    """

    name: str
    kind: str
    params: tuple[tuple[str, str], ...] = ()
    line: int = 0
    text: str = ""

    def __str__(self) -> str:
        rendered = ", ".join(
            name if not default else f"{name} = {default}"
            for name, default in self.params
        )
        return f"{self.kind} {self.name}({rendered})"

    @property
    def bare(self) -> tuple[str, ...]:
        """Just the parameter names -- what a name-only check would compare."""
        return tuple(name for name, _ in self.params)


def _balanced_after(text: str, start: int) -> tuple[str, bool]:
    """The group opening at ``text[start]``, and whether it closes there.

    A signature that runs off the end of the line comes back ``closed=False``
    and the caller keeps reading -- **which is the whole reason this module
    exists rather than a regex with `[^)]*` in it.** A default of `()` inside
    an annotation (``keep: tuple[str, str] = ()``) puts a `)` before the end
    of the signature, so the cheap version truncates there and reports the
    parameter list as one long wrong name. Measured, not assumed.
    """
    depth, out = 0, []
    # **`start` is the opening parenthesis and the scan begins past it.** The
    # first version returned the group *including* it, so every parameter list
    # began `(` and no parameter name was an identifier -- which read as
    # `add_parser()` against a real `add_parser(subparsers)` and reported the
    # whole corpus as drift.
    for character in text[start + 1:]:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            if depth == 0:
                return "".join(out), True
            depth -= 1
        out.append(character)
    return "".join(out), False


def _split_top(raw: str) -> list[str]:
    parts, depth, current = [], 0, ""
    for character in raw:
        if character in "([{":
            depth += 1
        elif character in ")]}":
            depth -= 1
        if character == "," and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += character
    parts.append(current)
    return [
        part.strip()
        for part in parts
        if part.strip() and part.strip() not in {"*", "/", "**"}
    ]


def documented_params(raw: str) -> tuple[tuple[str, str], ...]:
    """Parameters as a document writes them, defaults rendered as written.

    The annotation is separated from the default by a top-level ``=``, and
    everything after it is **kept**, because the value is the claim. A
    signature that pins a stale default agrees with the code on every name
    and is still wrong.
    """
    out: list[tuple[str, str]] = []
    for part in _split_top(raw):
        head, separator, value = part.partition("=")
        name = head.split(":", 1)[0].strip().lstrip("*")
        if not name or not name.isidentifier():
            continue
        out.append((name, value.strip() if separator else ""))
    return tuple(out)


def render_default(text: str) -> str:
    """Normalise a default's spelling so ``""`` and ``''`` compare equal.

    A quote style is not a claim, and ``ast.unparse`` rewrites one, so
    comparing the renderings is what stops a correct value being reported
    wrong. **Unparseable text is returned as written** rather than guessed at:
    a default the parser does not understand is compared as the text the
    document spells, which can produce a finding but cannot produce a
    silently wrong agreement.
    """
    text = text.strip()
    if not text:
        return ""
    try:
        return ast.unparse(ast.parse(text, mode="eval").body)
    except SyntaxError:
        return text.replace("'", '"')


@dataclass
class Index:
    """Every signature the project's own code declares, by name.

    One name may hold several -- an overload, a redefinition in a
    submodule -- and **all of them are kept**, because a document naming one
    of them is right and a tool that picked the first would be wrong half the
    time.
    """

    by_name: dict[str, list[Signature]] = field(default_factory=dict)

    def add(self, signature: Signature) -> None:
        self.by_name.setdefault(signature.name, []).append(signature)

    def __len__(self) -> int:
        return sum(len(seen) for seen in self.by_name.values())

    def accepts(self, written: Signature) -> bool:
        """Does any declaration of this name carry the signature written?

        **A default's value is part of it**, per the adopter's three returned
        lanes. A name-only match would agree with every one of those, and the
        agreement would be the whole failure.
        """
        for declared in self.by_name.get(written.name, ()):
            # **A call and a definition are the same claim**, so a `name(...)`
            # line is matched against a `def name(...)`. Requiring the kinds to
            # agree reported 30 findings on one tree, every one of them a call
            # that had the right parameters. The distinction that does matter is
            # a class: its parentheses hold **bases**, not parameters.
            if written.kind == "call" and declared.kind == "call":
                continue
            if written.kind == "class" != declared.kind:
                continue
            if _same(declared.params, written.params):
                return True
        return False


def _same(declared: tuple[tuple[str, str], ...], written: tuple[tuple[str, str], ...]) -> bool:
    """Parameter names in order, and each default's value.

    Length first, so a signature missing a trailing keyword-only parameter is
    caught by the cheap comparison rather than by a positional zip that would
    silently compare the tail against nothing.
    """
    if len(declared) != len(written):
        return False
    for (name, default), (written_name, written_default) in zip(declared, written, strict=True):
        if name != written_name:
            return False
        if render_default(default) != render_default(written_default):
            return False
    return True


def fenced_signatures(source: str) -> Iterator[Signature]:
    """Every signature a fenced block of ``source`` shows.

    Calls are included alongside definitions, and the two are kept apart by
    :attr:`Signature.kind` -- a document showing how a function is called has
    made the same claim about its parameters, and a ``name(...)`` line is
    exactly as unambiguous as a ``def``.

    **Fences are the boundary, which is the whole premise.** Text outside one
    is prose, and prose about an identifier is the guesser this mechanism
    exists not to be. A fence inside a fence is still shown, so a block
    displaying another block is read as display.
    """
    inside = False
    lines = source.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        if FENCE.match(line):
            inside = not inside
            index += 1
            continue
        if not inside:
            index += 1
            continue
        found = _signature_at(lines, index)
        if found is None:
            index += 1
            continue
        end, signature = found
        yield signature
        index = end + 1


def _signature_at(lines: list[str], start: int) -> tuple[int, Signature] | None:
    """The signature beginning at ``lines[start]``, read as far as it runs.

    **Returns the line it ended on** so the caller resumes past it rather
    than inside a signature it has already read -- which is what makes the
    wrapped case work at all, and is the difference between a check that reads
    a document and one that reads every line of it.
    """
    head = HEAD.match(lines[start])
    call = None if head else CALL.match(lines[start])
    match = head or call
    if match is None:
        return None
    name = match.group("name")
    if name in NOT_A_SIGNATURE:
        return None

    text = lines[start]
    end = start
    raw, closed = _balanced_after(text, text.index("("))
    while not closed and end + 1 < len(lines) and end - start < 40:
        end += 1
        text = text.rstrip() + " " + lines[end].strip()
        raw, closed = _balanced_after(text, text.index("("))
    if not closed:
        # Unclosed even after forty lines: this is prose that looked like a
        # call, not a signature. **Reading nothing is better than reading a
        # fragment**, and the fragment is what reports everything as drift.
        return None

    kind = match.groupdict().get("kind") or "call"
    return end, Signature(
        name=name,
        kind=kind,
        params=documented_params(raw),
        line=start + 1,
        text=lines[start].strip(),
    )


def index_source(source: str, *, suffix: str = ".py") -> Index:
    """Every signature ``source`` declares, by AST.

    **AST and not a regex, and this is the project's own standing rule**: a
    detector that reads Python's own structures has to answer at both ends of
    the supported matrix, and the token stream differs between them. An f-string
    is one ``STRING`` token at the floor and not one at all from 3.12.
    """
    index = Index()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return index
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index.add(Signature(
                name=node.name, kind="def",
                params=_declared_params(node.args), line=node.lineno,
            ))
        elif isinstance(node, ast.ClassDef):
            bases = tuple(ast.unparse(base) for base in node.bases)
            index.add(Signature(
                name=node.name, kind="class",
                params=tuple((base, "") for base in bases), line=node.lineno,
            ))
    return index


def _declared_params(args: ast.arguments) -> tuple[tuple[str, str], ...]:
    """Parameter names in declaration order, each with its default rendered.

    **A keyword-only argument with no default is required**, and
    ``kw_defaults[i] is None`` is what says so. Reading *keyword-only* as
    *defaulted* is what made this project report 55 findings where there was
    one -- the first of five corrections this module's measurement needed, and
    the reason each is written down here rather than only in the probe.
    """
    named = args.posonlyargs + args.args
    out: list[tuple[str, str]] = []
    defaulted = len(args.defaults)
    for position, argument in enumerate(named):
        offset = position - (len(named) - defaulted)
        default = args.defaults[offset] if offset >= 0 else None
        out.append((argument.arg, ast.unparse(default) if default else ""))
    for argument, default in zip(args.kwonlyargs, args.kw_defaults, strict=True):
        rendered = ast.unparse(default) if default is not None else ""
        out.append((argument.arg, rendered))
    if args.vararg:
        out.append((args.vararg.arg, ""))
    if args.kwarg:
        out.append((args.kwarg.arg, ""))
    return tuple(out)
