"""``[[registry]] only``: a registry that applies to named files and no others.

The inverse of ``home``. An entry fires everywhere except where it is defined,
and nothing could say *fires only here* -- which is what an import discipline
needs. An adopting project named the case on 2026-09-13: their bootstrap module
must stay free of imports, a pattern that is a finding in one file and the
ordinary shape of every other. A run narrowed to that file with a path argument
did it, but only in a CI step written for it; a plain ``check`` fired the
registry across the whole tree.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.cli import main
from kinemata.config import ConfigError, load

IMPORTS = """
    [project]
    root = "."

    [[registry]]
    name = "bootstrap-imports"
    kind = "code-patterns"
    match_mode = "code"
    {only}

      [[registry.entry]]
      id = "no-imports-in-bootstrap"
      antipatterns = ['^\\s*(import|from)\\s']
"""


def project(tmp_path, only='only = ["pkg/bootstrap.py"]', config=IMPORTS):
    (tmp_path / "pkg").mkdir(exist_ok=True)
    (tmp_path / "pkg" / "bootstrap.py").write_text("import os\nX = 1\n")
    (tmp_path / "pkg" / "app.py").write_text("import os\nimport sys\n")
    (tmp_path / "README.md").write_text("import os\n")
    path = tmp_path / "kinemata.toml"
    path.write_text(textwrap.dedent(config.format(only=only)).lstrip())
    return str(path)


def check(path, capsys):
    status = main(["check", "-c", path])
    return status, capsys.readouterr().out


def test_a_scoped_registry_fires_only_in_its_files(tmp_path, capsys):
    status, out = check(project(tmp_path), capsys)
    assert status == 1
    assert "pkg/bootstrap.py:1" in out
    assert "pkg/app.py" not in out


def test_without_the_key_a_registry_fires_everywhere(tmp_path, capsys):
    """The behavior this closes, pinned as the default for every registry before it."""
    status, out = check(project(tmp_path, only=""), capsys)
    assert status == 1
    assert "pkg/app.py:1" in out and "pkg/bootstrap.py:1" in out


def test_a_scope_reads_fragments_the_way_exclude_does(tmp_path, capsys):
    """Whole segments at any depth: ``bootstrap.py`` names the file wherever it is."""
    status, out = check(project(tmp_path, only='only = ["bootstrap.py"]'), capsys)
    assert status == 1
    assert "pkg/bootstrap.py:1" in out and "pkg/app.py" not in out


def test_undeclared_reads_only_the_scoped_files(tmp_path, capsys):
    """One rule for every scan that reads a registry's files."""
    (tmp_path / "keys.yaml").write_text("keys:\n  app.name: {}\n")
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "in.py").write_text('A = "app.stray"\n')
    (tmp_path / "pkg" / "out.py").write_text('B = "app.other"\n')
    (tmp_path / "kinemata.toml").write_text(textwrap.dedent("""
        [project]
        root = "."

        [[registry]]
        name = "keys"
        kind = "yaml-mapping"
        source = "keys.yaml"
        section = "keys"
        closed = true
        syntax = '\\bapp\\.[a-z_]+'
        only = ["pkg/in.py"]
        """).lstrip())
    assert main(["undeclared", "-c", str(tmp_path / "kinemata.toml")]) == 1
    out = capsys.readouterr().out
    assert "app.stray" in out and "app.other" not in out


@pytest.mark.parametrize(
    ("only", "refusal"),
    [
        ("only = []", "is empty"),
        ('only = "pkg/bootstrap.py"', "one character at a time"),
        ('only = ["pkg/boot.py"]', "matches no file it reads"),
        ('only = ["boot"]', "never part of a name"),
        ('only = ["README.md"]', "matches no file it reads"),  # not a .py file
    ],
    ids=["empty", "string", "typo", "part-of-a-name", "other-suffix"],
)
def test_a_scope_that_would_check_nothing_is_refused(tmp_path, only, refusal):
    with pytest.raises(ConfigError, match=refusal):
        load(project(tmp_path, only=only))


def test_a_narrowed_registry_keeps_its_scope(tmp_path, capsys):
    """``where`` wraps the registry; the wrapper must carry ``only`` over."""
    path = project(
        tmp_path,
        only='only = ["pkg/bootstrap.py"]\nwhere = { id_matches = "^no-" }',
    )
    status, out = check(path, capsys)
    assert status == 1
    assert "pkg/bootstrap.py:1" in out and "pkg/app.py" not in out
