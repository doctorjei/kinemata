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


#: Nodes a docstring can be the first statement of. Declared once and read once,
#: by :func:`docstring_rows`. Three functions here carried their own copy of
#: that walk and a fourth was about to make it four; they had not diverged, and
#: consolidating them costs less than re-checking that they still agree -- which
#: is the argument this package makes about every other project's constants.
DOCSTRING_HOLDERS = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def docstring_rows(tree: ast.Module) -> set[int]:
    """Every line a docstring occupies, by AST position rather than by shape.

    Structural, the way :func:`python_annotation_strings` is: a triple-quoted
    string is not a docstring because of how it is quoted, it is one because of
    where it sits. The shape test admits any long literal.
    """
    rows: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, DOCSTRING_HOLDERS):
            continue
        body = getattr(node, "body", None)
        if not body or not isinstance(body[0], ast.Expr):
            continue
        value = body[0].value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            end = getattr(value, "end_lineno", value.lineno) or value.lineno
            rows.update(range(value.lineno, end + 1))
    return rows


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

    for row in docstring_rows(tree):
        if 0 < row <= len(blanked):
            blanked[row - 1] = ""

    return "\n".join(blanked)


def python_prose_only(source: str) -> str:
    """Return ``source`` with everything blanked *except* docstrings and comments.

    The mirror of :func:`python_code_only`, and it exists because ``claims``
    could not see documentation that lives in code. A project declares which
    documents to falsify by suffix, and while that list said ``.md`` alone, a
    path cited in a docstring was outside the scan -- in a codebase whose
    convention is that a docstring names the incident or measurement that forced
    the design. Two module docstrings, ``contract.py`` and ``projection.py``,
    sent the reader to a design document at a path holding nothing but a note
    that the design had moved to ``docs/design.md``. Two dead references, in the
    two files a reader opens first, with every gate green.

    **A string literal is not a citation.** The reason this is a filter rather
    than a suffix added to the scan is that a Python file is mostly not prose: a
    path in a default value, a fixture, or an embedded workflow template is a
    *value* the code uses, and reading it as an assertion about the tree is the
    over-reporting failure. Measured on this repository, scanning ``.py`` whole
    read one line of executable code -- an adapter indexing a table -- as a
    markdown link and reported its target as a dead path.

    Docstrings are located structurally, so a long literal is not promoted to
    documentation by being triple-quoted; see :func:`docstring_rows`.

    On a syntax error the source is returned unchanged, matching
    :func:`python_code_only`: over-reporting is the safe direction, and a file
    this cannot parse is better read whole than silently skipped.

    Blanked in place rather than dropped, so a claim's reported line number
    still points at the right line in the real file.
    """
    lines = source.splitlines()
    if not lines:
        return source
    try:
        tree = parsed(source)
    except SyntaxError:
        return source

    kept = [" " * len(line) for line in lines]
    for row in docstring_rows(tree):
        if 0 < row <= len(kept):
            kept[row - 1] = lines[row - 1]

    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            row, col = token.start
            if 0 < row <= len(kept):
                line = kept[row - 1]
                kept[row - 1] = (
                    line[:col] + token.string + line[col + len(token.string):]
                )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass

    return "\n".join(kept)


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

    try:
        tree = parsed(source)
    except SyntaxError:
        tree = None
    prose_rows = docstring_rows(tree) if tree is not None else set()

    blanked = [" " * len(line) for line in lines]
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return source  # unparseable: over-report rather than skip

    for token in tokens:
        if token.type not in (tokenize.STRING, getattr(tokenize, "FSTRING_MIDDLE", -1)):
            continue
        start_row, start_col = token.start
        if start_row in prose_rows:
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

    try:
        tree = parsed(source)
    except SyntaxError:
        tree = None
    prose_rows = docstring_rows(tree) if tree is not None else set()

    found: list[tuple[int, str, str]] = []
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(source).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return []

    for token in tokens:
        if token.type != tokenize.STRING:
            continue
        row = token.start[0]
        if row in prose_rows:
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


