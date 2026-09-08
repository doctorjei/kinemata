"""Bypass detection, and the two filters that make it precise enough to use.

The numbers in these tests come from a real incident: kanibako-cli commit
``42ece129``, "Give the tier filenames and box_data one carrier each, and guard
it", which names its own eight sites. See ``tests/test_corpus_validation.py``
for the run against the actual tree.
"""

from __future__ import annotations

import textwrap

from kinemata import Entry, scan, unused
from kinemata.adapters.mapping import MappingRegistry
from kinemata.bypass import crossings, strays
from kinemata.contract import BaseRegistry
from kinemata.prose import python_code_only, python_strings_only


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


def test_strays_finds_an_identifier_the_registry_does_not_declare(tmp_path):
    """The closed-world catch, over a tree rather than a string.

    ``undeclared()`` had no command and no tree-walking caller for the whole
    life of the project, while the name ``kinemata undeclared`` belonged to an
    advisory scan over repeated text -- a different mechanism wearing it. Wired
    2026-09-08.
    """
    (tmp_path / "app.py").write_text(
        "cfg = get('config.settings')\ntmp = get('config.scratchpad')\n"
    )
    keys = MappingRegistry(
        {"config.settings": {}}, name="keys", syntax=r"\b[a-z_]+(?:\.[a-z_]+)+\b"
    )
    found = strays(keys, tmp_path)
    assert [(s.line, s.identifier) for s in found] == [(2, "config.scratchpad")]


def test_strays_honors_the_registry_match_mode(tmp_path):
    """A keyspace identifier is a string literal; the syntax that recognizes one
    also matches every dotted attribute access in the language.

    Measured on kanibako-cli with a permissive syntax: 48,685 findings matching
    raw lines against 7,266 reading string literals only. Without this the catch
    reports the language rather than the keyspace.
    """
    (tmp_path / "app.py").write_text(
        "import config.scratchpad\nvalue = get('config.settings')\n"
    )
    keys = MappingRegistry(
        {"config.settings": {}}, name="keys", syntax=r"\b[a-z_]+(?:\.[a-z_]+)+\b"
    )
    # default match_mode is "strings": the import is code, not a literal
    assert strays(keys, tmp_path) == []

    keys.match_mode = "raw"
    assert [s.identifier for s in strays(keys, tmp_path)] == ["config.scratchpad"]


# -- the walk -----------------------------------------------------------------


def test_the_walk_enters_a_symlinked_directory(tmp_path):
    """A tree reached through a link was scanned as empty and called clean.

    Measured 2026-09-08 on a real tree: 0 files through the link against 130 on
    the real path, because ``Path.rglob`` does not recurse a symlinked
    directory. Every check in the package inherited it, so a project laid out
    that way passed every gate by being invisible.
    """
    write(tmp_path, "real/pkg/names.py", 'p = root / "workset.yaml"\n')
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "linked").symlink_to(tmp_path / "real")

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    found = scan(reg, tmp_path / "tree")
    assert [hit.path for hit in found] == ["linked/pkg/names.py"]


def test_a_symlink_loop_yields_each_file_once(tmp_path):
    """Following links without identity tracking does not hang -- it inflates.

    Measured: ``os.walk(followlinks=True)`` and ``glob`` both expand a
    self-referential link about forty times before the OS refuses, reporting
    three files 120 times. Findings counted forty times over are a gate nobody
    can read.
    """
    write(tmp_path, "pkg/names.py", 'p = root / "workset.yaml"\n')
    (tmp_path / "pkg" / "loop").symlink_to(tmp_path / "pkg")

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert [hit.path for hit in scan(reg, tmp_path)] == ["pkg/names.py"]


def test_two_links_to_one_tree_are_walked_once(tmp_path):
    """Same mechanism as the loop guard, and the reason it keys on identity
    rather than on a path already seen: one file, two names, one finding."""
    write(tmp_path, "real/names.py", 'p = root / "workset.yaml"\n')
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "one").symlink_to(tmp_path / "real")
    (tmp_path / "tree" / "two").symlink_to(tmp_path / "real")

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert [hit.path for hit in scan(reg, tmp_path / "tree")] == ["one/names.py"]


def test_a_link_leaving_the_tree_is_followed_and_reported(tmp_path):
    """Followed, because an assembled tree is a real layout; reported, because
    the root then does not bound what was read."""
    write(tmp_path, "elsewhere/names.py", "x = 1\n")
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "linked").symlink_to(tmp_path / "elsewhere")

    (found,) = crossings(tmp_path / "tree")
    assert found.path == "linked"
    assert found.target == str((tmp_path / "elsewhere").resolve())


def test_a_link_inside_the_tree_is_not_a_crossing(tmp_path):
    """Nothing left the project, so there is nothing to announce. A warning on
    every internal link is how a real one stops being read."""
    write(tmp_path, "tree/real/names.py", "x = 1\n")
    (tmp_path / "tree" / "linked").symlink_to(tmp_path / "tree" / "real")

    assert crossings(tmp_path / "tree") == []


def test_skipped_directories_are_not_entered_through_a_link(tmp_path):
    """Pruning happens during the descent, so a linked tree carrying a
    ``.venv`` costs nothing rather than thousands of files."""
    write(tmp_path, "real/.venv/lib/names.py", 'p = root / "workset.yaml"\n')
    write(tmp_path, "real/names.py", 'p = root / "workset.yaml"\n')
    (tmp_path / "tree").mkdir()
    (tmp_path / "tree" / "linked").symlink_to(tmp_path / "real")

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert [hit.path for hit in scan(reg, tmp_path / "tree")] == ["linked/names.py"]


def test_a_broken_link_is_not_a_file_to_read(tmp_path):
    """A dangling link used to arrive at ``read_text`` as though it were
    source. It is skipped, and the walk keeps going rather than raising."""
    write(tmp_path, "names.py", 'p = root / "workset.yaml"\n')
    (tmp_path / "dangling.py").symlink_to(tmp_path / "gone.py")
    (tmp_path / "nowhere").symlink_to(tmp_path / "missing")

    reg = Constants({"WORKSET_META_FILE": (r"workset\.yaml", "config.py")})
    assert [hit.path for hit in scan(reg, tmp_path)] == ["names.py"]
