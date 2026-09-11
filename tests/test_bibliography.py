"""The bibliography: one declared place per source, and both ways to resolve one.

A stamp answers *when*. The key answers *which source*, and the entry answers
*where* -- so the volatile half of a citation is declared once and edited once
when it moves. What is worth testing here is not that a lookup works but that
every way of getting the declarations wrong is **refused** rather than loaded
half-way: a bibliography that resolves a key to nothing while still reporting as
configured is the inert signal this package exists to catch.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.adapters.bibliography import (
    INTERPRETED,
    STANDARDIZED,
    Bibliography,
)
from kinemata.bypass import strays, unused
from kinemata.citations import DEFAULT_ACCOMPANY_MAX, citations
from kinemata.cli import main
from kinemata.config import ConfigError, load

STAMP = "0TMQDKB"


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def book(**overrides):
    """One well-formed entry, with the fields a test cares about replaced."""
    record = {"key": "Pa0003", "target": "docs/design.md",
              "note": "the registry contract"}
    record.update(overrides)
    return record


def project(tmp_path, *, bibliography="", config="", document=""):
    """A tree with a config, a bibliography and one document that cites."""
    write(tmp_path, "docs/bibliography.toml", bibliography or """
        [[entry]]
        key = "Pa0003"
        target = "docs/design.md"
        note = "the registry contract"
    """)
    write(tmp_path, "notes.md", document or f"""
        The registry contract is `docs/design.md` [{STAMP}-Pa0003].
    """)
    return write(tmp_path, "kinemata.toml", config or """
        [project]
        root = "."

        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"
    """)


# -- the entry shape ----------------------------------------------------------


def test_an_entry_carries_the_key_the_target_and_a_note():
    """The three facts an entry must hold. The note is not decoration: a
    citation standing alone is read by resolving it, and a bare path resolves
    to another thing to go look at rather than to an answer."""
    (entry,) = Bibliography([book()], home="docs/bibliography.toml").entries()
    assert entry.id == "Pa0003"
    assert entry.extra["target"] == "docs/design.md"
    assert entry.extra["note"] == "the registry contract"
    assert entry.extra["type"] == "Pa"
    assert entry.home == ("docs/bibliography.toml",)


def test_an_entry_declares_no_antipattern():
    """Section 5.6: a citation *accompanies* its target by default, so a target
    spelled beside its key is the readable half of a declared citation rather
    than a re-derivation of it. Declaring the target as an antipattern would
    make the tool report the form its own specification prefers."""
    (entry,) = Bibliography([book()]).entries()
    assert entry.antipatterns == ()


def test_a_key_is_stored_canonically_however_it_was_written():
    (entry,) = Bibliography([book(key="pA0003")]).entries()
    assert entry.id == "Pa0003"


def test_the_foreign_identifier_is_kept_when_there_is_one():
    """Section 5.2: a key is this project's number for another's work, so the
    entry names the foreign identifier where one exists."""
    (entry,) = Bibliography([book(foreign="RFC 7159")]).entries()
    assert entry.extra["foreign"] == "RFC 7159"


# -- refusals over the declarations -------------------------------------------


def test_a_bibliography_with_no_entries_is_refused():
    with pytest.raises(ValueError, match="declares no entries"):
        Bibliography([])


@pytest.mark.parametrize("field", ["key", "target", "note"])
def test_an_entry_missing_any_of_the_three_is_refused(field):
    with pytest.raises(ValueError, match=f"missing {field}"):
        Bibliography([book(**{field: ""})])


def test_a_misspelled_field_is_refused_rather_than_dropped():
    """``not`` for ``note`` would leave an entry resolving to a bare path while
    the file looks like it says more."""
    with pytest.raises(ValueError, match="declares not,"):
        Bibliography([{"key": "Pa0003", "target": "d.md", "not": "oops"}])


def test_a_number_of_the_wrong_width_is_refused():
    with pytest.raises(ValueError, match="zero-padded"):
        Bibliography([book(key="Pa003")])


def test_a_duplicate_key_in_one_file_is_refused():
    with pytest.raises(ValueError, match="already declared"):
        Bibliography([book(), book(target="docs/structure.md")])


def test_the_same_number_under_two_types_is_not_a_conflict():
    """Digits are unique *within* a type, so the composite is what must be
    unique. ``Ru0169`` and ``De0169`` are two sources, not one key twice."""
    registry = Bibliography(
        [book(key="Ru0169", target="a"), book(key="De0169", target="b")],
        types={"De": "a decision recorded in this project"},
    )
    assert [e.id for e in registry.entries()] == ["Ru0169", "De0169"]


def test_a_type_nothing_declares_is_refused():
    """Every code is declared -- the reserved ones implicitly, a project's own
    explicitly -- so an unknown code is a typo the checker reports."""
    with pytest.raises(ValueError, match="nothing declares"):
        Bibliography([book(key="Zz0001")])


# -- the two reserved tiers ---------------------------------------------------


def test_redefining_an_interpreted_code_is_refused():
    """Behavior depends on the code meaning what it says, so reinterpreting it
    would leave a check silently answering a different question."""
    with pytest.raises(ValueError, match="reserved for 'path in this tree'"):
        Bibliography([book()], types={"Pa": "a paragraph"})


def test_redefining_a_standardized_code_is_a_notice_not_a_refusal():
    """The tool never reads these, so refusing would enforce a convention it
    cannot act on. The only cost of divergence is legibility across projects."""
    registry = Bibliography([book(key="Bk0001")], types={"Bk": "a bookmark"})
    assert [e.id for e in registry.entries()] == ["Bk0001"]
    assert any("standardized" in note for note in registry.notices)


def test_both_reserved_tiers_accept_additions():
    """A closed built-in set with no extension point is a defect this project
    has already shipped: the document-suffix set left an adopting project blind
    to the only two content files one of its repositories had."""
    registry = Bibliography(
        [book(key="Xy0001"), book(key="Zz0001", target="b")],
        interpreted={"Xy": "a thing this tool settles"},
        standardized={"Zz": "a thing every project spells the same way"},
    )
    assert [e.id for e in registry.entries()] == ["Xy0001", "Zz0001"]
    assert registry.declares("Xy") and registry.declares("Zz")


def test_reserving_an_already_reserved_code_again_is_refused():
    """Adding is all the extension point does; redeclaring a reserved code
    through it is the same redefinition by another road."""
    with pytest.raises(ValueError, match="already reserved"):
        Bibliography([book()], standardized={"Pa": "a paragraph"})


def test_the_reserved_tables_are_the_ones_the_specification_names():
    """Pinned because additions are not the tool's to make: the reserved set is
    a shared convention, and every code added to it is one some project may
    already be spending differently."""
    assert set(INTERPRETED) == {"Wb", "Pa", "Cm"}
    assert set(STANDARDIZED) == {"Dc", "Sp", "Ru", "Is", "Pr", "Rp", "Bk", "Ar"}


def test_a_reserved_table_cannot_be_edited_in_place():
    with pytest.raises(TypeError):
        INTERPRETED["Ms"] = "a manuscript"


# -- what counts as a citation ------------------------------------------------


def test_only_a_stamped_key_counts_as_a_citation():
    """A sentence mentioning a key in passing has not cited anything; the token
    has. The default matcher cannot tell them apart, and its boundary class
    would additionally treat the separator as part of the name -- so every entry
    would report as uncited."""
    registry = Bibliography([book()])
    assert registry.detect(f"see [{STAMP}-Pa0003] for this") == ["Pa0003"]
    assert registry.detect("see Pa0003 for this") == []


def test_a_citation_is_read_case_insensitively():
    registry = Bibliography([book()])
    assert registry.detect(f"[{STAMP.lower()}-pa0003]") == ["Pa0003"]


def test_an_undeclared_key_is_a_candidate_but_not_a_detection():
    """Closure needs the difference: to say "that is not a key" you must first
    recognize it as trying to be one."""
    registry = Bibliography([book()])
    text = f"[{STAMP}-Pa0003] and [{STAMP}-Ru0169]"
    assert registry.detect(text) == ["Pa0003"]
    assert registry.candidates(text) == ["Pa0003", "Ru0169"]


def test_a_closed_bibliography_reports_a_citation_nothing_declares(tmp_path):
    """Section 5.3's second catchable failure, through the catch that exists."""
    write(tmp_path, "notes.md", f"the ruling is [{STAMP}-Ru0169].\n")
    registry = Bibliography([book()], closed=True)
    (stray,) = strays(registry, tmp_path, suffixes=(".md",))
    assert "Ru0169" in str(stray)


