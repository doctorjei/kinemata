"""A declared probe corpus, and the vacuity it exists to make visible.

The mechanism exists because 15 of an adopting project's 125 manifest-parity
functions assert nothing but *this callable accepted that input, and refused
this one* -- the largest block no mechanism here reached, measured 2026-09-14.

Two hazards get most of the cases below, and neither is ordinary coverage:

**One-sided corpora.** A refusal-only corpus is satisfied by a callable that
refuses everything, and the sample's own docstrings say so. So the polarity
count is checked directly, checked as a run-time *failure* rather than a
warning, and checked to stall ``baseline --record``.

**An exception read as a refusal.** ``outcome = "raises"`` names the type that
means refusal; anything else must block. A probe that took every exception for a
refusal would report a corpus in perfect order against a function that had been
renamed out from under it.
"""

from __future__ import annotations

import textwrap
from datetime import date

import pytest

from kinemata.baseline import BASELINE_NAME, Accepted, Baseline
from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.probe import (
    ACCEPT,
    REFUSE,
    Case,
    Outcome,
    Probe,
    ProbeError,
    examine,
    is_probe_scope,
    probe_scope,
    survey,
)


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


#: A project whose code discriminates, in both outcome conventions, plus the
#: corpora a config points at. Written to disk so the probe resolves it the way
#: an adopter's would -- through an import, not through a fixture handing over
#: an object.
SUBJECT = '''
    class Refused(Exception):
        """The project's own refusal."""


    class Unrelated(Exception):
        """What a renamed dependency raises. NOT a refusal."""


    class NarrowlyRefused(Refused):
        """A refusal with its own name. `except Refused` catches it too."""


    ALLOWED = {"box", "workset"}


    def check(name):
        if name not in ALLOWED:
            raise Refused(name)


    def validity(name):
        """Returns a complaint, or None when the name is fine."""
        return None if name in ALLOWED else f"{name} is not a scope"


    def explodes(name):
        raise Unrelated(name)


    def check_narrowly(name):
        """Refuses with the named subclass rather than the base."""
        if name not in ALLOWED:
            raise NarrowlyRefused(name)


    def always_accepts(name):
        return None


    NOT_AN_EXCEPTION = "a string"


    class NotAnException:
        """Callable, and a type, and still not something you can `except`."""
'''

CORPUS = '''
    from kinemata.probe import Case


    def both():
        return [
            Case(expect="accept", args=("box",)),
            Case(expect="accept", args=("workset",)),
            Case(expect="refuse", args=("nonsense",)),
        ]


    def refuse_only():
        return [
            Case(expect="refuse", args=("nonsense",)),
            Case(expect="refuse", args=("also-nonsense",)),
        ]


    def accept_only():
        return [Case(expect="accept", args=("box",))]


    def empty():
        return []


    def not_iterable():
        return 7


    def wrong_rows():
        return [{"expect": "accept", "args": ("box",)}]


    def wrong_about_one():
        """Claims the code refuses a name it in fact accepts."""
        return [
            Case(expect="accept", args=("box",)),
            Case(expect="refuse", args=("workset",), label="workset"),
        ]
'''


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A tree on ``sys.path`` with a subject and a corpus in it."""
    write(tmp_path, "subject.py", SUBJECT)
    write(tmp_path, "corpus.py", CORPUS)
    monkeypatch.syspath_prepend(str(tmp_path))
    return tmp_path


RAISES = Outcome(mode="raises", refusal="subject:Refused")
RETURNS = Outcome(mode="returns", accepted="none")


def probe(cases, outcome=RAISES, target="subject:check", name="scopes"):
    return Probe(name=name, target=target, cases=f"corpus:{cases}",
                 outcome=outcome)


# --- the polarity count, which is the whole point --------------------------

def test_a_corpus_carrying_both_polarities_runs_and_passes(project):
    result = examine(probe("both"))
    assert not result.failed
    assert (result.accepting, result.refusing) == (2, 1)
    assert result.examined == 3


def test_a_refusal_only_corpus_is_vacuous_and_fails(project):
    """The sample's own argument: satisfied by a callable that refuses all."""
    result = examine(probe("refuse_only"))
    assert result.vacuous
    assert result.failed
    assert not result.mismatches
    assert "no accept case" in result.why_vacuous()


def test_an_acceptance_only_corpus_is_vacuous_too(project):
    """The mirror, and it is the one a permissive validator satisfies."""
    result = examine(probe("accept_only"))
    assert result.vacuous
    assert "no refuse case" in result.why_vacuous()


def test_an_empty_corpus_says_it_is_empty_rather_than_one_sided(project):
    """Same defect, but a reader told the wrong half is a reader who edits it."""
    result = examine(probe("empty"))
    assert result.vacuous
    assert result.why_vacuous() == "the case list is empty"


