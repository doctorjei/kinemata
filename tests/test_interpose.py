"""Watching a declared funnel: the mechanism, and the plugin that drives it.

The hazard this subject carries is not the patching, which is four lines. It is
that a run-time collector has three ways to look clean while checking nothing --
it never installed, nothing crossed it, or its extractor quietly returned
``None`` for everything -- and all three print the same reassuring silence. So
most of what follows is about those three staying distinguishable, and about the
class never being left patched afterwards.

The second hazard is the one an adopting project already walked into and
documented: excusing a write by *where it came from*. Their frame-matched origin
discriminator hid roughly forty real violations. Nothing here may key a verdict
on a site, and the AND rule below is what enforces it.
"""

from __future__ import annotations

import textwrap
import types

import pytest

from kinemata.config import ConfigError, load
from kinemata.interpose import (
    Census,
    Funnel,
    Session,
)

pytest_plugins = ["pytester"]


class Store:
    """Something with a write funnel, standing in for a project's own."""

    def __init__(self):
        self.data = {}

    def set(self, key, value):
        if key.startswith("_"):
            raise KeyError(key)  # a refusal: not a write
        self.data[key] = value
        return value


class Keys:
    """The smallest registry `Census` needs."""

    name = "keyspace"
    closed = True

    def __init__(self, *declared, raises=False):
        self._declared = set(declared)
        self._raises = raises

    def declared(self, identifier):
        if self._raises:
            raise RuntimeError("this registry cannot answer")
        return identifier in self._declared

    def entries(self):
        return []


@pytest.fixture
def module(monkeypatch):
    """A module the target string can actually name."""
    made = types.ModuleType("projectmod")
    made.Store = Store
    made.key_of = lambda crossing: crossing.args[1]
    monkeypatch.setitem(__import__("sys").modules, "projectmod", made)
    return made


def census(module, *declared, identify=None, **kwargs):
    funnel = Funnel(
        registry="keyspace",
        target="projectmod:Store.set",
        identify="projectmod:key_of",
    )
    watcher = Census(
        funnel, Keys(*declared, **kwargs), identify or module.key_of,
        site=lambda: "t.py:1",
    )
    watcher.install()
    return watcher


# -- the two ends -------------------------------------------------------------


def test_the_original_still_runs_and_still_returns(module):
    watcher = census(module, "a")
    store = Store()
    assert store.set("a", 1) == 1
    assert store.data == {"a": 1}
    watcher.uninstall()


def test_the_class_is_not_left_patched(module):
    before = Store.set
    watcher = census(module)
    assert Store.set is not before
    watcher.uninstall()
    assert Store.set is before


def test_uninstalling_twice_is_safe(module):
    before = Store.set
    watcher = census(module)
    watcher.uninstall()
    watcher.uninstall()
    assert Store.set is before


def test_a_target_that_cannot_be_patched_blocks_rather_than_raising(module):
    funnel = Funnel(registry="keyspace", target="projectmod:Nope.set",
                    identify="projectmod:key_of")
    watcher = Census(funnel, Keys(), module.key_of)
    watcher.install()
    assert not watcher.installed
    assert "is not there" in watcher.blocked
    assert watcher.watch().failed
    # The lookup itself, and every way it can refuse, is `test_targets.py`. What
    # belongs here is only that a refusal BLOCKS rather than raising: a census
    # that raised into `pytest_configure` would take the project's whole run
    # down over a misspelled config line.


def test_a_target_that_resolves_but_refuses_assignment_blocks_too(module):
    """Resolving is not patching, and the docstring promises about both.

    `resolve` answers by shape: `dict.__setitem__` is a perfectly good target
    until the assignment discovers that the type will not take one. The
    `TypeError` escaped to `pytest_configure` -- a raise at the caller by a
    method whose docstring says it never raises at the caller.
    """
    funnel = Funnel(registry="keyspace", target="builtins:dict.__setitem__",
                    identify="projectmod:key_of")
    watcher = Census(funnel, Keys(), module.key_of)
    watcher.install()
    assert not watcher.installed
    assert "cannot be patched" in watcher.blocked
    assert "TypeError" in watcher.blocked
    assert watcher.watch().failed


