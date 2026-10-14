"""Fenced signatures, checked against the code they claim to show.

The extraction was measured before it was wired, on the tree that asked for
it, and was wrong five times on the way: keyword-only read as defaulted, class
bases compared against parameters, ``ast.unparse`` quotes, absent defaults
treated as values, and a ``[^)]*`` truncating a parameter list. Each has a test
here, because each was a working-looking result rather than an error.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.claims import verify
from kinemata.config import load
from kinemata.signatures import (
    Index,
    fenced_signatures,
    index_source,
    read_signature,
)


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def fence(body: str) -> str:
    return "```python\n" + textwrap.dedent(body).strip() + "\n```\n"


def shown(text: str):
    return [str(found) for found in fenced_signatures(text)]


def signature_findings(result):
    return [claim for claim in result.broken if claim.kind == "signature"]


SOURCE = '''
def greet(name: str, times: int = 1) -> str:
    return name * times


def lookup(key, *, strict, default=None):
    return key


class Box(Base):
    pass


def settings_files(
    mode: str, metadata: str, keep: tuple[str, str] = ()
) -> str:
    return mode
'''


# -- extraction --------------------------------------------------------------


def test_a_wrapped_signature_is_one_claim():
    """16% of the measured population wraps, and both failures are silent.

    Line by line, half a signature reads as drift; whole lines only, a sixth of
    the corpus is never looked at.
    """
    document = fence("""
        def settings_files(
            mode: str, metadata: str, keep: tuple[str, str] = ()
        ) -> str:
    """)
    assert shown(document) == ["def settings_files(mode, metadata, keep = ())"]


def test_a_parenthesis_inside_a_default_does_not_end_the_list():
    """The ``[^)]*`` truncation, which read one long wrong name."""
    (found,) = fenced_signatures(fence("def f(keep: tuple[str, str] = (), last=1):"))
    assert found.bare == ("keep", "last")


def test_nothing_outside_a_fence_is_a_claim():
    """The premise: prose about an identifier is the guesser this declines."""
    assert shown("Call `greet(name)` or greet(name, times = 3) to say hi.\n") == []


def test_a_line_opening_with_an_inline_span_opens_no_fence():
    """CommonMark: a backtick fence's info string may not hold a backtick.

    A copy of the fence regex missed that, so a paragraph line beginning
    with a triple-backtick span flipped it into a fence and the prose after it
    was read as code -- 26 findings on one adopter's tree, every one a phrase
    like ``task(s)``. There is one fence reader now, and this is its rule.
    """
    document = (
        "```CONTINUE_MARKER``` names the task a box resumes.\n"
        "\n"
        + fence("def resume(box, marker = None):")
    )
    # **The silent direction is the one to pin.** A span read as an opener
    # makes the real fence's opener unable to close it, so the real fence's
    # contents are read under the span's "language" and skipped -- the one
    # signature this document actually shows is never checked.
    assert shown(document) == ["def resume(box, marker = None)"]


def test_a_word_before_a_parenthetical_is_not_a_call():
    """Terminal output and error text, both in untagged fences on one tree."""
    document = fence("""
        $ ls ~/private                          $ ls ~/private
        notes                                    (empty)
        none (goose pins no provider so its own config keeps it).
    """)
    assert shown(document) == []
    assert shown(fence("def f (a):")) == ["def f(a)"]


def test_a_fence_naming_another_language_is_not_python():
    """A shell function is spelled ``ok() {``, which reads exactly like a call."""
    assert shown("```bash\nok() {\n  echo ok\n}\n```\n") == []
    assert shown("```python\nok()\n```\n") == ["ok()"]
    assert shown("```\nok()\n```\n") == ["ok()"]


def test_a_signature_never_runs_on_into_the_next_block():
    document = "```python\ndef f(a,\n```\n\n```python\nb)\n```\n"
    assert shown(document) == []


def test_a_class_base_is_an_expression_not_a_name():
    """Dotted and subscripted bases were dropped as non-identifiers.

    So every such class read as having no bases: 24 correct classes on one
    adopter's API pages, reported as drift.
    """
    index = index_source(
        "import argparse\n"
        "class P(argparse.ArgumentParser):\n    pass\n"
        "class M(Mapping[str, 'Collection[str]']):\n    pass\n"
    )
    for text in (
        "class P(argparse.ArgumentParser):",
        'class M(Mapping[str, "Collection[str]"]):',
    ):
        (written,) = fenced_signatures(fence(text))
        assert index.accepts(written), text


def test_star_args_sit_before_the_keyword_only_parameters():
    """Where Python writes them. Appended last, a correct copy read as drift."""
    index = index_source("def run(*args, cwd, **kwargs):\n    pass\n")
    (written,) = fenced_signatures(fence("def run(*args: str, cwd: Path, **kwargs):"))
    assert index.accepts(written)


def test_a_keyword_only_parameter_without_a_default_is_required():
    """The first of the five corrections: 55 findings where there was one."""
    (declared,) = index_source(SOURCE).by_name["lookup"]
    assert declared.params == (
        ("key", ""), ("strict", ""), ("default", "None"),
    )


def test_a_class_is_compared_on_its_bases():
    index = index_source(SOURCE)
    (written,) = fenced_signatures(fence("class Box(Base):"))
    assert index.accepts(written)
    (wrong,) = fenced_signatures(fence("class Box(Other):"))
    assert not index.accepts(wrong)


def test_a_constructor_call_is_not_read():
    """A class's parentheses hold bases and a constructor's hold its fields.

    Reading ``Box(Base)`` as a claim would compare arguments against bases and
    accept any call that happened to pass the base's name. **What a constructor
    call does claim -- the fields of a dataclass -- is not checked**, and it is
    one of the two misses the adopter named next.
    """
    assert shown(fence("Box(Base)")) == []


def test_a_rendering_reads_back_as_the_same_signature():
    """A claim travels as text, so the text has to be readable by its reader.

    The rendering spelled a call ``call greet(...)`` until the wiring tried to
    read one back and every call in every tree came out as drift.
    """
    for text in ("greet(name, times = 1)", "def lookup(key, strict, default = None)"):
        (found,) = fenced_signatures(fence(text))
        again = read_signature(str(found))
        assert again is not None
        assert (again.kind, again.params) == (found.kind, found.params)


def test_an_index_merges_every_declaration_of_a_name():
    """An overload or a redefinition: a document naming either one is right."""
    index = Index()
    index.update(index_source("def f(a):\n    pass\n"))
    index.update(index_source("def f(a, b=2):\n    pass\n"))
    assert len(index.by_name["f"]) == 2
    (written,) = fenced_signatures(fence("f(a, b = 2)"))
    assert index.accepts(written)


# -- the claim kind ------------------------------------------------------------


def test_off_unless_asked(tmp_path):
    """Opt-in, and the only kind that is: it reads the project's own code."""
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", fence("greet(name, times = 9)"))
    assert signature_findings(verify(tmp_path)) == []


def test_a_signature_that_agrees_passes(tmp_path):
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", fence("""
        def greet(name: str, times: int = 1) -> str:
        greet(name, times = 1)
        def settings_files(
            mode: str, metadata: str, keep: tuple[str, str] = ()
        ) -> str:
    """))
    result = verify(tmp_path, signatures=True)
    assert signature_findings(result) == []
    assert not result.blocked


def test_a_wrong_default_value_fails(tmp_path):
    """The adopter's evidence, and the reason values are compared at all.

    Three of their documentation lanes came back for ``= ""`` where the code
    has ``= UNSET``. Names and order agree, so a presence check passes them.
    """
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", fence("greet(name, times = 2)"))
    (finding,) = signature_findings(verify(tmp_path, signatures=True))
    assert finding.line == 2
    # The disagreement is in the text a record fingerprints, and it names what
    # the reader should open: the code's own declaration.
    assert "the code declares def greet(name, times = 1)" in finding.text


def test_a_quote_style_is_not_a_claim(tmp_path):
    """``ast.unparse`` rewrites quotes, so comparing raw text reports right prose."""
    write(tmp_path, "src/mod.py", "def f(sep=''):\n    pass\n")
    write(tmp_path, "doc.md", fence('f(sep = "")'))
    assert signature_findings(verify(tmp_path, signatures=True)) == []


def test_a_parameter_out_of_order_fails(tmp_path):
    """Order alone, with no default to differ on.

    The first version of this test swapped a defaulted parameter too, so it
    failed on the default value and passed with the name comparison deleted --
    a mutation survived it, which is how it was found.
    """
    write(tmp_path, "src/mod.py", "def pair(left, right):\n    pass\n")
    write(tmp_path, "doc.md", fence("pair(right, left)"))
    assert len(signature_findings(verify(tmp_path, signatures=True))) == 1


def test_a_name_the_code_does_not_declare_fails(tmp_path):
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", fence("farewell(name)"))
    (finding,) = signature_findings(verify(tmp_path, signatures=True))
    assert finding.text == "farewell(name)"


def test_a_wrapped_signature_is_reported_where_it_starts(tmp_path):
    """The line a reader opens, and the one a baseline record fingerprints."""
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", "# Title\n\n" + fence("""
        def settings_files(
            mode: str, metadata: str, keep: tuple[str, str] = ("a", "b")
        ) -> str:
    """))
    (finding,) = signature_findings(verify(tmp_path, signatures=True))
    assert finding.line == 4
    assert finding.source == "def settings_files("


def test_somebody_elses_code_does_not_satisfy_a_claim(tmp_path):
    """An excluded tree is not this project's material, and that is load-bearing.

    A corpus of other projects' Python would otherwise answer for a fenced
    signature, hiding exactly the drift this exists for -- in the direction a
    reader would never notice.
    """
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "corpus/other/mod.py", "def farewell(name):\n    pass\n")
    write(tmp_path, "doc.md", fence("farewell(name)"))
    result = verify(tmp_path, signatures=True, exclude=("corpus",))
    assert len(signature_findings(result)) == 1


def test_a_narrowed_run_still_compares_against_the_whole_project(tmp_path):
    """``within`` narrows the documents read, never the code they describe."""
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "docs/guide.md", fence("greet(name, times = 1)"))
    result = verify(tmp_path, signatures=True, within=tmp_path / "docs")
    assert signature_findings(result) == []
    assert not result.blocked


def test_a_historical_document_is_not_held_to_the_current_code(tmp_path):
    """An archive shows what a signature *was*, which is what it is for."""
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "docs/guide.md", fence("greet(name, times = 1)"))
    write(tmp_path, "archives/old.md", fence("greet(name)"))
    result = verify(tmp_path, signatures=True, historical=("archives",))
    assert signature_findings(result) == []


def test_a_finding_rides_the_shared_ratchet(tmp_path):
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", fence("greet(name, times = 2)"))
    ((registry, finding),) = verify(tmp_path, signatures=True).findings()
    assert registry == "claims"
    assert finding.entry_id == "claim:signature"


# -- declared and examining nothing ------------------------------------------


def test_documents_showing_no_signature_block_the_run(tmp_path):
    """The oracle answered and nothing asked it -- `[[count]]`'s rule, reused."""
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", "# Guide\n\nSee `src/mod.py`.\n")
    result = verify(tmp_path, signatures=True)
    (why,) = result.blocked
    assert "no document showed a fenced signature" in why
    assert result.failed


def test_no_python_to_compare_against_blocks_rather_than_reporting_drift(tmp_path):
    """An empty index would report every signature shown, all of them its fault.

    And only the index's message: the documents *were* read, so saying no
    document showed a signature would be false about a tree full of them.
    """
    write(tmp_path, "doc.md", fence("def f(a, b = 2):"))
    result = verify(tmp_path, signatures=True)
    assert signature_findings(result) == []
    (why,) = result.blocked
    assert "no Python source was read" in why


@pytest.mark.parametrize("excluded", [("src",), ("mod.py",)])
def test_excluding_every_source_file_is_the_same_vacuity(tmp_path, excluded):
    write(tmp_path, "src/mod.py", SOURCE)
    write(tmp_path, "doc.md", fence("greet(name, times = 1)"))
    result = verify(tmp_path, signatures=True, exclude=excluded)
    (why,) = result.blocked
    assert "no Python source was read" in why


# -- the config ----------------------------------------------------------------


def test_the_config_arms_it(tmp_path):
    write(tmp_path, "kinemata.toml", """
        [claims]
        suffixes = [".md"]
        signatures = true
    """)
    assert load(tmp_path / "kinemata.toml").signatures


def test_the_config_leaves_it_off_by_default(tmp_path):
    write(tmp_path, "kinemata.toml", """
        [claims]
        suffixes = [".md"]
    """)
    assert not load(tmp_path / "kinemata.toml").signatures
