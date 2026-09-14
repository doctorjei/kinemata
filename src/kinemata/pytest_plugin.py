"""The runner half of :mod:`kinemata.interpose`: hooks, a marker, an exit code.

Deliberately thin, and deliberately separate. Everything that decides anything
is in :mod:`kinemata.interpose`, which imports no pytest -- so the mechanism is
testable without a nested session and usable from a runner that is not pytest.
What is here is the four events a session has that a mechanism cannot invent:
when to patch, what the running test declared, when to drain, and when to stop.

**Not registered as a ``pytest11`` entry point, on purpose.** A project opts in::

    # conftest.py
    pytest_plugins = ["kinemata.pytest_plugin"]

or ``-p kinemata.pytest_plugin``. Auto-loading a plugin that monkey-patches the
project's own classes into every environment that merely installs kinemata is a
thing to be asked for rather than defaulted into, and keeping the entry point
out is also what keeps pytest out of this package's runtime dependencies.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import CONFIG_NAMES, ConfigError, find_config, load
from .interpose import (
    SESSION,
    Census,
    Crossing,
    Identifier,
    Session,
    Watch,
    append,
    recorded,
)
from .targets import resolve

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pytest

#: What a test uses to say it will write an undeclared identifier on purpose.
#: Namespaced, because pytest's marker namespace is global and a project's own
#: ``undeclared`` marker is not this one.
MARKER = "kinemata_undeclared"

MARKER_HELP = (
    f"{MARKER}(*identifiers, reason=...): this test writes these undeclared "
    "identifiers on purpose, because it exercises a refusal. Each one must "
    "actually be written undeclared or the run fails."
)

_censuses: list[Census] = []
_session = Session()
_declared: set[str] = set()
_errors: list[str] = []
_finalized = False
#: The config's root, for resolving a declared `record` path. Held because the
#: settings are read once at configure and the write happens at the end.
_root: Path | None = None


def _install(config_path: Path) -> None:
    """Build a census per declared funnel. A refusal is recorded, not raised."""
    global _root
    settings = load(config_path)
    _root = settings.root
    by_name = {item.name: item for item in settings.registries}
    for funnel in settings.funnels:
        registry = by_name.get(funnel.registry)
        if registry is None:
            _errors.append(
                f"[[interpose]] names registry {funnel.registry!r}, which this "
                "config does not declare here"
            )
            continue
        try:
            identify = resolve(funnel.identify).value
        except Exception as exc:
            _errors.append(f"{funnel.target}: identify {funnel.identify!r}: {exc}")
            continue
        census = Census(funnel, registry, identify)
        census.install()
        _censuses.append(census)


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", MARKER_HELP)
    if _censuses:
        return
    found = find_config()
    if found is None:
        # Nothing to be silent about: a project that loaded this plugin and has
        # no config has made a mistake worth naming, and the terminal summary
        # is where it will be seen.
        _errors.append(
            f"no {CONFIG_NAMES[0]} found searching upward from the working directory"
        )
        return
    try:
        _install(found.resolve())
    except ConfigError as exc:
        _errors.append(str(exc))


def pytest_runtest_setup(item: pytest.Item) -> None:
    """Arm before fixtures run: a fixture's write is as much the test's as its own."""
    names = set()
    for mark in item.iter_markers(name=MARKER):
        names.update(str(arg) for arg in mark.args)
    for census in _censuses:
        census.arm(names)


def pytest_runtest_call(item: pytest.Item) -> None:
    """Register declarations only once the test actually runs.

    Not at setup. A skipped or setup-errored test never got the chance to write
    what it declared, and reporting its identifiers as unused would fail a run
    over a test that did not execute.
    """
    for mark in item.iter_markers(name=MARKER):
        _declared.update(str(arg) for arg in mark.args)


def pytest_runtest_teardown(item: pytest.Item) -> None:
    for census in _censuses:
        census.drain()
        census.arm(())


def _write(declared: list[tuple[str, Watch]]) -> None:
    """Append each declared artifact, or record why it did not happen.

    **A declared record that silently did not get written is the inert signal
    this package exists to report**, so a failure here lands in the session's
    errors and fails the run, the way a blocked oracle does. The cost is a run
    that can go red because a directory is unwritable; the alternative is a
    project believing it has a cross-process record of a suite it does not.

    Relative to the config's root, not the working directory: a shard runs each
    process from wherever its runner happens to be, and a path resolved against
    the cwd would scatter one suite's rows across the filesystem.
    """
    if not any(path for path, _ in declared):
        return
    for path, payload in recorded(declared, SESSION, sys.argv).items():
        target = Path(path)
        if not target.is_absolute():
            target = (_root or Path.cwd()) / target
        try:
            append(target, payload)
        except OSError as exc:
            _errors.append(
                f"record {path!r}: {type(exc).__name__}: {exc}. The funnel was "
                "watched and judged; only the durable copy is missing."
            )


def _finish() -> Session:
    """Drain, unpatch and settle -- once, however many hooks ask for it.

    Three hooks want the answer and any of them may be the last to run, so the
    work is idempotent rather than assigned to whichever one usually fires
    first. Guessing that would leave the class patched on the run where the
    guess was wrong.
    """
    global _session, _finalized
    if _finalized:
        return _session
    _finalized = True
    watches: list[Watch] = []
    exercised: set[str] = set()
    declared_records: list[tuple[str, Watch]] = []
    for census in _censuses:
        census.drain()
        census.uninstall()
        watch = census.watch()
        watches.append(watch)
        declared_records.append((census.funnel.record, watch))
        exercised |= census.exercised
    _write(declared_records)
    _session = Session(
        watches=tuple(watches),
        declared_by_tests=frozenset(_declared),
        exercised=frozenset(exercised),
        errors=tuple(_errors),
    )
    return _session


def pytest_terminal_summary(terminalreporter: Any) -> None:
    session = _finish()
    if not session.watches and not session.errors:
        return
    write = terminalreporter.write_line
    write("")
    write("kinemata interpose:")
    for line in session.lines():
        write(f"  {line}")
    for line in session.errors:
        write(f"  ERROR: {line}")
    if session.findings:
        write(
            f"  FAIL: {len(session.findings)} identifier(s) written that nothing "
            "declares. Either stop writing them or declare them; a test that "
            f"means to write one says so with @pytest.mark.{MARKER}."
        )


def pytest_sessionfinish(session: Any, exitstatus: Any) -> None:
    """Fail the run. This is the enforcement, and the report alone is not it."""
    result = _finish()
    # Escalate from clean only. Overwriting an interrupted or nothing-collected
    # status would relabel a run that never got far enough to observe anything.
    if result.failed and session.exitstatus == 0:
        session.exitstatus = 1


def pytest_unconfigure(config: pytest.Config) -> None:
    """Belt and braces: nothing may be left patched, whatever else happened."""
    for census in _censuses:
        census.uninstall()


def reset() -> None:
    """Drop all session state. For this package's own tests, and theirs.

    A module-global census is what a pytest plugin is; testing one in-process
    means being able to put it back. Published rather than reached into, so a
    project driving the plugin from its own harness is not depending on the
    spelling of a private name.
    """
    global _session, _finalized, _root
    for census in _censuses:
        census.uninstall()
    _censuses.clear()
    _declared.clear()
    _errors.clear()
    _session = Session()
    _finalized = False
    _root = None


__all__ = ["MARKER", "Crossing", "Identifier", "reset"]