def test_a_funnel_that_could_not_be_patched_is_not_restored_over(module):
    """`uninstall` must not write an attribute this census never replaced."""
    funnel = Funnel(registry="keyspace", target="builtins:dict.__setitem__",
                    identify="projectmod:key_of")
    watcher = Census(funnel, Keys(), module.key_of)
    watcher.install()
    watcher.uninstall()  # would raise the same TypeError if it tried
    assert dict.__setitem__ is not None


# -- what is recorded ---------------------------------------------------------


def test_a_declared_identifier_is_not_a_finding(module):
    watcher = census(module, "a")
    Store().set("a", 1)
    watcher.drain()
    watcher.uninstall()
    watch = watcher.watch()
    assert watch.crossings == 1 and watch.findings == ()


def test_an_undeclared_identifier_is_a_finding_with_its_site(module):
    watcher = census(module)
    Store().set("fabricated", 1)
    watcher.drain()
    watcher.uninstall()
    (found,) = watcher.watch().findings
    assert found.identifier == "fabricated" and found.site == "t.py:1"
    assert "declared by nothing" in str(found)


def test_a_refused_call_is_not_recorded(module):
    """Censusing one would invent a finding out of a test asserting a refusal."""
    watcher = census(module)
    with pytest.raises(KeyError):
        Store().set("_private", 1)
    watcher.drain()
    watcher.uninstall()
    assert watcher.watch().crossings == 0


def test_repeated_writes_are_one_row_with_a_count(module):
    watcher = census(module)
    store = Store()
    for _ in range(3):
        store.set("fabricated", 1)
    watcher.drain()
    watcher.uninstall()
    (found,) = watcher.watch().findings
    assert found.count == 3


def test_an_identifier_the_extractor_declines_is_counted_not_dropped(module):
    """A run that identified nothing must not read like one that found nothing."""
    watcher = census(module, identify=lambda crossing: None)
    Store().set("a", 1)
    watcher.drain()
    watcher.uninstall()
    watch = watcher.watch()
    assert watch.crossings == 1 and watch.observations == ()


def test_a_deferred_identifier_is_resolved_at_drain(module):
    """Their case: a node is written before it is attached to a parent."""
    box = ["before"]
    watcher = census(module, identify=lambda crossing: lambda: box[0])
    Store().set("a", 1)
    box[0] = "after"
    watcher.drain()
    watcher.uninstall()
    (found,) = watcher.watch().findings
    assert found.identifier == "after"


def test_a_deferred_identifier_reusing_one_box_is_one_row(module):
    box = ["x"]
    thunk = lambda: box[0]  # noqa: E731 - the reused box is the point
    watcher = census(module, identify=lambda crossing: thunk)
    store = Store()
    store.set("a", 1)
    store.set("b", 2)
    watcher.drain()
    watcher.uninstall()
    (found,) = watcher.watch().findings
    assert found.count == 2


# -- faults are not silence ---------------------------------------------------


def test_an_extractor_that_raises_does_not_break_the_project(module):
    def boom(crossing):
        raise ValueError("extractor is wrong")

    watcher = census(module, identify=boom)
    store = Store()
    assert store.set("a", 1) == 1  # the project's own call still works
    watcher.drain()
    watcher.uninstall()
    watch = watcher.watch()
    assert watch.errors and "extractor is wrong" in watch.errors[0]
    assert watch.failed  # a fault means the check has holes, and nothing else says so


def test_a_registry_that_cannot_answer_is_a_fault_not_a_pass(module):
    watcher = census(module, raises=True)
    Store().set("a", 1)
    watcher.drain()
    watcher.uninstall()
    watch = watcher.watch()
    assert watch.errors and watch.failed


def test_collector_faults_are_capped(module):
    def boom(crossing):
        raise ValueError("no")

    watcher = census(module, identify=boom)
    store = Store()
    for index in range(50):
        store.set(f"k{index}", 1)
    watcher.uninstall()
    assert len(watcher.watch().errors) == 20