# -- shown syntax versus used syntax ------------------------------------------


def test_a_key_shown_inside_a_fence_is_not_a_citation(tmp_path):
    """The defect this registry's mode exists for.

    ``docs/citations.md`` prints a whole reference key inside a fence so a
    reader can see the notation, and that illustration was the closed-world
    catch's only finding in this repository -- unfixable except by declaring a
    bibliography entry for a ruling that does not exist.
    """
    write(tmp_path, "notes.md", f"""
        the form is:

        ```
        [{STAMP}-Ru0169]
        ```
    """)
    registry = Bibliography([book()], closed=True)
    assert strays(registry, tmp_path, suffixes=(".md",)) == []


def test_a_citation_outside_a_fence_is_still_found(tmp_path):
    """The control. An exemption that also swallowed real citations would be
    the under-reporting failure wearing the fix's clothes, and the two live one
    line apart in the document that prompted this."""
    write(tmp_path, "notes.md", f"""
        the form is:

        ```
        [{STAMP}-Ru0169]
        ```

        and the ruling itself is [{STAMP}-Ru0170].
    """)
    registry = Bibliography([book()], closed=True)
    (stray,) = strays(registry, tmp_path, suffixes=(".md",))
    assert "Ru0170" in str(stray)
    assert stray.line == 7  # blanked in place, so the number still points home


