"""Documentation that lives in code, and the reason it is not simply scanned.

Two dead references paid for these. `contract.py` and `projection.py` each sent
the reader to a design document at a path that holds nothing but a note saying
the design moved, and both sat there through a CI gate whose whole job is
falsifying documentation -- because the declared document suffixes were markdown
alone, in a codebase whose convention is that a docstring names the incident
that forced the design.

The interesting half is not that a docstring can be read. It is that a Python
file is *mostly not prose*: reading one whole turns a default value, a fixture
and an embedded workflow template into assertions about the tree, which is the
over-reporting failure `claims` was built around. So the tests below are
weighted toward what must **not** become a claim.
"""

from __future__ import annotations

import textwrap

from kinemata.citations import citations
from kinemata.claims import Counted, verify
from kinemata.prose import outside_illustrations, python_prose_only
from kinemata.provenance import declared_foreign

PY = (".md", ".py")

#: A syntactically valid stamp, so these tests exercise the association rule
#: rather than the codec's refusals.
STAMP = "0TMQDKB"


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def broken(result):
    return {(claim.kind, claim.text) for claim in result.broken}


# -- the filter itself -------------------------------------------------------


def test_prose_only_keeps_docstrings_and_comments_and_drops_the_rest():
    source = textwrap.dedent('''
        """Module doc, see ``docs/design.md``."""
        # A comment about ``src/app.py``.
        DEFAULT = "config/settings.toml"


        def f():
            """Function doc, see ``docs/other.md``."""
            return "templates/page.html"
    ''').lstrip()
    kept = python_prose_only(source)
    assert "docs/design.md" in kept
    assert "src/app.py" in kept
    assert "docs/other.md" in kept
    assert "config/settings.toml" not in kept
    assert "templates/page.html" not in kept


def test_prose_only_keeps_line_numbers_stable():
    """A reported line number has to point at the right line in the real file.

    Blanking rather than deleting is the whole reason the filters here return a
    string of the same shape instead of a list of interesting lines.
    """
    source = textwrap.dedent('''
        """Doc."""
        X = "a/b.py"
        # tail ``c/d.py``
    ''').lstrip()
    kept = python_prose_only(source).splitlines()
    assert len(kept) == len(source.splitlines())
    assert kept[2].strip() == "# tail ``c/d.py``"


def test_a_long_literal_is_not_a_docstring_by_being_triple_quoted():
    """Docstrings are located structurally, not by how they are quoted."""
    source = textwrap.dedent('''
        TEMPLATE = """
        run: kinemata check
        see ``docs/design.md``
        """
    ''').lstrip()
    assert "docs/design.md" not in python_prose_only(source)


def test_an_unparseable_file_is_read_whole_rather_than_skipped():
    """Over-reporting is the safe direction; a silent skip is not."""
    source = 'def f(:\n    """doc ``docs/design.md``"""\n'
    assert python_prose_only(source) == source


# -- what a scanned .py file does and does not claim -------------------------


def test_a_dead_path_in_a_docstring_is_a_claim(tmp_path):
    """The incident: a module docstring pointing at a design that moved."""
    write(tmp_path, "src/app.py", '''
        """The registry contract.

        See ``designs/registry-contract.md``.
        """
    ''')
    assert broken(verify(tmp_path, suffixes=PY)) == {
        ("path", "designs/registry-contract.md")
    }


def test_a_live_path_in_a_docstring_resolves(tmp_path):
    write(tmp_path, "docs/design.md", "the design\n")
    write(tmp_path, "src/app.py", '"""See ``docs/design.md``."""\n')
    result = verify(tmp_path, suffixes=PY)
    assert result.broken == []
    assert result.checked >= 1


def test_a_path_in_a_comment_is_a_claim(tmp_path):
    write(tmp_path, "src/app.py", '''
        """Doc."""
        #: the loader lives in ``src/gone.py``
        X = 1
    ''')
    assert broken(verify(tmp_path, suffixes=PY)) == {("path", "src/gone.py")}


def test_a_path_in_a_string_literal_is_a_value_not_a_citation(tmp_path):
    """The reason ``.py`` is filtered rather than scanned whole.

    A default, a fixture and an embedded template all name paths the code uses.
    None of them asserts that the path is in this tree, and reading them that
    way is over-reporting on the scale that teaches a reader to skim the report.
    """
    write(tmp_path, "src/app.py", '''
        """Doc."""
        HELP = "point it at `conf/missing.toml` to start"
        FIXTURE = ["tests/data/absent.json"]
        TEMPLATE = """
        - run: build --design ``docs/absent.md``
        """
    ''')
    assert verify(tmp_path, suffixes=PY).broken == []


