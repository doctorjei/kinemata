"""Separating code from prose about code.

A bypass is a *literal in executable code*. The same characters in a comment or
a docstring are documentation, and flagging them is the over-reporting failure:
escalation fires on nearly every file, the reader learns the list is usually
noise, and the mechanism is disabled by being ignored.

This is not hypothetical. Scanning kanibako-cli for the literal ``workset.yaml``
finds 50 sites; 42 of them are comments and docstrings. The 8 that matter are
invisible in that list.

Blanking rather than deleting keeps line numbers stable, so a reported line
number still points at the right line in the real file.
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
import warnings
from collections.abc import Iterator
from contextlib import contextmanager


@contextmanager
def reading_foreign_source() -> Iterator[None]:
    """Suppress warnings *about the scanned project* while we read it.

    Python raises ``SyntaxWarning`` at parse time for an invalid escape
    sequence, and attributes it to whoever called the parser -- which is us.
    Running over httpie, whose own source has several, put ten warning lines in
    the middle of a report about httpie's duplication. **A foreign project's
    lint is not our finding**, and this is not a compiler.

    Found by pointing the tool at code this project did not write; it never
    surfaced on the original corpus, because that author's code is
    warning-clean.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", SyntaxWarning)
        yield


def parsed(source: str) -> ast.Module:
    """``ast.parse`` under :func:`reading_foreign_source`."""
    with reading_foreign_source():
        return ast.parse(source)


def evaluated(literal: str) -> object:
    """``ast.literal_eval`` under the same rule, and the site that mattered.

    The first pass at this replaced every ``ast.parse`` and missed here, because
    ``literal_eval`` parses without saying so. A string literal is precisely
    where an invalid escape sequence lives, so this was the call actually
    producing the noise -- and the test written for the fix is what caught the
    fix being incomplete.
    """
    with reading_foreign_source():
        return ast.literal_eval(literal)

def python_code_only(source: str) -> str:
    """Return ``source`` with comments and docstrings blanked out.

    Other string literals survive -- they are exactly what a bypass looks like.
    On a syntax error the source is returned unchanged: a file this cannot parse
    is better over-reported than silently skipped.
    """
    lines = source.splitlines()
    if not lines:
        return source

    blanked = list(lines)

    # Comments: blank from the '#' to end of line, keeping any code before it.
    try:
        tokens = tokenize.generate_tokens(io.StringIO(source).readline)
        for token in tokens:
            if token.type == tokenize.COMMENT:
                row, col = token.start
                if 0 < row <= len(blanked):
                    blanked[row - 1] = blanked[row - 1][:col]
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass

    # Docstrings: blank every line they span.
    try:
        tree = parsed(source)
    except SyntaxError:
        return "\n".join(blanked)

    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for node in ast.walk(tree):
        if not isinstance(node, holders):
            continue
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        start = value.lineno
        end = getattr(value, "end_lineno", start) or start
        for row in range(start, end + 1):
            if 0 < row <= len(blanked):
                blanked[row - 1] = ""

    return "\n".join(blanked)


