"""`under` — where a rule applies, as distinct from where its entry is declared.

The incident is kanibako's 2026-10-13 report, whose task board carries a section
whose rows must carry a marker and a section whose rows must not. Written
unscoped, each rule also fired on the other section: **five findings on a board
with two genuine misfiles, and the same five on a board with none** — the
report was indistinguishable from a correct one, which is worse than noise.

The numbers here come from their fixture, and two of its headings carry levels
that do not say what its comments say. `test_a_level_one_section_owns_the_level_two_ones_under_it`
is that finding, kept as a test because it is the rule someone will trip on next.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata import Entry, scan
from kinemata.config import ConfigError, load
from kinemata.contract import BaseRegistry
from kinemata.regions import markdown_headings, spans


class Scoped(BaseRegistry):
    """A code-patterns-shaped registry, declared as specs rather than literals.

    The same shape `adapters.patterns.CodePatterns` builds, so these tests are
    about `under` and not about a hand-rolled carrier that happens to agree.
    """

    name = "scoped"
    match_mode = "raw"

    def __init__(self, specs, suffixes=(".md",)):
        self.suffixes = tuple(suffixes)
        self._specs = tuple(specs)

    def entries(self):
        for spec in self._specs:
            yield Entry(
                id=spec["id"],
                antipatterns=tuple(spec["antipatterns"]),
                under=tuple(spec.get("under", ())),
            )


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


#: kanibako's board, verbatim from `heading-scope-fixture/planted/tasks/product.md`.
BOARD = """
    # Product Task Board

    # 🟢 UNBLOCKED — MINE TO DO, NO DECISION OWED

    - [ ] 🔵 **A row I can do now.**

    ## 🔴 HIS GATE — OPEN DECISIONS

    - [ ] 🔭 **[HIS JUDGEMENT] a decision he owes.**

    ## 🔴 MINE

    - [ ] 🔵 **Another row of mine.**
    """

UNBLOCKED = "🟢 UNBLOCKED — MINE TO DO, NO DECISION OWED"
HIS_GATE = "🔴 HIS GATE — OPEN DECISIONS"


def his_registry():
    """The two entries their fixture declares, in the region each one means."""
    return Scoped([
        {
            "id": "his-marked-row",
            "antipatterns": [r"^- \[ \] .*\*\*\[HIS\b"],
            "under": [UNBLOCKED],
        },
        {
            "id": "unmarked-row",
            "antipatterns": [r"^- \[ \] (?!.*\*\*\[HIS\b)"],
            "under": [HIS_GATE],
        },
    ])


def sites(registry, tmp_path):
    return {(hit.entry_id, hit.line) for hit in read(registry, tmp_path)}


def read(registry, tmp_path, inert=None):
    """`scan` with the file set this registry declares, as `check` passes it."""
    return scan(registry, tmp_path, suffixes=registry.suffixes, inert=inert)


# -- the mechanism ------------------------------------------------------------


def test_a_rule_scoped_to_a_section_fires_only_there(tmp_path):
    write(tmp_path, "board.md", """
        ## 🔴 HIS GATE

        - [ ] 🔭 **[HIS] a decision he owes.**       <- inside, and the violation
        ## 🔴 MINE

        - [ ] 🔭 **[HIS] misfiled out of the gate.** <- outside
        """)
    registry = Scoped([{
        "id": "row", "antipatterns": [r"\*\*\[HIS"], "under": ["🔴 HIS GATE"],
    }])
    assert sites(registry, tmp_path) == {("row", 3)}


def test_two_entries_can_be_scoped_to_two_sections_of_one_document(tmp_path):
    write(tmp_path, "board.md", """
        ## UNBLOCKED

        - [ ] 🔵 **mine**
        - [ ] 🔭 **[HIS] planted under UNBLOCKED.**
        ## HIS GATE

        - [ ] 🔭 **[HIS] correctly filed.**
        - [ ] 🔵 **planted under HIS GATE.**
        """)
    registry = Scoped([
        {
            "id": "his-marked-row",
            "antipatterns": [r"^- \[ \] .*\*\*\[HIS\b"],
            "under": ["UNBLOCKED"],
        },
        {
            "id": "unmarked-row",
            "antipatterns": [r"^- \[ \] (?!.*\*\*\[HIS\b)"],
            "under": ["HIS GATE"],
        },
    ])
    assert sites(registry, tmp_path) == {("his-marked-row", 4), ("unmarked-row", 8)}


def test_an_entry_with_no_under_matches_every_line(tmp_path):
    """What every entry written before this meant, so it is not a narrowed rule."""
    write(tmp_path, "board.md", "## A\n\n- [ ] one\n## B\n\n- [ ] two\n")
    registry = Scoped([{"id": "row", "antipatterns": [r"^- \[ \]"]}])
    assert len(read(registry, tmp_path)) == 2


def test_the_heading_line_is_inside_its_own_region(tmp_path):
    """A heading repeating a forbidden spelling is as reportable as the prose."""
    write(tmp_path, "doc.md", "## the forbidden word\n\nnothing here\n")
    registry = Scoped([{
        "id": "w", "antipatterns": [r"forbidden"], "under": ["the forbidden word"],
    }])
    assert sites(registry, tmp_path) == {("w", 1)}


# -- what a region is, which is the part that surprises ------------------------


def test_a_region_runs_to_the_next_heading_of_the_same_or_higher_level(tmp_path):
    """A `###` belongs to its `##`; the next `##` ends the section.

    Ending at the next heading of *any* level would leave a document with a
    subsection unable to declare the section it belongs to.
    """
    write(tmp_path, "doc.md", """
        ## A
        - [ ] one
        ### A.1
        - [ ] two
        ## B
        - [ ] three
        """)
    registry = Scoped([{"id": "row", "antipatterns": [r"^- \[ \]"], "under": ["A"]}])
    assert sites(registry, tmp_path) == {("row", 2), ("row", 4)}


def test_a_level_one_section_owns_the_level_two_ones_under_it(tmp_path):
    """kanibako's fixture, and the finding it turned up.

    Their board opens `# 🟢 UNBLOCKED` at **level one**, and states "the region
    running to the next heading of the same or higher level" in the same letter
    that asks for it. A level-one section has no level-one successor in that
    document, so it owns everything after it — including the `## 🔴 HIS GATE` and
    `## 🔴 MINE` beneath it. Scoping to it therefore reported **1** on their clean
    board and **3** on their planted one, where they expect **0** and **2**.

    **The tool is right and the fixture is mislevelled**: demoting that one
    heading to `##` gives 0 and 2 exactly. Worth a test of its own because it is
    the rule the next adopter will meet, and the failure looks like the mechanism
    not working rather than like a document that says what it means.
    """
    write(tmp_path, "board.md", BOARD)
    assert sites(his_registry(), tmp_path) == {("his-marked-row", 9)}
    demoted = (tmp_path / "board.md").read_text(encoding="utf-8").replace(
        "\n# 🟢 UNBLOCKED", "\n## 🟢 UNBLOCKED"
    )
    (tmp_path / "board.md").write_text(demoted, encoding="utf-8")
    assert sites(his_registry(), tmp_path) == set()


def test_the_two_heading_shapes_that_are_not_headings(tmp_path):
    """`##` alone and `#hashtag` are not sections, and treating them as ones
    would find a region under every `##` in a document."""
    assert markdown_headings("##\n#hashtag\n") == ()


def test_a_heading_inside_a_fence_is_not_a_heading(tmp_path):
    """Both halves matter, and they are the same fence.

    A `# comment` in a shell block would end the preceding section early and
    invent a region nothing declared. A fence inside a section is the other
    half: a document displaying a whole board shows its headings, and reading
    those would give the declaration a region that exists only in the figure.
    """
    write(tmp_path, "doc.md", """
        ## A
        - [ ] one
        ```sh
        # not a heading
        ```
        ## B
        - [ ] two
        """)
    assert [title for _, _, title in markdown_headings(
        (tmp_path / "doc.md").read_text(encoding="utf-8")
    )] == ["A", "B"]
    registry = Scoped([{"id": "row", "antipatterns": [r"^- \[ \]"], "under": ["A"]}])
    assert sites(registry, tmp_path) == {("row", 2)}


def test_a_closing_run_of_hashes_is_not_part_of_the_title():
    """CommonMark allows `## A ##`, and a reader declaring the section spells it
    once. Keeping the marks would name a region no document could declare."""
    assert markdown_headings("## A ##\n") == ((1, 2, "A"),)


def test_spans_of_a_title_that_is_absent_is_empty():
    assert spans(((1, 2, "A"),), frozenset({"B"}), 9) == ()


# -- refusing, and reporting ----------------------------------------------------


def test_under_on_a_format_with_no_region_reader_is_refused_at_load(tmp_path):
    """Refused rather than matching nothing, on every file, forever.

    A rule scoped to a section of a `.py` file has no meaning: "where the rule
    applies" is a question only a format that states its own containment can
    answer, and guessing at one for Python would be a guess about a language.
    """
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [[registry]]
        name = "scoped"
        kind = "code-patterns"
        suffixes = [".py"]

        [[registry.entry]]
        id = "row"
        antipatterns = ['forbidden']
        under = ['a section']
        """)
    with pytest.raises(ConfigError, match="no region reader"):
        load(tmp_path / "kinemata.toml")


