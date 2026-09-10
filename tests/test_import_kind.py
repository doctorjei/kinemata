"""``kind = "import"``: a registry class the project wrote, named from its config.

The gap this closes was reported by an adopting project on 2026-09-09 and is the
one the contract had been advertising all along -- ``declared()`` may be
overridden when membership cannot be enumerated, and no config file could reach
a class that overrode it. Every refusal below exists because the alternative is a
traceback from inside somebody else's package, or worse, a registry that loads
and is not one.
"""

from __future__ import annotations

import itertools
import textwrap

import pytest

from kinemata.config import ConfigError, load
from kinemata.contract import BaseRegistry, closure_guard, missing_members

_counter = itertools.count()


def module(tmp_path, monkeypatch, body):
    """Write an importable module with a name no other test has used.

    A fresh name per test rather than a shared one: ``sys.modules`` caches, and a
    suite that reuses a module name tests the first body five times.
    """
    name = f"adopter_{next(_counter)}"
    (tmp_path / f"{name}.py").write_text(textwrap.dedent(body).lstrip())
    monkeypatch.syspath_prepend(str(tmp_path))
    return name


def config(tmp_path, body):
    path = tmp_path / "kinemata.toml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


KEYSPACE = """
    from __future__ import annotations

    import re

    from kinemata.contract import BaseRegistry, Entry

    SECTIONS = {"core": ("box.name", "box.root"), "vault": ("vault.ro",)}


    class KeyspaceRegistry(BaseRegistry):
        name = "keyspace"
        closed = True

        def __init__(self, sections=None):
            self.sections = tuple(sections or sorted(SECTIONS))

        def entries(self):
            for section in self.sections:
                for key in SECTIONS[section]:
                    yield Entry(id=key, clauses=(f"spec~{section}",))

        def declared(self, identifier):
            return any(identifier in SECTIONS[s] for s in self.sections)

        def candidates(self, text):
            return re.findall(r"\\b[a-z_]+(?:\\.[a-z_]+)+\\b", text)
"""


# -- the path that was blocked -------------------------------------------------


def test_a_project_supplied_class_loads_from_the_config(tmp_path, monkeypatch):
    """The reported defect, in one test.

    Membership answered by an oracle rather than by enumeration -- which is what
    the adopter's keyspace needs, and what only a library import could reach.
    """
    name = module(tmp_path, monkeypatch, KEYSPACE)
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:KeyspaceRegistry"
        """,
    )
    (registry,) = load(path).registries
    assert registry.name == "keyspace"
    assert sorted(e.id for e in registry.entries()) == ["box.name", "box.root", "vault.ro"]
    assert registry.declared("vault.ro") and not registry.declared("vault.tmp")
    assert registry.resolve("box.name") == ("spec~core",)


def test_extra_keys_parameterize_the_projects_own_adapter(tmp_path, monkeypatch):
    """Keys this file has never heard of go to the class, not into the void."""
    name = module(tmp_path, monkeypatch, KEYSPACE)
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:KeyspaceRegistry"
        sections = ["core"]
        """,
    )
    (registry,) = load(path).registries
    assert sorted(e.id for e in registry.entries()) == ["box.name", "box.root"]
    assert not registry.declared("vault.ro")


def test_the_configs_name_wins_and_its_absence_leaves_the_classs_own(
    tmp_path, monkeypatch
):
    """Unlike every other kind there is something to fall back to.

    A project's class already carries a name, so overwriting it with a default
    nobody wrote would rename the registry in every report for no reason.
    """
    name = module(tmp_path, monkeypatch, KEYSPACE)
    renamed = load(
        config(
            tmp_path,
            f"""
            [[registry]]
            name = "settings"
            kind = "import"
            target = "{name}:KeyspaceRegistry"
            """,
        )
    ).registries[0]
    assert renamed.name == "settings"

    unnamed = load(
        config(
            tmp_path,
            f"""
            [[registry]]
            kind = "import"
            target = "{name}:KeyspaceRegistry"
            """,
        )
    ).registries[0]
    assert unnamed.name == "keyspace"