#: An opening or closing code fence: three or more backticks or tildes, and
#: whatever else the line carries. Indentation is matched and then ignored --
#: see :func:`outside_fenced_blocks` for why CommonMark's three-space limit is
#: not applied.
FENCE = re.compile(r"^[ \t]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")

#: The fence character whose info string may not contain it. CommonMark says so
#: of backticks and not of tildes, and the asymmetry is load-bearing here: it is
#: what keeps a sentence *about* fences from opening one.
BACKTICK = "`"


def outside_fenced_blocks(source: str) -> str:
    """Return ``source`` with fenced code blocks blanked, fence lines included.

    Shown syntax read as used syntax. A fence is the one place a document
    declares *this text is being displayed, not spoken*, which is the same
    mention-versus-use distinction :func:`outside_code_spans` draws for inline
    spans -- and the case where it bites hardest is a document specifying a
    notation, because specifying a notation means writing a whole example of it.

    **This is the third time in this repository that a document about a
    mechanism tripped that mechanism.** A byte count in backticks was reported
    as a dead commit; a README paragraph had to be written around its own
    checker; and ``docs/citations.md`` illustrates a reference key inside a
    fence, which the closed-world citation catch read as a citation of a source
    no bibliography declares. Each finding was true as stated and wrong in
    substance, and a project whose own specification cannot be written without
    tripping the check has a check that will be argued with rather than fixed.

    **Invisible rather than reported differently.** A separate "shown" section
    was considered: either it gates, which is the same finding under a new
    heading, or it is advisory -- and an advisory list whose every entry is
    correct by construction is the inert signal this package exists to refuse.
    The reader's action is the same in both spellings: none.

    **Deliberately not offered to the spelling registries.** A misspelling
    inside an example is still the project's prose, and this repository has
    already decided that once, in the other direction: the retired-name check
    fired on a README example and the example was reworded rather than the
    exemption widened. A citation is different in kind -- the notation exists to
    be mechanically unambiguous, so an illustration of it is indistinguishable
    from a use of it by construction, which is not true of a misspelled word.

    **The cost, named: a genuine citation inside a fence goes uncounted.** Real
    documentation does cite from inside code samples -- measured on two outside
    projects, every claim their documents make from inside a fence is a web
    address, and one of them is dead. Wherever this filter is applied, that
    finding is not made. It is applied to citations, where an illustration of
    the notation is indistinguishable from a use of it by construction; it is
    deliberately not applied to ``claims``, which is where the measurement said
    the loss would be real.

    ``unused`` reads whole files and honors no mode, so a fenced citation still
    answers "something mentions this" there. That is the right side to land on,
    since ``unused`` is a review list and the closed-world catch gates -- but it
    is ``unused``'s property rather than a decision taken here, and teaching it
    to honor modes would move the cost without anyone noticing.

    What is recognized, following CommonMark 4.5:

    * Backtick and tilde fences, three characters or more.
    * A closing fence of the same character, at least as long as the opener,
      carrying nothing but whitespace after it. An opener's info string cannot
      close anything.
    * A backtick fence whose info string contains a backtick opens nothing.
    * An unclosed fence runs to the end of the document.

    Two departures, both deliberate:

    **Indentation is not bounded.** CommonMark allows an opener three spaces of
    indentation *relative to its container*, and this does not parse containers,
    so a fence inside a list item is legitimately indented four or more.
    Applying the document-level limit would leave every list-item fence
    unrecognized, which is a common spelling in real documentation. The closing
    fence is unbounded for the same reason and a sharper one: a closer rejected
    on indentation leaves the fence open and blanks the rest of the file, which
    is the largest blast radius available here.

    **An indented four-space block is not treated as code.** Without container
    parsing, four spaces is equally a list continuation, a wrapped paragraph, or
    a nested bullet's body -- all of them prose. Blanking them would stop the
    check on ordinary documents while it still reported clean, which is the
    silent under-reporting ``claims`` already shipped once with its negation
    rule and had to scope back. Over-reporting is the safe direction for a
    catch, and the reader's fix is to put the example in a fence, which is what
    these documents do anyway.

    Blanked in place rather than dropped, so a reported line number still points
    at the right line in the real file.
    """
    lines = source.splitlines()
    kept = list(lines)
    opener: str | None = None
    for index, line in enumerate(lines):
        match = FENCE.match(line)
        if opener is None:
            if match is None:
                continue
            fence = match.group("fence")
            if fence[0] == BACKTICK and BACKTICK in match.group("info"):
                continue
            opener = fence
        elif (
            match is not None
            and match.group("fence")[0] == opener[0]
            and len(match.group("fence")) >= len(opener)
            and not match.group("info").strip()
        ):
            opener = None
        kept[index] = " " * len(line)
    return "\n".join(kept)