def test_executable_code_is_not_read_as_a_markdown_link(tmp_path):
    """Measured on this package: one line of its own source did exactly this.

    ``BOUNDARIES[boundary](str(forbidden))`` is a subscript followed by a call,
    and the link extractor read it as a bracket-and-parenthesis link whose
    target was a dead path.
    """
    write(tmp_path, "src/app.py", '''
        """Doc."""
        BOUNDARIES = {}
        boundary = "prose"
        forbidden = "x"
        pattern = BOUNDARIES[boundary](str(forbidden))
    ''')
    assert verify(tmp_path, suffixes=PY).broken == []


# -- the delimiter run, matched deliberately ---------------------------------


def test_a_doubled_delimiter_is_matched_as_a_run(tmp_path):
    """reStructuredText's inline literal, read on purpose rather than by luck.

    A single-backtick pattern found the token because the *inner* pair of a
    doubled delimiter is itself a markdown span. That holds only while nobody
    writes a longer run, which is the definition of working by accident.
    """
    write(tmp_path, "doc.md", "``a/one.md`` and ```a/two.md``` and `a/three.md`\n")
    assert broken(verify(tmp_path)) == {
        ("path", "a/one.md"), ("path", "a/two.md"), ("path", "a/three.md")
    }


def test_a_commit_in_a_doubled_delimiter_is_still_a_commit_claim(tmp_path):
    """The hash extractor takes the run too; this project's docstrings need it."""
    import subprocess

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    write(tmp_path, "src/app.py", '"""Fixed by ``0123456789ab``."""\n')
    assert broken(verify(tmp_path, suffixes=PY)) == {("commit", "0123456789ab")}


def test_adjacent_literals_do_not_fabricate_a_token_between_them(tmp_path):
    """Where the coincidence actually cost something, rather than in theory.

    A single-backtick pattern consumed one delimiter of a doubled pair and left
    the other in the stream, so the *closing* delimiter of one literal paired
    with the *opening* delimiter of the next and the text between two literals
    became a token of its own. This repository spells run-on literals that way
    in two places, and got a token there that no document wrote.
    """
    write(tmp_path, "docs/a.md", "x\n")
    write(tmp_path, "docs/b.md", "x\n")
    write(tmp_path, "doc.md", "``docs/a.md``docs/gone.md``docs/b.md``\n")
    assert verify(tmp_path).broken == []


# -- the suffix stays honest -------------------------------------------------


def test_a_declared_py_suffix_that_yields_nothing_still_warns(tmp_path):
    """Refuse, don't no-op: a suffix read for nothing says so.

    Every claim in this file is in code rather than prose, so the filter leaves
    nothing behind -- which is exactly the state a reader has to be told about,
    since it reads identically to a clean run.
    """
    write(tmp_path, "src/app.py", 'DEFAULT = "conf/missing.toml"\n')
    write(tmp_path, "doc.md", "nothing here\n")
    result = verify(tmp_path, suffixes=PY)
    assert any(".py" in message and "yielded no claims" in message
               for message in result.warnings)


# -- the illustration role ---------------------------------------------------
#
# Marking a span as shown rather than asserted. The eight sites in `src/` that
# forced it were all inside sentences: a capitalized filename spelling, a link
# target standing for any link target, two phrasings a count pattern has to
# handle, a pair of paths illustrating why a promise is matched exactly. A
# markdown document says this with a fence; a docstring had no way to say it.
#
# What is worth testing is the suppression's edges, since a suppression that
# takes more than it was asked for is the under-reporting failure with a tidy
# report: an unmarked path beside a marked one, some other role, a misspelled
# one, and markdown, which is deliberately left out.


def test_a_marked_path_is_not_a_claim(tmp_path):
    write(tmp_path, "src/app.py", '''
        """Doc.

        A capitalized document name -- :shown:`Introduction.md` -- is a
        spelling projects use.
        """
    ''')
    assert verify(tmp_path, suffixes=PY).broken == []


def test_an_unmarked_path_on_the_same_line_is_still_a_claim(tmp_path):
    """The suppression is the span, not the line.

    A docstring that shows one path usually asserts another in the same breath,
    and blanking the line would be this module's original negation bug in new
    clothes: it reported clean while checking less than it said.
    """
    write(tmp_path, "src/app.py", '''
        """Doc.

        Unlike :shown:`docs/shown.md`, ``docs/asserted.md`` is really there.
        """
    ''')
    assert broken(verify(tmp_path, suffixes=PY)) == {("path", "docs/asserted.md")}