def test_the_loaders_own_keys_are_applied_not_forwarded(tmp_path, monkeypatch):
    """``suffixes`` and ``machinery`` mean something here, so they are not kwargs.

    The class takes one keyword argument and would raise on either of these; that
    it does not is the assertion.
    """
    name = module(tmp_path, monkeypatch, KEYSPACE)
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:KeyspaceRegistry"
        suffixes = [".md"]
        machinery = ["manifest.yaml"]
        """,
    )
    (registry,) = load(path).registries
    assert registry.suffixes == (".md",)
    assert registry.machinery == ("manifest.yaml",)


def test_an_imported_registry_that_recognizes_nothing_is_still_refused(
    tmp_path, monkeypatch
):
    """The empty-registry guard is not waived for a class the project wrote.

    An adapter somebody authored is if anything likelier to bind to nothing than
    one shipped here, because nobody else has ever run it.
    """
    name = module(
        tmp_path,
        monkeypatch,
        """
        from kinemata.contract import BaseRegistry


        class Empty(BaseRegistry):
            def entries(self):
                return []
        """,
    )
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "empty"
        kind = "import"
        target = "{name}:Empty"
        """,
    )
    settings = load(path)
    assert settings.registries == []
    assert len(settings.unfitted) == 1
    assert "no entries" in settings.unfitted[0]


# -- refusals ------------------------------------------------------------------


@pytest.mark.parametrize(
    "target",
    [
        '"pkg.module.ClassName"',  # a dot where the colon goes
        '"pkg.module:"',
        '":ClassName"',
        '"pkg:module:ClassName"',
        "42",
        '""',
    ],
)
def test_a_malformed_target_is_refused(tmp_path, target):
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = {target}
        """,
    )
    with pytest.raises(ConfigError, match="is not a target"):
        load(path)


def test_a_missing_target_is_refused(tmp_path):
    path = config(
        tmp_path,
        """
        [[registry]]
        name = "keyspace"
        kind = "import"
        """,
    )
    with pytest.raises(ConfigError, match="is not a target"):
        load(path)


def test_a_module_that_does_not_exist_is_refused_naming_target_and_config(tmp_path):
    """A usable error, which is the point.

    Both halves are load-bearing: the target says what was asked for, and the
    config path says which file asked -- a config found by walking up from the
    working directory is not necessarily one the reader knows about.
    """
    path = config(
        tmp_path,
        """
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "no_such_package_anywhere:KeyspaceRegistry"
        """,
    )
    with pytest.raises(ConfigError) as caught:
        load(path)
    message = str(caught.value)
    assert "no_such_package_anywhere:KeyspaceRegistry" in message
    assert str(path) in message
    assert "ModuleNotFoundError" in message


def test_a_module_that_raises_on_import_is_refused_not_left_as_a_traceback(
    tmp_path, monkeypatch
):
    """Importing runs the project's code, so anything at all can come back."""
    name = module(tmp_path, monkeypatch, "raise RuntimeError('half-written module')\n")
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:KeyspaceRegistry"
        """,
    )
    with pytest.raises(ConfigError, match="half-written module"):
        load(path)


def test_a_missing_attribute_is_refused(tmp_path, monkeypatch):
    name = module(tmp_path, monkeypatch, KEYSPACE)
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:Keyspace"
        """,
    )
    with pytest.raises(ConfigError, match="defines no such attribute"):
        load(path)


def test_an_object_that_is_not_a_class_is_refused(tmp_path, monkeypatch):
    """An instance or a factory function is a near miss worth naming as one."""
    name = module(
        tmp_path,
        monkeypatch,
        """
        REGISTRY = "keyspace"
        """,
    )
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:REGISTRY"
        """,
    )
    with pytest.raises(ConfigError, match="is a str, not a class"):
        load(path)


def test_a_class_that_is_not_a_registry_is_refused_and_says_what_is_missing(
    tmp_path, monkeypatch
):
    """A warning here would load a registry that cannot answer anything."""
    name = module(
        tmp_path,
        monkeypatch,
        """
        class NotARegistry:
            pass
        """,
    )
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:NotARegistry"
        """,
    )
    with pytest.raises(ConfigError) as caught:
        load(path)
    message = str(caught.value)
    assert "is not a registry" in message
    for member in ("entries", "declared", "resolve", "detect", "name", "closed"):
        assert member in message