def test_an_entry_cited_only_from_inside_a_fence_is_not_mentioned(tmp_path):
    """The review list and the catch have to answer about the same tree.

    ``unused`` reads whole files and consults no ``match_mode``, so for a day
    this asserted the opposite: a fenced illustration counted as a mention while
    the closed-world catch and the reverse index both said the project cited
    nothing. Fixed in :meth:`Bibliography.detect` rather than in ``unused``,
    because ``match_mode`` governs where an *antipattern* counts and this asks
    where an *identifier* is mentioned -- applying the mode generally would
    blank the code and report every declared constant as unused.
    """
    write(tmp_path, "notes.md", f"""
        ```
        the contract is [{STAMP}-Pa0003]
        ```
    """)
    registry = Bibliography([book()], home="docs/bibliography.toml")
    assert unused(registry, tmp_path, suffixes=(".md",)) == ["Pa0003"]


def test_a_citation_outside_a_fence_still_counts_as_mentioned(tmp_path):
    """The negative control for the test above."""
    write(tmp_path, "notes.md", f"the contract is [{STAMP}-Pa0003]\n")
    registry = Bibliography([book()], home="docs/bibliography.toml")
    assert unused(registry, tmp_path, suffixes=(".md",)) == []


def test_an_inline_code_span_still_carries_a_citation(tmp_path):
    """Why the mode is not ``prose``. A stamp inside backticks on a prose line
    is a citation like any other; only a whole fenced block is display."""
    write(tmp_path, "notes.md", f"see `[{STAMP}-Ru0169]` for the form.\n")
    registry = Bibliography([book()], closed=True)
    (stray,) = strays(registry, tmp_path, suffixes=(".md",))
    assert "Ru0169" in str(stray)


