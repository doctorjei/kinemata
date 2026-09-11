"""Documents dated in a list, because they cannot carry the date themselves.

A citation stamp is apparatus. In a README it is a token the reader has to
learn to skip, and the first answer to that -- taking user-facing prose out of
the citation policy's reach -- bought the notation's absence by giving up the
coverage. This is the second answer, and what is worth testing about it is
exactly the ways it could become a suppression wearing a policy's clothes:

* **A declaration is not a verification.** A document listed with no date covers
  nothing; its citations are the findings they were. Otherwise the whole list is
  writable by anyone with a text editor and no oracle.
* **Only a settled document is dated.** A broken citation, one nothing could
  reach, one held open by a promise and one declared to live in another
  project's tree are all citations this run did not confirm.
* **The list cannot certify what nothing reads.** A resource outside the claims
  scope would be dated by every run for having nothing to falsify it, which is
  a green entry over a document nobody checked.
"""

from __future__ import annotations

import textwrap
from datetime import UTC, date, datetime, timedelta

import pytest

from kinemata.claims import Claim, Verification
from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.confirm import (
    CONFIRMED,
    CURRENT,
    GONE,
    REFUSED,
    UNSETTLED,
    ConfirmError,
    dating,
    redate,
)
from kinemata.provenance import survey
from kinemata.resources import ResourceError, coverage
from kinemata.resources import declared as declared_resources

#: A stamp from 2020, so "is this stale" is answered by the mechanism rather
#: than by what day the suite happens to run on.
OLD = "0M00000"

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)
TODAY = NOW.date()


def write(tmp_path, rel, body, *, dedent=True):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip() if dedent else body)
    return path


def tree(tmp_path, document, *, rel="README.md"):
    """One user-facing document, and the target its citations name."""
    write(tmp_path, "docs/design.md", "the contract\n")
    return write(tmp_path, rel, document)


def listed(tmp_path, *records):
    """Resource entries as the loader receives them."""
    return declared_resources(records, root=tmp_path, where="docs/resources.toml")


def entry(path="README.md", **extra):
    return {"path": path, "note": "user-facing", **extra}


# -- what a list may say -----------------------------------------------------


def test_a_list_declares_documents_and_the_day_they_were_verified(tmp_path):
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    (one,) = listed(tmp_path, entry(confirmed="2026-09-11"))
    assert one.path == "README.md"
    assert one.confirmed == date(2026, 9, 11)
    assert one.dated


def test_an_entry_with_no_date_is_declared_and_not_dated(tmp_path):
    """Saying where a date will live is not the same as having checked."""
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    (one,) = listed(tmp_path, entry())
    assert one.confirmed is None
    assert not one.dated
    assert coverage([one]) == {}


def test_a_leading_dot_slash_names_the_same_document(tmp_path):
    """A spelling that failed to match would read as coverage and give none."""
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    (one,) = listed(tmp_path, entry(path="./README.md"))
    assert one.path == "README.md"


def test_a_dotted_directory_survives_normalization(tmp_path):
    """The normalization drops a leading `.` component, not a leading dot.

    Written after a character strip did exactly that in the first draft, which
    would have turned a declaration of a hidden directory into a declaration of
    a path that does not exist -- caught here rather than by an adopter whose
    documentation lives under one.
    """
    write(tmp_path, ".github/NOTES.md", "the contract is `docs/design.md`.\n")
    write(tmp_path, "docs/design.md", "the contract\n")
    (one,) = listed(tmp_path, entry(path=".github/NOTES.md"))
    assert one.path == ".github/NOTES.md"


@pytest.mark.parametrize(
    "record, complaint",
    [
        ({"path": "README.md", "note": "x", "confirm": "2026-09-11"}, "confirm"),
        ({"note": "x"}, "path"),
        ({"path": "README.md"}, "note"),
        ({"path": "docs/missing.md", "note": "x"}, "no such file"),
        ({"path": "README.md", "note": "x", "confirmed": "soon"}, "not one"),
    ],
)
def test_a_list_refuses_rather_than_skipping(tmp_path, record, complaint):
    """Every one of these would leave a document silently unread or uncovered."""
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    with pytest.raises(ResourceError) as raised:
        listed(tmp_path, record)
    assert complaint in str(raised.value)


def test_a_date_in_the_future_is_refused(tmp_path):
    """The one thing a provenance record must never be able to say."""
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    ahead = (date.today() + timedelta(days=2)).isoformat()
    with pytest.raises(ResourceError) as raised:
        listed(tmp_path, entry(confirmed=ahead))
    assert "has not happened yet" in str(raised.value)


