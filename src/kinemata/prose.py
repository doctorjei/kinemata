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
import tokenize


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
        tree = ast.parse(source)
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
        tree = ast.parse(source)
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
        (start_row, start_col), (end_row, _) = token.start, token.end
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
        tree = ast.parse(source)
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
            content = ast.literal_eval(token.string)
        except (ValueError, SyntaxError):
            continue
        if not isinstance(content, str):
            continue
        line_text = lines[row - 1] if 0 < row <= len(lines) else ""
        found.append((row, content, line_text))
    return found


#: Filters by file suffix. A language with no filter is scanned raw, which
#: over-reports rather than under-reports -- the safe direction for a catch.
FILTERS = {".py": python_code_only}

#: Literal extractors by suffix, used for strong/weak classification.
LITERAL_EXTRACTORS = {".py": python_string_literals}

#: Stricter filters, for antipatterns that describe a *value* rather than a
#: code shape. Selected with ``scan(..., strings_only=True)``.
STRING_FILTERS = {".py": python_strings_only}