def test_under_alongside_a_readable_suffix_is_still_refused_and_says_which(tmp_path):
    write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [[registry]]
        name = "scoped"
        kind = "code-patterns"
        suffixes = [".md", ".py"]

        [[registry.entry]]
        id = "row"
        antipatterns = ['forbidden']
        under = ['a section']
        """)
    with pytest.raises(ConfigError, match=r"\.py has no region reader; \.md can be read"):
        load(tmp_path / "kinemata.toml")


def test_an_unmatched_section_is_reported_and_does_not_fail(tmp_path):
    """A warning rather than a stop, and the reason is not timidity.

    A section is something the *document* has, so a tree that legitimately does
    not have that board — a fresh clone, a project that has not written it yet —
    must not go red for it. That is the failure `kinemata init --ci` is written
    against. What it costs is that a renamed heading is a warning rather than a
    stop, so the message carries the string that did not match.
    """
    write(tmp_path, "board.md", "## UNBLOCKED\n\n- [ ] one\n")
    registry = Scoped([{
        "id": "row", "antipatterns": [r"^- \[ \]"], "under": ["UNBLOCKED (renamed)"],
    }])
    inert: list[str] = []
    assert read(registry, tmp_path, inert=inert) == []
    assert len(inert) == 1
    assert "'UNBLOCKED (renamed)'" in inert[0]
    assert "row" in inert[0]


def test_a_section_that_is_there_reports_nothing(tmp_path):
    write(tmp_path, "board.md", "## UNBLOCKED\n\nnothing\n")
    registry = Scoped([{
        "id": "row", "antipatterns": [r"^- \[ \]"], "under": ["UNBLOCKED"],
    }])
    inert: list[str] = []
    read(registry, tmp_path, inert=inert)
    assert inert == []


def test_a_section_in_one_document_settles_the_entry(tmp_path):
    """Not per file. "This heading is not in *that* document" is not a finding;
    "this heading is in none of them" is, and only the walk can say so."""
    write(tmp_path, "a.md", "# Title\n\nnothing\n")
    write(tmp_path, "b.md", "## THE SECTION\n\n- [ ] one\n")
    registry = Scoped([{
        "id": "row", "antipatterns": [r"^- \[ \]"], "under": ["THE SECTION"],
    }])
    inert: list[str] = []
    assert len(read(registry, tmp_path, inert=inert)) == 1
    assert inert == []
