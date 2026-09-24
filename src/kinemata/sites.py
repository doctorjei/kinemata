"""Where a name is defined in a Python module -- a ``home`` narrower than a file.

A ``home`` fragment is a file, and a file is usually bigger than a fact. Written
``path::NAME``, it is the **module-level statement binding** ``NAME`` in that
file, however many lines the statement spans, and a match anywhere else in the
file is reported like a match anywhere else in the tree.

**Forced by two adopters on the same day, 2026-09-24, from opposite sides.** One
declared a tuple vocabulary with ``code-patterns`` and found that two of the
three historical re-spellings it existed to catch sat in the home file itself,
so a file ``home`` would have passed the tree they had to fix. The other planted
a same-value literal in a constant's home module and measured it reported by
neither ``check``, which skipped the file, nor ``undeclared``, which had
deferred the value to that constant's registry. **Both were the file-granular
home**, and :class:`~kinemata.adapters.constants.PythonConstants` now records a
site for every entry, since it knows the statement it read the value from.

**A code-patterns site is declared, never inferred from the entry's id.**
Measured on an adopter's config before building: inferring it turned eight
legitimate uses of a name inside its own module into strong findings, because
that entry's antipattern *is* the name.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from functools import lru_cache

from .prose import parsed

#: Separates a ``home`` fragment's file from the name it binds.
SITE = "::"


def split(fragment: str) -> tuple[str, str | None]:
    """A ``home`` fragment as its file and the name it narrows to, if any."""
    path, sep, name = fragment.rpartition(SITE)
    return (path, name) if sep else (fragment, None)


def _unpacked(
    target: ast.Tuple | ast.List, value: ast.expr
) -> Iterator[tuple[str, ast.expr]]:
    """Element-wise ``A, B = "x", "y"``, and only where it is unambiguous.

    A starred element, or a right-hand side that is not a literal sequence of
    matching length, cannot be paired without evaluating it. Nothing is yielded
    in that case: attributing a value to the wrong name would put a real
    constant's antipattern under somebody else's identifier, which reports a
    bypass at a site that never touched it.
    """
    if not isinstance(value, (ast.Tuple, ast.List)):
        return
    if any(isinstance(element, ast.Starred) for element in target.elts):
        return
    if len(target.elts) != len(value.elts):
        return
    for element, item in zip(target.elts, value.elts, strict=True):
        if isinstance(element, ast.Name):
            yield element.id, item


def bindings(node: ast.stmt) -> Iterator[tuple[str, ast.expr]]:
    """Every ``NAME = <expression>`` a module-level statement binds.

    This read ``ast.Assign`` with exactly one plain target and nothing else,
    which is not the whole of how a constant is written. Measured across an
    adopting project's package on 2026-09-09: **195 bare-assign string
    constants were readable and 32 annotated ones were not** -- ``NAME:
    Final[str] = "..."`` is an ``ast.AnnAssign`` -- and the annotated ones
    concentrated in exactly the module that project most wanted to declare. It
    reached for a ``code-patterns`` registry instead of reshaping its source to
    suit the tool. That preference is the right one and the tool should not
    force it.

    Chained targets (``A = B = "x"``) and tuple unpacking are read here for the
    same reason: each is a spelling a project may already use, and being
    invisible to the scan is indistinguishable from being clean.

    **What is still invisible, stated rather than discovered later: enum
    members.** They bind inside a class body, so recognizing them means first
    deciding a class is an enum, and that decision is a base-name match -- which
    an import alias, a project's own intermediate base class, or a metaclass
    defeats without saying so. A recognizer that silently covers some enums and
    not others reports clean over the rest, and a check that quietly stops
    checking is worse than no check. Declare them with ``code-patterns``.
    """
    if isinstance(node, ast.AnnAssign):
        if node.value is not None and isinstance(node.target, ast.Name):
            yield node.target.id, node.value
        return
    if not isinstance(node, ast.Assign):
        return
    for target in node.targets:
        if isinstance(target, ast.Name):
            yield target.id, node.value
        elif isinstance(target, (ast.Tuple, ast.List)):
            yield from _unpacked(target, node.value)


@lru_cache(maxsize=16)
def definitions(source: str) -> dict[str, tuple[int, int]]:
    """Each module-level name, with the first and last line of the statement
    binding it.

    An assignment as :func:`bindings` reads one, plus ``def`` and ``class``,
    which bind a name as surely and are what a helper's home usually is. The
    **first** binding wins: a later rebinding of the same name is a second
    spelling, which is what a site exists to leave visible. Source that does
    not parse defines nothing, so no line of it is exempt.

    Cached, because a scan asks once per entry and a constants module is home
    to every entry it declares. The mapping is shared; callers only read it.
    """
    try:
        tree = parsed(source)
    except (SyntaxError, ValueError):
        return {}
    found: dict[str, tuple[int, int]] = {}
    for node in tree.body:
        span = (node.lineno, node.end_lineno or node.lineno)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # A decorator is part of the statement; ``lineno`` is the ``def``.
            first = min([span[0], *(d.lineno for d in node.decorator_list)])
            found.setdefault(node.name, (first, span[1]))
            continue
        for name, _ in bindings(node):
            found.setdefault(name, span)
    return found
