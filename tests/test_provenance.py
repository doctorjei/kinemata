"""Citations that carry no time, and the clock over the ones that do.

Section 6 of ``docs/citations.md`` settles the policy and this suite pins the
two things about it that are easy to get quietly wrong.

**The association rule.** *"This path citation has no stamp"* requires knowing
which stamp belongs to which citation, and that association was deliberately
left unbuilt until the catch needed it. What is worth testing is therefore not
that a stamp can be found but that the rule is the narrow one it claims to be:
a stamp immediately after its citation, at most one space away, on the same
line -- and that everything else is reported as *nothing* rather than as a
wrong accusation. A false accusation of an undated citation teaches its reader
that the check is noise, which switches the check off for the findings that
were real.

**Adoption.** Armed on a tree that has never dated a citation, the catch
reports every citation in it. A gate that fires on everything on day one is one
somebody switches off, so the findings have to go through the ratchet that
already exists rather than a second one built beside it.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, datetime, timedelta

import pytest

from kinemata.adapters.bibliography import Bibliography
from kinemata.baseline import record
from kinemata.claims import CLAIM_KINDS
from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.confirm import _accompanied
from kinemata.provenance import (
    _BY_KIND,
    CLOCKED,
    DEFAULT_STALE_AFTER,
    PROVENANCE_REGISTRY,
    ProvenanceError,
    survey,
)

#: A stamp from 2020, so "is this stale" is answered by the mechanism rather
#: than by what day the suite happens to run on.
OLD = "0M00000"

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)

#: A commit-shaped token that is not a run of digits, which ``_commit_claims``
#: passes over: an adopter's eleven-digit byte count was reported as a dead
#: commit, and all-decimal short hashes are rare enough not to be worth it.
SHA = "abcdef12"


def write(tmp_path, rel, body, *, dedent=True):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip() if dedent else body)
    return path


def tree(tmp_path, document, *, rel="notes.md"):
    """One document, and the target its path citations name."""
    write(tmp_path, "docs/design.md", "the contract\n")
    return write(tmp_path, rel, document)


def look(tmp_path, document, **kwargs):
    tree(tmp_path, document)
    return survey(tmp_path, suffixes=(".md",), **kwargs)


def project(tmp_path, document, *, citations="provenance = true"):
    """The same tree, reachable through the command line."""
    tree(tmp_path, document)
    write(tmp_path, "words.toml", """
        [[word]]
        prefer = "color"
        instead_of = ["colour"]
    """)
    return write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."

        [claims]
        suffixes = [".md"]
        historical = ["archives/"]

        [citations]
        {citations}

        [[registry]]
        name = "spelling"
        kind = "substitutions"
        source = "words.toml"
    """)


def only(found):
    """The single sighting a test is about."""
    (seen,) = found.sightings
    return seen


# -- the association rule, and what it cannot see ----------------------------


@pytest.mark.parametrize(
    "line, dated",
    [
        ("The contract is `docs/design.md`[STAMP-Pa].", True),
        ("The contract is `docs/design.md` [STAMP-Pa].", True),
        ("The contract is `docs/design.md`  [STAMP-Pa].", False),
        ("The contract is `docs/design.md`. [STAMP-Pa]", False),
        ("[STAMP-Pa] the contract is `docs/design.md`.", False),
        ("The contract [STAMP-Pa] is `docs/design.md`.", False),
        ("The contract is `docs/design.md` and also `docs/design.md`.", False),
    ],
)
def test_the_stamp_follows_its_citation(tmp_path, line, dated):
    """The whole rule: nothing, or one space, between the two.

    Stated rather than inferred, because the alternative is guessing which of a
    sentence's several backticked words a stamp was about. The cases that read
    as near misses -- two spaces, a period in between, a stamp in front -- are
    all *undated*, which is a finding somebody fixes by moving the stamp, not a
    silence somebody never learns about.
    """
    found = look(tmp_path, line.replace("STAMP", OLD) + "\n")
    assert only(found).dated is dated


def test_the_two_directions_agree(tmp_path):
    """The forward rule here and ``confirm``'s backward one read one relation.

    ``confirm`` walks from a stamp to the target beside it; this walks from a
    citation to the stamp after it. Two rules for one relation eventually
    disagree about one line, and the disagreement would show up as a citation
    this check calls undated and that writer happily dates.
    """
    for gap in ("", " ", "  ", ". "):
        line = f"The contract is `docs/design.md`{gap}[{OLD}-Pa0003].\n"
        found = look(tmp_path, line)
        start = line.index("[")
        forward = only(found).dated
        backward = _accompanied(line, start) == "docs/design.md"
        assert forward is backward, line


