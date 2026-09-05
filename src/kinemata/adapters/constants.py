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
from pathlib import Path
from typing import Iterable, Sequence

from ..contract import BaseRegistry, Entry

#: Values shorter than this are skipped. ``"/"`` or ``"y"`` as an antipattern
#: matches half the tree; the noise would bury the real findings.
MIN_VALUE_LENGTH = 4

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
            tree = ast.parse(path.read_text(errors="ignore"))
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
        if len(value) < self._min_length or value.lower() in self._generic:
            return ()
        return (re.escape(value),)


def constants_from(
    paths: Sequence[str | Path], **kwargs
) -> PythonConstants:
    """Convenience constructor, so a config file line maps to one call."""
    return PythonConstants(paths, **kwargs)
