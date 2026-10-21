"""Attestations: a finding declared correct, with the reason, and no expiry.

**The case that asked for it** is ``yapyon``'s (2026-10-17): their bytes-literal
spec writes the value `` `badf00d0` ``, a pure-hex code span, and ``claims``
reads it as a commit that does not resolve. They parked it in their baseline
until a date, which misdescribes correct text as debt and lapses with it.
"""

from __future__ import annotations

import json
import subprocess
import textwrap

import pytest

from kinemata.attestations import ATTESTATIONS_PATH
from kinemata.cli import main
from kinemata.config import ConfigError, load

LINE = "the bytes `badf00d0`, padded from `hex'badf00d'`."

CONFIG = """
    [project]
    root = "."

    [claims]

    [[registry]]
    name = "words"
    kind = "code-patterns"
    match_mode = "raw"

      [[registry.entry]]
      id = "no-frobnicate"
      antipatterns = ['frobnicate']
"""

COMMIT = {
    "registry": "claims",
    "entry": "claim:commit",
    "antipattern": "badf00d0",
    "path": "SPEC.md",
    "text": LINE,
    "correct": "badf00d0 is the bytes value of hex'badf00d', not a commit",
}

CODE = {
    "registry": "words",
    "entry": "no-frobnicate",
    "antipattern": "frobnicate",
    "path": "app.py",
    "text": "frobnicate()  # the vendor's spelling, not ours",
    "correct": "the vendor API is named frobnicate; this line calls it",
}


def project(tmp_path, *, source="X = 1\n", git=True):
    if git:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / "SPEC.md").write_text(f"# Spec\n\n{LINE}\n")
    (tmp_path / "app.py").write_text(source)
    path = tmp_path / "kinemata.toml"
    path.write_text(textwrap.dedent(CONFIG).lstrip())
    return str(path)


def attest(tmp_path, *entries, raw=None):
    """Write the attestations file -- in yapyon, as a project would."""
    target = tmp_path / ATTESTATIONS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    if raw is None:
        lines = ["attestations:"]
        for entry in entries:
            first = True
            for key, value in entry.items():
                lead = "  - " if first else "    "
                lines.append(f"{lead}{key}: {json.dumps(value, ensure_ascii=False)}")
                first = False
        raw = "\n".join(lines) + "\n"
    target.write_text(raw)


def run(capsys, *argv):
    status = main(list(argv))
    captured = capsys.readouterr()
    return status, captured.out + captured.err


# -- the reported case ----------------------------------------------------------


def test_the_hex_value_is_a_finding_without_an_attestation(tmp_path, capsys):
    status, out = run(capsys, "claims", "-c", project(tmp_path))
    assert status == 1
    assert "badf00d0" in out


def test_an_attestation_excuses_it(tmp_path, capsys):
    config = project(tmp_path)
    attest(tmp_path, COMMIT)
    status, out = run(capsys, "claims", "-c", config)
    assert status == 0, out
    assert "attested: 1 finding(s) declared correct" in out


def test_the_attestations_file_is_not_read_as_a_document(tmp_path, capsys):
    """It quotes the flagged line verbatim, so read as prose it would flag itself."""
    config = project(tmp_path)
    (tmp_path / "kinemata.toml").write_text(
        (tmp_path / "kinemata.toml").read_text().replace(
            "[claims]", '[claims]\nsuffixes = [".md", ".yap"]'
        )
    )
    attest(tmp_path, COMMIT)
    status, out = run(capsys, "claims", "-c", config)
    assert status == 0, out
    assert "attestations.yap:" not in out


# -- what makes it not the baseline ------------------------------------------------


def test_an_attestation_whose_text_is_gone_fails(tmp_path, capsys):
    """The line was edited: the attestation vouches for text that is gone."""
    config = project(tmp_path)
    attest(tmp_path, COMMIT)
    (tmp_path / "SPEC.md").write_text("# Spec\n\nthe bytes `0xbadf00d0`.\n")
    status, out = run(capsys, "claims", "-c", config)
    assert status == 1
    assert "1 attestation(s) in attestations.yap vouch for text that is gone" in out
    assert "SPEC.md: 'badf00d0'" in out


def test_a_run_that_could_not_produce_the_finding_is_idle_not_failed(tmp_path, capsys):
    """No ``.git``, as in an unpacked sdist: no commit claim resolves or fails.

    The line is unchanged, so nothing about the attestation is wrong -- the run
    could not check. Both of this repository's own attestations hit exactly this.
    """
    config = project(tmp_path, git=False)
    attest(tmp_path, COMMIT)
    status, out = run(capsys, "claims", "-c", config)
    assert status == 0, out
    assert "idle: 1 attestation(s)" in out