def test_one_document_cannot_be_declared_twice(tmp_path):
    """Two entries would let a run write one and leave the other reading true."""
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    with pytest.raises(ResourceError) as raised:
        listed(tmp_path, entry(), entry(path="./README.md"))
    assert "already declared" in str(raised.value)


def test_an_empty_list_is_refused(tmp_path):
    with pytest.raises(ResourceError) as raised:
        listed(tmp_path)
    assert "declares no resources" in str(raised.value)


# -- what the policy does with one --------------------------------------------


def look(tmp_path, document, **kwargs):
    tree(tmp_path, document)
    return survey(tmp_path, suffixes=(".md",), **kwargs)


def test_a_listed_document_dates_every_citation_in_it(tmp_path):
    """One entry, every citation in the file -- which is the whole bargain."""
    found = look(
        tmp_path,
        "the contract is `docs/design.md`.\nso is <https://example.invalid/>.\n",
        covered={"README.md": date(2026, 9, 11)},
    )
    assert found.undated == ()
    assert len(found.listed) == 2
    assert all(seen.dated for seen in found.sightings)


def test_a_listed_document_with_no_date_covers_nothing(tmp_path):
    """The coverage map holds only entries a run has confirmed."""
    found = look(tmp_path, "the contract is `docs/design.md`.\n", covered={})
    assert len(found.undated) == 1
    assert found.listed == ()


def test_an_inline_stamp_beats_the_list(tmp_path):
    """A stamp dates one line and an entry dates a document: the line is finer.

    Taking the coarser answer would report the stale of the two, which is the
    one direction a freshness record must not err in.
    """
    found = look(
        tmp_path,
        f"the contract is `docs/design.md` [{OLD}-Pa].\n",
        covered={"README.md": date(2026, 9, 11)},
    )
    (seen,) = found.sightings
    assert seen.stamp is not None
    assert found.listed == ()
    assert seen.age(NOW) > timedelta(days=365)


def test_a_listed_address_is_clocked_from_the_entrys_date(tmp_path):
    """What the list buys beyond coverage, and the only thing that ages here.

    A path is settled locally on every run, so a date over one restates what the
    run already knows. An address has to leave the machine -- so a user-facing
    document that cites one is where a file-level date starts paying.
    """
    fresh = look(
        tmp_path,
        "the specification is <https://example.invalid/spec>.\n",
        covered={"README.md": TODAY},
    )
    assert len(fresh.clocked()) == 1
    assert fresh.stale(after=timedelta(days=7), now=NOW) == ()

    old = look(
        tmp_path,
        "the specification is <https://example.invalid/spec>.\n",
        covered={"README.md": TODAY - timedelta(days=30)},
    )
    (past,) = old.stale(after=timedelta(days=7), now=NOW)
    assert past.path == "README.md"
    assert past.age(NOW).days == 30


def test_a_document_confirmed_today_is_not_yet_stale(tmp_path):
    """The entry's day is read as its first instant, never as its last.

    Rounding the other way would let the clock call a citation stale before the
    threshold the project declared.
    """
    found = look(
        tmp_path,
        "the specification is <https://example.invalid/spec>.\n",
        covered={"README.md": TODAY},
    )
    (seen,) = found.sightings
    assert seen.age(NOW) < timedelta(days=1)


# -- deciding which documents a run may date ----------------------------------


def claim(path="README.md", kind="path", text="docs/gone.md"):
    return Claim(kind, text, path, 3, f"a line citing `{text}`")


def decide(tmp_path, found, **extra):
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    source = write(tmp_path, "docs/resources.toml", "")
    return dating(
        listed(tmp_path, entry(**extra)), found, source=source, when=NOW
    )


def test_a_document_whose_every_citation_resolved_is_dated(tmp_path):
    (one,) = decide(tmp_path, Verification()).datings
    assert one.verdict == CONFIRMED
    assert (one.old, one.new) == ("", TODAY.isoformat())


def test_a_document_confirmed_today_is_left_alone(tmp_path):
    (one,) = decide(
        tmp_path, Verification(), confirmed=TODAY.isoformat()
    ).datings
    assert one.verdict == CURRENT
    assert one.old == one.new


@pytest.mark.parametrize(
    "attribute, verdict",
    [
        ("broken", GONE),
        ("unsettled", UNSETTLED),
        ("deferred", UNSETTLED),
        ("foreign", UNSETTLED),
    ],
)
def test_a_citation_this_run_did_not_confirm_stops_the_date(
    tmp_path, attribute, verdict
):
    """Four ways not to have confirmed something, and none of them is a yes.

    The first is a defect and the rest are honest, which is why they get
    different verdicts and the same refusal to write.
    """
    (one,) = decide(
        tmp_path, Verification(**{attribute: [claim()]})
    ).datings
    assert one.verdict == verdict
    assert not one.writes
    assert one.old == one.new