def test_a_class_missing_one_member_is_still_refused(tmp_path, monkeypatch):
    """Half a registry is the case a hasattr-free check would let through."""
    name = module(
        tmp_path,
        monkeypatch,
        """
        class Partial:
            name = "partial"
            closed = False

            def entries(self):
                return []

            def declared(self, identifier):
                return False

            def resolve(self, identifier):
                return ()
        """,
    )
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:Partial"
        """,
    )
    with pytest.raises(ConfigError, match="it has no detect"):
        load(path)


def test_keys_the_class_will_not_take_are_refused_not_swallowed(tmp_path, monkeypatch):
    """A misspelled key would otherwise build the adapter's default instead.

    Which is the silent-drift failure wearing a config file: the run stays green
    and the parameter nobody spelled right never took effect.
    """
    name = module(tmp_path, monkeypatch, KEYSPACE)
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:KeyspaceRegistry"
        sektions = ["core"]
        """,
    )
    with pytest.raises(ConfigError) as caught:
        load(path)
    message = str(caught.value)
    assert "will not take the keys" in message
    assert "sektions" in message
    assert str(path) in message


def test_a_constructor_that_raises_is_refused_naming_the_target(tmp_path, monkeypatch):
    name = module(
        tmp_path,
        monkeypatch,
        """
        from kinemata.contract import BaseRegistry


        class Explodes(BaseRegistry):
            def __init__(self):
                raise ValueError("manifest is unreadable")

            def entries(self):
                return []
        """,
    )
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:Explodes"
        """,
    )
    with pytest.raises(ConfigError) as caught:
        load(path)
    assert "raised while being constructed" in str(caught.value)
    assert "manifest is unreadable" in str(caught.value)


def test_a_project_class_that_cannot_recognize_identifiers_cannot_be_closed(
    tmp_path, monkeypatch
):
    """The closure guard is not waived for a class the project wrote.

    It would be the worst place to waive it: the registries a project authors are
    the ones nobody else has ever run.
    """
    name = module(
        tmp_path,
        monkeypatch,
        """
        from kinemata.contract import BaseRegistry, Entry


        class Closed(BaseRegistry):
            closed = True

            def entries(self):
                return [Entry(id="box.name")]
        """,
    )
    path = config(
        tmp_path,
        f"""
        [[registry]]
        name = "keyspace"
        kind = "import"
        target = "{name}:Closed"
        """,
    )
    with pytest.raises(ConfigError, match="cannot be closed"):
        load(path)


# -- the two helpers the kind leans on ----------------------------------------


def test_missing_members_is_read_off_the_protocol():
    """Not a second copy of the member names, which would go stale."""

    class Nothing:
        pass

    assert set(missing_members(Nothing())) == {
        "name",
        "closed",
        "entries",
        "declared",
        "resolve",
        "detect",
    }
    assert missing_members(_Whole()) == ()


def test_closure_guard_reaches_a_class_that_does_not_inherit_the_base():
    """A protocol-satisfying class has no ``__post_init_check__`` to call.

    Calling it directly would raise ``AttributeError`` where the honest answer is
    that this class cannot be closed, and an unasked guard is the inert check.
    """

    class Duck:
        name = "duck"
        closed = True

        def entries(self):
            return []

        def declared(self, identifier):
            return False

        def resolve(self, identifier):
            return ()

        def detect(self, text):
            return []

    with pytest.raises(NotImplementedError, match="Duck does not implement"):
        closure_guard(Duck())

    open_duck = Duck()
    open_duck.closed = False
    closure_guard(open_duck)  # an open registry is never asked


def test_closure_guard_uses_a_ducks_own_candidates_when_it_has_one():
    class Recognizer:
        name = "recognizer"
        closed = True
        asked = False

        def entries(self):
            return []

        def declared(self, identifier):
            return False

        def resolve(self, identifier):
            return ()

        def detect(self, text):
            return []

        def candidates(self, text):
            type(self).asked = True
            return []

    closure_guard(Recognizer())
    assert Recognizer.asked


class _Whole(BaseRegistry):
    def entries(self):
        return []