def test_a_narrowed_run_does_not_judge_what_it_did_not_read(tmp_path, capsys):
    config = project(tmp_path)
    attest(tmp_path, COMMIT)
    (tmp_path / "SPEC.md").write_text("# Spec\n\nnothing here.\n")
    (tmp_path / "other.md").write_text("fine\n")
    status, out = run(capsys, "claims", "-c", config, str(tmp_path / "other.md"))
    assert status == 0, out


def test_another_command_does_not_judge_an_attestation_it_does_not_own(tmp_path, capsys):
    """``check`` never reads prose, so a claims attestation is not unused there."""
    config = project(tmp_path)
    attest(tmp_path, COMMIT)
    status, out = run(capsys, "check", "-c", config)
    assert status == 0, out
    assert "excuse nothing" not in out


def test_it_works_for_every_check_not_only_claims(tmp_path, capsys):
    config = project(tmp_path, source=CODE["text"] + "\n")
    status, _ = run(capsys, "check", "-c", config)
    assert status == 1
    attest(tmp_path, CODE)
    status, out = run(capsys, "check", "-c", config)
    assert status == 0, out
    assert "attested: 1" in out


def test_an_attestation_covers_every_identical_line_in_its_file(tmp_path, capsys):
    """Identical text in one file is one statement, correct once."""
    config = project(tmp_path, source=CODE["text"] + "\n" + CODE["text"] + "\n")
    attest(tmp_path, CODE)
    status, out = run(capsys, "check", "-c", config)
    assert status == 0, out
    assert "attested: 2" in out


def test_record_never_writes_an_attested_finding_as_debt(tmp_path, capsys):
    config = project(tmp_path, source=CODE["text"] + "\nfrobnicate(1)\n")
    attest(tmp_path, CODE)
    assert main(["baseline", "-c", config, "--record", "--until", "2099-01-01"]) == 0
    recorded = json.loads((tmp_path / ".kinemata-baseline.json").read_text())
    texts = [finding["text"] for finding in recorded["findings"]]
    assert "frobnicate(1)" in texts
    # Not `CODE["text"] not in texts`: a record holds the line normalized, so
    # the raw spelling is absent either way and that assertion could not fail.
    assert not any("vendor" in text for text in texts)


def test_a_narrowed_record_never_writes_one_either(tmp_path, capsys):
    """``-r`` writes through its own path, which returned before the filter once."""
    config = project(tmp_path, source=CODE["text"] + "\nfrobnicate(1)\n")
    attest(tmp_path, CODE)
    assert main(["baseline", "-c", config, "-r", "words", "--record",
                 "--until", "2099-01-01"]) == 0
    recorded = json.loads((tmp_path / ".kinemata-baseline.json").read_text())
    texts = [finding["text"] for finding in recorded["findings"]]
    assert "frobnicate(1)" in texts
    assert not any("vendor" in text for text in texts)


def test_a_record_an_attestation_replaces_is_left_stale_for_prune(tmp_path, capsys):
    """yapyon's migration: the baseline record goes, the attestation stays."""
    config = project(tmp_path)
    assert main(["baseline", "-c", config, "--record", "--until", "2099-01-01"]) == 0
    attest(tmp_path, COMMIT)
    capsys.readouterr()
    status, out = run(capsys, "claims", "-c", config)
    assert status == 0, out
    assert "1 no longer present" in out


# -- refused at load -------------------------------------------------------------


@pytest.mark.parametrize(
    ("change", "refusal"),
    [
        ({"correct": "   "}, "is blank"),
        ({"correct": None}, "missing correct"),
        ({"note": "x"}, "unknown note"),
        ({"entry": None}, "missing entry"),
    ],
    ids=["blank-correct", "no-correct", "unknown-key", "no-entry"],
)
def test_a_malformed_attestation_is_refused(tmp_path, change, refusal):
    config = project(tmp_path)
    entry = {**COMMIT, **change}
    attest(tmp_path, {key: value for key, value in entry.items() if value is not None})
    with pytest.raises(ConfigError, match=refusal):
        load(config)


def test_a_repeated_attestation_is_refused(tmp_path):
    config = project(tmp_path)
    attest(tmp_path, COMMIT, COMMIT)
    with pytest.raises(ConfigError, match="repeats attestation 1"):
        load(config)


def test_a_file_that_is_not_a_yapyon_record_is_refused(tmp_path):
    config = project(tmp_path)
    attest(tmp_path, raw="attestations:\n  - registry: claims\n")
    with pytest.raises(ConfigError, match="not a yapyon record"):
        load(config)


def test_a_missing_file_attests_nothing(tmp_path):
    assert load(project(tmp_path)).attestations == ()
