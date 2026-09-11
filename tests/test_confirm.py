"""The one command that writes into prose, and the boundary drawn around it.

Section 7 of ``docs/citations.md``: the checker writes what it verified, because
a stamp advanced by hand is unverifiable -- nothing prevents the date moving
without the check ever running. What is worth testing here is therefore not that
a date can be written but that **nothing else can**: that the gates stay
read-only, that a citation this run could not settle keeps the date it has, that
a document comes back byte-identical apart from the seven characters that were
the point, and that an association the tool cannot make is refused rather than
guessed.
"""

from __future__ import annotations

import subprocess
import textwrap
from datetime import UTC, datetime

import pytest

from kinemata.adapters.bibliography import INTERPRETED, Bibliography
from kinemata.cli import main
from kinemata.confirm import (
    CONFIRMED,
    CURRENT,
    GONE,
    REFUSED,
    SETTLERS,
    UNSETTLED,
    ConfirmError,
    apply,
    plan,
)
from kinemata.stamps import StampError

#: A stamp from 2020, so that "was this confirmed today" is answered by the
#: mechanism rather than by what day the suite happens to run on.
OLD = "0M00000"

NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=UTC)


def write(tmp_path, rel, body, *, dedent=True):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip() if dedent else body)
    return path


def books(**overrides):
    """A bibliography covering one of each interpreted code, plus a book."""
    records = {
        "Pa0003": ("docs/design.md", "the registry contract"),
        "Pa0007": ("docs/gone.md", "a document that is not there"),
        "Wb0001": ("https://example.invalid/", "an address"),
        "Bk0001": ("Knuth, volume 3", "a book, which nothing here can settle"),
    }
    records.update(overrides)
    return [
        Bibliography(
            [{"key": key, "target": target, "note": note}
             for key, (target, note) in records.items()],
            home="docs/bibliography.toml",
        )
    ]


def tree(tmp_path, document, *, rel="notes.md", dedent=True):
    """A tree with one document and the target the default bibliography names."""
    write(tmp_path, "docs/design.md", "the contract\n")
    return write(tmp_path, rel, document, dedent=dedent)


