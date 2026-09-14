"""``claims`` refuses a scope nobody declared, like every other mechanism.

**The incident.** An adopter runs two commands against two configs. Their
registry-only config declares no ``[claims]`` at all -- they never run
``kinemata claims`` with it -- but the command ran anyway on built-in defaults,
and ``kinemata baseline --record`` wrote **356 claim findings** into that
config's baseline. Measured under *its* excludes, so not even the answer their
real claims config gives, and filed where nothing would ever consult it.

``parity``, ``shape``, ``context`` and ``undeclared`` all exit 2 when nothing
declares them. ``claims`` was the only mechanism that defaulted, and a scope
nobody chose is not a safe default: it is a second answer to a question another
config already answers differently.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.cli import main
from kinemata.config import load


def write(tmp_path, body, name="kinemata.toml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


REGISTRY_ONLY = """
    [[registry]]
    name = "values"
    kind = "python-constants"
    modules = ["values.py"]
"""

WITH_CLAIMS = REGISTRY_ONLY + """
[claims]
suffixes = [".md"]
"""


@pytest.fixture
def tree(tmp_path):
    (tmp_path / "values.py").write_text("NAME = 'x'\n")
    (tmp_path / "README.md").write_text("Nothing claimed here.\n")
    return tmp_path


# -- the refusal -------------------------------------------------------------


def test_claims_refuses_when_no_claims_table_is_declared(tree, capsys):
    write(tree, REGISTRY_ONLY)
    assert main(["claims", "-c", str(tree / "kinemata.toml")]) == 2
    assert "no [claims], no [[gate]]" in capsys.readouterr().err


def test_the_refusal_says_what_to_do(tree, capsys):
    write(tree, REGISTRY_ONLY)
    main(["claims", "-c", str(tree / "kinemata.toml")])
    said = capsys.readouterr().err
    assert "Declare one, or do not run this" in said


def test_an_empty_claims_table_is_a_declaration(tree):
    """`[claims]` with nothing under it is a project choosing the defaults.

    The discriminator is whether anyone wrote the heading, not whether they
    filled it in -- the adopter's fix was `suffixes = []`, which is a choice.
    """
    write(tree, REGISTRY_ONLY + "\n[claims]\n")
    assert load(tree / "kinemata.toml").claims_declared
    assert main(["claims", "-c", str(tree / "kinemata.toml")]) == 0


def test_claims_still_runs_where_it_is_declared(tree):
    write(tree, WITH_CLAIMS)
    assert main(["claims", "-c", str(tree / "kinemata.toml")]) == 0


# -- and the write path it was noticed through -------------------------------


def test_baseline_records_no_claim_findings_without_a_claims_table(tree, capsys):
    """The symptom that made it visible: a baseline nobody would read."""
    (tree / "NOTES.md").write_text("See `does/not/exist.md` for details.\n")
    write(tree, REGISTRY_ONLY)
    assert main(["baseline", "-c", str(tree / "kinemata.toml"), "--record",
                 "--until", "2099-01-01", "--by", "test"]) == 0
    recorded = (tree / ".kinemata-baseline.json").read_text()
    assert "does/not/exist.md" not in recorded


def test_baseline_still_records_them_where_claims_is_declared(tree):
    (tree / "NOTES.md").write_text("See `does/not/exist.md` for details.\n")
    write(tree, WITH_CLAIMS)
    assert main(["baseline", "-c", str(tree / "kinemata.toml"), "--record",
                 "--until", "2099-01-01", "--by", "test"]) == 0
    recorded = (tree / ".kinemata-baseline.json").read_text()
    assert "does/not/exist.md" in recorded


def test_this_repository_declares_claims_and_is_unaffected():
    """The refusal is worthless if it refuses the tree that ships it."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    assert load(root / "kinemata.toml").claims_declared
