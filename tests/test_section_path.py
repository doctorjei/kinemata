"""A registry addressing a nested section, by a declared path of keys.

``yaml-mapping`` took one top-level key, so a project whose declaration nests
its table -- ``policy.seed_whitelists`` -- could not address it at all. That is
an *addressing* limit rather than a limit of any check: a rule can only speak
about entries a registry produces, so a table the adapter cannot reach is a
table no mechanism here can say anything about.

Measured on a real adopter's manifest rather than guessed at: of their 31
declaration-shape rules, 9 are addressable with one top-level section and a
path reaches 18.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.config import ConfigError, load


def build(tmp_path, yaml_body, section):
    (tmp_path / "keys.yaml").write_text(textwrap.dedent(yaml_body).lstrip())
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            root = "."

            [[registry]]
            name = "keyspace"
            kind = "yaml-mapping"
            source = "keys.yaml"
            section = {section}
            """
        ).lstrip()
    )
    return load(tmp_path / "kinemata.toml")


def ids(settings):
    return sorted(entry.id for entry in settings.registries[0].entries())


NESTED = """
    policy:
      seed_whitelists:
        app.alpha:
          spec: first
        app.beta:
          spec: second
      other:
        app.gamma:
          spec: third
    """


# -- the form --------------------------------------------------------------


def test_a_two_segment_path_addresses_a_nested_table(tmp_path):
    settings = build(tmp_path, NESTED, '["policy", "seed_whitelists"]')
    assert ids(settings) == ["app.alpha", "app.beta"]


def test_a_three_segment_path_addresses_a_deeper_one(tmp_path):
    settings = build(
        tmp_path,
        """
        a:
          b:
            c:
              app.deep:
                spec: yes
        """,
        '["a", "b", "c"]',
    )
    assert ids(settings) == ["app.deep"]


def test_a_bare_string_is_one_segment_and_still_works(tmp_path):
    """Backward compatibility is total: no existing config changes meaning."""
    settings = build(
        tmp_path,
        """
        keys:
          app.alpha:
            spec: first
        """,
        '"keys"',
    )
    assert ids(settings) == ["app.alpha"]


def test_a_key_containing_a_dot_is_addressable(tmp_path):
    """The case the list form exists for.

    A dotted string could not express this without the loader guessing which of
    two splits the project meant, over a file it did not write.
    """
    settings = build(
        tmp_path,
        """
        policy.v2:
          app.alpha:
            spec: first
        """,
        '["policy.v2"]',
    )
    assert ids(settings) == ["app.alpha"]


# -- refusals, each naming what failed -------------------------------------


def test_a_missing_segment_names_itself_and_what_the_level_held(tmp_path):
    """"Section not found" against a deep path is a refusal somebody has to
    go and locate by hand."""
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, NESTED, '["policy", "seed_whitelist"]')
    message = str(caught.value)
    assert "'seed_whitelist'" in message          # the segment that failed
    assert "under 'policy'" in message            # where it was looked for
    assert "seed_whitelists" in message           # the near-miss, beside it
    assert "other" in message


def test_a_missing_first_segment_does_not_claim_to_be_under_anything(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, NESTED, '["polcy", "seed_whitelists"]')
    message = str(caught.value)
    assert "'polcy'" in message and "under" not in message
    assert "'policy'" in message


def test_a_segment_landing_on_a_list_is_refused_by_type(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(
            tmp_path,
            """
            policy:
              seed_whitelists:
                - app.alpha
                - app.beta
            """,
            '["policy", "seed_whitelists", "app.alpha"]',
        )
    message = str(caught.value)
    assert "list" in message and "not a mapping" in message


def test_a_path_ending_on_a_scalar_is_refused(tmp_path):
    """A mapping registry addresses a table of entries, not a value."""
    with pytest.raises(ConfigError) as caught:
        build(
            tmp_path,
            """
            policy:
              seed_whitelists: 4
            """,
            '["policy", "seed_whitelists"]',
        )
    message = str(caught.value)
    assert "int" in message and "not a mapping" in message


def test_an_empty_list_addresses_nothing_and_is_refused(tmp_path):
    """Refuse rather than silently meaning "the whole document"."""
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, NESTED, "[]")
    assert "empty list" in str(caught.value)


def test_a_section_that_is_neither_a_string_nor_a_list_is_refused(tmp_path):
    with pytest.raises(ConfigError) as caught:
        build(tmp_path, NESTED, "4")
    assert "takes one key, or a list of keys" in str(caught.value)


# -- the flatten: a two-level table as composite-id entries -----------------

