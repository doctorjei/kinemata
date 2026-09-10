"""Reaching a declared registry from the project's own code, while it runs.

Every other mechanism here reads **source text at rest**, and that is a real
boundary rather than a missing feature -- ``docs/structure.md`` draws it as the
second axis. The first project to adopt this layer inventoried its 326-check
conformance suite against the tool on 2026-09-09 and found 291 of the checks,
89%, not expressible. Their largest single item was exactly the shape nothing
static can see: a session-wide interposition on a key-store write funnel,
judging every key path written during a test run.

This module is the complement to that boundary, not a way around it. A registry
built from ``kinemata.toml`` is already a live Python object carrying
``declared``, ``resolve`` and ``detect``, so an adopting project's **own** test
suite can consult the declaration while its own code runs::

    from kinemata import registry

    keys = registry("keyspace")
    # ... inside the project's own write funnel, during its own test run:
    assert keys.declared(path), f"{path} is not a declared key"

That was already possible by accident, since the loader and the registry
classes were importable. What is added here is a supported way to say it and a
promise that the names keep working; the surface is held to what such a fixture
actually needs, because a published name cannot be withdrawn later.

**This is not a run-time instrument.** Kinemata does not interpose, instrument,
monitor, trace, or execute any of the project's code. The project's tests do
the importing and the asserting; this package only hands back the declaration
they assert against. The value of the pairing is that the run-time assertion
reads the *same* declared registry the static scan reads, instead of a second
copy of the facts -- a second copy being the failure this package exists to
report. Neither half covers the other.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from .config import CONFIG_NAMES, ConfigError, Settings, find_config, load
from .contract import Registry


class UnknownRegistry(ConfigError):
    """Nothing in the config is declared under that name.

    A subclass rather than a bare ``KeyError`` so a fixture can tell "this
    project does not declare that registry" from "this project's config is
    broken" while ``except ConfigError`` still catches both. Returning ``None``
    was never the alternative: an assertion handed ``None`` reports a clean run
    for a registry that does not exist, which is the inert signal this package
    refuses everywhere else.
    """


@cache
def _loaded(path: Path) -> Settings:
    """One parse of one config per process.

    Cached because of where the caller stands. The adopting case is an
    assertion inside a write funnel, reached once per write for a whole test
    session; re-reading the TOML and rebuilding every adapter per assertion
    would make the pairing too slow to keep, and each rebuild would discard the
    index and detector the registry had already memoized.

    Safe here because a test process does not rewrite its own config mid-run,
    and a caller who needs a fresh read has one already: :func:`load` is
    published alongside this and does not cache.
    """
    return load(path)


def registry(name: str, config: str | Path | None = None) -> Registry:
    """The registry declared as ``name``, ready to answer at run time.

    ``config`` defaults to the nearest config found by searching upward from
    the working directory, which under a test runner is wherever the runner was
    invoked rather than wherever the tests live. Name the path from a fixture
    when that is not reliably the tree meant: the upward walk picking up a
    parent's config is a failure this project has had reported against it, not
    a hypothetical one.

    Two limits are inherited from the registry itself and are easy to forget on
    this side of the boundary. :meth:`~kinemata.contract.Registry.declared`
    answers about what the adapter recognized in the source it was pointed at,
    so it is only ever as good as that data model -- it does not know the
    project's intent. And a registry that cannot recognize its own identifiers
    raises rather than answering, so no path through here degrades into a quiet
    ``False``.
    """
    path = Path(config) if config is not None else find_config()
    if path is None:
        raise ConfigError(
            f"no {CONFIG_NAMES[0]} found (searched upward from the working "
            "directory); pass config= to name one explicitly"
        )
    settings = _loaded(path.resolve())

    # Nothing forbids two declarations sharing a name: every other command
    # iterates the whole list and so never has to ask which one is "keys".
    # Publishing a lookup *by name* is what makes the ambiguity reachable, so
    # it is refused here rather than resolved by declaration order -- picking
    # the first would answer a question that has two answers, and the test
    # asserting against the wrong one would pass.
    matches = [candidate for candidate in settings.registries if candidate.name == name]
    if len(matches) > 1:
        raise ConfigError(
            f"{path}: {len(matches)} registries are declared as {name!r}, so "
            "naming one is ambiguous. Give them distinct names."
        )
    if matches:
        return matches[0]

    known = sorted(candidate.name for candidate in settings.registries)
    detail = f"declared: {', '.join(known)}" if known else "the config declares none"
    # A registry whose adapter recognized nothing is dropped from `registries`
    # and kept in `unfitted`, so "no registry named X" would be true and
    # useless -- the declaration is sitting right there in the file being
    # named. The loader already worded why, so its words are carried through
    # rather than restated.
    unfitted = " ".join(settings.unfitted)
    raise UnknownRegistry(
        f"{path}: no registry named {name!r} ({detail})."
        + (f" {unfitted}" if unfitted else "")
    )