def project(tmp_path, document, *, config_extra=""):
    """The same tree, reachable through the command line."""
    tree(tmp_path, document)
    write(tmp_path, "docs/bibliography.toml", """
        [[entry]]
        key = "Pa0003"
        target = "docs/design.md"
        note = "the registry contract"
    """)
    return write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."

        [claims]
        suffixes = [".md"]
        historical = ["archives/"]
        {config_extra}

        [[registry]]
        name = "sources"
        kind = "bibliography"
        source = "docs/bibliography.toml"
    """)


def only(made, verdict=None):
    """The single outcome a test is about, with its verdict asserted."""
    (outcome,) = made.outcomes
    if verdict is not None:
        assert outcome.verdict == verdict, outcome.detail
    return outcome


# -- the boundary: who may write ---------------------------------------------


def test_planning_writes_nothing(tmp_path):
    """The default mode of the writing command is to describe the edit. A user
    who has not asked for a modified tree must not get one."""
    path = tree(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert only(made, CONFIRMED)
    assert path.read_bytes() == before


@pytest.mark.parametrize("command", ["check", "claims", "context", "undeclared"])
def test_a_gate_writes_nothing(tmp_path, command):
    """Section 7: the gate only ever reports. A check that rewrites the tree it
    is judging can make itself pass, which is the failure this project exists to
    catch -- so this is asserted over the whole tree rather than trusted to the
    absence of a call."""
    config = project(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    before = {
        path: path.read_bytes()
        for path in sorted(tmp_path.rglob("*")) if path.is_file()
    }
    main([command, "-c", str(config)])
    after = {
        path: path.read_bytes()
        for path in sorted(tmp_path.rglob("*")) if path.is_file()
    }
    assert after == before


def test_writing_needs_the_flag(tmp_path):
    """``--write`` and nothing else reaches the file. The report is the same
    either way, so a reader can compare the two runs."""
    config = project(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    document = tmp_path / "notes.md"
    before = document.read_bytes()
    assert main(["confirm", "-c", str(config)]) == 0
    assert document.read_bytes() == before
    assert main(["confirm", "-c", str(config), "--write"]) == 0
    assert document.read_bytes() != before


def test_the_command_never_gates(tmp_path, capsys):
    """Exit 0 even with a dead citation and a refusal in the report. The exit
    code is what a project would wire into CI, and a writer that gates is the
    check-that-can-pass-itself this whole boundary exists to prevent."""
    config = project(tmp_path, f"""
        A missing target is [{OLD}-Pa0007].
        An undeclared key is [{OLD}-Pa0099].
    """)
    assert main(["confirm", "-c", str(config), "--write"]) == 0
    out = capsys.readouterr().out
    assert "refused" in out


# -- what a confirmation records ---------------------------------------------


def test_a_confirmation_records_the_moment_of_the_run(tmp_path):
    path = tree(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    made = plan(tmp_path, books(), when=NOW)
    assert apply(made) == (("notes.md", 1),)
    text = path.read_text()
    assert f"[{OLD}-Pa0003]" not in text
    assert f"[{only(made, CONFIRMED).new}-Pa0003]" in text


def test_only_the_seven_timestamp_characters_change(tmp_path):
    """The key is written *inside* the stamp, so a keyed citation always carries
    a timestamp already: there is nothing to insert. The edit is an overwrite of
    the same width, which is what makes the rest of the document provably
    untouched."""
    body = (
        "﻿# Notes\r\n"
        "\r\n"
        f"The contract is `docs/design.md` [{OLD}-Pa0003].   \r\n"
        "\ttrailing tab and no final newline"
    )
    path = tree(tmp_path, body, dedent=False)
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    apply(made)
    after = path.read_bytes()
    outcome = only(made, CONFIRMED)
    assert after == before.replace(
        outcome.old.encode(), outcome.new.encode()
    )
    assert len(outcome.new) == len(outcome.old)


def test_the_document_is_not_reflowed_or_normalized(tmp_path):
    """Byte for byte, with only the stamp replaced: line endings, trailing
    whitespace, the missing final newline and the byte order mark all survive.
    A tool that tidied the file it was dating would put an unreviewable diff in
    front of whoever has to read it."""
    body = (
        "﻿mixed endings\n"
        f"windows line `docs/design.md` [{OLD}-Pa0003]\r\n"
        "trailing spaces   \n"
        "no final newline"
    )
    path = tree(tmp_path, body, dedent=False)
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert only(made, CONFIRMED)
    apply(made)
    after = path.read_bytes()
    assert len(before) == len(after)
    changed = [
        index
        for index, (one, two) in enumerate(zip(before, after, strict=True))
        if one != two
    ]
    assert changed and len(changed) <= 7
    assert OLD.encode() not in after
    assert after.count(b"\r\n") == before.count(b"\r\n")
    assert after.endswith(b"no final newline")


def test_running_twice_changes_nothing_the_second_time(tmp_path):
    """Idempotence, and it is not incidental: a citation already confirmed today
    is left alone, so a second run minutes after the first does not rewrite
    every stamp in the tree for no new information."""
    path = tree(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    apply(plan(tmp_path, books(), when=NOW))
    once = path.read_bytes()

    second = plan(tmp_path, books(), when=NOW)
    assert only(second, CURRENT)
    assert apply(second) == ()
    assert path.read_bytes() == once


def test_a_second_run_later_the_same_day_still_writes_nothing(tmp_path):
    """The floor is the day, not the second. Otherwise two runs an hour apart
    produce a diff touching every citation, which is how a mechanism gets
    switched off."""
    path = tree(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    apply(plan(tmp_path, books(), when=NOW))
    once = path.read_bytes()
    later = plan(tmp_path, books(), when=NOW.replace(hour=23, minute=59))
    assert only(later, CURRENT)
    assert path.read_bytes() == once


def test_a_stamp_confirmed_today_is_still_checked(tmp_path):
    """Currency decides whether to *write*, never whether to *look*. A citation
    confirmed this morning whose target went missing this afternoon is gone, and
    reporting it as current would be the check quietly not running."""
    tree(tmp_path, f"A missing target is [{OLD}-Pa0007].\n")
    made = plan(tmp_path, books(), when=NOW)
    assert only(made, GONE)


def test_several_citations_on_one_line_are_all_recorded(tmp_path):
    """Same-width replacement is what keeps the second span valid after the
    first is written. A shorter or longer token would move everything after it,
    and the second stamp on the line would be written into the wrong place."""
    path = tree(
        tmp_path,
        f"Two: `docs/design.md` [{OLD}-Pa0003] and [{OLD}-Pa0003].\n",
    )
    made = plan(tmp_path, books(), when=NOW)
    assert [outcome.verdict for outcome in made.outcomes] == [CONFIRMED, CONFIRMED]
    apply(made)
    text = path.read_text()
    assert OLD not in text
    assert text.count("-Pa0003]") == 2


# -- only what this run confirmed --------------------------------------------


def test_a_target_that_is_not_there_is_not_dated(tmp_path):
    path = tree(tmp_path, f"A missing target is [{OLD}-Pa0007].\n")
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert only(made, GONE).detail == "no such path: docs/gone.md"
    assert apply(made) == ()
    assert path.read_bytes() == before


def test_an_address_is_unsettled_until_the_project_asks_for_the_network(tmp_path):
    """Opt-in, exactly as ``claims`` has it. Off is *reported*: a run that
    quietly declined to ask reads like a run that asked and got a yes."""
    tree(tmp_path, f"An address is [{OLD}-Wb0001].\n")
    outcome = only(plan(tmp_path, books(), when=NOW), UNSETTLED)
    assert "external = true" in outcome.detail


def test_a_type_the_tool_does_not_interpret_is_never_dated(tmp_path):
    """A book has no oracle, so no run can confirm it. Said out loud rather than
    passed over -- silence here would read as a clean tree."""
    tree(tmp_path, f"A book is [{OLD}-Bk0001].\n")
    outcome = only(plan(tmp_path, books(), when=NOW), UNSETTLED)
    assert "type Bk" in outcome.detail


def test_a_commit_is_settled_against_the_history(tmp_path):
    """The third interpreted code, and the one that needs a repository. Its
    unavailable case is *not* a confirmation: a tree git cannot answer for
    leaves the stamp where it is."""
    write(tmp_path, "notes.md", "placeholder\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "-c", "user.email=t@example.invalid",
         "-c", "user.name=Test", "commit", "-qm", "first", "--allow-empty"],
        check=True,
    )
    sha = subprocess.run(
        ["git", "-C", str(tmp_path), "rev-parse", "--short", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    write(tmp_path, "notes.md", f"The first commit is [{OLD}-Cm0001].\n")
    known = books(Cm0001=(sha, "the first commit"))
    assert only(plan(tmp_path, known, when=NOW), CONFIRMED)

    absent = books(Cm0001=("0" * len(sha), "a commit nothing knows"))
    assert only(plan(tmp_path, absent, when=NOW), GONE)


def test_a_stamp_carrying_a_type_alone_is_left_alone(tmp_path):
    """Association is the key inside the token and nothing else. A stamp with no
    key says when *something* was looked at, and nothing here can tell what."""
    path = tree(tmp_path, f"A typed citation is `docs/design.md` [{OLD}-Pa].\n")
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert made.outcomes == ()
    assert path.read_bytes() == before


# -- refusals -----------------------------------------------------------------


def test_a_key_no_entry_declares_is_refused(tmp_path):
    tree(tmp_path, f"An undeclared key is [{OLD}-Pa0099].\n")
    outcome = only(plan(tmp_path, books(), when=NOW), REFUSED)
    assert "no entry declares Pa0099" in outcome.detail


def test_a_stamp_followed_by_an_opening_parenthesis_is_refused(tmp_path):
    """Section 3.3: that shape is read as link text with the parenthesized words
    as its target. The fix is an edit to the sentence, and a tool that reworded
    prose to make its own write legal would be doing something nobody asked."""
    path = tree(tmp_path, f"See `docs/design.md` [{OLD}-Pa0003](below).\n")
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert "3.3" in only(made, REFUSED).detail
    assert apply(made) == ()
    assert path.read_bytes() == before


def test_a_sentence_disagreeing_with_the_bibliography_is_refused(tmp_path):
    """Section 5.6: the target may be spelled twice, and the redundancy is
    checkable -- the entry says where the key points, the sentence says where it
    points, and disagreement is a finding. Dating it would record a check of one
    thing as a check of another."""
    path = tree(tmp_path, f"The contract is `docs/structure.md` [{OLD}-Pa0003].\n")
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert "5.6" in only(made, REFUSED).detail
    assert apply(made) == ()
    assert path.read_bytes() == before


def test_an_agreeing_sentence_is_confirmed(tmp_path):
    """The other half of the same rule: accompanying is the default form, so the
    ordinary sentence must not be refused for using it."""
    tree(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    assert only(plan(tmp_path, books(), when=NOW), CONFIRMED)


def test_a_backticked_span_further_off_is_not_read_as_the_target(tmp_path):
    """Deliberately narrow. Only a code span ending immediately before the token
    is the accompanied target; anything looser starts guessing which of a
    sentence's several backticked words the citation was about."""
    tree(
        tmp_path,
        f"Unlike `docs/structure.md`, the contract is [{OLD}-Pa0003].\n",
    )
    assert only(plan(tmp_path, books(), when=NOW), CONFIRMED)


