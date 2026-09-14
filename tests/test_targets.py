"""Resolving a ``module:attribute`` a config names.

Three of these moved here from ``test_interpose.py`` when the lookup did, and
the reason they are worth their own file is the one the module docstring gives:
two mechanisms now depend on this failing the same way, so a regression here is
not an interposition's regression.
"""

from __future__ import annotations

import dataclasses
import re
import types

import pytest

from kinemata.targets import TARGET_FORM, Target, TargetError, resolve


@pytest.fixture
def module(monkeypatch):
    """A module a target string can actually name."""
    made = types.ModuleType("projectmod")
    made.NUMBER = 3
    made.key_of = lambda crossing: crossing.args[1]

    class Store:
        def set(self, key):
            return key

    made.Store = Store
    monkeypatch.setitem(__import__("sys").modules, "projectmod", made)
    return made


def test_it_names_the_thing_and_where_it_hangs(module):
    found = resolve("projectmod:key_of")
    assert found.value is module.key_of
    assert found.owner is module
    assert found.name == "key_of"


def test_a_dotted_attribute_reaches_a_method(module):
    found = resolve("projectmod:Store.set")
    assert found.owner is module.Store
    assert found.name == "set"
    assert found.value is module.Store.set


def test_the_owner_is_what_a_caller_would_patch(module):
    """The field that exists for :class:`kinemata.interpose.Census` alone.

    Stated as its own case because a ``Target`` whose ``owner`` was the module
    rather than the class would still pass every other case here, and would put
    the patch on the wrong object.
    """
    found = resolve("projectmod:Store.set")
    setattr(found.owner, found.name, lambda self, key: "replaced")
    assert module.Store().set("k") == "replaced"


def test_something_with_no_colon_is_not_a_target():
    with pytest.raises(TargetError, match="is not a target"):
        resolve("projectmod.key_of")
    with pytest.raises(TargetError, match="is not a target"):
        resolve(":key_of")
    with pytest.raises(TargetError, match="is not a target"):
        resolve("projectmod:")


def test_the_refusal_says_how_to_spell_one():
    """A form nobody can read off the error is a form they will guess at."""
    with pytest.raises(TargetError, match=re.escape("package.module")):
        resolve("nonsense")
    assert "package.module" in TARGET_FORM


def test_an_unimportable_module_is_a_refusal_by_name():
    with pytest.raises(TargetError, match="cannot import"):
        resolve("no_such_module_anywhere:thing")


def test_a_missing_attribute_is_a_refusal(module):
    with pytest.raises(TargetError, match="is not there"):
        resolve("projectmod:absent")
    with pytest.raises(TargetError, match="is not there"):
        resolve("projectmod:Nope.set")


def test_a_target_naming_something_uncallable_is_refused(module):
    with pytest.raises(TargetError, match="not a callable"):
        resolve("projectmod:NUMBER")


def test_a_module_that_raises_on_import_is_named_with_its_own_error(
    tmp_path, monkeypatch
):
    """The reason the ``except`` is bare, asserted rather than assumed.

    A project's module body runs on import, so the failure is not limited to
    ``ImportError`` -- and a target reported as "cannot import" with no sign of
    the real ``ZeroDivisionError`` sends its reader looking at the config.
    """
    (tmp_path / "explodesmod.py").write_text("raise ZeroDivisionError('boom')\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    with pytest.raises(TargetError, match="ZeroDivisionError: boom") as caught:
        resolve("explodesmod:thing")
    assert isinstance(caught.value.__cause__, ZeroDivisionError)


def test_a_target_is_frozen():
    """Nothing may edit what a lookup returned and leave the next reader wrong."""
    found = Target(owner=types.ModuleType("m"), name="x", value=print)
    with pytest.raises(dataclasses.FrozenInstanceError):
        found.name = "y"  # type: ignore[misc]