def test_marking_does_not_change_the_token(tmp_path):
    """The marker goes outside the delimiters, and this is why.

    A stamp placed *inside* backticks changed the path it was attached to and
    the citation stopped resolving. So the same characters have to mean the same
    path whether or not the span carries the role -- here the marked copy is
    suppressed and the unmarked copy is reported, and the two spell the same
    thing.
    """
    token = "docs/gone.md"
    write(tmp_path, "src/app.py", f'''
        """Doc.

        Shown: :shown:`{token}`. Asserted: ``{token}``.
        """
    ''')
    assert broken(verify(tmp_path, suffixes=PY)) == {("path", token)}


def test_a_marked_link_target_is_not_a_claim(tmp_path):
    """One of the eight: a link target standing in for any link target."""
    write(tmp_path, "src/app.py", '''
        """Doc.

        A checker that only reads :shown:`[text](target)` walks past a bare URL.
        """
    ''')
    assert verify(tmp_path, suffixes=PY).broken == []


def test_a_marked_value_is_not_a_counted_claim(tmp_path):
    """``[[count]]`` reads the same reduced text every other kind does.

    The site that forced it cannot be reworded: the docstring explaining the
    count oracle recounts the numbers this project's notes once claimed, and the
    stale numbers *are* the record.
    """
    spec = Counted(
        pattern=r"\*\*(\d+) tests\*\*|\b(\d+) tests pass\b",
        command=("{python}", "-c", "print('7 tests collected')"),
        extract=r"(\d+) tests collected",
        label="test count",
    )
    write(tmp_path, "src/app.py", '''
        """Doc.

        Written as alternation -- :shown:`**103 tests**` or
        :shown:`103 tests pass` -- so every branch but one captures nothing.
        """
    ''')
    assert verify(tmp_path, suffixes=PY, counts=[spec]).broken == []


def test_an_unmarked_value_is_still_a_counted_claim(tmp_path):
    """The other half: the suffix still reaches ``[[count]]``."""
    spec = Counted(
        pattern=r"\*\*(\d+) tests\*\*",
        command=("{python}", "-c", "print('7 tests collected')"),
        extract=r"(\d+) tests collected",
        label="test count",
    )
    write(tmp_path, "src/app.py", '"""Doc. The suite is **103 tests** long."""\n')
    assert [claim.kind for claim in verify(
        tmp_path, suffixes=PY, counts=[spec]
    ).broken] == ["test count"]


def test_a_cross_reference_role_suppresses_nothing(tmp_path):
    """One role, not any role, and this is the cost of the alternative.

    Skipping every role-prefixed span was the tempting rule: none of the six
    roles this codebase uses denotes a path in its tree, and 0 of the 88 spans
    they mark carried a claim when this was measured. But Sphinx's ``doc`` and
    ``download`` take a path in the tree as their target, so "there is a role"
    would silence a real citation the day somebody writes one -- quietly, which
    is the direction this module has already had to scope back once.
    """
    write(tmp_path, "src/app.py", '''
        """Doc.

        See :doc:`docs/gone.md` and :func:`docs/also-gone.md`.
        """
    ''')
    assert broken(verify(tmp_path, suffixes=PY)) == {
        ("path", "docs/gone.md"), ("path", "docs/also-gone.md")
    }


def test_a_misspelled_role_suppresses_nothing_and_the_claim_goes_red(tmp_path):
    """Refuse, don't no-op -- and here the refusal costs no machinery.

    There is no table of recognized roles to typo against: an unknown role is
    simply not this one, so the span is still read and a dead path still fails.
    A typo surfaces as a finding the author already knows how to fix, rather
    than as a claim that quietly stopped being checked.
    """
    write(tmp_path, "src/app.py", '"""Doc. See :shwon:`docs/gone.md`."""\n')
    assert broken(verify(tmp_path, suffixes=PY)) == {("path", "docs/gone.md")}


def test_marked_spans_are_counted(tmp_path):
    """Suppression is reported, never silent.

    Counted rather than listed: the sites are correct by construction and the
    reader's action on each is none, but a suppression nobody can count is an
    allowlist with a good story.
    """
    write(tmp_path, "src/app.py", '''
        """Doc.

        :shown:`Introduction.md`, :shown:`Changelog.md`, :shown:`docs/plan.md`.
        """
    ''')
    result = verify(tmp_path, suffixes=PY)
    assert result.broken == []
    assert result.shown == 3


def test_a_run_of_delimiters_is_matched_too(tmp_path):
    """reStructuredText wants single backticks after a role, and this codebase
    spells literals doubled.

    Matching one run length while doing nothing at the other is behavior held
    together by coincidence, which is the argument :data:`_BACKTICKED` already
    makes.
    """
    write(tmp_path, "src/app.py", '''
        """Doc. :shown:`a/one.md`, :shown:``a/two.md``, :shown:```a/three.md```."""
    ''')
    result = verify(tmp_path, suffixes=PY)
    assert result.broken == []
    assert result.shown == 3