def test_a_vacuous_probe_calls_the_target_no_times(project, monkeypatch):
    """A corpus that cannot discriminate does not get to run the code.

    Otherwise its findings would be produced, reported, and read as evidence by
    the same run that is about to say the corpus proves nothing.
    """
    import subject

    called: list[str] = []
    monkeypatch.setattr(
        subject, "check", lambda name: called.append(name), raising=True
    )
    examine(probe("refuse_only"))
    assert called == []


def test_a_probe_that_could_not_discriminate_claims_no_scope(project):
    """So ``--prune`` cannot delete its records on the strength of this run."""
    assert examine(probe("refuse_only")).scopes() == ()
    assert examine(probe("both")).scopes() == (probe_scope("scopes"),)


# --- the outcome modes ------------------------------------------------------

def test_the_returns_mode_reads_none_as_acceptance(project):
    result = examine(probe("both", RETURNS, target="subject:validity"))
    assert not result.failed
    assert (result.accepting, result.refusing) == (2, 1)


def test_an_unrelated_exception_blocks_rather_than_reading_as_a_refusal(project):
    """🛑 The permissive-oracle hazard, in one function.

    ``explodes`` raises something that is not the declared refusal. Read as a
    refusal it would make every ``refuse`` case pass -- a corpus reporting a
    validator in perfect order against a function that no longer works.
    """
    result = examine(probe("both", RAISES, target="subject:explodes"))
    assert result.blocked
    assert "Unrelated" in result.blocked
    assert not result.mismatches
    assert result.scopes() == ()


def test_a_raise_under_returns_blocks_rather_than_counting_as_refusal(project):
    result = examine(probe("both", RETURNS, target="subject:explodes"))
    assert result.blocked
    assert "not an answer" in result.blocked


def test_a_refusal_naming_a_callable_that_is_not_an_exception_blocks(project):
    """The case ``resolve`` cannot catch: a class is callable and still not one.

    ``except`` would raise ``TypeError`` at the first case, so the probe has to
    say what is wrong with the declaration rather than let the run die inside a
    handler.
    """
    outcome = Outcome(mode="raises", refusal="subject:NotAnException")
    result = examine(probe("both", outcome))
    assert result.blocked
    assert "not an exception type" in result.blocked


def test_a_refusal_of_Exception_is_refused(project):
    """The one spelling that defeats the whole design.

    ``except`` matches subclasses, so how broad a refusal type may be is the
    project's judgement -- measured against a real tree, a base class two levels
    up still passed every case. At the root it stops being a judgement:
    ``Exception`` reads a renamed function as the code correctly refusing.
    """
    outcome = Outcome(mode="raises", refusal="builtins:Exception")
    result = examine(probe("both", outcome))
    assert result.blocked
    assert "every failure is" in result.blocked


def test_a_refusal_naming_something_uncallable_is_refused_by_resolve(project):
    """Caught one layer earlier, and the message should still be usable."""
    outcome = Outcome(mode="raises", refusal="subject:NOT_AN_EXCEPTION")
    result = examine(probe("both", outcome))
    assert result.blocked
    assert "not a callable" in result.blocked


def test_an_unresolvable_target_blocks_and_is_not_a_finding(project):
    result = examine(probe("both", target="subject:nowhere"))
    assert result.blocked
    assert not result.mismatches


def test_a_case_supplier_that_is_not_one_blocks(project):
    assert "not an iterable" in examine(probe("not_iterable")).blocked


def test_rows_that_are_not_cases_block_rather_than_being_guessed_at(project):
    """A dict is not a smaller Case; guessing is how a check does less."""
    result = examine(probe("wrong_rows"))
    assert "not a Case" in result.blocked


# --- findings ---------------------------------------------------------------

def test_a_case_the_code_answers_otherwise_is_a_finding(project):
    result = examine(probe("wrong_about_one"))
    assert not result.vacuous and not result.blocked
    assert len(result.mismatches) == 1
    hit = result.mismatches[0]
    assert (hit.case, hit.expected, hit.observed) == ("workset", REFUSE, ACCEPT)
    assert "the code is on trial" in str(hit)


def test_a_finding_rides_the_shared_ratchet_under_its_own_scope(project):
    result = examine(probe("wrong_about_one"))
    scope, finding = result.findings()[0]
    assert scope == "probe:scopes"
    assert is_probe_scope(scope)
    assert finding.line == 0 and finding.antipattern == ""
    assert finding.path == "scopes"


def test_a_permissive_target_is_caught_by_the_refuse_half(project):
    """``always_accepts`` is the callable the polarity rule exists for."""
    result = examine(probe("both", RETURNS, target="subject:always_accepts"))
    assert len(result.mismatches) == 1
    assert result.mismatches[0].expected == REFUSE


