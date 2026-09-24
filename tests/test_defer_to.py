"""``defer_to``: a closed registry handing a candidate to the registry declaring it.

Reported by an adopting project on 2026-09-24: its closed keyspace spots
key-shaped tokens, and ``BOX_META_FILE = "box.yaml"`` -- the line *declaring*
that filename as another registry's constant -- was an undeclared key. Two
vocabularies shared one lexical shape, and nothing separates them but which
registry declares which.

The case these tests are built around is the one that made the obvious fix
wrong. That project's constants registry also holds **key strings**
(``SETUP_MARKER_KEY``), so deferring to *every* registry's values would have
silenced a mistyped key constant at the only line its literal appears on. The
deference is therefore declared, and a mixed registry is narrowed with
``where`` before anything defers to it.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.cli import _gating_strays, _strays, main
from kinemata.config import ConfigError, load

KEYSPACE = """
    [project]
    root = "."

    [[registry]]
    name = "keyspace"
    kind = "yaml-mapping"
    source = "keys.yaml"
    section = "keys"
    closed = true
    syntax = '\\bbox\\.[a-z_]+(?:\\.[a-z_]+)*\\b'
    {defer}

    [[registry]]
    name = "meta-files"
    kind = "python-constants"
    modules = ["pkg/config.py"]

    [[registry]]
    name = "filenames"
    kind = "python-constants"
    modules = ["pkg/config.py"]
    where = {{ id_matches = "_FILE$" }}
"""


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def project(tmp_path, defer=""):
    write(tmp_path, "keys.yaml", "keys:\n  box.enable_vault: {}\n")
    # One filename constant and one KEY constant, mistyped, in one module --
    # the mix the adopter's own registry holds.
    write(tmp_path, "pkg/config.py", """
        BOX_META_FILE = "box.yaml"
        SETUP_MARKER_KEY = "box.setup_completd"
        """)
    write(tmp_path, "pkg/use.py", """
        KEY = "box.enable_vault"
        STRAY = "box.nonsense"
        AGAIN = "box.yaml"
        NEAR = "box.yaml_old"
        """)
    write(tmp_path, "kinemata.toml", KEYSPACE.format(defer=defer))
    return tmp_path / "kinemata.toml"


def undeclared(path, capsys):
    status = main(["undeclared", "--config", str(path)])
    return status, capsys.readouterr().out


def test_without_a_deferral_the_declaration_home_is_reported(tmp_path, capsys):
    """The reported behavior, pinned as the default: deference is opt-in."""
    status, out = undeclared(project(tmp_path), capsys)
    assert status == 1
    assert "pkg/config.py:1: box.yaml" in out
    assert "deferred:" not in out


def test_a_deferral_hands_over_the_values_and_keeps_the_key_typo(tmp_path, capsys):
    status, out = undeclared(project(tmp_path, 'defer_to = ["filenames"]'), capsys)
    assert status == 1
    assert "box.yaml" not in out.replace("box.yaml_old", "")
    # The catch the generic fix would have lost, and the ordinary stray.
    assert "pkg/config.py:2: box.setup_completd" in out
    assert "pkg/use.py:2: box.nonsense" in out
    assert "deferred: 2 to filenames (declared there as a value)" in out


def test_a_partial_match_is_not_deferred(tmp_path, capsys):
    """``box.yaml_old`` is not the value ``box.yaml``; the whole candidate must be."""
    _, out = undeclared(project(tmp_path, 'defer_to = ["filenames"]'), capsys)
    assert "pkg/use.py:4: box.yaml_old" in out


def test_deferring_to_a_mixed_registry_hands_over_its_keys_too(tmp_path, capsys):
    """Why the project chooses, and why ``where`` is the tool for choosing.

    Deferred to the unnarrowed registry, the mistyped key constant is that
    registry's declared value, and the keyspace stops reporting it.
    """
    _, out = undeclared(project(tmp_path, 'defer_to = ["meta-files"]'), capsys)
    assert "box.setup_completd" not in out
    assert "deferred: 3 to meta-files" in out


def test_baseline_records_exactly_what_undeclared_fails_on(tmp_path):
    """Both read ``_strays``, so a deferred candidate is never an exemption."""

    class Args:
        registry = None
        path = None

    path = project(tmp_path, 'defer_to = ["filenames"]')
    settings = load(path)
    recorded = [hit.entry_id for _, hit in _gating_strays(_strays(Args(), settings, tmp_path))]
    assert sorted(recorded) == ["box.nonsense", "box.setup_completd", "box.yaml_old"]


def test_a_narrowed_registry_keeps_its_deferral(tmp_path, capsys):
    """``where`` wraps the registry; the wrapper must carry ``defer_to`` over.

    Open, because ``closed`` with ``where`` is refused on its own grounds -- and
    an open registry's advisory list is still narrowed by what it hands over.
    """
    path = project(tmp_path, 'defer_to = ["filenames"]\nwhere = { id_matches = "^box" }')
    path.write_text(path.read_text().replace("closed = true", "closed = false", 1))
    status, out = undeclared(path, capsys)
    assert status == 0
    assert "deferred: 2 to filenames" in out


@pytest.mark.parametrize(
    ("defer", "refusal"),
    [
        ('defer_to = "filenames"', "would be read one character at a time"),
        ("defer_to = []", "non-empty list of registry names"),
        ('defer_to = ["nobody"]', "no loaded registry is called"),
        ('defer_to = ["keyspace"]', "defers to itself"),
    ],
)
def test_a_deferral_that_would_do_nothing_is_refused(tmp_path, defer, refusal):
    with pytest.raises(ConfigError, match=refusal):
        load(project(tmp_path, defer))


def test_deferring_to_a_registry_that_declares_no_values_is_refused(tmp_path):
    """A mapping of keys carries no antipattern, so nothing could ever match."""
    path = project(tmp_path)
    write(tmp_path, "other.yaml", "keys:\n  box.other: {}\n")
    text = path.read_text().replace(
        "closed = true\n",
        'closed = true\ndefer_to = ["other"]\n',
        1,
    ) + textwrap.dedent("""
        [[registry]]
        name = "other"
        kind = "yaml-mapping"
        source = "other.yaml"
        section = "keys"
        """)
    path.write_text(text)
    with pytest.raises(ConfigError, match="none of whose entries declares a value"):
        load(path)


def test_a_registry_with_no_candidates_cannot_defer(tmp_path):
    path = project(tmp_path)
    path.write_text(path.read_text().replace(
        'modules = ["pkg/config.py"]\n',
        'modules = ["pkg/config.py"]\ndefer_to = ["filenames"]\n',
        1,
    ))
    with pytest.raises(ConfigError, match="recognizes no identifiers"):
        load(path)
