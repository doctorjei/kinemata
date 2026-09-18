"""A scalar a TOML file declares, as the identifier itself.

Every other adapter makes an identifier out of a *name*. This one makes it out
of the value, which is what a claim like "the version this tree declares is not
already on the index" needs on its declared side.

The relation that claim uses was **not** built for it: ``relation = "disjoint"``
already answered both directions against the live index before any of this
existed, measured in a scratch tree. What was missing was only a way to get the
value into a registry without the project writing a ``kind = "import"`` class,
which is what these tests cover.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.config import ConfigError, load


def build(tmp_path, toml_body, path='["project", "version"]', extra=""):
    (tmp_path / "subject.toml").write_text(textwrap.dedent(toml_body).lstrip())
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            root = "."

            [[registry]]
            name = "tree-version"
            kind = "toml-value"
            source = "subject.toml"
            path = {path}
            {extra}
            """
        ).lstrip()
    )
    return load(tmp_path / "kinemata.toml")


def ids(settings):
    return [entry.id for entry in settings.registries[0].entries()]


PYPROJECT = """
    [project]
    name = "subject"
    version = "0.1.3.dev1"
"""


def test_a_scalar_becomes_one_entry_spelled_as_itself(tmp_path):
    assert ids(build(tmp_path, PYPROJECT)) == ["0.1.3.dev1"]


def test_one_key_is_a_path_of_one(tmp_path):
    """A bare string addresses a top-level value, as `section` always has."""
    settings = build(tmp_path, 'top = "value"\n', path='"top"')
    assert ids(settings) == ["value"]


def test_a_flat_list_becomes_one_entry_each(tmp_path):
    settings = build(
        tmp_path,
        """
        [project]
        keywords = ["registry", "parity", "drift"]
        """,
        path='["project", "keywords"]',
    )
    assert ids(settings) == ["registry", "parity", "drift"]


def test_a_repeated_value_is_kept_rather_than_collapsed(tmp_path):
    """The declaration said it twice; a check may be looking for exactly that."""
    settings = build(
        tmp_path,
        """
        [project]
        keywords = ["a", "a", "b"]
        """,
        path='["project", "keywords"]',
    )
    assert ids(settings) == ["a", "a", "b"]


def test_extra_is_empty_because_the_value_is_the_identifier(tmp_path):
    """Not an oversight: `id` and `extra["value"]` would be one fact twice,
    which is the duplication this package reports on other people's code."""
    entry = next(iter(build(tmp_path, PYPROJECT).registries[0].entries()))
    assert entry.extra == {}


def test_a_number_renders_as_a_command_would_print_it(tmp_path):
    settings = build(tmp_path, "[schema]\nrevision = 4\n", path='["schema", "revision"]')
    assert ids(settings) == ["4"]


# -- refusals. Each one is verified by inducing it, not by a green run. --


def test_a_table_is_refused_and_the_refusal_names_the_way_on(tmp_path):
    """The remedy, not just the complaint: an author who stopped one key short
    is told which keys that level holds so they can finish the path."""
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, PYPROJECT, path='["project"]')
    message = str(caught.value)
    assert "reads the values themselves rather than the keys" in message
    assert "'name', 'version'" in message


def test_a_nested_list_is_refused(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, "[project]\nmatrix = [[1, 2], [3]]\n", path='["project", "matrix"]')
    assert "no spelling an oracle would print by accident" in str(caught.value)


def test_a_datetime_is_refused_though_toml_calls_it_a_scalar(tmp_path):
    """`str` of a datetime is a spelling no oracle agrees with by accident,
    which is the same line `parity` draws on the declared side."""
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, "[release]\ncut = 2026-09-18\n", path='["release", "cut"]')
    assert "which has no spelling an oracle would print" in str(caught.value)


def test_a_missing_segment_names_the_key_the_author_wrote(tmp_path):
    """`path`, never `section` -- this kind has no `section` to be told about."""
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, PYPROJECT, path='["project", "vershion"]')
    message = str(caught.value)
    assert "path segment 'vershion' is not in" in message
    assert "'name', 'version'" in message


def test_descending_through_a_scalar_is_refused(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, PYPROJECT, path='["project", "version", "major"]')
    assert "not a mapping, so 'major' cannot be looked up" in str(caught.value)


def test_no_path_is_refused(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, PYPROJECT, path="[]")
    assert "needs 'path'" in str(caught.value)


def test_no_source_is_refused(tmp_path):
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            """
            [project]
            root = "."

            [[registry]]
            name = "tree-version"
            kind = "toml-value"
            path = ["project", "version"]
            """
        ).lstrip()
    )
    with pytest.raises(ConfigError) as caught:
        load(tmp_path / "kinemata.toml")
    assert "needs 'source'" in str(caught.value)


def test_a_missing_file_is_refused(tmp_path):
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            """
            [project]
            root = "."

            [[registry]]
            name = "tree-version"
            kind = "toml-value"
            source = "nope.toml"
            path = ["project", "version"]
            """
        ).lstrip()
    )
    with pytest.raises(ConfigError) as caught:
        load(tmp_path / "kinemata.toml")
    assert "no such file" in str(caught.value)


def test_unreadable_toml_is_refused_as_toml_rather_than_crashing(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, "[project\nversion = 1\n")
    assert "not readable as TOML" in str(caught.value)


def test_an_unknown_key_is_refused_for_this_kind_too(tmp_path):
    """`KIND_KEYS` is differenced per kind, so a key another kind owns is
    refused here rather than accepted and read by nobody."""
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, PYPROJECT, extra='section = "project"')
    assert "section" in str(caught.value)


def test_closed_without_syntax_is_refused(tmp_path):
    """The contract's rule, not this adapter's: a registry that cannot
    recognize its own identifiers cannot answer the closed-world question."""
    with pytest.raises((ConfigError, ValueError)) as caught:
        build(tmp_path, PYPROJECT, extra="closed = true")
    assert "syntax" in str(caught.value)