def test_survey_runs_every_declared_probe(project):
    results = survey([probe("both"), probe("accept_only", name="other")])
    assert [item.probe for item in results] == ["scopes", "other"]
    assert not results[0].failed and results[1].vacuous


# --- Case -------------------------------------------------------------------

def test_a_case_refuses_a_polarity_that_is_not_one():
    with pytest.raises(ProbeError, match="not a polarity"):
        Case(expect="maybe")


def test_a_case_names_itself_from_its_arguments_when_unlabeled():
    assert Case(expect=ACCEPT, args=("box",), kwargs={"strict": True}).name == (
        "'box', strict=True"
    )


def test_a_label_wins_over_the_arguments():
    assert Case(expect=ACCEPT, args=("box",), label="the box arm").name == (
        "the box arm"
    )


# --- the config layer -------------------------------------------------------

def config(tmp_path, body):
    write(tmp_path, "kinemata.toml", body)
    return tmp_path / "kinemata.toml"


def test_a_probe_loads(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "raises"
        refusal = "subject:Refused"
    ''')
    settings = load(path)
    assert len(settings.probes) == 1
    assert settings.probes[0].outcome.mode == "raises"


def test_an_outcome_that_is_not_a_mode_is_refused(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "predicate"
        refusal = "subject:Refused"
    ''')
    with pytest.raises(ConfigError, match="supplying the verdict"):
        load(path)


def test_raises_without_a_refusal_is_refused(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "raises"
    ''')
    with pytest.raises(ConfigError, match="required rather than defaulted"):
        load(path)


def test_returns_without_an_accepted_is_refused(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:validity"
        cases = "corpus:both"
        outcome = "returns"
    ''')
    with pytest.raises(ConfigError, match="required rather than defaulted"):
        load(path)


def test_the_other_modes_discriminator_is_refused(tmp_path):
    """A key nothing reads is indistinguishable from a check switched off."""
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:validity"
        cases = "corpus:both"
        outcome = "returns"
        accepted = "none"
        refusal = "subject:Refused"
    ''')
    with pytest.raises(ConfigError, match="Nothing here would use it"):
        load(path)


def test_an_accepted_spelling_outside_the_table_is_refused(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:validity"
        cases = "corpus:both"
        outcome = "returns"
        accepted = "zero"
    ''')
    with pytest.raises(ConfigError, match="not one of"):
        load(path)


def test_a_refusal_that_is_not_a_target_is_refused_at_load(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "raises"
        refusal = "Refused"
    ''')
    with pytest.raises(ConfigError, match="not a target"):
        load(path)


def test_an_unknown_key_is_refused(tmp_path):
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "raises"
        refusal = "subject:Refused"
        predicate = "corpus:judge"
    ''')
    with pytest.raises(ConfigError, match="means nothing here"):
        load(path)


def test_two_probes_of_one_name_are_refused(tmp_path):
    """They would share a baseline scope, so a record could not say whose."""
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "raises"
        refusal = "subject:Refused"

        [[probe]]
        name = "scopes"
        target = "subject:validity"
        cases = "corpus:both"
        outcome = "returns"
        accepted = "none"
    ''')
    with pytest.raises(ConfigError, match="already is"):
        load(path)


def test_a_probe_alone_is_enough_of_a_config(tmp_path):
    """It is a declared check, so a config carrying only one checks something."""
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:both"
        outcome = "raises"
        refusal = "subject:Refused"
    ''')
    assert load(path).probes


# --- the command ------------------------------------------------------------

def declared(tmp_path, cases="both", extra=""):
    write(tmp_path, "kinemata.toml", f'''
        [[probe]]
        name = "scopes"
        target = "subject:check"
        cases = "corpus:{cases}"
        outcome = "raises"
        refusal = "subject:Refused"
        {extra}
    ''')


def test_the_command_refuses_when_nothing_declares_a_probe(tmp_path, capsys):
    write(tmp_path, "kinemata.toml", '[project]\nroot = "."\n[claims]\n')
    assert main(["probe", "--config", str(tmp_path / "kinemata.toml")]) == 2
    assert "no [[probe]] declared" in capsys.readouterr().err


def test_the_command_passes_and_prints_both_counts(project, capsys):
    declared(project)
    assert main(["probe", "--config", str(project / "kinemata.toml")]) == 0
    out = capsys.readouterr().out
    assert "3 case(s), 2 accept / 1 refuse" in out


def test_the_command_fails_on_a_one_sided_corpus(project, capsys):
    """And says so as a probe that did not answer, not as a wrong case.

    One summary line covering both would name the wrong defect to the only
    reader who has to fix it.
    """
    declared(project, "refuse_only")
    assert main(["probe", "--config", str(project / "kinemata.toml")]) == 1
    err = capsys.readouterr().err
    assert "VACUOUS" in err
    assert "1 probe(s) that did not answer" in err
    assert "does not answer as declared" not in err


