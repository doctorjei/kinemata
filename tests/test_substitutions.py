"""Forbidden spellings as declared data, and prose matching.

The point being tested is that a word list is a registry. Kept in a checker's
source it goes unmaintained -- the table this replaces was missing two words
that were sitting in live documents while it reported clean.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.adapters.substitutions import Substitutions, bounded
from kinemata.bypass import scan
from kinemata.config import ConfigError, load


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def test_a_forbidden_spelling_is_found_in_prose(tmp_path):
    write(tmp_path, "doc.md", "This behaviour is documented.\n")
    registry = Substitutions({"behaviour": "behavior"})
    (site,) = scan(registry, tmp_path, suffixes=(".md",))
    assert site.entry_id == "behavior"


def test_case_is_ignored_unless_asked(tmp_path):
    """A sentence-initial ``Behaviour`` is the same violation."""
    write(tmp_path, "doc.md", "Behaviour matters.\n")
    assert scan(Substitutions({"behaviour": "behavior"}), tmp_path, suffixes=(".md",))
    strict = Substitutions({"behaviour": "behavior"}, case_sensitive=True)
    assert scan(strict, tmp_path, suffixes=(".md",)) == []


def test_a_word_inside_a_longer_one_is_not_a_violation(tmp_path):
    write(tmp_path, "doc.md", "The oldest behaviourism text.\n")
    registry = Substitutions({"behaviour": "behavior"})
    assert scan(registry, tmp_path, suffixes=(".md",)) == []


def test_a_mention_in_a_code_span_is_not_a_use(tmp_path):
    """Prose recording that a word was corrected has to spell the word.

    Reading that as a violation makes the record of a fix indistinguishable
    from the fix's absence.
    """
    write(tmp_path, "doc.md", "Corrected `behaviour` to the American spelling.\n")
    registry = Substitutions({"behaviour": "behavior"})
    assert scan(registry, tmp_path, suffixes=(".md",)) == []


def test_a_double_backtick_span_is_also_a_mention(tmp_path):
    """reST writes ``word``; a single-backtick pattern reads that as two empty
    spans and leaves the word between them exposed -- which it did."""
    write(tmp_path, "doc.md", "Corrected ``behaviour`` in the docstring.\n")
    registry = Substitutions({"behaviour": "behavior"})
    assert scan(registry, tmp_path, suffixes=(".md",)) == []


def test_a_fenced_block_is_still_checked(tmp_path):
    """The exemption is code *spans*, not examples. A spelling inside a fence
    is still the project's prose, and widening the exemption is how a check
    quietly stops checking."""
    write(tmp_path, "doc.md", "```\nthis behaviour is wrong\n```\n")
    registry = Substitutions({"behaviour": "behavior"})
    assert scan(registry, tmp_path, suffixes=(".md",))


def test_a_pattern_that_could_never_match_is_refused():
    """``\\b`` after ``)`` never matches, so the entry would check nothing."""
    assert bounded("enumerate()") == r"\benumerate\(\)"
    assert bounded("traceface") == r"\btraceface\b"


def test_words_come_from_a_file_so_a_long_list_is_not_config(tmp_path):
    write(tmp_path, "words.toml", '[words]\nbehaviour = "behavior"\n')
    write(tmp_path, "doc.md", "This behaviour is documented.\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [[registry]]
        name = "spelling"
        kind = "substitutions"
        source = "words.toml"
        suffixes = [".md"]
        """,
    )
    (registry,) = load(tmp_path / "kinemata.toml").registries
    assert [entry.id for entry in registry.entries()] == ["behavior"]


def test_declaring_both_a_file_and_inline_words_is_refused(tmp_path):
    write(tmp_path, "words.toml", '[words]\na = "b"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "spelling"
        kind = "substitutions"
        source = "words.toml"

          [registry.words]
          behaviour = "behavior"
        """,
    )
    with pytest.raises(ConfigError, match="not both"):
        load(tmp_path / "kinemata.toml")


# -- boundaries: a spelling in prose and a spelling in code are two jobs -------


def test_an_identifier_does_not_match_inside_a_longer_one(tmp_path):
    """The failure that produced this, measured on a real clause-ID scheme.

    Prose boundaries assert `\\b` after `vault`, and `-` supplies that boundary,
    so a retired `spec~box-vault` matched inside the live `spec~box-vault-enable`
    — reporting a surviving reference to the retired ID at exactly the site that
    proves the rename happened. Shared hyphenated prefixes are the natural
    spelling for a family of clauses, so a project meets this at its first such
    rename, and the report is indistinguishable from a real one.
    """
    write(tmp_path, "notes.md", "Renamed to spec~box-vault-enable this week.\n")
    words = {"spec~box-vault": "spec~box-vault-enable"}

    prose = Substitutions(words, case_sensitive=True)
    assert [hit.entry_id for hit in scan(prose, tmp_path, suffixes=[".md"])]

    identifiers = Substitutions(words, case_sensitive=True, boundary="identifier")
    assert scan(identifiers, tmp_path, suffixes=[".md"]) == []


def test_an_identifier_in_a_code_span_is_seen(tmp_path):
    """The second half of the same defect, and the one that made the registry
    report clean over documents carrying the retired name.

    `prose` blanks inline code spans — right for a word list, since a document
    correcting `recognisable` has to spell it — and wrong for a name list,
    because a retired identifier is nearly always written in backticks. So the
    boundary choice carries the match mode with it.
    """
    write(tmp_path, "notes.md", "Still references `spec~box-vault` here.\n")
    words = {"spec~box-vault": "spec~box-vault-enable"}

    found = scan(Substitutions(words, case_sensitive=True, boundary="identifier"),
                 tmp_path, suffixes=[".md"])
    assert [hit.entry_id for hit in found] == ["spec~box-vault-enable"]


def test_prose_keeps_the_boundary_an_identifier_would_reject(tmp_path):
    """Why this is a declared choice and not a replacement. A sentence ending
    `behaviour.` is a real violation that prose boundaries catch and identifier
    boundaries reject, because `.` legitimately abuts an identifier."""
    write(tmp_path, "notes.md", "We documented the behaviour.\n")
    words = {"behaviour": "behavior"}

    assert [hit.entry_id for hit in scan(Substitutions(words), tmp_path,
                                         suffixes=[".md"])] == ["behavior"]
    assert scan(Substitutions(words, boundary="identifier"), tmp_path,
                suffixes=[".md"]) == []


def test_an_unknown_boundary_is_refused():
    """A misspelled boundary silently falling back to prose would reinstate the
    false positive this exists to remove."""
    with pytest.raises(ValueError, match="unknown boundary"):
        Substitutions({"a": "b"}, boundary="identifiers")


def test_a_spelling_holding_a_regex_metacharacter_still_matches(tmp_path):
    """Regression on my own first draft, which stripped `|` out of the compiled
    pattern and would have silently broken any spelling containing one."""
    write(tmp_path, "notes.md", "The `a|b` form is retired.\n")
    found = scan(Substitutions({"a|b": "c"}, boundary="identifier"),
                 tmp_path, suffixes=[".md"])
    assert [hit.entry_id for hit in found] == ["c"]