def test_the_role_is_not_honored_in_markdown(tmp_path):
    """Markdown is left out on purpose, not overlooked.

    A reStructuredText role renders as literal text in markdown, so honoring it
    there would put checker syntax in front of a human reader. Markdown's answer
    to the same problem is the fence, whose cost ``claims`` has already named
    and measured; a second notation would hide that decision rather than make
    it.
    """
    write(tmp_path, "doc.md", "See :shown:`docs/gone.md`.\n")
    result = verify(tmp_path)
    assert broken(result) == {("path", "docs/gone.md")}
    assert result.shown == 0


def test_the_filter_keeps_line_numbers_and_line_lengths(tmp_path):
    """Blanked in place, like every other filter here.

    A reported line number has to point at the right line in the real file.
    """
    source = 'x :shown:`a/b.md` y\nz ``c/d.md`` w\n'
    kept = outside_illustrations(source)
    assert kept.splitlines() == ["x                 y", "z ``c/d.md`` w"]


# -- evidence in somebody else's tree ----------------------------------------
#
# A tool validated against other projects cites those projects. The citations
# are real and permanently unresolvable here, which left the docstring scan
# with a residue it could never drive to zero -- and a gate that can never go
# green over text nobody should change is a gate its reader learns to skim.


def test_a_citation_beside_a_foreign_key_is_not_a_claim_about_this_tree(tmp_path):
    write(tmp_path, "mod.py", '''
        """Their tripwire scanned ``project/workset.py`` [{stamp}-Pa0004]."""
    '''.replace("{stamp}", STAMP))

    assert broken(verify(tmp_path, suffixes=PY)) == {("path", "project/workset.py")}

    settled = verify(tmp_path, suffixes=PY, foreign=declared_foreign({"Pa0004"}))
    assert settled.broken == []
    assert [claim.text for claim in settled.foreign] == ["project/workset.py"]


def test_a_key_nothing_declares_foreign_settles_nothing(tmp_path):
    """The predicate answers for the keys it was given and no others.

    Otherwise any keyed citation would exempt itself, which would make the
    citation notation a suppression syntax -- the opposite of what declaring is
    for.
    """
    write(tmp_path, "mod.py", '''
        """Their tripwire scanned ``project/workset.py`` [{stamp}-Pa0004]."""
    '''.replace("{stamp}", STAMP))

    result = verify(tmp_path, suffixes=PY, foreign=declared_foreign({"Cm0001"}))
    assert broken(result) == {("path", "project/workset.py")}
    assert result.foreign == []


def test_one_keyed_occurrence_does_not_cover_an_unkeyed_one(tmp_path):
    """Every occurrence, not any: the line still contains a live claim.

    A sentence naming one path as another project's and then as this one's has
    something in it that this tree can be wrong about, and the conservative
    reading keeps checking it. Getting this backwards would let a declaration
    switch off a real claim.
    """
    write(tmp_path, "mod.py", '''
        """Theirs ``a/thing.py`` [{stamp}-Pa0004], ours ``a/thing.py`` too."""
    '''.replace("{stamp}", STAMP))

    result = verify(tmp_path, suffixes=PY, foreign=declared_foreign({"Pa0004"}))
    assert broken(result) == {("path", "a/thing.py")}
    assert result.foreign == []


def test_a_foreign_key_cannot_take_a_live_claim_out_of_the_check(tmp_path):
    """Resolution is asked first, so the declaration never overrides the tree.

    A path that exists here is this project's whatever a key beside it says --
    and it is reported as resolved rather than as foreign, so the count of
    waived citations stays honest.
    """
    write(tmp_path, "src/real.py", "x = 1\n")
    write(tmp_path, "mod.py", '''
        """Also in their tree: ``src/real.py`` [{stamp}-Pa0004]."""
    '''.replace("{stamp}", STAMP))

    result = verify(tmp_path, suffixes=PY, foreign=declared_foreign({"Pa0004"}))
    assert result.broken == []
    assert result.foreign == []


def test_an_illustrated_citation_is_not_a_citation(tmp_path):
    """The unfenced filter reads `.py` now, and a role is how it is told.

    Before it did, the closed-world catch and the reverse index read source
    files whole -- so this package's own ``stamps`` module, whose docstrings
    display a malformed key to explain why the width is fixed, refused every
    command that scanned it.
    """
    write(tmp_path, "mod.py", '''
        """Pinning the width would make :shown:`[{stamp}-Ru0169]` match nothing."""
        WIRE = "[{stamp}-Ru0170] is not prose either"
    '''.replace("{stamp}", STAMP))

    assert citations(tmp_path, suffixes=[".py"]) == []