def test_a_stamp_on_the_next_line_dates_nothing(tmp_path):
    """Section 2 shows the stamp on the line of the citation it annotates.

    Reaching across a line break would mean a wrapped paragraph could date a
    citation four sentences away, which is the guessing this rule refuses.
    """
    found = look(tmp_path, f"""
        The contract is `docs/design.md`
        [{OLD}-Pa].
    """)
    assert not only(found).dated


def test_an_occurrence_that_disagrees_reports_nothing(tmp_path):
    """One target, twice on a line, one stamped and one not.

    The extractors answer with text and no position, so which occurrence the
    sentence asserts cannot be recovered. Reporting either would be a coin
    flip, and the wrong side of it is a false accusation -- so the sighting is
    counted as unjudged and no finding is produced.
    """
    found = look(
        tmp_path,
        f"Both `docs/design.md` [{OLD}-Pa] and `docs/design.md` again.\n",
    )
    assert found.sightings == ()
    assert len(found.ambiguous) == 1
    assert found.findings() == []


def test_occurrences_that_agree_are_judged(tmp_path):
    """When every occurrence answers the same way there is nothing to guess.

    Silence here would be the rule costing real findings for no gain: the
    verdict is the same whichever occurrence the sentence meant.
    """
    found = look(tmp_path, "Both `docs/design.md` and `docs/design.md` again.\n")
    assert not only(found).dated
    assert found.ambiguous == ()


def test_the_unit_is_a_target_on_a_line(tmp_path):
    """One line citing one target undated is one finding, not two.

    The extractors disagree about repeats -- ``_url_claims`` collapses them and
    ``_path_claims`` does not -- so counting occurrences would make the size of
    the finding list depend on which extractor produced it.
    """
    found = look(tmp_path, "Both `docs/design.md` and `docs/design.md` again.\n")
    assert len(found.findings()) == 1


# -- no exemption list -------------------------------------------------------


def test_every_citation_kind_can_be_placed():
    """Asked which kinds would be exempt, the answer was: which ones wouldn't.

    A kind with no locator is one this check passes over while reporting a
    clean tree, which is the shape of exemption the policy refuses. Checked
    against the claim table rather than trusted to stay in step, the way
    ``confirm``'s oracles are checked against the interpreted type codes.
    """
    assert set(_BY_KIND) == {kind.name for kind in CLAIM_KINDS}


def test_a_commit_hash_is_not_exempt(tmp_path):
    """The correction section 6 records, and the general rule behind it.

    A hash is immutable *content* identity, not a place and not a guarantee of
    existence: rebase, amend and a dropped branch rewrite history, so a hash
    can stop resolving. Without a stamp there is no telling *true when written*
    from *wrong when written*, which is the entire purpose of provenance.
    """
    found = look(tmp_path, f"The commit is `{SHA}`.\n")
    seen = only(found)
    assert seen.kind == "commit"
    assert not seen.dated


@pytest.mark.parametrize(
    "kind, citation",
    [
        ("path", "`docs/design.md`"),
        ("link", "[the contract](docs/design.md)"),
        ("commit", f"`{SHA}`"),
        ("url", "https://example.invalid/page"),
    ],
)
def test_each_kind_needs_a_stamp(tmp_path, kind, citation):
    undated = look(tmp_path, f"See {citation}.\n")
    assert only(undated).kind == kind
    assert not only(undated).dated

    dated = look(tmp_path, f"See {citation} [{OLD}-Xy].\n")
    assert only(dated).dated


def test_a_trailing_period_belongs_to_the_address(tmp_path):
    """``_url_claims`` strips sentence punctuation off an address, so the text
    on the page is longer than the token it yielded. The stamp still follows
    the citation as the reader sees it."""
    found = look(tmp_path, f"See https://example.invalid/page. [{OLD}-Wb]\n")
    assert only(found).dated


def test_a_negated_mention_is_not_a_citation(tmp_path):
    """``claims`` decides what is a citation; this decides whether it is dated.

    A second opinion about what counts would mean this check reporting an
    undated citation of something the documentation checker does not consider
    cited at all.
    """
    found = look(tmp_path, "There is no `docs/design.md` here.\n")
    assert found.sightings == ()


# -- what is left alone ------------------------------------------------------


