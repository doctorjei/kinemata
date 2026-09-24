"""Reading shell, YAML and TOML the way ``.py`` is read: comments and literals.

**One rule for every language kinemata can read** (user, 2026-09-24): *a
comment is nothing, a literal that IS a declared value is strong, a literal that
merely contains it is weak* -- which is what a ``.py`` file always got and every
other suffix did not. Before this, a registry pointed at ``.sh``, ``.yaml`` or
``.toml`` read raw lines, so ``# see box.yaml for the format`` was a gating
finding and ``echo "restoring box.yaml.bak"`` was as strong as a real bypass.
An adopting project named it as the reason one of its checks could not migrate
(2026-09-13): theirs exempts YAML comments, and here nothing could.

Each language gives two things, registered by suffix in :mod:`kinemata.prose`:

* ``*_literals(source)`` -- every string the file writes, as
  ``(line, content, full_line)``, the shape
  :func:`~kinemata.prose.python_string_literals` returns;
* ``*_code_only(source)`` -- the source with its comments blanked and every
  line kept, so a finding's line number is the file's.

**A literal is a string as the language writes it.** A Python triple-quoted
string is one literal, so a shell heredoc body, a YAML block scalar and a TOML
multi-line string are one literal each, reported at the line where it starts.
Only strings count, as in Python: a YAML ``8080`` or ``true`` is not one, a
TOML bare key is an identifier. A shell word **is** a string -- ``cp box.yaml
"$DEST"`` spells the value exactly as ``open("box.yaml")`` does -- and a word
is everything between unquoted separators, quoted parts included, so
``--name="box.yaml"`` is the one literal :shown:`--name=box.yaml`. An
assignment's value is its own literal: :shown:`FILE=box.yaml` names
:shown:`box.yaml`.

**Where a reader cannot tell, it keeps the text.** Stripping something that
was content hides a real bypass; keeping a comment that was not recognized
reports one too many. Only the second is safe, so every rule here errs that
way: a ``#`` inside quotes, a heredoc or a block scalar is content, and one not
at the start of a shell word is part of the word.
"""

from __future__ import annotations

import re

Literal = tuple[int, str, str]


# -- shell ---------------------------------------------------------------------

#: Characters that end an unquoted shell word and are not part of any.
_SHELL_SEPARATORS = frozenset(" \t;&|()<>")

#: ``NAME=value`` at the start of a word: the value is the literal.
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _shell(source: str) -> tuple[list[Literal], dict[int, int]]:
    """Every word and heredoc body, and where each line's comment begins.

    Comment columns are keyed by 0-based row. A ``#`` is a comment only
    unquoted and at the start of a word, which is also why ``$#``, ``${#x}``
    and ``a#b`` are not.
    """
    lines = source.split("\n")
    literals: list[Literal] = []
    comments: dict[int, int] = {}

    word = ""
    started = False
    word_row = 0
    quote = ""  # "'" or '"' while inside one
    expect_delimiter: bool | None = None  # strip-tabs flag once `<<` was seen
    pending: list[tuple[str, bool]] = []  # heredocs opened on this line

    def flush(row: int) -> None:
        nonlocal word, started, expect_delimiter
        if started:
            if expect_delimiter is not None:
                pending.append((word, expect_delimiter))
                expect_delimiter = None
            else:
                value = word[_ASSIGNMENT.match(word).end():] if _ASSIGNMENT.match(
                    word
                ) else word
                if value:
                    literals.append((word_row + 1, value, lines[word_row]))
        word, started = "", False

    row = 0
    while row < len(lines):
        line = lines[row]
        col = 0
        while col < len(line):
            char = line[col]
            if quote == "'":
                if char == "'":
                    quote = ""
                else:
                    word += char
            elif quote == '"':
                if char == "\\" and col + 1 < len(line) and line[col + 1] in '"\\$`':
                    word += line[col + 1]
                    col += 1
                elif char == '"':
                    quote = ""
                else:
                    word += char
            elif char in _SHELL_SEPARATORS:
                flush(row)
                if line.startswith("<<", col) and not line.startswith("<<<", col):
                    col += 2
                    strip = line.startswith("-", col)
                    if strip:
                        col += 1
                    expect_delimiter = strip
                    continue
            elif char == "#" and not started:
                comments[row] = col
                break
            else:
                if not started:
                    started, word_row = True, row
                if char in "'\"":
                    quote = char
                elif char == "\\" and col + 1 < len(line):
                    word += line[col + 1]
                    col += 1
                else:
                    word += char
            col += 1
        if quote:
            word += "\n"
        else:
            flush(row)
        row += 1
        # Heredoc bodies follow the line that opened them, in order.
        while pending and not quote:
            delimiter, strip = pending.pop(0)
            start, body = row, []
            while row < len(lines):
                text = lines[row].lstrip("\t") if strip else lines[row]
                row += 1
                if text == delimiter:
                    break
                body.append(text)
            content = "\n".join(body)
            if content:
                literals.append((start + 1, content, lines[start]))
    return literals, comments