def test_an_entry_nothing_cites_shows_up_as_unused(tmp_path):
    """No separate machinery for a key nothing cites: it is a declared entry
    nothing mentions, which the existing review list already describes."""
    write(tmp_path, "notes.md", f"the contract is [{STAMP}-Pa0003].\n")
    registry = Bibliography(
        [book(), book(key="Pa0001", target="docs/structure.md")],
        home="docs/bibliography.toml",
    )
    assert unused(registry, tmp_path, suffixes=(".md",)) == ["Pa0001"]


# -- the reverse index --------------------------------------------------------


def test_citations_are_found_with_their_file_and_line(tmp_path):
    write(tmp_path, "notes.md", f"""
        first line
        the contract is [{STAMP}-Pa0003].
        and again [{STAMP}-Pa0003] here
    """)
    found = citations(tmp_path, suffixes=(".md",))
    assert [str(c) for c in found] == ["notes.md:2", "notes.md:3"]
    assert {c.key for c in found} == {"Pa0003"}


def test_an_unkeyed_stamp_is_not_a_citation_of_anything(tmp_path):
    """A stamp carrying a type alone is a dated citation naming no entry, which
    is a legitimate thing to write."""
    write(tmp_path, "notes.md", f"read on [{STAMP}-Pa].\n")
    assert citations(tmp_path, suffixes=(".md",)) == []


def test_the_reverse_index_refuses_a_malformed_token(tmp_path):
    """Reporting a worklist that quietly omitted a wrong-width key is the worse
    of the two outcomes: a move would leave that mention behind."""
    write(tmp_path, "notes.md", f"the ruling is [{STAMP}-Ru169].\n")
    with pytest.raises(Exception, match="zero-padded"):
        citations(tmp_path, suffixes=(".md",))


# -- configuration ------------------------------------------------------------


def test_a_declared_bibliography_loads(tmp_path):
    settings = load(project(tmp_path))
    (registry,) = settings.registries
    assert registry.name == "sources"
    assert [e.id for e in registry.entries()] == ["Pa0003"]


def test_a_missing_source_file_is_refused(tmp_path):
    write(tmp_path, "kinemata.toml", """
        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/nowhere.toml"
    """)
    with pytest.raises(ConfigError, match="no such file"):
        load(tmp_path / "kinemata.toml")


def test_a_bibliography_without_a_source_is_refused(tmp_path):
    write(tmp_path, "kinemata.toml", """
        [[registry]]
        name = "sources"
        kind = "bibliography"
    """)
    with pytest.raises(ConfigError, match="needs 'source'"):
        load(tmp_path / "kinemata.toml")


def test_a_misspelled_table_in_the_source_is_refused(tmp_path):
    """``[[entries]]`` for ``[[entry]]`` would load a bibliography with nothing
    in it, and a key resolving to nothing is worse than a key nobody wrote."""
    config = project(tmp_path, bibliography="""
        [[entries]]
        key = "Pa0003"
    """)
    with pytest.raises(ConfigError, match="means nothing here"):
        load(config)


def test_a_duplicate_key_across_two_sources_is_refused(tmp_path):
    """The key space is project-wide. Each file is internally consistent here,
    so only something holding both can see this."""
    write(tmp_path, "docs/other.toml", """
        [[entry]]
        key = "Pa0003"
        target = "docs/structure.md"
        note = "a second source wearing an existing key"
    """)
    config = project(tmp_path, config="""
        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"

        [[registry]]
        name = "standards"
        kind = "bibliography"
        source = "docs/other.toml"
    """)
    with pytest.raises(ConfigError, match="Pa0003 is declared by sources and standards"):
        load(config)