# -- the declaration a test makes ---------------------------------------------


def test_an_armed_identifier_is_excused(module):
    watcher = census(module)
    watcher.arm({"fabricated"})
    Store().set("fabricated", 1)
    watcher.drain()
    watcher.uninstall()
    watch = watcher.watch()
    assert watch.findings == ()
    assert watcher.exercised == frozenset({"fabricated"})


def test_one_crossing_from_outside_a_declaring_test_makes_it_a_finding_again(module):
    """`and`, never `or` -- and the reason a row is not keyed on its site."""
    watcher = census(module)
    store = Store()
    watcher.arm({"fabricated"})
    store.set("fabricated", 1)
    watcher.drain()
    watcher.arm(())
    store.set("fabricated", 1)
    watcher.drain()
    watcher.uninstall()
    assert [item.identifier for item in watcher.watch().findings] == ["fabricated"]


def test_a_declaration_that_changed_nothing_is_not_exercised(module):
    """The identifier was declared all along, so the marker excused nothing."""
    watcher = census(module, "a")
    watcher.arm({"a"})
    Store().set("a", 1)
    watcher.drain()
    watcher.uninstall()
    watcher.watch()
    assert watcher.exercised == frozenset()


def test_an_unused_declaration_fails_the_session():
    session = Session(declared_by_tests=frozenset({"never.written"}))
    assert session.unused_markers == ("never.written",)
    assert session.failed


def test_a_funnel_nothing_crossed_is_reported_and_is_not_a_failure(module):
    watcher = census(module)
    watcher.uninstall()
    session = Session(watches=(watcher.watch(),))
    assert session.silent and not session.failed
    assert any("says nothing about it" in line for line in session.lines())


# -- the config surface -------------------------------------------------------


def write_config(tmp_path, body):
    (tmp_path / "keys.yaml").write_text("keys:\n  app.name:\n    spec: \"§1\"\n")
    (tmp_path / "kinemata.toml").write_text(textwrap.dedent(f"""
        [project]
        root = "."

        [[registry]]
        name = "keyspace"
        kind = "yaml-mapping"
        source = "keys.yaml"
        section = "keys"
        clause_field = "spec"

        {body}
        """).lstrip())
    return tmp_path / "kinemata.toml"


GOOD = """
[[interpose]]
registry = "keyspace"
target = "projectmod:Store.set"
identify = "projectmod:key_of"
"""


def test_a_declared_funnel_loads(tmp_path):
    settings = load(write_config(tmp_path, GOOD))
    assert settings.funnels[0].target == "projectmod:Store.set"


def test_the_target_is_not_resolved_at_load(tmp_path):
    """Importing the project belongs in the project's session, not in every check."""
    settings = load(write_config(tmp_path, GOOD.replace("projectmod", "not_a_module")))
    assert settings.funnels[0].registry == "keyspace"


def test_an_interpose_missing_a_key_is_refused(tmp_path):
    body = GOOD.replace('identify = "projectmod:key_of"\n', "")
    with pytest.raises(ConfigError, match="is missing identify"):
        load(write_config(tmp_path, body))


def test_a_malformed_target_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="not a target"):
        load(write_config(tmp_path, GOOD.replace("projectmod:Store.set", "Store.set")))


def test_two_declarations_on_one_callable_are_refused(tmp_path):
    """The second uninstall would restore the first wrapper, not the original."""
    with pytest.raises(ConfigError, match="already watches"):
        load(write_config(tmp_path, GOOD + GOOD.replace('"keyspace"', '"keyspace"')))


def test_an_interpose_naming_an_unknown_registry_is_refused(tmp_path):
    with pytest.raises(ConfigError, match="no \\[\\[registry\\]\\] declares"):
        load(write_config(tmp_path, GOOD.replace('"keyspace"\n', '"nope"\n', 1)))