def test_the_command_fails_on_a_mismatch(project, capsys):
    declared(project, "wrong_about_one")
    assert main(["probe", "--config", str(project / "kinemata.toml")]) == 1
    assert "1 case(s) the code does not answer" in capsys.readouterr().err


def test_an_accepted_mismatch_does_not_gate(project, capsys):
    declared(project, "wrong_about_one")
    Baseline(
        path=project / BASELINE_NAME,
        until=date(2099, 1, 1),
        accepted=(
            Accepted(
                registry="probe:scopes",
                entry_id="workset",
                antipattern="",
                path="scopes",
                text="scopes: workset declared refuse",
            ),
        ),
    ).save()
    assert main(["probe", "--config", str(project / "kinemata.toml")]) == 0
    assert "1 case(s) accepted as pre-existing" in capsys.readouterr().out


def test_baseline_record_refuses_while_a_corpus_is_one_sided(project, capsys):
    """*Running a probe is not the probe answering* -- the third trigger.

    The rule was paid for by a blocked oracle and then by a shape rule that
    selected nothing. A corpus carrying one polarity is the same failure again:
    it ran, and it could not tell a discriminating callable from a constant one.
    """
    declared(project, "refuse_only")
    code = main([
        "baseline", "--config", str(project / "kinemata.toml"),
        "--record", "--until", "2099-01-01",
    ])
    assert code == 2
    err = capsys.readouterr().err
    assert "cannot answer" in err
    assert "all of them refuse" in err
    assert not (project / BASELINE_NAME).exists()


def test_baseline_record_refuses_while_a_probe_is_blocked(project, capsys):
    write(project, "kinemata.toml", '''
        [[probe]]
        name = "scopes"
        target = "subject:nowhere"
        cases = "corpus:both"
        outcome = "raises"
        refusal = "subject:Refused"
    ''')
    code = main([
        "baseline", "--config", str(project / "kinemata.toml"),
        "--record", "--until", "2099-01-01",
    ])
    assert code == 2
    assert "cannot answer" in capsys.readouterr().err


def test_baseline_records_a_mismatch_when_the_corpus_discriminates(project):
    declared(project, "wrong_about_one")
    code = main([
        "baseline", "--config", str(project / "kinemata.toml"),
        "--record", "--until", "2099-01-01",
    ])
    assert code == 0
    written = Baseline.load(project / BASELINE_NAME)
    assert [item.registry for item in written.accepted] == ["probe:scopes"]


def test_a_baseline_record_reads_as_its_own_sentence():
    record = Accepted(
        registry="probe:scopes",
        entry_id="workset",
        antipattern="",
        path="scopes",
        text="scopes: workset declared refuse",
    )
    assert "answers otherwise" in str(record)
    assert "bypasses" not in str(record)


# --- exact: which refusal, not just whether -------------------------------
#
# An adopter's case, and it is theirs rather than a preference about
# strictness: their closed keyspace refuses an undeclared key BY NAME, their
# retired-key paths refuse BY NAME, and a version skew and a capability limit
# are different refusals that must not read as each other.

def test_a_subclass_satisfies_a_declared_base_by_default(project):
    """The published reading, kept: ``except`` matches subclasses, and a
    project naming a base is usually saying *any of these means refusal*."""
    result = examine(probe("both", target="subject:check_narrowly"))
    assert not result.failed
    assert (result.accepting, result.refusing) == (2, 1)


def test_exact_refuses_a_related_refusal(project):
    """A ``ConfigError`` standing in for a ``TemplateScopeError`` is not a near
    miss for a project whose refusals are named: it is the refusal saying
    something else, and a probe that cannot tell them apart lets a
    wrong-but-related error report agreement."""
    exact = Outcome(mode="raises", refusal="subject:Refused", exact=True)
    result = examine(probe("both", outcome=exact, target="subject:check_narrowly"))
    assert result.failed
    assert result.blocked
    assert "NarrowlyRefused" in result.blocked


def test_exact_passes_when_the_named_type_is_the_one_raised(project):
    """The negative control: exact is not simply stricter about everything."""
    exact = Outcome(mode="raises", refusal="subject:NarrowlyRefused", exact=True)
    result = examine(probe("both", outcome=exact, target="subject:check_narrowly"))
    assert not result.failed
    assert (result.accepting, result.refusing) == (2, 1)


def test_exact_beside_returns_is_refused_at_load(tmp_path):
    """There is no exception type to be exact about, so it means nothing."""
    path = config(tmp_path, '''
        [[probe]]
        name = "scopes"
        target = "subject:validity"
        cases = "corpus:both"
        outcome = "returns"
        accepted = "none"
        exact = true
    ''')
    with pytest.raises(ConfigError, match="no exception type to be exact about"):
        load(path)