def python_strings_only(source: str) -> str:
    """Return ``source`` with everything blanked *except* string literals.

    The sharpest filter for a value bypass, because a value bypass is always a
    string literal. Without it, an antipattern like ``box_data`` also matches
    the identifier ``box_data`` -- and the lines that name a variable after the
    thing are usually the lines that use the constant *correctly*. Measured on
    kanibako-cli, that single confusion accounts for most false positives.

    Docstrings are dropped with the rest of the prose; other literals survive
    whole, so a value embedded in a longer string
    (``"@meta.workset.path/workset.yaml"``) is still found.
    """
    lines = source.splitlines()
    if not lines:
        return source

    docstring_rows: set[int] = set()
    try:
        tree = parsed(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        for node in ast.walk(tree):
            if not isinstance(node, holders):
                continue
            body = getattr(node, "body", None)
            if not body or not isinstance(body[0], ast.Expr):
                continue
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                end = getattr(value, "end_lineno", value.lineno) or value.lineno
                docstring_rows.update(range(value.lineno, end + 1))

    blanked = [" " * len(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source  # unparseable: over-report rather than skip

    for token in tokens:
        if token.type not in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)):
            continue
        start_row, start_col = token.start
        if start_row in docstring_rows:
            continue
        for offset, piece in enumerate(token.string.splitlines()):
            row = start_row + offset
            if not (0 < row <= len(blanked)):
                continue
            col = start_col if offset == 0 else 0
            line = blanked[row - 1]
            blanked[row - 1] = line[:col] + piece + line[col + len(piece):]

    return "\n".join(blanked)


def python_string_literals(source: str) -> list[tuple[int, str, str]]:
    """Every non-docstring string literal, as ``(line, content, full_line)``.

    Knowing where a literal *ends* is what separates a bypass from a coincidence.
    ``WORKSPACES_PATH = "workspaces"`` is bypassed by the literal
    ``"workspaces"``, but ``"workset.workspaces"`` is a settings key that merely
    contains those characters -- a different namespace, which the corpus flags
    as its own hazard ("the same string for different namespaces ... nothing
    kept them apart but convention").
    """
    lines = source.splitlines()
    if not lines:
        return []

    docstring_rows: set[int] = set()
    try:
        tree = parsed(source)
    except SyntaxError:
        tree = None
    if tree is not None:
        holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        for node in ast.walk(tree):
            if not isinstance(node, holders):
                continue
            body = getattr(node, "body", None)
            if not body or not isinstance(body[0], ast.Expr):
                continue
            value = body[0].value
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                end = getattr(value, "end_lineno", value.lineno) or value.lineno
                docstring_rows.update(range(value.lineno, end + 1))

    found: list[tuple[int, str, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []

    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        row = token.start[0]
        if row in docstring_rows:
            continue
        try:
            content = evaluated(token.string)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(content, str):
            continue
        line_text = lines[row - 1] if 0 < row <= len(lines) else ""
        found.append((row, content, line_text))
    return found


def python_message_skeletons(source: str) -> list[tuple[int, str, str]]:
    """Every f-string as ``(line, skeleton, full_line)``, interpolations as ``{}``.

    ``python_string_literals`` cannot see f-strings at all: it resolves a token
    with ``literal_eval``, which refuses them. That is correct for bypass
    detection, where the question is whether a *value* was respelled -- but it
    hides almost every user-facing message in modern Python, and duplicated
    messages are a large share of the undeclared-literal failure.

    Evidence: kento-core ``e84b9504`` harmonized three resolver messages that
    were each ``f"Error: no {thing} named '{name}'"``. Compared as raw tokens
    they share nothing useful; compared as skeletons they are near-identical.

    Deliberately a separate function rather than a change to
    ``python_string_literals``, whose behavior the validated bypass scan depends
    on. A blind spot in a new check is cheaper than a regression in a measured
    one.
    """
    try:
        tree = parsed(source)
    except SyntaxError:
        return []
    lines = source.splitlines()

    found: list[tuple[int, str, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        parts: list[str] = []
        for piece in node.values:
            if isinstance(piece, ast.Constant) and isinstance(piece.value, str):
                parts.append(piece.value)
            else:
                parts.append("{}")
        skeleton = "".join(parts)
        row = node.lineno
        line_text = lines[row - 1] if 0 < row <= len(lines) else ""
        found.append((row, skeleton, line_text))
    return found


def python_annotation_strings(source: str) -> set[str]:
    """String literals used as type annotations, by AST position not by shape.

    A forward reference is quoted code, not a value: ``"Path | None"`` in six
    modules is six modules importing the same type, and reporting it as repeated
    text is noise on a scale that hides the real findings. Measured on
    kanibako-cli, annotations were the largest single source of false clusters.

    Recognized structurally, the way docstrings are, because the shape test
    ("looks like a type") also matches real messages -- and a filter that guesses
    is a filter that eventually drops something that mattered.
    """
    try:
        tree = parsed(source)
    except SyntaxError:
        return set()

    found: set[str] = set()

    def collect(node: ast.AST | None) -> None:
        if node is None:
            return
        for child in ast.walk(node):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                found.add(child.value)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            collect(node.returns)
            args = node.args
            for arg in (*args.posonlyargs, *args.args, *args.kwonlyargs,
                        args.vararg, args.kwarg):
                if arg is not None:
                    collect(arg.annotation)
        elif isinstance(node, ast.AnnAssign):
            collect(node.annotation)
    return found


#: Filters by file suffix. A language with no filter is scanned raw, which
#: over-reports rather than under-reports -- the safe direction for a catch.
FILTERS = {".py": python_code_only}

#: An inline code span, with the run of backticks that opens it matched by an
#: equal run closing it. A single-backtick pattern reads ``x`` as two empty
#: spans and leaves the word between them exposed -- which it did, on this
#: module's own docstrings, in reST where the double form is the normal one.
#:
#: Bounded to one line, so a fenced block is not read as one enormous span.
#: Fences stay checked on purpose: a spelling inside an example is still the
#: project's prose, and an exemption that grows to cover examples covers most
#: documents.
CODE_SPAN = re.compile(r"(`+)[^`\n]*\1")


def outside_code_spans(source: str) -> str:
    """Return ``source`` with inline ``code spans`` blanked.

    Mention versus use, for a registry whose antipatterns are *spellings*. A
    note recording that ``recognisable`` was corrected has to spell the word to
    say what was corrected, and reading that as a violation makes the record of
    a fix indistinguishable from the fix's absence.

    Backticks are the marker because a word genuinely misspelled in prose is not
    in a code span -- so the exemption cannot swallow the case the check exists
    for. Fenced blocks are deliberately still checked: a spelling inside an
    example is still the project's prose.
    """
    return CODE_SPAN.sub(lambda match: " " * len(match.group(0)), source)


#: Literals that are quoted *code* rather than values, by suffix.
ANNOTATION_STRINGS = {".py": python_annotation_strings}

#: Filters for antipatterns that are *spellings*. Language-independent: a
#: backticked token is a mention in markdown and in a docstring alike.
PROSE_FILTERS = {".md": outside_code_spans, ".py": outside_code_spans}

#: f-string skeletons, for comparing messages rather than values.
MESSAGE_SKELETONS = {".py": python_message_skeletons}

#: Literal extractors by suffix, used for strong/weak classification.
LITERAL_EXTRACTORS = {".py": python_string_literals}

#: Stricter filters, for antipatterns that describe a *value* rather than a
#: code shape. Selected with ``scan(..., strings_only=True)``.
STRING_FILTERS = {".py": python_strings_only}
