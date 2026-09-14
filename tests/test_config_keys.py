"""Every config table refuses a key it cannot mean.

**The incident.** An adopter wrote two ``[[gate]]`` tables between ``suffixes``
and ``historical`` inside ``[claims]``. TOML gives every bare key to the most
recent table, so ``historical`` became a key of the second gate, the suppression
it declared stopped applying, and nothing said so: no error, no warning, no
unknown-key complaint. The only symptom was the claim denominator moving between
two runs of the same command, which they noticed because they happened to be
comparing runs.

That is this package's own failure shape -- *the check reports success while
checking less than it says* -- reached through its config layer rather than
through a check. These tests pin the refusal for **every** table, because the
report named ``[[gate]]`` and fixing only ``[[gate]]`` would repeat the mistake
the same adopter described in the same letter: a correction issued over a set
after checking only the member that prompted it.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.config import ConfigError, load


def write(tmp_path, body, name="kinemata.toml"):
    path = tmp_path / name
    path.write_text(textwrap.dedent(body).lstrip())
    return path


REGISTRY = """
    [[registry]]
    name = "values"
    kind = "python-constants"
    modules = ["values.py"]
"""


def load_with(tmp_path, body):
    (tmp_path / "values.py").write_text("NAME = 'x'\n")
    return load(write(tmp_path, REGISTRY + textwrap.dedent(body)))


# -- the incident, reproduced ------------------------------------------------


def test_a_gate_carrying_a_stolen_claims_key_is_refused(tmp_path):
    """The adopter's config, reduced to the two lines that mattered."""
    with pytest.raises(ConfigError) as caught:
        load_with(
            tmp_path,
            """
            [claims]
            suffixes = [".md"]

            [[gate]]
            command = "kinemata check"

            historical = ["archives/"]
            """,
        )
    message = str(caught.value)
    assert "historical" in message
    assert "[[gate]] 0" in message


def test_the_refusal_explains_why_the_key_landed_where_it_did(tmp_path):
    """Refusing the key is half an answer; the reader wrote it under `[claims]`.

    Without this sentence the error names a key the author never typed inside a
    gate, under a heading they did not associate with it.
    """
    with pytest.raises(ConfigError) as caught:
        load_with(
            tmp_path,
            """
            [[gate]]
            command = "kinemata check"
            historical = ["archives/"]
            """,
        )
    message = str(caught.value)
    assert "array-of-tables takes every bare key written after it" in message
    assert "moved above the first one" in message


def test_a_plain_table_is_refused_without_the_absorption_note(tmp_path):
    """`[claims]` steals from nobody, so the sentence would be a wrong guess."""
    with pytest.raises(ConfigError) as caught:
        load_with(
            tmp_path,
            """
            [claims]
            historcal = ["archives/"]
            """,
        )
    message = str(caught.value)
    assert "historcal" in message and "[claims]" in message
    assert "array-of-tables" not in message


# -- every table, not the one that prompted the report -----------------------


@pytest.mark.parametrize(
    "body, where",
    [
        ('[project]\nexlcude = ["x/"]\n', "[project]"),
        ('[claims]\nhistorcal = ["x/"]\n', "[claims]"),
        (
            '[context]\ninclude = ["*.md"]\nbudget = 1000\nstip = ["comments"]\n',
            "[context]",
        ),
        ('[[gate]]\ncommand = "x"\nnotes = "y"\n', "[[gate]] 0"),
        (
            '[[count]]\ncommand = ["echo", "1"]\npattern = "p"\n'
            'extract = "e"\nlabl = "n"\n',
            "[[count]] 0",
        ),
        (
            '[[parity]]\nregistry = "values"\ncommand = ["echo"]\n'
            'extract = "e"\nfeild = "default"\n',
            "[[parity]] 0",
        ),
        (
            '[[interpose]]\nregistry = "values"\ntarget = "m:f"\n'
            'identify = "m:i"\nregistery = "values"\n',
            "[[interpose]] 0",
        ),
        (
            '[[shape]]\nregistry = "values"\nrules = []\n',
            "[[shape]] 0",
        ),
    ],
)
def test_each_table_refuses_an_unknown_key(tmp_path, body, where):
    with pytest.raises(ConfigError) as caught:
        load_with(tmp_path, body)
    assert where in str(caught.value)


# -- the two tables that were still absorbing ---------------------------------


def test_a_misspelled_gate_array_is_refused_at_the_document_root(tmp_path):
    """The spelling that disarms a check rather than decorating one.

    `[[gates]]` loaded without complaint and declared zero gates, so the
    inventory saying *these checks must still run* was never declared at all --
    and the only guard, "this config declares no check whatsoever", is satisfied
    by the registry sitting next to it.
    """
    with pytest.raises(ConfigError) as caught:
        load_with(tmp_path, '[[gates]]\ncommand = "kinemata check"\n')
    message = str(caught.value)
    assert "gates" in message and "document root" in message
    assert "gate" in message  # what it could have been