def test_an_archive_is_left_alone(tmp_path):
    """Section 6: a record cites what was true when it was written.

    Wider than ``claims``' per-kind ``current_only``, deliberately. There, a
    dead URL in a changelog is still a dead link a reader will follow. Here,
    the archive's citations were dated when they were written and demanding a
    stamp now would ask somebody to re-date a record.
    """
    write(tmp_path, "docs/design.md", "the contract\n")
    write(tmp_path, "archives/old.md", "It cited `docs/design.md` back then.\n")
    found = survey(tmp_path, suffixes=(".md",), historical=("archives/",))
    assert found.sightings == ()
    assert found.archived == ("archives/old.md",)


def test_an_illustration_is_not_a_citation(tmp_path):
    """A document specifying a notation writes whole examples of it.

    The same filter ``kinemata.citations`` uses, so the catch and the reverse
    index describe the same tree -- they disagreed once already, between the
    fence filter landing and the index being taught about it.
    """
    found = look(tmp_path, """
        Write it like this:

        ```markdown
        The contract is `docs/design.md`.
        ```
    """)
    assert found.sightings == ()


# -- the ratchet -------------------------------------------------------------


def test_a_finding_fingerprints_for_the_ratchet(tmp_path):
    """Recorded, the existing population goes quiet; a new one still gates.

    This is the whole adoption story. Turning the catch on in a repository that
    has never dated a citation reports every citation in it, and a wall of red
    on day one gets the gate switched off -- which is the failure the ratchet
    exists to prevent.
    """
    found = look(tmp_path, "The contract is `docs/design.md`.\n")
    accepted = record(tmp_path / "b.json", found.findings(), until=NOW.date())
    assert accepted.size == 1
    assert accepted.split(found.findings()).new == ()

    write(tmp_path, "notes.md",
          "The contract is `docs/design.md`.\nAnd again, `docs/design.md` here.\n")
    after = survey(tmp_path, suffixes=(".md",))
    split = accepted.split(after.findings())
    assert len(split.new) == 1
    assert split.new[0][0] == PROVENANCE_REGISTRY


def test_a_record_survives_an_edit_above_it(tmp_path):
    """Line numbers are absent from a baseline key on purpose: every edit above
    a finding shifts it, and churn reported as new findings trains people to
    re-record -- which absorbs whatever else arrived in the same commit."""
    found = look(tmp_path, "The contract is `docs/design.md`.\n")
    accepted = record(tmp_path / "b.json", found.findings(), until=NOW.date())

    write(tmp_path, "notes.md",
          "A new opening paragraph.\n\nThe contract is `docs/design.md`.\n")
    after = survey(tmp_path, suffixes=(".md",))
    assert accepted.split(after.findings()).new == ()


# -- the clock, which is a different axis ------------------------------------


def test_the_clock_covers_what_leaves_the_machine():
    """Section 6: a path or a commit is settled locally on every run, so a
    clock over them would restate what the run already knows. An address costs
    a network request, which is why the date on it is worth keeping.

    Read off the claim table so a later kind that needs the network is clocked
    without an edit -- and so nothing here can name a kind that does not exist.
    """
    assert CLOCKED == {kind.name for kind in CLAIM_KINDS if kind.needs_network}
    assert CLOCKED == {"url"}


def test_a_stale_path_citation_is_not_on_the_list(tmp_path):
    """It is dated 2020 and it is not stale, because the run just settled it.

    The two axes are separate. Putting a path on the clock would produce a
    review list whose every entry is either already a finding or already known
    good, which is a list nobody reads twice.
    """
    found = look(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa].\n")
    assert found.clocked() == ()
    assert found.stale(after=timedelta(days=1), now=NOW) == ()


def test_a_tired_address_is_surfaced(tmp_path):
    found = look(tmp_path, f"See https://example.invalid/page [{OLD}-Wb].\n")
    (seen,) = found.stale(after=timedelta(days=DEFAULT_STALE_AFTER), now=NOW)
    assert seen.text == "https://example.invalid/page"


def test_a_fresh_address_is_not(tmp_path):
    from kinemata.stamps import encode

    body = encode(NOW - timedelta(days=1))
    found = look(tmp_path, f"See https://example.invalid/page [{body}-Wb].\n")
    assert found.clocked()
    assert found.stale(after=timedelta(days=DEFAULT_STALE_AFTER), now=NOW) == ()


def test_an_undated_address_has_no_age(tmp_path):
    """The clock's blind spot, raised rather than silently treated as ancient.

    An undated citation is the catch's finding. Calling it infinitely stale
    would put the same site on two lists with two different fixes.
    """
    found = look(tmp_path, "See https://example.invalid/page\n")
    seen = only(found)
    assert found.unclocked() == (seen,)
    with pytest.raises(ProvenanceError):
        seen.age(NOW)