CELLS = """
    cells:
      create:
        parent_missing: reject
        parent_present: accept
      delete:
        parent_missing: accept
    """


def build_flat(tmp_path, yaml_body, section, extra):
    (tmp_path / "keys.yaml").write_text(textwrap.dedent(yaml_body).lstrip())
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(
            f"""
            [project]
            root = "."

            [[registry]]
            name = "keyspace"
            kind = "yaml-mapping"
            source = "keys.yaml"
            section = {section}
            {extra}
            """
        ).lstrip()
    )
    return load(tmp_path / "kinemata.toml")


def test_a_two_level_map_becomes_composite_id_entries(tmp_path):
    """A cell had no identifier, so no rule could speak about one."""
    settings = build_flat(
        tmp_path, CELLS, '"cells"', 'flatten = 2\nseparator = "."'
    )
    assert ids(settings) == [
        "create.parent_missing",
        "create.parent_present",
        "delete.parent_missing",
    ]


def test_a_scalar_leaf_lands_in_value_by_the_existing_rule(tmp_path):
    """No new convention: `MappingRegistry` already decides this."""
    settings = build_flat(
        tmp_path, CELLS, '"cells"', 'flatten = 2\nseparator = "."'
    )
    entries = {entry.id: entry.extra for entry in settings.registries[0].entries()}
    assert entries["create.parent_missing"] == {"value": "reject"}


def test_a_mapping_leaf_still_becomes_extra(tmp_path):
    settings = build_flat(
        tmp_path,
        """
        cells:
          create:
            parent_missing:
              outcome: reject
              note: n
        """,
        '"cells"',
        'flatten = 2\nseparator = "."',
    )
    entries = {entry.id: entry.extra for entry in settings.registries[0].entries()}
    assert entries["create.parent_missing"]["outcome"] == "reject"


def test_flatten_one_is_exactly_todays_behavior(tmp_path):
    settings = build_flat(
        tmp_path,
        """
        keys:
          app.alpha:
            spec: first
        """,
        '"keys"',
        "flatten = 1",
    )
    assert ids(settings) == ["app.alpha"]


def test_a_deeper_flatten_is_accepted_rather_than_capped(tmp_path):
    """An arbitrary ceiling is a rule with no reason behind it.

    Two is what was measured; the documentation says so and claims no more.
    """
    settings = build_flat(
        tmp_path,
        """
        cells:
          a:
            b:
              c: out
        """,
        '"cells"',
        'flatten = 3\nseparator = "/"',
    )
    assert ids(settings) == ["a/b/c"]


# -- flatten refusals ------------------------------------------------------


def test_a_separator_collision_is_refused_naming_both_pairs(tmp_path):
    """Silent shadowing: one entry overwrites another and the set reads right."""
    with pytest.raises(ConfigError) as caught:
        build_flat(
            tmp_path,
            """
            cells:
              a.b:
                c: one
              a:
                b.c: two
            """,
            '"cells"',
            'flatten = 2\nseparator = "."',
        )
    message = str(caught.value)
    assert "'a.b.c'" in message
    assert "'a.b' -> 'c'" in message and "'a' -> 'b.c'" in message


def test_flatten_without_a_separator_is_refused(tmp_path):
    """No default: the separator spells every identifier this registry makes."""
    with pytest.raises(ConfigError) as caught:
        build_flat(tmp_path, CELLS, '"cells"', "flatten = 2")
    assert "no 'separator'" in str(caught.value)
    assert "no default" in str(caught.value)


def test_a_separator_with_no_flatten_is_refused_as_inert(tmp_path):
    """A config that says something confidently while doing nothing."""
    with pytest.raises(ConfigError) as caught:
        build_flat(tmp_path, CELLS, '"cells"', 'separator = "."')
    assert "does nothing" in str(caught.value)


@pytest.mark.parametrize("value", ["0", "-1", '"2"', "true"])
def test_a_flatten_that_is_not_a_positive_whole_number_is_refused(tmp_path, value):
    with pytest.raises(ConfigError) as caught:
        build_flat(tmp_path, CELLS, '"cells"', f"flatten = {value}")
    assert "positive whole number" in str(caught.value)


def test_a_scalar_row_under_a_flatten_is_refused_not_skipped(tmp_path):
    """Skipping would make the registry quietly smaller."""
    with pytest.raises(ConfigError) as caught:
        build_flat(
            tmp_path,
            """
            cells:
              create:
                parent_missing: reject
              delete: straight_to_scalar
            """,
            '"cells"',
            'flatten = 2\nseparator = "."',
        )
    message = str(caught.value)
    assert "'delete'" in message and "not a mapping" in message