def test_the_root_is_refused_before_anything_is_read_out_of_it(tmp_path):
    """A config whose only check is the misspelled one must not read as empty."""
    with pytest.raises(ConfigError) as caught:
        load(write(tmp_path, '[[gates]]\ncommand = "kinemata check"\n'))
    assert "document root" in str(caught.value)
    assert "declares no check at all" not in str(caught.value)


def test_a_registry_refuses_a_key_no_kind_declares(tmp_path):
    with pytest.raises(ConfigError) as caught:
        load(
            write(
                tmp_path,
                """
                [[registry]]
                name = "values"
                kind = "python-constants"
                modules = ["values.py"]
                mach1nery = ["build/"]
                """,
            )
        )
    assert "mach1nery" in str(caught.value)


def test_a_registry_refuses_a_key_that_belongs_to_another_kind(tmp_path):
    """Differenced per kind, never unioned.

    `section` is real, and means nothing at all on a registry of Python
    constants. A union of every kind's vocabulary would take it and read it to
    nobody, which is the same silence this whole file is about.
    """
    with pytest.raises(ConfigError) as caught:
        load(
            write(
                tmp_path,
                """
                [[registry]]
                name = "values"
                kind = "python-constants"
                modules = ["values.py"]
                section = "keys"
                """,
            )
        )
    message = str(caught.value)
    assert "section" in message and "python-constants" in message


def test_a_registry_says_the_key_was_absorbed_from_an_enclosing_table(tmp_path):
    """`[[registry]]` is an array-of-tables, so it steals like `[[gate]]` does."""
    (tmp_path / "values.py").write_text("NAME = 'x'\n")
    with pytest.raises(ConfigError) as caught:
        load(
            write(
                tmp_path,
                """
                [project]
                root = "."

                [[registry]]
                name = "values"
                kind = "python-constants"
                modules = ["values.py"]
                exclude = ["build/"]
                """,
            )
        )
    message = str(caught.value)
    assert "exclude" in message and "array-of-tables" in message


def test_an_import_registry_still_takes_keys_this_file_does_not_know(tmp_path):
    """The one kind deliberately left out, and why.

    Everything `IMPORT_KEYS` does not name is handed to the project's own class
    as a keyword argument. Refusing an unrecognized key there would refuse the
    parameterization that naming a class exists to allow -- so that kind checks
    its own vocabulary, through its constructor.
    """
    from kinemata.config import KIND_KEYS

    assert "import" not in KIND_KEYS


def test_a_shape_rule_refuses_an_unknown_key(tmp_path):
    """`[[shape.rule]]` absorbs from `[[shape]]` exactly as `[[gate]]` does."""
    with pytest.raises(ConfigError) as caught:
        load_with(
            tmp_path,
            """
            [[shape]]
            registry = "values"

            [[shape.rule]]
            name = "every entry has a default"
            present = "default"
            feild = "default"
            """,
        )
    assert "feild" in str(caught.value)
    assert "[[shape.rule]] 0" in str(caught.value)


def test_a_rule_may_spell_any_claim_the_evaluator_knows(tmp_path):
    """The known set is read from `SHAPE_CLAIMS`, never restated.

    A second list would let an operator be accepted by the config layer and
    rejected by the evaluator, or the reverse -- the failure the two operator
    tables are already asserted equal to prevent.
    """
    from kinemata.config import RULE_KEYS, SHAPE_CLAIMS

    config = load_with(
        tmp_path,
        """
        [[shape]]
        registry = "values"

        [[shape.rule]]
        name = "ids look like constants"
        id_matches = "^[A-Z_]+$"
        """,
    )
    assert config.shapes[0].rules[0].name == "ids look like constants"
    assert not RULE_KEYS & frozenset(SHAPE_CLAIMS)


# -- what must keep loading --------------------------------------------------


def test_a_retired_key_still_gets_its_migration_message(tmp_path):
    """`[claims] promised` is known-but-refused, and the order matters.

    A generic "means nothing here" would reach it first and drop the one thing
    the author needs: where the key went.
    """
    with pytest.raises(ConfigError) as caught:
        load_with(
            tmp_path,
            """
            [claims]
            promised = ["docs/x.md"]
            """,
        )
    assert "[[promise]]" in str(caught.value)


def test_this_repository_s_own_config_still_loads():
    """The check is worthless if it refuses the tree that ships it."""
    from pathlib import Path

    config = load(Path(__file__).resolve().parent.parent / "kinemata.toml")
    assert config.gates and config.registries
