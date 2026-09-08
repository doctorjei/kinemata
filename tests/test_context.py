"""The context budget: bounding what a session loads, not what the tool emits.

The failure being defended against is growth nobody watches. Every individual
addition to an instruction layer is defensible; only the total is a problem, and
the total is the number nobody looks at.
"""

from __future__ import annotations

import re
import textwrap

import pytest

from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.context import STRIPPERS, measure


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# -- what gets counted -------------------------------------------------------


def test_a_glob_counts_what_arrives_later(tmp_path):
    """The anti-allowlist property. A file list would silently omit whatever is
    added next, which is precisely how an instruction layer grows unnoticed."""
    write(tmp_path, "docs/a.md", "a" * 100)
    before = measure(tmp_path, ["docs/*.md"], ceiling=1000)
    assert before.size == 100

    write(tmp_path, "docs/b.md", "b" * 250)
    after = measure(tmp_path, ["docs/*.md"], ceiling=1000)
    assert after.size == 350
    assert len(after.files) == 2


def test_a_file_matched_twice_is_counted_once(tmp_path):
    """Overlapping globs are ordinary. Double-counting one would inflate the
    total and make the ceiling meaningless."""
    write(tmp_path, "docs/a.md", "a" * 100)
    found = measure(tmp_path, ["docs/*.md", "docs/**/*.md", "**/*.md"], ceiling=1000)
    assert (len(found.files), found.size) == (1, 100)


def test_directories_matching_a_glob_are_not_weighed(tmp_path):
    write(tmp_path, "docs/sub/a.md", "a" * 10)
    found = measure(tmp_path, ["docs/*"], ceiling=1000)
    assert found.files == ()


def test_size_is_bytes_not_characters(tmp_path):
    """A byte budget, for the reason the projection budget is one: tokenizers
    differ between harnesses, bytes do not."""
    write(tmp_path, "docs/a.md", "é" * 10)
    assert measure(tmp_path, ["docs/*.md"], ceiling=1000).size == 20


# -- flattening --------------------------------------------------------------


def test_stripping_measures_what_the_harness_loads(tmp_path):
    """Measuring the file on disk over-reports whatever the assembler removes.
    In one real corpus, comment blocks held the original packaged text of every
    document -- 44% of its bytes, none of it ever loaded."""
    write(tmp_path, "docs/a.md", "keep<!-- drop this entirely -->keep")
    plain = measure(tmp_path, ["docs/*.md"], ceiling=1000)
    flat = measure(tmp_path, ["docs/*.md"], ceiling=1000, strip=["html-comments"])

    assert plain.size == 35
    assert flat.size == 8            # the two "keep"s
    assert flat.raw == 35            # what is on disk is still reported
    assert flat.files[0].stripped == 27


def test_a_comment_spanning_lines_is_stripped(tmp_path):
    write(tmp_path, "docs/a.md", "a\n<!--\nnote\nnote\n-->\nb")
    assert measure(tmp_path, ["docs/*.md"], ceiling=99, strip=["html-comments"]).size == 4


# -- the ceiling -------------------------------------------------------------


def test_over_the_ceiling_fails_and_says_by_how_much(tmp_path):
    write(tmp_path, "docs/a.md", "a" * 500)
    found = measure(tmp_path, ["docs/*.md"], ceiling=400)
    assert found.failed and found.over == 100
    assert "OVER by 100 B" in found.text()


def test_under_the_ceiling_reports_the_headroom(tmp_path):
    write(tmp_path, "docs/a.md", "a" * 300)
    found = measure(tmp_path, ["docs/*.md"], ceiling=400)
    assert not found.failed
    assert "100 B spare" in found.text()


# -- declaring it ------------------------------------------------------------


def configured(tmp_path, body):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        f"""
        [project]
        root = "."

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]

        {body}
        """,
    )
    return tmp_path / "kinemata.toml"


def test_a_half_declared_budget_is_refused(tmp_path):
    """A set with no ceiling, or a ceiling with nothing to weigh, checks
    nothing while looking configured."""
    with pytest.raises(ConfigError):
        load(configured(tmp_path, '[context]\ninclude = ["docs/*.md"]'))