def test_an_interpose_alone_is_a_declared_check(tmp_path):
    """A config carrying only this one still configures something real."""
    (tmp_path / "kinemata.toml").write_text(textwrap.dedent("""
        [project]
        root = "."

        [[registry]]
        name = "keyspace"
        kind = "code-patterns"

          [[registry.entry]]
          id = "app.name"
          antipatterns = ['"app\\.name"']

        [[interpose]]
        registry = "keyspace"
        target = "projectmod:Store.set"
        identify = "projectmod:key_of"
        """).lstrip())
    assert load(tmp_path / "kinemata.toml").funnels


# -- end to end, through a real pytest session --------------------------------


PROJECT = {
    "projectmod.py": """
        DECLARED = ("app.name",)

        class Store:
            def __init__(self):
                self.data = {}
            def set(self, key, value):
                self.data[key] = value

        def key_of(crossing):
            return crossing.args[1]
    """,
    "registries.py": """
        from kinemata.contract import BaseRegistry, Entry
        import projectmod

        class Keys(BaseRegistry):
            name = "keyspace"
            def entries(self):
                return [Entry(id=key) for key in projectmod.DECLARED]
    """,
    "conftest.py": 'pytest_plugins = ["kinemata.pytest_plugin"]',
    "kinemata.toml": """
        [project]
        root = "."

        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "registries:Keys"

        [[interpose]]
        registry = "keyspace"
        target = "projectmod:Store.set"
        identify = "projectmod:key_of"
    """,
}


def make_project(pytester, test_body):
    for name, body in PROJECT.items():
        (pytester.path / name).write_text(textwrap.dedent(body).lstrip())
    pytester.makepyfile(test_it=textwrap.dedent(test_body))
    pytester.syspathinsert()


def test_a_fabricated_identifier_fails_a_real_session(pytester):
    make_project(pytester, """
        import projectmod

        def test_writes():
            projectmod.Store().set("app.fabricated", 1)
    """)
    result = pytester.runpytest_subprocess()
    result.stdout.fnmatch_lines(["*app.fabricated*declared by nothing*"])
    assert result.ret == 1


def test_a_declared_identifier_leaves_the_session_clean(pytester):
    make_project(pytester, """
        import projectmod

        def test_writes():
            projectmod.Store().set("app.name", 1)
    """)
    result = pytester.runpytest_subprocess()
    assert result.ret == 0


def test_a_marker_excuses_the_identifier_it_names(pytester):
    make_project(pytester, """
        import pytest
        import projectmod

        @pytest.mark.kinemata_undeclared("app.fabricated", reason="drives a refusal")
        def test_writes():
            projectmod.Store().set("app.fabricated", 1)
    """)
    result = pytester.runpytest_subprocess()
    assert result.ret == 0


def test_a_marker_naming_something_never_written_fails(pytester):
    make_project(pytester, """
        import pytest
        import projectmod

        @pytest.mark.kinemata_undeclared("app.stale", reason="outlived its reason")
        def test_writes():
            projectmod.Store().set("app.name", 1)
    """)
    result = pytester.runpytest_subprocess()
    result.stdout.fnmatch_lines(["*STALE: app.stale*"])
    assert result.ret == 1


def test_a_marker_does_not_excuse_another_test_writing_the_same_thing(pytester):
    make_project(pytester, """
        import pytest
        import projectmod

        @pytest.mark.kinemata_undeclared("app.fabricated", reason="drives a refusal")
        def test_declared_it():
            projectmod.Store().set("app.fabricated", 1)

        def test_did_not():
            projectmod.Store().set("app.fabricated", 1)
    """)
    result = pytester.runpytest_subprocess()
    assert result.ret == 1


def test_the_project_class_is_unpatched_when_the_session_ends(pytester):
    make_project(pytester, """
        import projectmod

        def test_writes():
            projectmod.Store().set("app.name", 1)

        def test_the_patch_is_visible_while_running():
            assert getattr(projectmod.Store.set, "__kinemata_watched__", False)
    """)
    result = pytester.runpytest_subprocess()
    assert result.ret == 0