def test_a_claim_in_another_document_does_not_block_this_one(tmp_path):
    (one,) = decide(
        tmp_path, Verification(broken=[claim(path="docs/other.md")])
    ).datings
    assert one.verdict == CONFIRMED


def test_a_blocked_oracle_stops_the_whole_pass(tmp_path):
    """A date written under a check that did not run records a skipped check."""
    (one,) = decide(
        tmp_path, Verification(blocked=["test count: the command produced no value"])
    ).datings
    assert one.verdict == REFUSED
    assert "did not run" in one.detail


# -- writing the date ---------------------------------------------------------


LIST = """
    # the list
    [[resource]]
    path = "README.md"
    note = "user-facing"

    [[resource]]
    path = "docs/design.md"
    confirmed = "2020-01-01"
    note = "the contract"
"""


def written(tmp_path, *paths):
    """Date the named entries in a two-entry list, and hand back the file."""
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    source = write(tmp_path, "docs/resources.toml", LIST)
    records = [
        {"path": "README.md", "note": "user-facing"},
        {"path": "docs/design.md", "confirmed": "2020-01-01", "note": "the contract"},
    ]
    made = dating(
        declared_resources(records, root=tmp_path, where="docs/resources.toml"),
        Verification(broken=[claim(path=rel) for rel in paths]),
        source=source,
        when=NOW,
    )
    redate(made)
    return source.read_text()


def test_a_first_date_is_inserted_under_the_path(tmp_path):
    """Prose never needs an insertion; a list the tool maintains does.

    Under ``path``, because that is the line a reader looks at to know which
    document the date belongs to.
    """
    body = written(tmp_path, "docs/design.md")
    assert 'path = "README.md"\nconfirmed = "2026-09-10"' in body
    assert 'confirmed = "2020-01-01"' in body  # the blocked entry is untouched


def test_an_existing_date_is_replaced_in_place(tmp_path):
    body = written(tmp_path, "README.md")
    assert 'path = "docs/design.md"\nconfirmed = "2026-09-10"' in body
    assert 'path = "README.md"\nnote' in body  # the blocked entry gains nothing


def test_the_comments_and_the_order_survive(tmp_path):
    """The reason this is a line edit rather than a round trip through a writer.

    Half the value of a declared-data file is the reasoning written above the
    entries, and a serializer would drop every line of it.
    """
    body = written(tmp_path)
    assert body.startswith("# the list\n")
    assert body.index('"README.md"') < body.index('"docs/design.md"')


def test_nothing_to_write_leaves_the_file_alone(tmp_path):
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    source = write(tmp_path, "docs/resources.toml", LIST)
    before = source.read_bytes()
    made = dating(
        listed(tmp_path, entry(confirmed=TODAY.isoformat())),
        Verification(), source=source, when=NOW,
    )
    assert redate(made) == 0
    assert source.read_bytes() == before


def test_a_list_that_changed_under_the_run_is_refused(tmp_path):
    """The same refusal the prose writer makes, and for the same reason.

    Writing regardless would put a date on an entry nothing in this run
    examined; searching for where it went is the guess this module does not
    make.
    """
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    source = write(tmp_path, "docs/resources.toml", LIST)
    records = [{"path": "docs/design.md", "confirmed": "2020-01-01",
                "note": "the contract"}]
    made = dating(
        declared_resources(records, root=tmp_path, where="docs/resources.toml"),
        Verification(), source=source, when=NOW,
    )
    source.write_text(source.read_text().replace("2020-01-01", "2021-02-02"))
    with pytest.raises(ConfirmError) as raised:
        redate(made)
    assert "no longer reads the way it did" in str(raised.value)


def test_an_entry_the_list_does_not_declare_is_refused(tmp_path):
    tree(tmp_path, "the contract is `docs/design.md`.\n")
    source = write(tmp_path, "docs/resources.toml", """
        [[resource]]
        path = "docs/design.md"
        note = "the contract"
    """)
    made = dating(
        listed(tmp_path, entry()), Verification(), source=source, when=NOW
    )
    with pytest.raises(ConfirmError) as raised:
        redate(made)
    assert "no [[resource]] entry declares README.md" in str(raised.value)


# -- the declaration, through the config --------------------------------------


def project(tmp_path, *, citations, resources=None, claims='suffixes = [".md"]',
            document="the contract is `docs/design.md`.\n"):
    tree(tmp_path, document)
    if resources is not None:
        write(tmp_path, "docs/resources.toml", resources)
    return write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."
        exclude = ["vendor/"]

        [claims]
        {claims}

        [citations]
        {citations}
    """)


RESOURCES = """
    [[resource]]
    path = "README.md"
    note = "user-facing"