#: The role that marks a span as shown rather than asserted. Declared once
#: because it is spelled in three places -- into :data:`ILLUSTRATION`, into the
#: line a run prints when it suppressed something, and into every docstring that
#: uses it -- and a marker whose name is respelled is the failure this package
#: reports on everybody else's constants.
#:
#: ``shown`` rather than a Sphinx role name. Nothing in docutils or Sphinx
#: defines it, so it cannot come to mean something contradictory if this project
#: ever builds documentation; it would need registering, which is three lines.
#: The near misses were all taken and all wrong here: ``literal`` and ``samp``
#: are docutils and Sphinx roles about *rendering*, and ``file`` is Sphinx's
#: role for "this is a filename" -- which is precisely what a real citation is
#: too, so borrowing it would make an illustration and an assertion the same
#: spelling. The word also matches what this module already calls the thing:
#: :func:`outside_fenced_blocks` exists because a fence declares text *shown
#: rather than spoken*.
ILLUSTRATION_ROLE = "shown"

#: An illustration: the role, then the span it names. Built from
#: :data:`CODE_SPAN` rather than respelling the delimiter rule, so the two
#: cannot drift into disagreeing about where a span ends.
#:
#: reStructuredText puts a role before *single* backticks and that is the
#: spelling to write. The run is matched at any length anyway, for the reason
#: :data:`kinemata.claims._BACKTICKED` gives: this codebase spells literals with
#: a doubled delimiter, and a marker that works at one run length while doing
#: nothing at the other is behavior held together by coincidence.
ILLUSTRATION = re.compile(rf":{ILLUSTRATION_ROLE}:" + CODE_SPAN.pattern)


