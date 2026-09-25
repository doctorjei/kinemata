"""Every reducer keeps a file's line count, including a trailing blank line.

The filters blank in place so that a line number or an offset read from the
reduced text points at the same place in the file on disk. Five of them joined
their lines with ``"\\n".join``, which drops the final line break, so a file
ending in a blank line came back one line short. ``kinemata confirm`` asserts
the count, and refused outright on this package's own ``coverage.py`` when it
was first written with one (found by the gate sweep, 2026-09-25).
"""

from __future__ import annotations

import pytest

import kinemata.bypass as bypass
import kinemata.prose as prose

SAMPLES = {
    ".py": ['x = 1  # note\n\n', '"""doc"""\n\n\n', "x = 1\n", "x = 1"],
    ".md": ["text\n\n", "```\ncode\n```\n\n\n", "text"],
    ".sh": ["echo hi\n\n"],
    ".yaml": ["a: 1\n\n"],
    ".yml": ["a: 1\n\n"],
    ".toml": ["a = 1\n\n"],
}


def reducers():
    tables = {
        name: table
        for name in dir(prose)
        if name.endswith("FILTERS") and isinstance(table := getattr(prose, name), dict)
    }
    tables.update({f"MODE_FILTERS[{mode}]": table for mode, table in bypass.MODE_FILTERS.items()})
    for name, table in sorted(tables.items()):
        for suffix, reduce in table.items():
            for source in SAMPLES.get(suffix, []):
                yield pytest.param(reduce, source, id=f"{name}{suffix}:{source!r}")


@pytest.mark.parametrize(("reduce", "source"), list(reducers()))
def test_a_reducer_keeps_the_line_count(reduce, source):
    assert len(reduce(source).splitlines()) == len(source.splitlines())


def test_confirm_reads_a_module_ending_in_a_blank_line(tmp_path, capsys):
    from kinemata.cli import main

    (tmp_path / "module.py").write_text('"""A module."""\n\nX = 1\n\n')
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/design.md").write_text("the contract\n")
    (tmp_path / "docs/bibliography.toml").write_text(
        '[[entry]]\nkey = "Pa0003"\ntarget = "docs/design.md"\nnote = "the contract"\n'
    )
    (tmp_path / "kinemata.toml").write_text(
        '[project]\nroot = "."\n\n[claims]\nsuffixes = [".py"]\n\n'
        '[[registry]]\nname = "sources"\nkind = "bibliography"\n'
        'source = "docs/bibliography.toml"\nsuffixes = [".py"]\n'
    )
    status = main(["confirm", "--config", str(tmp_path / "kinemata.toml")])
    assert status == 0, capsys.readouterr().err