def shell_literals(source: str) -> list[Literal]:
    """Every word a shell file writes, and every heredoc body."""
    return _shell(source)[0]


def shell_code_only(source: str) -> str:
    """The shell source with its comments blanked, every line kept."""
    return _blank(source, _shell(source)[1])


# -- YAML ----------------------------------------------------------------------

#: A plain scalar YAML's core schema reads as something other than a string.
_YAML_NOT_STRING = re.compile(
    r"""^(?:~|null|Null|NULL|true|True|TRUE|false|False|FALSE
       |[-+]?[0-9]+|0o[0-7]+|0x[0-9a-fA-F]+
       |[-+]?(?:\.[0-9]+|[0-9]+(?:\.[0-9]*)?)(?:[eE][-+]?[0-9]+)?
       |[-+]?\.(?:inf|Inf|INF)|\.(?:nan|NaN|NAN))$""",
    re.VERBOSE,
)

#: ``|`` or ``>`` with optional chomping and indentation indicators.
_BLOCK_SCALAR = re.compile(r"^[|>][-+0-9]*$")

_YAML_ESCAPES = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "/": "/", "0": "\0"}


def _yaml(source: str) -> tuple[list[Literal], dict[int, int]]:
    """Every string scalar -- keys and values -- and where comments begin."""
    lines = source.split("\n")
    literals: list[Literal] = []
    comments: dict[int, int] = {}

    def emit(row: int, text: str, *, quoted: bool) -> None:
        if quoted or (text and not _YAML_NOT_STRING.match(text)):
            if text:
                literals.append((row + 1, text, lines[row]))

    row = 0
    quote, buffer, quote_row = "", "", 0
    while row < len(lines):
        line = lines[row]
        indent = len(line) - len(line.lstrip(" "))
        col, depth = (0 if quote else indent), 0
        block = False
        while col < len(line):
            char = line[col]
            if quote == "'":
                if char == "'" and line.startswith("''", col):
                    buffer += "'"
                    col += 2
                    continue
                if char == "'":
                    emit(quote_row, buffer, quoted=True)
                    quote, buffer = "", ""
                else:
                    buffer += char
                col += 1
                continue
            if quote == '"':
                if char == "\\" and col + 1 < len(line):
                    buffer += _YAML_ESCAPES.get(line[col + 1], "\\" + line[col + 1])
                    col += 2
                    continue
                if char == '"':
                    emit(quote_row, buffer, quoted=True)
                    quote, buffer = "", ""
                else:
                    buffer += char
                col += 1
                continue
            if char in " \t":
                col += 1
                continue
            if char == "#" and (col == 0 or line[col - 1] in " \t"):
                comments[row] = col
                break
            if col == indent and line.startswith(("---", "..."), col) and (
                len(line) == col + 3 or line[col + 3] in " \t"
            ):
                col += 3
                continue
            if col == 0 and char == "%":
                break  # a directive
            if char in "-?:" and (col + 1 == len(line) or line[col + 1] in " \t"):
                col += 1  # sequence entry, complex key, empty value
                continue
            if char in "[{":
                depth += 1
                col += 1
                continue
            if char in "]},":
                depth = max(depth - 1, 0) if char != "," else depth
                col += 1
                continue
            if char in "&*!":
                while col < len(line) and line[col] not in " \t,[]{}":
                    col += 1
                continue
            if char in "'\"":
                quote, buffer, quote_row = char, "", row
                col += 1
                continue
            token = re.match(r"\S+", line[col:]).group(0)
            if _BLOCK_SCALAR.match(token):
                block = True
                col += len(token)
                continue
            # A plain scalar: up to ": ", " #", end of line, or a flow indicator.
            end = col
            while end < len(line):
                if line.startswith(": ", end) or (
                    line[end] == ":" and end + 1 == len(line)
                ):
                    break
                if line[end] == "#" and line[end - 1] in " \t":
                    break
                if depth and line[end] in ",]}":
                    break
                end += 1
            emit(row, line[col:end].rstrip(), quoted=False)
            col = end
        if quote:
            buffer += " "  # a quoted scalar folds its line breaks
        row += 1
        if block:
            start, body, content_indent = row, [], None
            while row < len(lines):
                text = lines[row]
                if text.strip():
                    this = len(text) - len(text.lstrip(" "))
                    if this <= indent:
                        break
                    content_indent = this if content_indent is None else content_indent
                    body.append(text[content_indent:])
                else:
                    body.append("")
                row += 1
            content = "\n".join(body).strip("\n")
            if content and start < len(lines):
                literals.append((start + 1, content, lines[start]))
    return literals, comments