def test_two_sources_may_hold_different_keys(tmp_path):
    write(tmp_path, "docs/other.toml", """
        [[entry]]
        key = "Sp0001"
        target = "https://spec.commonmark.org/"
        note = "what a bracket group does in a document"
    """)
    config = project(tmp_path, config="""
        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"

        [[registry]]
        name = "standards"
        kind = "bibliography"
        source = "docs/other.toml"
    """)
    settings = load(config)
    assert [e.id for r in settings.registries for e in r.entries()] == [
        "Pa0003", "Sp0001"
    ]


def test_an_interpreted_conflict_in_the_source_refuses_the_load(tmp_path):
    config = project(tmp_path, bibliography="""
        [types]
        Pa = "a paragraph"

        [[entry]]
        key = "Dc0001"
        target = "docs/design.md"
        note = "the registry contract"
    """)
    with pytest.raises(ConfigError, match="reserved for 'path in this tree'"):
        load(config)


def test_a_standardized_conflict_loads_and_is_carried_as_a_notice(tmp_path):
    config = project(tmp_path, bibliography="""
        [types]
        Bk = "a bookmark"

        [[entry]]
        key = "Bk0001"
        target = "docs/design.md"
        note = "the registry contract"
    """)
    settings = load(config)
    assert [e.id for r in settings.registries for e in r.entries()] == ["Bk0001"]
    assert any("standardized" in note for note in settings.notices)


# -- the accompany threshold --------------------------------------------------


def test_the_accompany_threshold_has_a_measured_default(tmp_path):
    """Targets in this project's own notes run to a median of 20 characters and
    a 90th percentile of 50, with a maximum of 107. Fifty accepts the common
    case and lets the real tail stand alone."""
    assert load(project(tmp_path)).accompany_max == DEFAULT_ACCOMPANY_MAX == 50


def test_a_project_may_declare_its_own_threshold(tmp_path):
    config = project(tmp_path, config="""
        [citations]
        accompany_max = 90

        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"
    """)
    assert load(config).accompany_max == 90


def test_a_threshold_that_cannot_mean_anything_is_refused(tmp_path):
    config = project(tmp_path, config="""
        [citations]
        accompany_max = 0

        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"
    """)
    with pytest.raises(ConfigError, match="length in characters"):
        load(config)


def test_an_unknown_citations_key_is_refused(tmp_path):
    config = project(tmp_path, config="""
        [citations]
        accompany_maximum = 90

        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"
    """)
    with pytest.raises(ConfigError, match="means nothing here"):
        load(config)


# -- the command --------------------------------------------------------------


def test_cite_forward_gives_the_readable_form(tmp_path, capsys):
    config = project(tmp_path)
    assert main(["cite", "-c", str(config), "Pa0003"]) == 0
    assert capsys.readouterr().out == (
        "Pa0003  docs/design.md  -- the registry contract\n"
    )


