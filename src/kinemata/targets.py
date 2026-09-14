"""Resolving the ``module:attribute`` a config names. Lookup only; no policy.

Two mechanisms let a project name its own code in a declaration, because two
questions turned out to be the project's own model rather than this package's:
how a call becomes an identifier (:mod:`kinemata.interpose`) and what a rule
over a project's own declaration claims (:mod:`kinemata.shape`). Both need the
same three lines of import-and-getattr, and both need it to fail the same way.

**It lives here rather than in either of them** so that neither has to import
the other to get it. A shape rule failing to resolve should not raise an
interposition's error type, and a second spelling of these three lines is the
duplication this package reports in other people's trees.

⚑ **The form is explicit and never discovered.** One module and one attribute
in it, so the code a config causes to run is readable in the diff that adds it
-- the rule ``[[registry]]``'s ``target`` follows and for the same reason. No
scan of the tree, no entry points, no guessing from a package name.

**What is deliberately NOT a caller.** :func:`kinemata.config._build_import`
resolves a registry class and keeps its own three lines, because it runs at
**config load** and must raise ``ConfigError``: a config naming a class that is
not there is a file to refuse, while a target that fails here is a *run* to
report as blocked. That is the same split ``_build_funnels`` draws when it
checks a target's shape without resolving it.
"""

from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any

#: How a target is spelled. The attribute may be dotted -- a method on a class
#: is the motivating case, since the funnel an adopter names is one.
TARGET_FORM = 'target = "package.module:ClassName.method"'


class TargetError(Exception):
    """A target that cannot be resolved as written."""


@dataclass(frozen=True)
class Target:
    """What a target names: the thing, and where it is attached.

    ``owner`` and ``name`` are here for a caller that means to *replace* the
    value -- :class:`kinemata.interpose.Census` patches and must put the
    original back. A caller that only means to call it reads :attr:`value`.

    **A named field rather than a tuple**, because the one call site that
    wanted only the value indexed a three-tuple to get it, and ``[2]`` does not
    say what it took.
    """

    owner: Any
    name: str
    value: Any


def resolve(target: str) -> Target:
    """Import what *target* names and return it, or raise :class:`TargetError`.

    Resolved when a caller asks, never when a config loads, and the distinction
    is not cosmetic: importing the project's own modules is a thing to do inside
    the project's own run, not inside every ``kinemata check``. The config checks
    the *shape* of a target; this resolves it, and a failure belongs to the run.

    **The value must be callable.** Both callers name a function -- a funnel to
    patch, a predicate to ask -- and a target that resolved to a string would
    fail later, at a call, with nothing saying the config was wrong.
    """
    module_name, _, attribute = target.partition(":")
    if not module_name.strip() or not attribute.strip():
        raise TargetError(f"{target!r} is not a target. Write {TARGET_FORM}.")
    try:
        owner: Any = importlib.import_module(module_name.strip())
    # Importing runs the project's module, so anything can come back out of it.
    except Exception as exc:
        raise TargetError(
            f"cannot import {module_name!r} for target {target!r}: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    parts = attribute.strip().split(".")
    for step in parts[:-1]:
        if not hasattr(owner, step):
            raise TargetError(f"{target!r}: {step!r} is not there")
        owner = getattr(owner, step)
    name = parts[-1]
    if not hasattr(owner, name):
        raise TargetError(f"{target!r}: {name!r} is not there")
    value = getattr(owner, name)
    if not callable(value):
        raise TargetError(
            f"{target!r} names a {type(value).__name__}, not a callable"
        )
    return Target(owner=owner, name=name, value=value)
