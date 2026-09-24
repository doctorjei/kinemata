"""A list-typed config key given as a string is refused, never iterated.

A string is iterable, so every key read with ``tuple(...)`` took one apart a
character at a time. Measured 2026-09-24, and the failures were mostly silent:
``suffixes = ".py"`` on a registry read as ``('.', 'p', 'y')`` and its ``check``
went from one bypass to exiting 0; a code-patterns ``home`` became one-letter
fragments every path contains, so every bypass read as canonical use;
``choices = "str"`` accepted ``"s"`` and refused ``"str"``. ``command`` had been
fixed for this alone. One case per key, so the next list key that reads its
value some other way has a table to join.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.config import ConfigError, load
from kinemata.contract import strings

BASE = """
    [project]
    root = "."
    exclude = ["build/"]
    suffixes = [".py"]

    [[registry]]
    name = "constants"
    kind = "python-constants"
    modules = ["pkg/c.py"]
    suffixes = [".py"]
    machinery = ["pkg/c.py"]

    [[registry]]
    name = "helpers"
    kind = "code-patterns"

      [[registry.entry]]
      id = "run_or_die"
      antipatterns = ['check\\s*=\\s*True']
      home = ["pkg/run.py"]
      clauses = ["spec~run"]

    [[registry]]
    name = "keys"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"

    [claims]
    suffixes = [".md"]
    file_suffixes = [".conf"]
    historical = ["archive/"]
    resolve_in = ["src"]
    commits_in = ["."]

    [context]
    include = ["*.md"]
    budget = 100000
    strip = []
    external = []

    [[gate]]
    command = "kinemata check"
    where = [".github/workflows/"]

    [[shape]]
    registry = "keys"

      [[shape.rule]]
      name = "a type is one of the vocabulary"
      field = "type"
      choices = ["str", "int"]
"""

#: (the line as the base spells it, the same key given as a string)
CASES = [
    ('exclude = ["build/"]', 'exclude = "build/"'),
    ('suffixes = [".py"]\n\n    [[registry]]', 'suffixes = ".py"\n\n    [[registry]]'),
    ('modules = ["pkg/c.py"]', 'modules = "pkg/c.py"'),
    ('    suffixes = [".py"]\n    machinery', '    suffixes = ".py"\n    machinery'),
    ('machinery = ["pkg/c.py"]', 'machinery = "pkg/c.py"'),
    ("antipatterns = ['check\\s*=\\s*True']", "antipatterns = 'check\\s*=\\s*True'"),
    ('home = ["pkg/run.py"]', 'home = "pkg/run.py"'),
    ('clauses = ["spec~run"]', 'clauses = "spec~run"'),
    ('suffixes = [".md"]', 'suffixes = ".md"'),
    ('file_suffixes = [".conf"]', 'file_suffixes = ".conf"'),
    ('historical = ["archive/"]', 'historical = "archive/"'),
    ('resolve_in = ["src"]', 'resolve_in = "src"'),
    ('commits_in = ["."]', 'commits_in = "."'),
    ('include = ["*.md"]', 'include = "*.md"'),
    ("strip = []", 'strip = "comments"'),
    ("external = []", 'external = "/etc/motd"'),
    ('where = [".github/workflows/"]', 'where = ".github/workflows/"'),
    ('choices = ["str", "int"]', 'choices = "str"'),
]


def project(tmp_path, body):
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "c.py").write_text('NAME = "a.long.enough.value"\n')
    (tmp_path / "keys.yaml").write_text("keys:\n  alpha:\n    type: str\n")
    path = tmp_path / "kinemata.toml"
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_the_base_config_loads(tmp_path):
    """Every refusal below is caused by its one change, not by the base."""
    load(project(tmp_path, BASE))


@pytest.mark.parametrize(("listed", "stringed"), CASES, ids=[c[1] for c in CASES])
def test_a_list_key_given_as_a_string_is_refused(tmp_path, listed, stringed):
    assert BASE.count(listed) == 1, listed
    with pytest.raises(ConfigError, match="one character at a time"):
        load(project(tmp_path, BASE.replace(listed, stringed)))


def test_choices_keeps_the_type_of_its_items():
    """Validated as a list, but not turned into text: ``[1, 2]`` compares integers."""
    from kinemata.config import _shape_condition

    condition = _shape_condition(
        {"field": "n", "choices": [1, 2]}, "rule", allow_set=False
    )
    assert condition.argument == (1, 2)


@pytest.mark.parametrize("value", [{"a": 1}, 3, None])
def test_strings_refuses_what_is_not_a_list(value):
    with pytest.raises(ValueError, match="is a list, not"):
        strings(value, "a key")
