"""The run-time surface: the names published, and that they behave.

A published surface with no test is a promise nothing keeps. These names are
what an adopting project's own test fixture imports in order to assert against
a declaration while its code runs -- the complement to the static/dynamic
boundary in ``docs/structure.md``, forced by an adopter whose 326-check suite
inventoried 291 checks, 89%, as not expressible against a scan of source at
rest.

The pin is a *subset* check, not an equality check against ``__all__``. Equality
would fail every time an unrelated mechanism published an unrelated name, which
trains people to edit the test rather than read it. What is being promised is
that these particular names exist and keep working, not that no others do.
"""

from __future__ import annotations

import textwrap

import pytest

import kinemata
from kinemata import ConfigError, Settings, UnknownRegistry, find_config, load, registry

#: The run-time surface. Each of these is a name an adopter may import, and
#: therefore a name that cannot be withdrawn or re-spelled later.
PUBLISHED = (
    "ConfigError",
    "Settings",
    "UnknownRegistry",
    "find_config",
    "load",
    "registry",
)


def write_project(tmp_path, *, closed=False):
    """A minimal adopting tree: one declared registry over one module."""
    (tmp_path / "consts.py").write_text('KEYSPACE_ROOT = "box.vault.keys"\n')
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            root = "."

            [[registry]]
            name = "keyspace"
            kind = "python-constants"
            modules = ["consts.py"]
            closed = {str(closed).lower()}
            """
        ).lstrip()
    )
    return tmp_path / "kinemata.toml"


# -- the names ---------------------------------------------------------------


def test_every_published_name_is_importable_from_the_package_root():
    """The import path is the package, never a submodule.

    An adopter who has to write ``from kinemata.config import load`` is coupled
    to a module layout that is free to change; that is the reaching-into-
    privates the re-export exists to prevent.
    """
    for name in PUBLISHED:
        assert name in kinemata.__all__, f"{name} dropped from __all__"
        assert hasattr(kinemata, name), f"{name} named in __all__ but not bound"


def test_the_published_names_are_the_expected_kinds():
    assert callable(registry)
    assert callable(load)
    assert callable(find_config)
    assert isinstance(Settings, type)
    assert issubclass(UnknownRegistry, ConfigError)


# -- behavior ----------------------------------------------------------------


def test_a_declared_registry_answers_at_run_time(tmp_path):
    """The gesture an adopter's write-funnel interposer makes."""
    config = write_project(tmp_path)
    keys = registry("keyspace", config=config)

    assert keys.name == "keyspace"
    assert keys.declared("KEYSPACE_ROOT")
    assert not keys.declared("KEYSPACE_UNDECLARED")


def test_config_may_be_given_as_a_string(tmp_path):
    config = write_project(tmp_path)
    assert registry("keyspace", config=str(config)).declared("KEYSPACE_ROOT")


def test_the_same_config_is_parsed_once(tmp_path):
    """Identity, not equality: the caller is inside a per-write assertion.

    Re-reading the TOML and rebuilding the adapters once per write would make
    the run-time half too slow to keep, and would discard the index and
    detector the registry had already memoized.
    """
    config = write_project(tmp_path)
    assert registry("keyspace", config=config) is registry("keyspace", config=config)


def test_load_stays_uncached_as_the_escape_hatch(tmp_path):
    """``registry`` caches; ``load`` is published beside it and does not."""
    config = write_project(tmp_path)
    assert load(config) is not load(config)


# -- refusals ----------------------------------------------------------------


def test_an_undeclared_name_refuses_and_says_what_is_declared(tmp_path):
    """Never ``None``. An assertion handed ``None`` reports a clean run."""
    config = write_project(tmp_path)
    with pytest.raises(UnknownRegistry) as caught:
        registry("keyspac", config=config)  # a plausible typo
    message = str(caught.value)
    assert "keyspac" in message
    assert "keyspace" in message, "the refusal must name what is declared"


def test_an_undeclared_name_is_catchable_as_a_config_error(tmp_path):
    config = write_project(tmp_path)
    with pytest.raises(ConfigError):
        registry("absent", config=config)


def test_a_missing_config_refuses_rather_than_returning_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(ConfigError) as caught:
        registry("keyspace")
    assert "kinemata.toml" in str(caught.value)


def test_an_unfitted_registry_is_named_rather_than_reported_absent(tmp_path):
    """The declaration is in the file; "no such registry" would mislead.

    A registry whose adapter recognized nothing is dropped from ``registries``
    and kept in ``unfitted``. Asking for it must repeat the loader's reason,
    not claim it was never declared.
    """
    (tmp_path / "empty.py").write_text("# no module-level constants at all\n")
    config = tmp_path / "kinemata.toml"
    config.write_text(
        textwrap.dedent(
            """
            [[registry]]
            name = "keyspace"
            kind = "python-constants"
            modules = ["empty.py"]
            """
        ).lstrip()
    )
    with pytest.raises(UnknownRegistry) as caught:
        registry("keyspace", config=config)
    assert "produced no entries" in str(caught.value)


def test_two_registries_under_one_name_refuse_rather_than_picking_the_first(tmp_path):
    """Ambiguity this surface is the first to expose.

    Every other command iterates all registries and never asks which one is
    "keys". Resolving it by declaration order would answer a two-answer
    question, and an assertion against the wrong one would pass.
    """
    (tmp_path / "a.py").write_text('KEYSPACE_ROOT = "box.vault.keys"\n')
    (tmp_path / "b.py").write_text('OTHER_ROOT = "box.other.keys"\n')
    config = tmp_path / "kinemata.toml"
    config.write_text(
        textwrap.dedent(
            """
            [[registry]]
            name = "keyspace"
            kind = "python-constants"
            modules = ["a.py"]

            [[registry]]
            name = "keyspace"
            kind = "python-constants"
            modules = ["b.py"]
            """
        ).lstrip()
    )
    with pytest.raises(ConfigError) as caught:
        registry("keyspace", config=config)
    assert "ambiguous" in str(caught.value)


def test_a_registry_that_cannot_be_closed_still_refuses_through_this_surface(tmp_path):
    """The inherited limit, checked on this side of the boundary.

    ``declared`` is only as good as the data model behind it, and a registry
    that cannot recognize its own identifiers refuses rather than answering.
    Publishing a run-time entry point must not open a path that degrades that
    refusal into a quiet ``False``.
    """
    config = write_project(tmp_path, closed=True)
    with pytest.raises(ConfigError) as caught:
        registry("keyspace", config=config)
    assert "cannot be closed" in str(caught.value)