"""


def test_a_declared_list_is_loaded(tmp_path):
    config = project(
        tmp_path,
        citations='provenance = true\nresources = "docs/resources.toml"',
        resources=RESOURCES,
    )
    settings = load(config)
    assert [one.path for one in settings.resources] == ["README.md"]
    assert settings.resources_path == tmp_path / "docs/resources.toml"


def test_a_list_without_the_policy_is_refused(tmp_path):
    """A scope for a policy nobody declared reads as a decision and is not one."""
    config = project(
        tmp_path,
        citations='resources = "docs/resources.toml"',
        resources=RESOURCES,
    )
    with pytest.raises(ConfigError) as raised:
        load(config)
    assert "not provenance = true" in str(raised.value)


def test_a_missing_list_is_refused(tmp_path):
    config = project(
        tmp_path, citations='provenance = true\nresources = "docs/resources.toml"'
    )
    with pytest.raises(ConfigError) as raised:
        load(config)
    assert "no such file" in str(raised.value)


def test_a_document_the_policy_does_not_read_is_refused(tmp_path):
    """Its citations are not findings, so dating them buys nothing."""
    config = project(
        tmp_path,
        citations=('provenance = true\nsuffixes = [".py"]\n'
                   'resources = "docs/resources.toml"'),
        resources=RESOURCES,
    )
    with pytest.raises(ConfigError) as raised:
        load(config)
    assert "the citation policy does not read" in str(raised.value)


def test_a_document_the_claims_check_does_not_read_is_refused(tmp_path):
    """The one that earns its keep: a green entry over an unchecked document.

    Confirmation asks whether everything a document cites still holds, and
    ``claims`` is what answers. A resource it never reads has nothing to
    falsify it, so every run would date it.
    """
    config = project(
        tmp_path,
        citations=('provenance = true\nsuffixes = [".md"]\n'
                   'resources = "docs/resources.toml"'),
        claims='suffixes = [".py"]',
        resources=RESOURCES,
    )
    with pytest.raises(ConfigError) as raised:
        load(config)
    assert "the claims check does not read" in str(raised.value)


def test_an_excluded_document_is_refused(tmp_path):
    config = project(
        tmp_path,
        citations='provenance = true\nresources = "docs/resources.toml"',
        resources="""
            [[resource]]
            path = "vendor/READ.md"
            note = "somebody else's"
        """,
    )
    write(tmp_path, "vendor/READ.md", "the contract is `docs/design.md`.\n")
    with pytest.raises(ConfigError) as raised:
        load(config)
    assert "keeps out of every scan" in str(raised.value)


def test_an_unknown_key_in_the_list_file_is_refused(tmp_path):
    config = project(
        tmp_path,
        citations='provenance = true\nresources = "docs/resources.toml"',
        resources='[[resources]]\npath = "README.md"\nnote = "x"\n',
    )
    with pytest.raises(ConfigError) as raised:
        load(config)
    assert "means nothing here" in str(raised.value)


# -- end to end ---------------------------------------------------------------


def test_the_catch_and_the_writer_meet_in_the_command_line(tmp_path, capsys):
    """Declare, fail, confirm, pass -- the whole adoption path in one test.

    The middle step is the one worth pinning: declaring a document does **not**
    make its citations pass. Only a run that settled them does, and the run is
    what writes the date.
    """
    config = project(
        tmp_path,
        citations='provenance = true\nresources = "docs/resources.toml"',
        resources=RESOURCES,
    )
    assert main(["check", "-c", str(config)]) == 1
    assert "docs/design.md" in capsys.readouterr().out

    assert main(["confirm", "-c", str(config), "--write"]) == 0
    assert "resource date(s)" in capsys.readouterr().out

    assert main(["check", "-c", str(config)]) == 0
    assert "1 citation(s) in 1 document(s)" in capsys.readouterr().out


def test_a_declared_document_that_dates_nothing_is_named(tmp_path, capsys):
    """The ``unused`` signal, applied to this list.

    A document that has not started citing anything and a rename that left the
    entry pointing somewhere harmless look identical from here, so this is a
    review line and never a failure.
    """
    config = project(
        tmp_path,
        citations='provenance = true\nresources = "docs/resources.toml"',
        document="nothing here cites anything.\n",
        resources="""
            [[resource]]
            path = "docs/design.md"
            confirmed = "2026-09-11"
            note = "cites nothing yet"
        """,
    )
    assert main(["check", "-c", str(config)]) == 0
    out = capsys.readouterr().out
    assert "1 declared resource(s) date no citation: docs/design.md" in out
