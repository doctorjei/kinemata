"""kinemata's own files are not the project's material, so no scan reads them.

**The incident** (2026-10-21, measured while designing attestations): a project
whose suffixes reached ``.toml`` and ``.json`` had ``check`` report the config's
own antipattern declarations as bypasses, and once ``baseline --record`` had run,
the baseline's copies of the findings it accepted. 2 accepted findings made 7 new
ones, re-recording made 18, and the gate could never go green.
"""

from __future__ import annotations

import textwrap

from kinemata.cli import main

CONFIG = """
    [project]
    root = "."
    suffixes = [".py", ".toml", ".json"]
    {extra}

    [[registry]]
    name = "words"
    kind = "code-patterns"
    match_mode = "raw"

      [[registry.entry]]
      id = "no-frobnicate"
      antipatterns = ['frobnicate']
"""


def project(tmp_path, *, extra="", source="X = 1\n"):
    (tmp_path / "app.py").write_text(source)
    path = tmp_path / "kinemata.toml"
    path.write_text(textwrap.dedent(CONFIG.format(extra=extra)).lstrip())
    return str(path)


def run(capsys, *argv):
    status = main(list(argv))
    return status, capsys.readouterr().out


def test_the_config_is_not_scanned(tmp_path, capsys):
    """An absence rule overrides ``exclude``, and still does not read the config."""
    status, out = run(capsys, "check", "-c", project(tmp_path))
    assert status == 0, out
    assert "kinemata.toml:" not in out


def test_the_baseline_is_not_scanned(tmp_path, capsys):
    config = project(tmp_path, source="frobnicate()\n")
    assert main(["baseline", "-c", config, "--record", "--until", "2099-01-01"]) == 0
    capsys.readouterr()
    status, out = run(capsys, "check", "-c", config)
    assert status == 0, out
    assert ".kinemata-baseline.json:" not in out
    assert "baseline: 1 accepted finding(s)" in out


def test_a_relocated_baseline_is_recognized_where_it_went(tmp_path, capsys):
    config = project(
        tmp_path, extra='baseline = "state/accepted.json"', source="frobnicate()\n"
    )
    (tmp_path / "state").mkdir()
    assert main(["baseline", "-c", config, "--record", "--until", "2099-01-01"]) == 0
    capsys.readouterr()
    status, out = run(capsys, "check", "-c", config)
    assert status == 0, out
    assert "state/accepted.json:" not in out


def test_the_ratchet_directory_is_not_scanned(tmp_path, capsys):
    config = project(tmp_path)
    ratchets = tmp_path / ".kinemata" / "ratchets"
    ratchets.mkdir(parents=True)
    (ratchets / "layers.json").write_text('{"text": "frobnicate"}\n')
    status, out = run(capsys, "check", "-c", config)
    assert status == 0, out


def test_claims_does_not_read_the_config_either(tmp_path, capsys):
    """Every scan takes the shared ``exclude``, so the documentation half agrees."""
    config = project(
        tmp_path,
        extra='\n[claims]\nsuffixes = [".toml"]\n# see `nothere.md`',
    )
    (tmp_path / "notes.toml").write_text("# see `alsonothere.md`\n")
    status, out = run(capsys, "claims", "-c", config)
    assert "alsonothere.md" in out
    assert "kinemata.toml:" not in out
    assert status == 1