def outside_illustrations(source: str) -> str:
    """Return ``source`` with role-marked illustrations blanked.

    What a fence does for a markdown block, for a span inside a sentence.

    ``claims`` can read docstrings now, and arming it here produces findings
    that are correct prose. Measured 2026-09-11: with ``.py`` declared, 18
    claims under ``src`` do not resolve, and 8 of them are text that *shows* a
    shape rather than citing anything -- a capitalized filename spelling, a link
    target standing for any link target, two phrasings a count pattern has to
    handle, a pair of paths illustrating why a promise is matched by exact
    spelling. That was the largest single class, and the only one a marker can
    reach: the other 10 are true citations to the corpus repositories this
    project validated against, gitignored here and absent from a clean clone. A
    markdown document has a fence for this and ``match_mode`` ``"unfenced"``
    honors it; a docstring had no equivalent, which is the gap this closes.

    **Inline, because every one of those 8 sits mid-sentence.** A fence is
    block-level. Lifting a phrase out of its sentence to satisfy a checker is
    how the checker starts costing the prose, and these are good sentences.

    **A role, because a role is what this codebase already reaches for**: 88 of
    them across ``src`` when this was written -- ``func``, ``data``, ``meth``,
    ``class``, ``attr``, ``mod``. A role says what a span *is*, which is the
    operation needed.

    **One role, not any role.** Skipping every role-prefixed span was the
    tempting rule, on the reasoning that none of the six in use denotes a path
    in this tree. Measured: 0 of those 88 spans carry a claim, so the broad rule
    would silence nothing today *and* settle none of the 8 -- it buys no
    measurable thing. What it costs is the guarantee, because the reasoning is
    only true of the roles in use today: Sphinx's ``doc`` and ``download`` take
    a path in the tree as their target, so "there is a role" would silence
    exactly those the day somebody writes one, and silence them quietly. This
    module has shipped a silent suppression once already and had to scope it
    back; a rule that suppresses real citations is worse than the findings it
    removes.

    **The token inside the span is untouched.** The marker sits outside the
    delimiters, which is not a detail: a stamp placed *inside* backticks changed
    the path it was attached to and the citation stopped resolving. Same trap,
    and the reason the role goes in front rather than a sigil going within.

    **A misspelled role suppresses nothing, loudly.** There is no table of
    recognized roles to typo against -- an unknown role is simply not this one,
    so the span is still read, the claim is still checked, and a dead path still
    goes red. The failure mode of a typo is a finding the author already knows
    how to fix, rather than a claim that quietly stopped being checked.

    **``.py`` only, and that is a decision.** A reStructuredText role renders as
    literal text in markdown, so adopting it there would put checker syntax in
    front of a human reader; and no markdown claim in this tree needs it.
    Markdown's answer to the same problem is the fence, which ``claims``
    deliberately does not honor -- a cost named and measured in
    :func:`outside_fenced_blocks`, not a gap to paper over with a second
    notation. A suffix with no entry is scanned whole, which over-reports rather
    than under-reports.

    **Declared rather than guessed.** ``claims`` already infers illustrations
    from shape -- a one-letter stem, a placeholder word -- and those heuristics
    stay, because a project that never writes this role still gets them. This is
    the other half: the author saying so, rather than the checker inferring it.

    Blanked in place rather than dropped, so a reported line number still points
    at the right line in the real file.
    """
    return ILLUSTRATION.sub(lambda match: " " * len(match.group(0)), source)


#: Literals that are quoted *code* rather than values, by suffix.
ANNOTATION_STRINGS = {".py": python_annotation_strings}

#: Filters for antipatterns that are *spellings*. Language-independent: a
#: backticked token is a mention in markdown and in a docstring alike.
PROSE_FILTERS = {".md": outside_code_spans, ".py": outside_code_spans}

#: A document reduced to the part of it that is documentation, by suffix. Used
#: by ``claims``, whose declared suffixes read as "these files are documents" --
#: true whole of a markdown file and true of only part of a source file. A
#: suffix with no entry here is read whole, which over-reports rather than
#: under-reports: the safe direction for a catch.
DOCUMENTATION_FILTERS = {".py": python_prose_only}

#: Documents minus what they merely *show*. Selected by ``match_mode``
#: ``"unfenced"``, and markdown only: the fence is a markdown construct, and a
#: language with no entry here is scanned whole, which over-reports rather than
#: under-reports.
UNFENCED_FILTERS = {".md": outside_fenced_blocks}

#: Documents minus the spans they merely *show*, marked inline with the
#: illustration role. Applied by ``claims`` after
#: :data:`DOCUMENTATION_FILTERS`, since a role means nothing outside prose.
#: ``.py`` only -- see :func:`outside_illustrations` for why markdown is left
#: out on purpose.
ILLUSTRATION_FILTERS = {".py": outside_illustrations}

#: f-string skeletons, for comparing messages rather than values.
MESSAGE_SKELETONS = {".py": python_message_skeletons}

#: Literal extractors by suffix, used for strong/weak classification.
LITERAL_EXTRACTORS = {".py": python_string_literals}

#: Stricter filters, for antipatterns that describe a *value* rather than a
#: code shape. Selected with ``scan(..., strings_only=True)``.
STRING_FILTERS = {".py": python_strings_only}
