"""Bypass detection, and the two filters that make it precise enough to use.

The numbers in these tests come from a real incident: kanibako-cli commit
``42ece129``, "Give the tier filenames and box_data one carrier each, and guard
it", which names its own eight sites. See ``tests/test_corpus_validation.py``
for the run against the actual tree.
"""

from __future__ import annotations

import textwrap

from registry import Entry, scan, unused
from registry.contract import BaseRegistry
from registry.prose import python_code_only, python_strings_only


class Constants(BaseRegistry):
    """A registry of constants, each declaring the literal that bypasses it."""

    name = "constants"

    def __init__(self, defs):
        self.defs = defs

    def entries(self):
        for cid, (literal, home) in self.defs.items():
            yield Entry(id=cid, antipatterns=(literal,), home=(home,))


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# -- the core catch -----------------------------------------------------------


def test_finds_a_literal_that_should_have_been_the_constant(tmp_path):
    write(tmp_path, "config.py", 'WORKSET_META_FILE = "workset.yaml"\n')
    write(tmp_path, "names.py", 'p = root / "workset.yaml"\n')

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    (hit,) = scan(reg, tmp_path)
    assert hit.entry_id == "WORKSET_META_FILE"
    assert hit.path == "names.py"
    assert hit.line == 1


def test_the_definition_itself_is_not_a_bypass(tmp_path):
    write(tmp_path, "config.py", 'WORKSET_META_FILE = "workset.yaml"\n')
    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert scan(reg, tmp_path) == []


def test_scope_is_the_whole_tree_not_one_module(tmp_path):
    # 42ece129's own lesson: their tripwire scanned project/workset.py alone
    # and missed eight sites in six other modules.
    write(tmp_path, "config.py", 'BOX_META_FILE = "box.yaml"\n')
    for module in ("a.py", "deep/b.py", "deep/deeper/c.py"):
        write(tmp_path, module, 'p = root / "box.yaml"\n')

    reg = Constants({"BOX_META_FILE": (r"box\.yaml", "config.py")})
    assert len(scan(reg, tmp_path)) == 3


def test_a_value_embedded_in_a_longer_string_is_still_found(tmp_path):
    # settings_launch.py:243 composed "@meta.workset.path/workset.yaml" by hand.
    # A quote-anchored pattern misses it; this is why the pattern is a substring.
    write(tmp_path, "config.py", 'WORKSET_META_FILE = "workset.yaml"\n')
    write(tmp_path, "launch.py", 'floor["x"] = "@meta.workset.path/workset.yaml"\n')

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert len(scan(reg, tmp_path)) == 1


def test_no_antipatterns_means_no_scan(tmp_path):
    class Bare(BaseRegistry):
        name = "bare"

        def entries(self):
            yield Entry(id="thing")

    write(tmp_path, "a.py", "thing = 1\n")
    assert scan(Bare(), tmp_path) == []


# -- filter: comments and docstrings ------------------------------------------


def test_code_only_drops_comments_and_docstrings():
    source = '''
    """Docstring mentioning workset.yaml."""
    # comment mentioning workset.yaml
    path = "workset.yaml"  # trailing comment about workset.yaml
    '''
    out = python_code_only(textwrap.dedent(source))
    assert out.count("workset.yaml") == 1
    assert 'path = "workset.yaml"' in out


def test_code_only_preserves_line_numbers():
    source = '"""doc"""\n# comment\nx = 1\n'
    assert len(python_code_only(source).splitlines()) == 3


def test_prose_mentions_are_not_bypasses(tmp_path):
    write(tmp_path, "config.py", 'WORKSET_META_FILE = "workset.yaml"\n')
    write(
        tmp_path,
        "docs.py",
        '''
        """Settings live at <root>/workset.yaml."""
        # The workset.yaml file is the workset tier.
        value = 1
        ''',
    )
    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert scan(reg, tmp_path) == []


# -- filter: string literals only ---------------------------------------------


def test_strings_only_ignores_an_identifier_of_the_same_name():
    # The big false-positive source: `box_data = root / STANDALONE_META_DIR`
    # NAMES a variable after the thing while using the constant correctly.
    source = 'box_data = root / STANDALONE_META_DIR\nother = "box_data"\n'
    out = python_strings_only(source)
    assert out.splitlines()[0].strip() == ""
    assert '"box_data"' in out


def test_strings_only_keeps_a_value_inside_a_longer_literal():
    out = python_strings_only('x = "@meta.workset.path/workset.yaml"\n')
    assert "workset.yaml" in out


def test_strings_only_drops_docstrings():
    out = python_strings_only('"""mentions box_data."""\nx = 1\n')
    assert "box_data" not in out


def test_correct_use_of_a_constant_is_not_flagged(tmp_path):
    write(tmp_path, "defaults.py", 'STANDALONE_META_DIR = "box_data"\n')
    write(tmp_path, "clean.py", "box_data = root / STANDALONE_META_DIR\n")

    reg = Constants({"STANDALONE_META_DIR": (r"box_data", "defaults.py")})
    # The registry's own match_mode is "strings", so this is the default now.
    assert scan(reg, tmp_path) == []
    # Asking for code mode explicitly reproduces the false positive, which is
    # why the registry chooses rather than the caller.
    assert len(scan(reg, tmp_path, strings_only=False)) == 1


def test_unparseable_source_is_over_reported_not_skipped(tmp_path):
    write(tmp_path, "config.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "broken.py", 'this is not python "box.yaml"\n')

    reg = Constants({"BOX_META_FILE": (r"box\.yaml", "config.py")})
    assert len(scan(reg, tmp_path, strings_only=True)) == 1


# -- exclusions ---------------------------------------------------------------


def test_excluded_paths_are_skipped(tmp_path):
    write(tmp_path, "config.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "tests/test_paths.py", 'assert p == "box.yaml"\n')

    reg = Constants({"BOX_META_FILE": (r"box\.yaml", "config.py")})
    assert scan(reg, tmp_path) != []
    assert scan(reg, tmp_path, exclude=["tests/"]) == []


# -- unused: a review list, never a cut list ----------------------------------


def test_unused_finds_a_declared_thing_no_code_references(tmp_path):
    write(tmp_path, "keys.py", "USED = 1\n")
    write(tmp_path, "app.py", "print(USED)\n")

    class Keys(BaseRegistry):
        name = "keys"

        def entries(self):
            yield Entry(id="USED", home=("keys.py",))
            yield Entry(id="NEVER_READ", home=("keys.py",))

    assert unused(Keys(), tmp_path) == ["NEVER_READ"]


def test_a_reference_only_in_its_own_definition_does_not_count_as_use(tmp_path):
    write(tmp_path, "keys.py", "ORPHAN = 1\n")

    class Keys(BaseRegistry):
        name = "keys"

        def entries(self):
            yield Entry(id="ORPHAN", home=("keys.py",))

    assert unused(Keys(), tmp_path) == ["ORPHAN"]