# -- declaring the policy ----------------------------------------------------


def test_off_unless_declared(tmp_path):
    config = load(project(tmp_path, "The contract is `docs/design.md`.\n",
                          citations="accompany_max = 50"))
    assert config.provenance is False
    assert config.stale_after == DEFAULT_STALE_AFTER


def test_a_clock_without_a_catch_is_refused(tmp_path):
    """Half a policy is refused, not run.

    The clock only sees citations that carry a stamp. With the stamp
    requirement off it would report on whichever citations happen to be dated
    and say nothing about the rest -- a short list that reads like a clean
    tree, which is the inert signal this package exists to refuse.
    """
    config = project(tmp_path, "See `docs/design.md`.\n",
                     citations="stale_after = 7")
    with pytest.raises(ConfigError, match="stale_after but not"):
        load(config)


@pytest.mark.parametrize(
    "citations",
    [
        "provenance = true\nstale_after = 0",
        "provenance = true\nstale_after = -1",
        'provenance = "yes"',
        "provenance = true\nfossilize = true",
    ],
)
def test_a_policy_that_cannot_mean_anything_is_refused(tmp_path, citations):
    with pytest.raises(ConfigError):
        load(project(tmp_path, "See `docs/design.md`.\n", citations=citations))


# -- the commands ------------------------------------------------------------


def test_the_gate_is_quiet_until_it_is_armed(tmp_path, capsys):
    config = project(tmp_path, "The contract is `docs/design.md`.\n",
                     citations="accompany_max = 50")
    assert main(["check", "-c", str(config)]) == 0
    assert PROVENANCE_REGISTRY not in capsys.readouterr().out


def test_the_gate_fails_on_an_undated_citation(tmp_path, capsys):
    config = project(tmp_path, "The contract is `docs/design.md`.\n")
    assert main(["check", "-c", str(config)]) == 1
    assert "provenance:path" in capsys.readouterr().out


def test_the_gate_writes_nothing(tmp_path):
    """Section 7: the gate only ever reports. A check that rewrites the tree it
    is judging can make itself pass."""
    config = project(tmp_path, "The contract is `docs/design.md`.\n")
    before = {
        path: path.read_bytes()
        for path in sorted(tmp_path.rglob("*")) if path.is_file()
    }
    main(["check", "-c", str(config)])
    after = {
        path: path.read_bytes()
        for path in sorted(tmp_path.rglob("*")) if path.is_file()
    }
    assert after == before


def test_the_clock_never_gates(tmp_path, capsys):
    """Exit 0 with a tired address in the report. Gating on the calendar means
    a build that goes red on a day nobody touched the repository."""
    config = project(tmp_path, f"See https://example.invalid/page [{OLD}-Wb].\n")
    assert main(["stale", "-c", str(config)]) == 0
    assert "https://example.invalid/page" in capsys.readouterr().out


def test_the_clock_refuses_when_the_catch_is_off(tmp_path):
    config = project(tmp_path, "See https://example.invalid/page\n",
                     citations="accompany_max = 50")
    assert main(["stale", "-c", str(config)]) == 2


def test_the_clock_counts_what_it_cannot_see(tmp_path, capsys):
    """A review list is only meaningful beside the size of what it was drawn
    from -- the same argument the baseline's printed size rests on."""
    config = project(tmp_path, "See https://example.invalid/page\n")
    assert main(["stale", "-c", str(config)]) == 0
    assert "carry no stamp at all" in capsys.readouterr().out


def test_what_could_not_be_judged_is_printed(tmp_path, capsys):
    """Not suppressed by ``--quiet``, the same rule the baseline size follows.

    Silence about a citation the tool could not place is indistinguishable
    from one it placed and found dated, and the argument for the narrow
    association rule holds only while the misses are counted.
    """
    config = project(
        tmp_path,
        f"Both `docs/design.md` [{OLD}-Pa] and `docs/design.md` again.\n",
    )
    assert main(["check", "-c", str(config), "--quiet"]) == 0
    assert "unjudged: 1 citation(s)" in capsys.readouterr().out


# -- where the policy reaches --------------------------------------------------