def yaml_literals(source: str) -> list[Literal]:
    """Every string scalar a YAML file writes, keys included, block scalars whole."""
    return _yaml(source)[0]


def yaml_code_only(source: str) -> str:
    """The YAML source with its comments blanked, every line kept."""
    return _blank(source, _yaml(source)[1])


# -- TOML ----------------------------------------------------------------------

_TOML_ESCAPES = {"b": "\b", "t": "\t", "n": "\n", "f": "\f", "r": "\r", '"': '"',
                 "\\": "\\"}


def _toml_unescape(text: str) -> str:
    def one(match: re.Match[str]) -> str:
        code = match.group(1)
        if code[0] in "uU":
            return chr(int(code[1:], 16))
        if code[0] in " \t\n":  # a line-ending backslash trims the break
            return ""
        return _TOML_ESCAPES.get(code, "\\" + code)

    return re.sub(
        r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|[ \t]*\n\s*|.)", one, text
    )


def _toml(source: str) -> tuple[list[Literal], dict[int, int]]:
    """Every string -- quoted keys and values -- and where comments begin."""
    lines = source.split("\n")
    literals: list[Literal] = []
    comments: dict[int, int] = {}
    index, row, col = 0, 0, 0

    def advance(upto: int) -> None:
        nonlocal index, row, col
        while index < upto:
            if source[index] == "\n":
                row, col = row + 1, 0
            else:
                col += 1
            index += 1

    while index < len(source):
        char = source[index]
        if char == "#":
            comments[row] = col
            newline = source.find("\n", index)
            advance(newline if newline >= 0 else len(source))
            continue
        for opener, basic in (('"""', True), ("'''", False), ('"', True), ("'", False)):
            if source.startswith(opener, index):
                start_row = row
                close = source.find(opener, index + len(opener))
                if len(opener) == 1:
                    close = _toml_line_close(source, index + 1, opener, basic)
                if close < 0:
                    advance(len(source))
                    break
                raw = source[index + len(opener):close]
                if len(opener) == 3 and raw.startswith("\n"):
                    raw = raw[1:]
                content = _toml_unescape(raw) if basic else raw
                if content:
                    literals.append((start_row + 1, content, lines[start_row]))
                advance(close + len(opener))
                break
        else:
            advance(index + 1)
    return literals, comments


def _toml_line_close(source: str, start: int, quote: str, basic: bool) -> int:
    """Where a one-line string ends, or -1 when the line ends first."""
    index = start
    while index < len(source) and source[index] != "\n":
        if basic and source[index] == "\\":
            index += 2
            continue
        if source[index] == quote:
            return index
        index += 1
    return -1


def toml_literals(source: str) -> list[Literal]:
    """Every string a TOML file writes; bare keys, numbers and dates are not."""
    return _toml(source)[0]


def toml_code_only(source: str) -> str:
    """The TOML source with its comments blanked, every line kept."""
    return _blank(source, _toml(source)[1])


# -- shared --------------------------------------------------------------------


def _blank(source: str, comments: dict[int, int]) -> str:
    """Cut each line at its comment column, keeping every line."""
    lines = source.split("\n")
    for row, col in comments.items():
        lines[row] = lines[row][:col].rstrip()
    return "\n".join(lines)