def test_cite_forward_takes_several_keys(tmp_path, capsys):
    config = project(tmp_path, bibliography="""
        [[entry]]
        key = "Pa0001"
        target = "docs/structure.md"
        note = "the method"

        [[entry]]
        key = "Pa0003"
        target = "docs/design.md"
        note = "the registry contract"
    """)
    assert main(["cite", "-c", str(config), "Pa0003", "Pa0001"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert [line.split()[0] for line in lines] == ["Pa0003", "Pa0001"]


def test_cite_where_is_a_plain_pipeable_worklist(tmp_path, capsys):
    config = project(tmp_path, document=f"""
        first line
        the contract is [{STAMP}-Pa0003].
        and again [{STAMP}-Pa0003] here
    """)
    assert main(["cite", "-c", str(config), "--where", "Pa0003"]) == 0
    assert capsys.readouterr().out == "notes.md:2\nnotes.md:3\n"


def test_cite_with_no_argument_counts_every_key(tmp_path, capsys):
    config = project(tmp_path, bibliography="""
        [[entry]]
        key = "Pa0001"
        target = "docs/structure.md"
        note = "the method"

        [[entry]]
        key = "Pa0003"
        target = "docs/design.md"
        note = "the registry contract"
    """)
    assert main(["cite", "-c", str(config)]) == 0
    assert capsys.readouterr().out == "Pa0001  0\nPa0003  1\n"


def test_cite_refuses_a_key_no_entry_declares(tmp_path, capsys):
    assert main(["cite", "-c", str(project(tmp_path)), "Ru0169"]) == 2
    assert "no entry declares Ru0169" in capsys.readouterr().err


def test_cite_refuses_a_key_of_the_wrong_width(tmp_path, capsys):
    assert main(["cite", "-c", str(project(tmp_path)), "Pa003"]) == 2
    assert "zero-padded" in capsys.readouterr().err


def test_cite_refuses_both_directions_at_once(tmp_path, capsys):
    config = project(tmp_path)
    assert main(["cite", "-c", str(config), "--where", "Pa0003", "Pa0003"]) == 2
    assert "not both" in capsys.readouterr().err


def test_cite_refuses_a_project_with_no_bibliography(tmp_path, capsys):
    write(tmp_path, "kinemata.toml", """
        [claims]
        suffixes = [".md"]
    """)
    assert main(["cite", "-c", str(tmp_path / "kinemata.toml")]) == 2
    assert "no bibliography is declared" in capsys.readouterr().err


def test_cite_says_when_nothing_cites_a_key_without_polluting_stdout(
    tmp_path, capsys
):
    config = project(tmp_path, document="nothing cites anything here\n")
    assert main(["cite", "-c", str(config), "--where", "Pa0003"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nothing cites Pa0003" in captured.err


def test_a_long_target_is_reported_as_standing_alone(tmp_path, capsys):
    """Reported, never enforced: whether a sentence reads better with its target
    spelled beside the key is a judgment about that sentence."""
    long_target = "docs/" + "a" * 60 + ".md"
    config = project(tmp_path, bibliography=f"""
        [[entry]]
        key = "Pa0003"
        target = "{long_target}"
        note = "a target past the threshold"
    """)
    assert main(["cite", "-c", str(config), "-v", "Pa0003"]) == 0
    assert "reads better standing alone" in capsys.readouterr().out


def test_a_short_target_gets_no_such_note(tmp_path, capsys):
    assert main(["cite", "-c", str(project(tmp_path)), "-v", "Pa0003"]) == 0
    assert "standing alone" not in capsys.readouterr().out


def test_stamp_reads_a_key_back(capsys):
    assert main(["stamp", f"[{STAMP}-Ru0169]"]) == 0
    assert "type Ru key Ru0169" in capsys.readouterr().out


# -- the index and the catch must describe the same tree --------------------


def test_a_fenced_illustration_is_not_counted_as_a_citation(tmp_path):
    """A specification writes whole examples of the notation it defines.

    Found 2026-09-10, between the fence filter landing and this being fixed:
    ``undeclared`` had begun calling a fenced stamp display while ``citations``
    still counted it as a use, so the reverse index reported citations of a key
    the tree does not cite anywhere. Two directions that could disagree about
    what a citation is eventually will.
    """
    write(tmp_path, "spec.md", """
        Shown, not spoken:

        ```markdown
        The contract is `docs/design.md` [0TMQDKB-Pa0003].
        ```
    """)
    assert citations(tmp_path) == []


def test_a_citation_below_a_fence_is_still_found_at_its_own_line(tmp_path):
    """The negative control, and the reason the filter blanks rather than drops.

    A worklist whose line numbers shifted by the length of a fence is not a
    worklist -- it is a list of places to look near.
    """
    write(tmp_path, "spec.md", """
        ```markdown
        The contract is [0TMQDKB-Pa0003].
        ```

        And in prose, genuinely: [0TMQDKB-Pa0003].
    """)
    found = citations(tmp_path)
    assert [str(one) for one in found] == ["spec.md:5"]
