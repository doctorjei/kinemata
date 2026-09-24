"""A ``home`` narrower than a file: ``path::NAME``, the statement binding NAME.

Two adopters reported the file-granular home on 2026-09-24. One declared a tuple
vocabulary with ``code-patterns`` and two of its three historical re-spellings
were in the home file; the other planted a same-value literal in a constant's
home module and measured it reported by neither ``check`` nor, once the value was
deferred, ``undeclared``. These tests are built around both.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.adapters.constants import PythonConstants
from kinemata.adapters.patterns import CodePatterns
from kinemata.bypass import scan, unused
from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.sites import definitions, split


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# -- the constant's home module -----------------------------------------------


PLANT = """
    [project]
    root = "."

    [[registry]]
    name = "keyspace"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"
    closed = true
    syntax = '\\bbox\\.[a-z_]+(?:\\.[a-z_]+)*\\b'
    defer_to = ["filenames"]

    [[registry]]
    name = "filenames"
    kind = "python-constants"
    modules = ["pkg/config.py"]
"""


def plant(tmp_path):
    write(tmp_path, "keys.yaml", "keys:\n  box.enable_vault: {}\n")
    write(tmp_path, "pkg/config.py", """
        BOX_META_FILE = "box.yaml"
        _STRAY = "box.yaml"
        """)
    write(tmp_path, "kinemata.toml", PLANT)
    return tmp_path / "kinemata.toml"


def test_a_respelling_in_the_constants_own_module_is_a_bypass(tmp_path, capsys):
    """The adopter's plant: deferred by ``undeclared``, and now caught by ``check``.

    Before the site, ``check`` skipped the whole module and ``undeclared`` had
    handed the value to the constant's registry, so neither reported it.
    """
    config = plant(tmp_path)
    assert main(["undeclared", "--config", str(config)]) == 0
    capsys.readouterr()
    assert main(["check", "--config", str(config)]) == 1
    out = capsys.readouterr().out
    assert 'pkg/config.py:2  _STRAY = "box.yaml"' in out
    # The definition is still the canonical use.
    assert "pkg/config.py:1" not in out


def test_a_constants_home_is_its_statement(tmp_path):
    write(tmp_path, "pkg/config.py", 'A_FILE = "a.yaml"\nB_FILE = "b.yaml"\n')
    registry = PythonConstants([tmp_path / "pkg/config.py"], root=tmp_path)
    assert {e.id: e.home for e in registry.entries()} == {
        "A_FILE": ("pkg/config.py::A_FILE",),
        "B_FILE": ("pkg/config.py::B_FILE",),
    }


def test_a_rebinding_after_the_definition_is_not_the_definition():
    """The first binding is the site; a later one spelling the value again is
    exactly what a site exists to leave visible."""
    assert definitions('A_FILE = "a.yaml"\nA_FILE = "a.yaml"\n') == {"A_FILE": (1, 1)}


# -- a declared site ------------------------------------------------------------


VOCABULARY = """
    GRADING_TYPES = (
        "none",
        "on_paper",
    )


    def exclusive(mode):
        return mode in ("none", "on_paper")
    """


def patterns(home):
    return CodePatterns([{
        "id": "grading-types",
        "antipatterns": [r'"none",\s*"on_paper"'],
        "home": home,
    }])


def test_a_site_reports_the_respelling_beside_a_multi_line_definition(tmp_path):
    """The case a line-anchored lookahead cannot express: continuation lines
    carry no name, so only the statement's span can exempt them."""
    write(tmp_path, "pkg/push.py", VOCABULARY)
    hits = scan(patterns(["pkg/push.py::GRADING_TYPES"]), tmp_path, strings_only=False)
    assert [hit.line for hit in hits] == [8]


def test_a_file_home_still_exempts_the_whole_file(tmp_path):
    """Unchanged: a fragment naming a file means what it always meant."""
    write(tmp_path, "pkg/push.py", VOCABULARY)
    assert scan(patterns(["pkg/push.py"]), tmp_path, strings_only=False) == []


def test_a_site_matches_by_path_suffix_like_a_file_home(tmp_path):
    """A scan pointed below the root reports shorter paths; the site still applies."""
    write(tmp_path, "src/pkg/push.py", VOCABULARY)
    hits = scan(patterns(["src/pkg/push.py::GRADING_TYPES"]), tmp_path / "src",
                strings_only=False)
    assert [(hit.path, hit.line) for hit in hits] == [("pkg/push.py", 8)]


def test_a_definition_spans_its_decorators_and_body():
    source = textwrap.dedent("""
        import functools


        @functools.cache
        def helper():
            return 1


        class Box:
            pass
        """)
    assert definitions(source) == {"helper": (5, 7), "Box": (10, 11)}


def test_source_that_does_not_parse_defines_nothing():
    assert definitions("A = (\n") == {}


def test_split():
    assert split("pkg/push.py::GRADING_TYPES") == ("pkg/push.py", "GRADING_TYPES")
    assert split("pkg/push.py") == ("pkg/push.py", None)


# -- refusals -------------------------------------------------------------------


SITE_CONFIG = """
    [project]
    root = "."

    [[registry]]
    name = "vocab"
    kind = "code-patterns"

      [[registry.entry]]
      id = "grading-types"
      antipatterns = ['"none",\\s*"on_paper"']
      home = ["{home}"]
"""


@pytest.mark.parametrize(
    "home, message",
    [
        ("pkg/push.py::GRADING_TYPE", "binds nothing called 'GRADING_TYPE'"),
        ("pkg/pull.py::GRADING_TYPES", "names no file"),
        ("pkg/push.yaml::GRADING_TYPES", "a site is `path/to/module.py::NAME`"),
        ("pkg/push.py::not a name", "a site is `path/to/module.py::NAME`"),
    ],
)
def test_a_site_that_would_exempt_nothing_is_refused(tmp_path, home, message):
    write(tmp_path, "pkg/push.py", VOCABULARY)
    write(tmp_path, "kinemata.toml", SITE_CONFIG.format(home=home))
    with pytest.raises(ConfigError, match=message):
        load(tmp_path / "kinemata.toml")


def test_a_site_is_found_by_suffix_when_not_at_the_root(tmp_path):
    write(tmp_path, "src/pkg/push.py", VOCABULARY)
    write(tmp_path, "kinemata.toml", SITE_CONFIG.format(home="pkg/push.py::GRADING_TYPES"))
    assert load(tmp_path / "kinemata.toml").registries


# -- unused ---------------------------------------------------------------------


def test_a_mention_beside_the_definition_is_a_use(tmp_path):
    """The other half of a site: only the statement is the definition, so the
    module using its own constant is a use rather than a self-reference."""
    write(tmp_path, "pkg/config.py", """
        USED_FILE = "used.yaml"
        IDLE_FILE = "idle.yaml"
        PATH = "/etc/" + USED_FILE
        """)
    registry = PythonConstants([tmp_path / "pkg/config.py"], root=tmp_path)
    assert unused(registry, tmp_path) == ["IDLE_FILE"]
