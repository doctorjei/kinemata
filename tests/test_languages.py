"""Shell, YAML and TOML read the way ``.py`` is: comments are nothing, a literal
that IS a declared value is strong, a literal merely containing it is weak.

The rule is the user's, 2026-09-24, on three lines: ``# see box.yaml for the
format`` *"in sh or py or any source, this should not be an error ... consistent
(so nothing, since comments are nothing for py)"*, and ``"restoring
box.yaml.bak"`` *"should be weak, just like the py example"*. Before, every
suffix but ``.py`` read raw lines and every hit was strong.

The reader cases lean on what a naive ``#`` strip gets wrong, because that is
the failure that hides a real bypass: a ``#`` in quotes, a heredoc, a block
scalar or a URL is content.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.cli import main
from kinemata.languages import (
    shell_code_only,
    shell_literals,
    toml_code_only,
    toml_literals,
    yaml_code_only,
    yaml_literals,
)


def contents(literals):
    return [content for _, content, _ in literals]


# -- end to end: the three lines the rule was stated on ------------------------


@pytest.mark.parametrize(
    ("name", "body"),
    [
        ("deploy.sh", """
            #!/bin/sh
            # see box.yaml for the format
            cp box.yaml "$DEST"
            echo "restoring box.yaml.bak"
            """),
        ("settings.yaml", """
            # see box.yaml for the format
            meta: box.yaml
            note: restored from box.yaml.bak
            """),
        ("settings.toml", """
            # see box.yaml for the format
            meta = "box.yaml"
            note = "restored from box.yaml.bak"
            """),
    ],
)
def test_a_comment_is_nothing_a_whole_literal_strong_a_longer_one_weak(
    tmp_path, capsys, name, body
):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "config.py").write_text('BOX_META_FILE = "box.yaml"\n')
    (tmp_path / name).write_text(textwrap.dedent(body).lstrip())
    suffix = name.rsplit(".", 1)[1]
    (tmp_path / "kinemata.toml").write_text(textwrap.dedent(f"""
        [project]
        root = "."
        suffixes = [".py", ".{suffix}"]

        [[registry]]
        name = "meta-files"
        kind = "python-constants"
        modules = ["pkg/config.py"]
        """).lstrip())
    assert main(["check", "-v", "-c", str(tmp_path / "kinemata.toml")]) == 1
    out = capsys.readouterr().out
    strong, _, weak = out.partition("Weak")
    assert f"{name}:1" not in out  # the comment
    assert f"{name}:{2 if suffix != 'sh' else 3}" in strong  # the whole literal
    assert f"{name}:{3 if suffix != 'sh' else 4}" in weak  # the longer one


# -- shell ---------------------------------------------------------------------


def test_a_shell_comment_starts_only_at_a_word():
    source = 'echo a#b $# ${#x} "q # q"  # real\n'
    assert contents(shell_literals(source)) == ["echo", "a#b", "$#", "${#x}", "q # q"]
    assert shell_code_only(source) == 'echo a#b $# ${#x} "q # q"\n'


def test_a_shell_word_joins_its_quoted_parts():
    assert contents(shell_literals('git log --name="box.yaml"\n'))[-1] == "--name=box.yaml"


def test_a_shell_assignment_s_value_is_the_literal():
    assert contents(shell_literals('FILE="box.yaml"\nexport X=y\n')) == [
        "box.yaml", "export", "y",
    ]


def test_a_heredoc_body_is_one_literal_and_its_hash_is_content():
    source = "cat <<'EOF' > out\n# kept\nbox.yaml\nEOF\necho done\n"
    literals = shell_literals(source)
    assert (2, "# kept\nbox.yaml", "# kept") in literals
    assert "EOF" not in contents(literals)
    assert "# kept" in shell_code_only(source)


def test_a_shell_quote_spanning_lines_is_one_literal():
    assert "a\nb" in contents(shell_literals('echo "a\nb"\n'))


# -- YAML ----------------------------------------------------------------------


def test_yaml_keys_and_string_values_are_literals_and_other_scalars_are_not():
    assert contents(yaml_literals("port: 8080\nname: box.yaml\nok: true\n")) == [
        "port", "name", "box.yaml", "ok",
    ]


def test_a_yaml_hash_is_a_comment_only_after_whitespace_and_outside_quotes():
    source = 'url: http://x/#frag\nnote: "a # b"  # real\n'
    assert contents(yaml_literals(source)) == ["url", "http://x/#frag", "note", "a # b"]
    assert yaml_code_only(source) == 'url: http://x/#frag\nnote: "a # b"\n'


def test_a_block_scalar_is_one_literal_and_its_hash_is_content():
    source = "desc: |\n  # kept\n  box.yaml\nnext: x\n"
    literals = yaml_literals(source)
    assert (2, "# kept\nbox.yaml", "  # kept") in literals
    assert "# kept" in yaml_code_only(source)


def test_yaml_flow_collections_and_quote_escapes():
    assert contents(yaml_literals("l: [a, 'b''s', \"c\\\"d\"]\n")) == [
        "l", "a", "b's", 'c"d',
    ]


# -- TOML ----------------------------------------------------------------------


def test_toml_strings_are_literals_and_bare_keys_are_not():
    source = 'file = "box.yaml"\n"quoted.key" = \'lit # kept\'\nn = 3\n'
    assert contents(toml_literals(source)) == ["box.yaml", "quoted.key", "lit # kept"]


def test_a_toml_comment_is_blanked_and_a_hash_in_a_string_is_not():
    source = 'a = "x # y"  # real\n'
    assert toml_code_only(source) == 'a = "x # y"\n'


def test_a_toml_multiline_string_is_one_literal():
    source = 'm = """\nline\nbox.yaml"""\n'
    assert (1, "line\nbox.yaml", 'm = """') in toml_literals(source)


def test_toml_basic_escapes_are_read():
    assert contents(toml_literals('a = "q\\"\\u0041"\n')) == ['q"A']


# -- every reader keeps every line ----------------------------------------------


@pytest.mark.parametrize(
    ("strip", "source"),
    [
        (shell_code_only, "# a\necho x # b\n\n# c\n"),
        (yaml_code_only, "# a\nk: v # b\n\n# c\n"),
        (toml_code_only, "# a\nk = 1 # b\n\n# c\n"),
    ],
)
def test_a_stripped_file_keeps_its_line_count(strip, source):
    """A finding's line number is the file's, so no line may be dropped."""
    assert strip(source).count("\n") == source.count("\n")
