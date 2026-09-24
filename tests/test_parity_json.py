"""``[[parity]] format = "json"``: comparing a field's values as data.

The ``text`` form renders the declared cell with ``str`` and refuses any cell
holding a mapping, and one such cell stands the whole registry's value
comparison down. An adopter measured 18 of their 66 ``default`` rows as
mode-keyed maps -- reachable one arm at a time through a path, never as the
column they are. JSON is a spelling for a map that the declaration does not have
to invent, and parsing it back compares data rather than two renderings.
"""

from __future__ import annotations

import json
import textwrap

import pytest

from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.parity import Oracle, compare


def project(tmp_path, rows, printed, extra='format = "json"'):
    """A yaml registry of ``rows`` and an oracle printing ``printed`` as JSON.

    ``printed`` maps an identifier to a value, or to a list of raw strings to
    print verbatim (for output that is not JSON, or more than one line).
    """
    (tmp_path / "keys.yaml").write_text("keys:\n" + "".join(
        f"  {key}: {json.dumps(row)}\n" for key, row in rows.items()
    ))
    lines = []
    for key, value in printed.items():
        raws = value if isinstance(value, list) else [json.dumps(value)]
        lines += [f"{key} {raw}" for raw in raws]
    (tmp_path / "oracle.py").write_text(
        "print(" + repr("\n".join(lines)) + ")\n"
    )
    (tmp_path / "kinemata.toml").write_text(textwrap.dedent(f"""
        [project]
        root = "."

        [[registry]]
        name = "keys"
        kind = "yaml-mapping"
        source = "keys.yaml"
        section = "keys"

        [[parity]]
        registry = "keys"
        command = ["{{python}}", "oracle.py"]
        extract = '(?m)^(\\S+) (.*)$'
        field = "default"
        authority = "declared"
        {extra}
        """).lstrip())
    return str(tmp_path / "kinemata.toml")


def run(path, capsys):
    status = main(["parity", "-c", path])
    captured = capsys.readouterr()
    return status, captured.out + captured.err


MAP = {"primary": "p", "named": "n"}


def test_a_column_of_scalars_and_maps_is_one_comparison(tmp_path, capsys):
    """The adopter's shape, and a map printed in another key order agreeing."""
    path = project(
        tmp_path,
        {"a.scalar": {"default": "x"}, "b.map": {"default": MAP}},
        {"a.scalar": "x", "b.map": {"named": "n", "primary": "p"}},
    )
    status, out = run(path, capsys)
    assert status == 0, out


def test_a_wrong_arm_diverges_and_names_both_values(tmp_path, capsys):
    path = project(
        tmp_path,
        {"b.map": {"default": MAP}},
        {"b.map": {"primary": "p", "named": "WRONG"}},
    )
    status, out = run(path, capsys)
    assert status == 1
    assert '{"named":"n","primary":"p"}' in out
    assert '{"named":"WRONG","primary":"p"}' in out


def test_the_text_form_still_refuses_a_map(tmp_path, capsys):
    """The default is unchanged: a declaration written before the key keeps its reading."""
    path = project(
        tmp_path, {"b.map": {"default": MAP}}, {"b.map": MAP}, extra=""
    )
    status, out = run(path, capsys)
    assert status == 1
    assert "not a scalar or a list" in out


def test_a_declared_null_is_a_value_and_an_absent_field_is_not(tmp_path, capsys):
    """The text form collapses these; as data they are different claims."""
    path = project(
        tmp_path,
        {"d.null": {"default": None}, "e.absent": {"other": 1}},
        {"d.null": None, "e.absent": None},
    )
    status, out = run(path, capsys)
    assert status == 1
    assert "d.null" not in out
    assert "e.absent: the declaration records no default" in out


def test_types_are_kept(tmp_path, capsys):
    """``1``, ``"1"`` and ``true`` are three values, not one spelling."""
    path = project(
        tmp_path,
        {"n": {"default": 1}, "b": {"default": True}},
        {"n": "1", "b": 1},
    )
    status, out = run(path, capsys)
    assert status == 1
    assert "n: default declared '1', code produces '\"1\"'" in out
    assert "b: default declared 'true', code produces '1'" in out


def test_output_that_is_not_json_diverges_on_its_row_only(tmp_path, capsys):
    path = project(
        tmp_path,
        {"good": {"default": "x"}, "bad": {"default": "y"}},
        {"good": "x", "bad": ["y"]},  # bare y: not JSON
    )
    status, out = run(path, capsys)
    assert status == 1
    assert "<not JSON: y>" in out
    assert "good" not in out


def test_two_values_printed_for_one_identifier_diverge(tmp_path, capsys):
    path = project(
        tmp_path, {"k": {"default": "x"}}, {"k": ['"x"', '"x"']}
    )
    status, out = run(path, capsys)
    assert status == 1
    assert "k: default" in out


def test_membership_still_runs_beside_the_values(tmp_path, capsys):
    """A value comparison runs on top of membership, never instead of it."""
    path = project(
        tmp_path, {"k": {"default": "x"}}, {"k": "x", "extra.key": "y"}
    )
    status, out = run(path, capsys)
    assert status == 1
    assert "extra.key" in out


def test_a_value_json_cannot_spell_blocks_rather_than_guessing(tmp_path, capsys):
    """A YAML date has no JSON spelling; rendering it some other way is the guess."""
    path = project(tmp_path, {"k": {"default": "x"}}, {"k": "x"})
    keys = tmp_path / "keys.yaml"
    keys.write_text("keys:\n  k:\n    default: 2026-09-24\n")
    status, out = run(path, capsys)
    assert status == 1
    assert "JSON cannot spell" in out


@pytest.mark.parametrize(
    ("extra", "refusal"),
    [
        ('format = "yaml"', "must be one of text, json"),
        ('format = "json"\nordered = true', "already compared in order"),
        ('format = "json"\ntranslate = { from = "a", to = "b" }', "rewrite of text"),
    ],
)
def test_a_format_that_would_mean_nothing_is_refused(tmp_path, extra, refusal):
    path = project(tmp_path, {"k": {"default": "x"}}, {"k": "x"}, extra=extra)
    with pytest.raises(ConfigError, match=refusal):
        load(path)


def test_json_without_a_field_is_refused(tmp_path):
    path = project(tmp_path, {"k": {"default": "x"}}, {"k": "x"})
    text = open(path).read().replace('field = "default"\n', "").replace(
        'authority = "declared"\n', ""
    )
    open(path, "w").write(text)
    with pytest.raises(ConfigError, match="compares no field"):
        load(path)


def test_compare_refuses_the_same_spec_a_caller_assembles_itself(tmp_path):
    spec = Oracle(
        registry="keys", command=("true",), extract="(x)", format="json"
    )
    with pytest.raises(ValueError, match="json parity"):
        compare(object(), spec, tmp_path)
