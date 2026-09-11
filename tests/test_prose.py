"""Fenced code blocks: what a document *shows* rather than says.

The incident these exist for is this repository's own specification of the
citation notation. ``docs/citations.md`` prints a reference key inside a fence
so a reader can see what one looks like, and the closed-world citation catch
read that illustration as a citation of a source no bibliography declares --
true as stated, wrong in substance, and the third time here that a document
about a mechanism tripped that mechanism.

What is worth testing is the boundary rather than the happy case: the shapes
CommonMark distinguishes, the two places this deliberately departs from it, and
above all that prose *outside* a fence is untouched. A filter that quietly took
more than it was asked for would be the under-reporting failure with a tidier
report.
"""

from __future__ import annotations

from kinemata.prose import outside_code_spans, outside_fenced_blocks

CITATION = "[0TMQDKB-Ru0169]"


def blanked(source: str) -> list[str]:
    """The lines the filter removed, in order, stripped of whitespace."""
    before = source.splitlines()
    after = outside_fenced_blocks(source).splitlines()
    assert len(before) == len(after), "line numbers must survive the filter"
    return [
        raw.strip()
        for raw, kept in zip(before, after, strict=True)
        if raw.strip() and not kept.strip()
    ]


def survives(source: str, text: str) -> bool:
    return text in outside_fenced_blocks(source)


# -- the shapes CommonMark specifies ------------------------------------------


def test_a_backtick_fence_hides_what_it_shows():
    source = f"before\n```\n{CITATION}\n```\nafter\n"
    assert CITATION in blanked(source)
    assert survives(source, "before")
    assert survives(source, "after")


def test_a_tilde_fence_hides_what_it_shows():
    """The spelling a document reaches for when the sample itself has
    backticks in it -- which is exactly the sample this catch got wrong."""
    source = f"~~~\n{CITATION}\n~~~\n"
    assert blanked(source) == ["~~~", CITATION, "~~~"]


def test_a_fence_may_carry_an_info_string():
    source = f"```python\n{CITATION}\n```\n"
    assert CITATION in blanked(source)


def test_a_closing_fence_may_not_carry_an_info_string():
    """A fence line carrying a language name opens; it never closes. Without
    this a document showing two fenced samples has the prose between them read
    as code."""
    source = f"```\nfirst\n```python\nstill inside\n```\n{CITATION}\n"
    assert survives(source, CITATION)
    assert "still inside" in blanked(source)


def test_a_closing_fence_must_be_at_least_as_long_as_the_opener():
    """The reason long fences exist: a sample that itself contains a fence."""
    source = f"`````\n```\n{CITATION}\n```\n`````\nafter\n"
    assert CITATION in blanked(source)
    assert survives(source, "after")


def test_a_longer_closing_fence_still_closes():
    source = f"```\ninside\n``````\n{CITATION}\n"
    assert "inside" in blanked(source)
    assert survives(source, CITATION)


def test_a_tilde_fence_is_not_closed_by_backticks():
    source = f"~~~\n```\nstill inside\n~~~\n{CITATION}\n"
    assert "still inside" in blanked(source)
    assert survives(source, CITATION)


def test_a_backtick_run_whose_info_string_has_a_backtick_opens_nothing():
    """What keeps a sentence *about* fences from opening one. CommonMark says
    this of backticks and not of tildes, and the asymmetry is the whole
    protection: prose discussing the notation is the commonest place a stray
    run of three backticks appears."""
    source = f"``` and ``` are how you open one\n{CITATION}\n"
    assert blanked(source) == []
    assert survives(source, CITATION)


def test_a_tilde_info_string_may_contain_anything():
    source = f"~~~ and ~~~\n{CITATION}\n"
    assert CITATION in blanked(source)


def test_an_unclosed_fence_runs_to_the_end_of_the_document():
    """CommonMark's rule, and the safe one: the alternative is deciding on
    the author's behalf where they meant to stop."""
    source = f"before\n```\n{CITATION}\nand more\n"
    assert blanked(source) == ["```", CITATION, "and more"]
    assert survives(source, "before")


# -- indentation: where this departs from CommonMark, on purpose --------------


def test_a_fence_indented_three_spaces_is_a_fence():
    source = f"   ```\n   {CITATION}\n   ```\n"
    assert CITATION in blanked(source)


def test_a_fence_inside_a_list_item_is_a_fence():
    """CommonMark bounds an opener to three spaces *relative to its
    container*, and this parses no containers. Applying the document-level
    limit would leave every list-item sample unrecognized, which is a spelling
    real documentation uses constantly."""
    source = f"- an example:\n\n    ```\n    {CITATION}\n    ```\n\n- and on\n"
    assert CITATION in blanked(source)
    assert survives(source, "an example:")
    assert survives(source, "and on")


def test_a_closing_fence_may_be_indented_differently_from_its_opener():
    """Rejecting a closer on indentation leaves the fence open and blanks the
    rest of the file, which is the largest blast radius available here."""
    source = f"    ```\nsample\n```\n{CITATION}\n"
    assert "sample" in blanked(source)
    assert survives(source, CITATION)


def test_an_indented_block_is_not_treated_as_code():
    """Deliberate, and the cost is named in the docstring. Four spaces is
    equally a list continuation or a wrapped paragraph, and blanking those
    would stop the check on ordinary documents while it still read clean."""
    source = f"a paragraph:\n\n    {CITATION}\n\nand on\n"
    assert blanked(source) == []
    assert survives(source, CITATION)


# -- what the filter must not take --------------------------------------------


def test_prose_outside_a_fence_is_returned_verbatim():
    source = "one `span` two\n\n| a | b |\n\nplain prose\n"
    assert outside_fenced_blocks(source) == source.rstrip("\n")


def test_an_inline_span_is_left_alone():
    """The two filters answer different questions and compose rather than
    overlap: a backticked token on a prose line is a *mention*, which is
    ``outside_code_spans``'s job, and this one must not pre-empt it."""
    source = "the key `Ru0169` names a ruling\n"
    assert outside_fenced_blocks(source) == source.rstrip("\n")
    assert "Ru0169" not in outside_code_spans(source)


def test_two_fences_leave_the_prose_between_them():
    source = f"```\nfirst\n```\n\n{CITATION} in prose\n\n```\nsecond\n```\n"
    assert blanked(source) == ["```", "first", "```", "```", "second", "```"]
    assert survives(source, CITATION)