def test_a_budget_with_nothing_to_weigh_is_refused(tmp_path):
    with pytest.raises(ConfigError):
        load(configured(tmp_path, "[context]\nbudget = 1000"))


def test_an_unknown_transform_is_refused_not_ignored(tmp_path):
    """Ignoring it would measure raw bytes while the config says otherwise --
    a check quietly doing something other than what it was told."""
    with pytest.raises(ConfigError) as caught:
        load(configured(
            tmp_path,
            '[context]\ninclude = ["docs/*.md"]\nbudget = 10\nstrip = ["yaml-frontmatter"]',
        ))
    assert "html-comments" in str(caught.value)   # names what it does know


def test_no_context_table_is_not_an_empty_one(tmp_path):
    assert load(configured(tmp_path, "")).context is None


# -- the command -------------------------------------------------------------


def test_the_command_gates(tmp_path, capsys):
    config = configured(
        tmp_path, '[context]\ninclude = ["docs/*.md"]\nbudget = 50'
    )
    write(tmp_path, "docs/a.md", "a" * 200)

    assert main(["context", "-c", str(config)]) == 1
    out = capsys.readouterr()
    assert "150 B over its ceiling" in out.err
    assert "ceiling 50 B" in out.out


def test_verbose_names_the_biggest_files(tmp_path, capsys):
    """The total says there is a problem; the breakdown says where it is."""
    config = configured(
        tmp_path, '[context]\ninclude = ["docs/*.md"]\nbudget = 5000'
    )
    write(tmp_path, "docs/small.md", "a" * 10)
    write(tmp_path, "docs/huge.md", "b" * 900)

    assert main(["context", "-c", str(config), "-v"]) == 0
    lines = [line for line in capsys.readouterr().out.splitlines() if "docs/" in line]
    assert "huge.md" in lines[0]      # largest first
    assert "small.md" in lines[1]


def test_running_it_undeclared_is_an_error_not_a_pass(tmp_path, capsys):
    """A command that measures an empty set and exits 0 is the inert signal."""
    assert main(["context", "-c", str(configured(tmp_path, ""))]) == 2
    assert "no [context] declared" in capsys.readouterr().err


def test_every_declared_transform_is_reachable_by_name():
    """The table is the interface: a transform nothing can name is unreachable,
    and one the config cannot refuse would be unvalidated."""
    for name, transform in STRIPPERS.items():
        assert re.fullmatch(r"[a-z-]+", name)
        assert transform("plain text") == "plain text"


def test_a_file_behind_a_symlink_is_weighed(tmp_path):
    """``Path.glob`` does not descend a symlinked directory, so an instruction
    layer assembled from links weighed nothing -- an under-count in a ceiling
    check, which passes. A budget that cannot see what it is bounding is worse
    than no budget."""
    write(tmp_path, "real/policy.md", "p" * 400)
    (tmp_path / "canon").mkdir()
    (tmp_path / "canon" / "linked").symlink_to(tmp_path / "real")

    found = measure(tmp_path / "canon", ["**/*.md"], ceiling=1000)
    assert [f.path for f in found.files] == ["linked/policy.md"]
    assert found.size == 400


def test_a_symlink_loop_counts_a_file_once(tmp_path):
    """Measured: ``glob`` expands a self-referential link about forty deep
    before the OS refuses. Counting the same file forty times would fail a
    ceiling that nothing had actually breached."""
    write(tmp_path, "docs/policy.md", "p" * 400)
    (tmp_path / "docs" / "loop").symlink_to(tmp_path / "docs")

    found = measure(tmp_path, ["**/*.md"], ceiling=1000)
    assert found.size == 400
    assert len(found.files) == 1


def test_a_declared_dotfile_is_still_counted(tmp_path):
    """The trap that came with the fix. Unlike ``Path.glob``, the ``glob``
    module skips names beginning with a dot unless told otherwise -- and an
    instruction layer is full of them. Dropping one silently would have traded
    one under-count for another."""
    write(tmp_path, ".claude/CLAUDE.md", "c" * 120)
    found = measure(tmp_path, ["**/*.md"], ceiling=1000)
    assert [f.path for f in found.files] == [".claude/CLAUDE.md"]
