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
from collections.abc import Iterable, Sequence
from pathlib import Path

from ..contract import BaseRegistry, Entry
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
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name):
                continue
            name = target.id
            if not _is_constant_name(name):
                continue
            if name.startswith("_") and not self._include_private:
                continue
            value = node.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
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