def test_the_policy_can_be_scoped_away_from_user_facing_prose(tmp_path):
    """`[citations] suffixes`, and why it is a scope and not an ignore list.

    A dead path in a README is a defect wherever it appears, so claims keeps
    reading it. A stamp beside that path is apparatus -- it records when a
    checker last confirmed the reference -- and in the first page a reader of
    the project sees it is a token they have to learn to skip. Without this, the
    only way to keep stamps out of a README was to drop the README from claims
    entirely, which throws away the more valuable of the two checks.
    """
    write(tmp_path, "docs/design.md", "# Design\n")
    write(tmp_path, "README.md", "The contract is `docs/design.md`.\n")
    write(tmp_path, "mod.py", '"""Also the contract: `docs/design.md`."""\n')
    config = write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md", ".py"]

        [citations]
        provenance = true
        suffixes = [".py"]
    """)

    settings = load(config)
    assert settings.citation_suffixes == (".py",)
    assert settings.claim_suffixes == (".md", ".py")

    assert [seen.path for seen in survey(
        tmp_path, suffixes=settings.citation_suffixes).undated] == ["mod.py"]
    # The negative control: unscoped, the README citation is a finding too.
    # Without it this passes on a tree whose README was never read at all.
    assert len(survey(tmp_path, suffixes=settings.claim_suffixes).undated) == 2


def test_scoping_a_policy_that_is_off_is_refused(tmp_path):
    """Half a declaration reads in the file as though a decision were made."""
    config = write(tmp_path, "kinemata.toml", """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]

        [citations]
        suffixes = [".py"]
    """)
    with pytest.raises(ConfigError, match="not provenance = true"):
        load(config)


def test_a_declared_source_is_a_record_and_the_clock_leaves_it_alone(tmp_path):
    """The distinction the design was missing: a pointer versus a record.

    A citation written inline and undeclared says *go and read this*, so it has
    to keep resolving and a weekly reminder to look again is the point. A source
    entered in a bibliography with the day it was verified is the sense §5.2
    means by *"reference 12 in one paper"* -- a journal reorganizing its site
    does not invalidate the reference, and nagging about it weekly is noise.
    """
    # Bare rather than angle-bracketed: a closing `>` between the address and
    # the stamp is two characters, and the association rule allows nothing or
    # one space. The rule is right; the first draft of this fixture was not.
    write(tmp_path, "notes.md", f"""
        Declared: https://example.invalid/a [{OLD}-Wb0001]
        Inline: https://example.invalid/b [{OLD}-Wb]
    """)
    found = survey(tmp_path, recorded=["Wb0001"])

    clocked = {seen.text for seen in found.clocked()}
    assert clocked == {"https://example.invalid/b"}
    # The negative control: with nothing declared as a record, both are clocked.
    assert len(survey(tmp_path).clocked()) == 2
    assert len(found.stale(after=timedelta(days=7), now=NOW)) == 1


def test_a_confirmed_date_is_read_off_the_entry(tmp_path):
    (entry,) = Bibliography(
        [{"key": "Wb0001", "target": "https://example.invalid/a",
          "note": "a source", "confirmed": "2026-09-11"}]
    ).entries()
    assert entry.extra["confirmed"] == "2026-09-11"


@pytest.mark.parametrize("value", ["soon", "2026-13-01", "", "11/09/2026"])
def test_a_confirmed_date_that_is_not_a_date_is_refused(value):
    """A source verified on an unreadable day is one nothing can say was
    verified. Empty is in the list because a blank field reads as declared."""
    record = {"key": "Wb0001", "target": "x", "note": "y", "confirmed": value}
    if value == "":
        # Falsy, so it is simply absent rather than malformed -- pinned so the
        # distinction is deliberate rather than an accident of truthiness.
        assert "confirmed" not in Bibliography([record]).entries()[0].extra
        return
    with pytest.raises(ValueError, match="not one"):
        Bibliography([record])


def test_a_confirmation_in_the_future_is_refused():
    """The one thing a provenance record must never be able to say.

    The purpose is telling *true when written* from *wrong when written*, and a
    date nobody could have checked at settles neither.
    """
    ahead = (datetime.now(UTC).date() + timedelta(days=1)).isoformat()
    with pytest.raises(ValueError, match="has not happened yet"):
        Bibliography([{"key": "Wb0001", "target": "x", "note": "y",
                       "confirmed": ahead}])


@pytest.mark.parametrize("declared", ["[]", '".py"', '["py"]'])
def test_a_citation_scope_that_is_not_a_list_of_extensions_is_refused(
    tmp_path, declared
):
    """An empty list would turn the policy off while leaving it declared, and a
    bare word never matches what the walk compares it against."""
    config = write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."

        [citations]
        provenance = true
        suffixes = {declared}
    """)
    with pytest.raises(ConfigError):
        load(config)
