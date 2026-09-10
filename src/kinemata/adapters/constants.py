"""Constants as a registry, with antipatterns derived from their own values.

The corpus evidence points straight here. In kanibako-cli the canonical thing is
``WORKSET_META_FILE = "workset.yaml"``; in kento-core it is ``read_mode()`` and
``run_or_die``. For the constant case the antipattern needs no authoring at all:
**a constant's value is exactly the spelling that means it was bypassed.**

That matters for adoption. A project points at the module holding its canonical
constants and gets a working registry with no per-entry configuration -- which
is the difference between a mechanism people turn on and one they mean to.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Iterator, Sequence
from pathlib import Path

from ..contract import _NAME_BOUNDARY, BaseRegistry, Entry
from ..prose import parsed

#: Below this, a value is matched **only as a whole literal**. ``"box_data"``
#: is worth finding inside a longer string; ``"GET"`` is not, because it is a
#: substring of half the tree and the noise would bury the real findings.
MIN_VALUE_LENGTH = 4

#: Below *this*, a value gets no antipattern at all, anchored or otherwise.
#: **Set by measurement, not taste.** At 2, kanibako-cli's settings package went
#: from 14 strong findings to 31, and all seventeen were one constant:
#: ``RW_PATH = "rw"``, matching the unrelated mount-binding key in
#: ``bindings["rw"]``. A two-character value collides across namespaces even as
#: a whole literal, which is the noise the original threshold existed to
#: prevent. At 3 the same package is unchanged and httpie's ``HTTP_GET`` is
#: still found.
MIN_ANCHORED_LENGTH = 3

#: Values that are common English or code punctuation regardless of length.
#: Deliberately short -- an over-eager denylist hides real duplication.
GENERIC_VALUES = frozenset({"true", "false", "none", "null", "utf-8", "main"})


def _is_constant_name(name: str) -> bool:
    return name.isupper() or (name.startswith("_") and name[1:].isupper())


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


def _bindings(node: ast.stmt) -> Iterator[tuple[str, ast.expr]]:
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


class PythonConstants(BaseRegistry):
    """Module-level string constants in one or more Python modules.

    :param paths: modules to read constants from.
    :param root: repo root, so ``home`` is recorded repo-relative.
    :param min_length: values shorter than this are not given antipatterns.
    :param include_private: also take ``_LEADING_UNDERSCORE`` constants. Off by
        default -- a private constant is usually deliberately module-local, and
        ``import_reconcile._STANDALONE_BOX_DIR`` (a real duplicate) is found as
        a *bypass* of the public constant, which is the more useful report.
    """

    name = "constants"

    #: A Python constant does not contain a dot; it is *reached* through one.
    #: With the dotted default, ``bootstrap.CHANNELS_PATH`` detected nothing at
    #: all, and an adopting project's four module-qualified constants were
    #: reported as unmentioned on 2026-09-09.
    #:
    #: **The false positive this accepts.** Letting a dot abut means any
    #: attribute access spelled the same way counts: ``settings.CHANNELS_PATH``
    #: on an unrelated object, or a same-named class attribute, is read as a
    #: mention of this constant. Text matching cannot tell those apart -- doing
    #: so means resolving the receiver, which is dataflow analysis and out of
    #: scope here.
    #:
    #: Which direction that errs matters. In
    #: :func:`~kinemata.bypass.unused` a spurious mention *suppresses* a report,
    #: so the cost is a missed finding rather than a false alarm on a live
    #: constant -- the better trade for a list a human reads. It is the wrong
    #: trade for any future check that treats a mention as an accusation, and
    #: such a check should set its own boundary rather than inherit this one.
    #:
    #: This is a **second, separate** cause from the weakness
    #: :func:`~kinemata.bypass.unused` already documents. That one detects
    #: mention rather than use and was measured at 0/3 against a labeled
    #: incident; fixing the boundary does not touch it.
    boundary = _NAME_BOUNDARY

    def __init__(
        self,
        paths: Iterable[str | Path],
        *,
        root: str | Path = ".",
        min_length: int = MIN_VALUE_LENGTH,
        include_private: bool = False,
        generic: frozenset[str] = GENERIC_VALUES,
        closed: bool = False,
    ) -> None:
        self._paths = [Path(p) for p in paths]
        self._root = Path(root)
        self._min_length = min_length
        self._include_private = include_private
        self._generic = generic
        self.closed = closed

    def entries(self) -> Iterable[Entry]:
        for path in self._paths:
            yield from self._entries_in(path)

    def _entries_in(self, path: Path) -> Iterable[Entry]:
        try:
            tree = parsed(path.read_text(errors="ignore"))
        except (OSError, SyntaxError):
            return
        try:
            home = str(path.relative_to(self._root))
        except ValueError:
            home = str(path)

        for node in tree.body:
            for name, value in _bindings(node):
                if not _is_constant_name(name):
                    continue
                if name.startswith("_") and not self._include_private:
                    continue
                if not (
                    isinstance(value, ast.Constant) and isinstance(value.value, str)
                ):
                    continue

                yield Entry(
                    id=name,
                    antipatterns=self._antipatterns_for(value.value),
                    home=(home,),
                    extra={"value": value.value},
                )

    def _antipatterns_for(self, value: str) -> tuple[str, ...]:
        """The value as a pattern, in one of three tiers.

        A short value used to get **nothing**, and nothing is invisible.
        Measured on httpie: it declares ``HTTP_GET = 'GET'`` and
        ``HTTP_POST = 'POST'`` on adjacent lines, a lexer table writes both as
        literals two lines apart, and ``check`` reported POST and said nothing
        about GET -- three characters against a threshold of four. A reader
        seeing one of two identical constructs reported concludes the other is
        fine. **18 of that project's 21 declared entries were in this
        position.**

        The threshold is still right about what it was measuring: ``GET`` as a
        *substring* matches ``target``, ``budget``, ``widget``. What it got
        wrong is treating "cannot be matched loosely" as "cannot be matched".
        Anchoring gives the precise half and drops the noisy half -- a short
        value is reported when a literal *is* that value, and never when a
        literal merely contains it. The weak tier is unavailable to it by
        construction, which is the correct trade rather than a limitation.

        Generic values still get nothing at any length: ``"true"`` is generic in
        meaning, not merely short, and anchoring does not make it a finding.
        """
        if value.lower() in self._generic or len(value) < MIN_ANCHORED_LENGTH:
            return ()
        if len(value) < self._min_length:
            return (rf"\A{re.escape(value)}\Z",)
        return (re.escape(value),)


def constants_from(
    paths: Sequence[str | Path], **kwargs
) -> PythonConstants:
    """Convenience constructor, so a config file line maps to one call."""
    return PythonConstants(paths, **kwargs)