def test_a_document_that_is_not_utf8_is_named_and_not_read(tmp_path):
    """A writer that guessed an encoding would corrupt the half of the file it
    did not understand."""
    write(tmp_path, "docs/design.md", "the contract\n")
    path = tmp_path / "notes.md"
    path.write_bytes(f"caf\xe9 [{OLD}-Pa0003]\n".encode("latin-1"))
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert made.unreadable == ("notes.md",)
    assert made.outcomes == ()
    assert path.read_bytes() == before


def test_a_document_that_moved_under_the_run_is_refused(tmp_path):
    """The plan carries offsets, and an offset is only meaningful against the
    text it was measured in. Writing anyway would date something nothing in this
    run examined."""
    path = tree(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    made = plan(tmp_path, books(), when=NOW)
    path.write_text(f"Shifted. The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    moved = path.read_bytes()
    with pytest.raises(ConfirmError, match="no longer reads the way"):
        apply(made)
    assert path.read_bytes() == moved


# -- what is never read at all ------------------------------------------------


def test_archived_material_is_left_alone(tmp_path):
    """Section 6: archived material is left alone on both axes, because a record
    cites what was true when it was written. Dating it would rewrite history's
    provenance to say it was checked today."""
    write(tmp_path, "docs/design.md", "the contract\n")
    path = write(
        tmp_path, "archives/old.md",
        f"An old record cites `docs/design.md` [{OLD}-Pa0003].\n",
    )
    before = path.read_bytes()
    made = plan(tmp_path, books(), historical=["archives/"], when=NOW)
    assert made.archived == ("archives/old.md",)
    assert made.outcomes == ()
    assert path.read_bytes() == before


def test_gitignored_documents_are_never_touched(tmp_path):
    """A tree carrying somebody else's documents is where an unwanted edit does
    the most damage, and git is where the project already declared what is not
    its own. This one is not covered by the project's exclude list."""
    write(tmp_path, "docs/design.md", "the contract\n")
    write(tmp_path, ".gitignore", "corpus/\n")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    path = write(
        tmp_path, "corpus/theirs.md",
        f"Not ours: `docs/design.md` [{OLD}-Pa0003].\n",
    )
    before = path.read_bytes()
    made = plan(tmp_path, books(), when=NOW)
    assert made.outcomes == ()
    assert path.read_bytes() == before


def test_an_excluded_path_is_not_read(tmp_path):
    write(tmp_path, "docs/design.md", "the contract\n")
    path = write(tmp_path, "vendor/theirs.md",
                 f"Not ours: `docs/design.md` [{OLD}-Pa0003].\n")
    before = path.read_bytes()
    made = plan(tmp_path, books(), exclude=["vendor/"], when=NOW)
    assert made.outcomes == ()
    assert path.read_bytes() == before


# -- the tables agree ---------------------------------------------------------


def test_every_interpreted_code_has_an_oracle():
    """An interpreted code is one whose meaning the tool acts on. One with
    nothing to settle it would be a promise nothing keeps, so the two tables are
    checked against each other rather than trusted to stay in step."""
    assert {settler.code for settler in SETTLERS} == set(INTERPRETED)


def test_the_report_names_the_file_the_line_and_both_stamps(tmp_path, capsys):
    """A person has to be able to check the edit against the diff afterward, so
    the report prints the two tokens the diff will show."""
    config = project(tmp_path, f"The contract is `docs/design.md` [{OLD}-Pa0003].\n")
    main(["confirm", "-c", str(config)])
    out = capsys.readouterr().out
    assert "notes.md" in out
    assert f"{OLD} ->" in out
    assert "1 keyed citation(s): 1 confirmed" in out


# -- reading a source file: what it says, not what it shows -------------------


ILLUSTRATED = '''
    """A module that displays a malformed key to explain the width rule.

    The width is fixed, so :shown:`[0TMQDKB-Ru169]` matches nothing at all.
    The contract is `docs/design.md` [{stamp}-Pa0003].
    """
'''


def test_an_illustrated_key_does_not_stop_the_run(tmp_path):
    """Found by running this command after `.py` came into scope, not by a test.

    This package's own ``stamps`` module illustrates a malformed key to explain
    why the width is fixed. Read raw that is not an illustration, it is a
    malformed citation -- so ``confirm`` refused outright, exit 2, before
    examining a single real one. The identical break had already been found and
    fixed in ``unused`` a few hours earlier; nothing checked the third reader.
    """
    write(tmp_path, "docs/design.md", "the contract\n")
    write(tmp_path, "module.py", ILLUSTRATED.format(stamp=OLD))
    made = plan(tmp_path, books(), suffixes=(".py",), when=NOW)
    assert only(made, CONFIRMED).key == "Pa0003"


def test_an_unmarked_malformed_key_still_refuses(tmp_path):
    """The negative control, because the fix must not have widened into silence.

    A malformed key nobody marked as shown is a malformed citation, and the
    reduction is what tells the two apart -- not the file's extension.
    """
    write(tmp_path, "docs/design.md", "the contract\n")
    write(tmp_path, "module.py", '"""The key is [0TMQDKB-Ru169], allegedly."""\n')
    with pytest.raises(StampError):
        plan(tmp_path, books(), suffixes=(".py",), when=NOW)


def test_a_stamp_in_executable_code_is_not_a_citation(tmp_path):
    """``shown_python`` keeps the prose and drops the code, and both halves
    matter here: a literal that happens to contain a stamp is data, not a
    sentence citing anything."""
    write(tmp_path, "docs/design.md", "the contract\n")
    write(tmp_path, "module.py", f'EXAMPLE = "[{OLD}-Pa0003]"\n')
    assert plan(tmp_path, books(), suffixes=(".py",), when=NOW).outcomes == ()


# -- evidence in somebody else's tree -----------------------------------------


def test_a_foreign_source_is_unsettled_rather_than_gone(tmp_path):
    """Every oracle here answers about *this* tree.

    A foreign commit therefore reads as "the history does not know it" and a
    foreign path as "no such path" -- true statements that say the source is
    gone, when what is true is that this is not the repository that can tell.
    Eight of this project's own citations were reported that way, which is a
    report a reader would act on by deleting real evidence.
    """
    book = Bibliography([{
        "key": "Pa0009",
        "target": "src/theirs/module.py",
        "foreign": "doctorjei/kanibako-cli",
        "note": "the module their tripwire scanned",
    }], home="docs/bibliography.toml")
    tree(tmp_path, f"Their module is `src/theirs/module.py` [{OLD}-Pa0009].\n")
    outcome = only(plan(tmp_path, [book], when=NOW), UNSETTLED)
    assert "doctorjei/kanibako-cli" in outcome.detail
    assert outcome.old == outcome.new
