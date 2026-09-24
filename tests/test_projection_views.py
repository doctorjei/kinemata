"""A view's projection is not printed twice.

A project comparing several fields of one declaration declares one
``[[registry]]`` view per field, because each field is carried by a different
subset of the rows and ``where`` is where that subset is stated. Measured on an
adopter's manifest: ``default`` is absent from 34 of its 99 ``keys`` rows and
``type`` from 23, so three views select 65, 76 and 99 rows, and each field's
``[[parity]]`` passes with every mutation caught and named in its own view.

**What that cost was the projection**, not the views: ``ids`` printed 240
identifier lines for 99 distinct keys, and the adopter measured one extra view
at +101 lines. The projection is the list an agent loads to see what already
exists, so a second copy of it is the context this package exists to keep down.
A view's *membership* is a question for the checks that read it, and
``ids -r NAME`` still answers it in full.
"""

from __future__ import annotations

import textwrap

from kinemata.cli import main

MANIFEST = """
    keys:
      alpha:
        type: path
        default: "/a"
      beta:
        type: path
      gamma:
        default: "/c"
    """


def build(tmp_path, *registries: str) -> str:
    (tmp_path / "keys.yaml").write_text(textwrap.dedent(MANIFEST).lstrip())
    blocks = "\n".join(
        textwrap.dedent(
            f"""
            [[registry]]
            name = "{name}"
            kind = "yaml-mapping"
            source = "keys.yaml"
            section = "keys"
            {where}
            """
        )
        for name, where in (spec.split("|", 1) for spec in registries)
    )
    config = tmp_path / "kinemata.toml"
    config.write_text('[project]\nroot = "."\n' + blocks)
    return str(config)


def run(capsys, *argv: str) -> list[str]:
    assert main(["ids", *argv]) == 0
    return capsys.readouterr().out.splitlines()


def test_a_view_inside_another_registry_prints_a_pointer_not_a_copy(tmp_path, capsys):
    config = build(tmp_path, 'keys|', 'typed|where = { present = "type" }')
    out = run(capsys, "-c", config)
    assert out == [
        "# keys (3 entries, 17 B)",
        "alpha",
        "beta",
        "gamma",
        "# typed (2 entries, every one listed under keys; "
        "`kinemata ids -r typed` prints them)",
    ]


def test_the_view_may_be_declared_before_the_registry_that_covers_it(tmp_path, capsys):
    """Declaration order decides nothing here but which of two EQUAL sets prints."""
    config = build(tmp_path, 'typed|where = { present = "type" }', 'keys|')
    out = run(capsys, "-c", config)
    assert out[0].startswith("# typed (2 entries, every one listed under keys;")
    assert out[1:] == ["# keys (3 entries, 17 B)", "alpha", "beta", "gamma"]


def test_of_two_identical_views_the_first_declared_prints(tmp_path, capsys):
    config = build(tmp_path, 'first|', 'second|')
    out = run(capsys, "-c", config)
    assert out[:4] == ["# first (3 entries, 17 B)", "alpha", "beta", "gamma"]
    assert out[4].startswith("# second (3 entries, every one listed under first;")
    assert len(out) == 5


def test_every_view_points_at_one_that_is_printed(tmp_path, capsys):
    """A chain -- defaulted inside typed-or-defaulted inside everything -- never
    points at a registry that was itself replaced by a pointer."""
    config = build(
        tmp_path,
        'defaulted|where = { present = "default" }',
        'keys|',
        'typed|where = { present = "type" }',
    )
    out = run(capsys, "-c", config)
    headers = [line for line in out if line.startswith("#")]
    assert all("listed under keys;" in line for line in headers if "listed" in line)
    assert sum(line in ("alpha", "beta", "gamma") for line in out) == 3


def test_views_that_only_overlap_are_both_printed(tmp_path, capsys):
    """A pointer is only honest when every line is under the other header. For
    a partial overlap it would drop the lines the other registry lacks."""
    config = build(
        tmp_path,
        'typed|where = { present = "type" }',
        'defaulted|where = { present = "default" }',
    )
    out = run(capsys, "-c", config)
    assert out == [
        "# typed (2 entries, 11 B)", "alpha", "beta",
        "# defaulted (2 entries, 12 B)", "alpha", "gamma",
    ]


def test_naming_the_view_prints_it_in_full(tmp_path, capsys):
    config = build(tmp_path, 'keys|', 'typed|where = { present = "type" }')
    assert run(capsys, "-c", config, "-r", "typed") == [
        "# typed (2 entries, 11 B)", "alpha", "beta",
    ]


def test_quiet_prints_each_line_once(tmp_path, capsys):
    config = build(tmp_path, 'keys|', 'typed|where = { present = "type" }')
    assert run(capsys, "-c", config, "-q") == ["alpha", "beta", "gamma"]


def test_a_view_that_is_not_printed_still_answers_for_its_budget(tmp_path, capsys):
    """The budget belongs to the registry, not to what this run happened to
    print. Skipping it would make a pointer a way to silence a warning."""
    config = build(tmp_path, 'keys|', 'typed|where = { present = "type" }\nbudget = 4')
    assert main(["ids", "-c", config, "--strict"]) == 1
    captured = capsys.readouterr()
    assert "over its 4 B budget" in captured.err
    assert "every one listed under keys" in captured.out


def test_an_empty_registry_is_not_called_covered(tmp_path, capsys):
    """Nothing is a subset of everything, and a pointer from it would say its
    lines are elsewhere when it has none."""
    config = build(tmp_path, 'keys|')
    (tmp_path / "empty.yaml").write_text("keys: {}\n")
    with open(config, "a") as handle:
        handle.write(textwrap.dedent(
            """
            [[registry]]
            name = "none"
            kind = "yaml-mapping"
            source = "empty.yaml"
            section = "keys"
            allow_empty = true
            """
        ))
    out = run(capsys, "-c", config)
    assert "# none (0 entries, 0 B)" in out
