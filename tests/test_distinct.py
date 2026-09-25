"""``[[distinct]]``: separate facts that happen to share a spelling.

Reported by an adopter on 2026-09-25. Its packaged-template directory,
``PACKAGED_AGENT_DEFAULT = "agent_default"``, and the ``agent_default:`` section
a loader reads from a YAML file are two facts -- renaming either would not
rename the other -- and ``check`` read the second as a bypass of the first.
Declaring the section as its own constant made it worse: each definition became
a bypass of the other. These tests are built around that case.
"""

from __future__ import annotations

import textwrap

import pytest

from kinemata.cli import main
from kinemata.config import ConfigError, load

CONFIG = """
    [project]
    root = "."

    [[registry]]
    name = "constants"
    kind = "python-constants"
    modules = ["pkg/templates.py", "pkg/loader.py"]
    {distinct}
"""

DISTINCT = """
    [[distinct]]
    entries = ["PACKAGED_AGENT_DEFAULT", "AGENT_DEFAULT_SECTION"]
    note = "a template directory and a YAML section, named after one concept"
"""


def project(tmp_path, distinct="", loader=None):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg/templates.py").write_text('PACKAGED_AGENT_DEFAULT = "agent_default"\n')
    (tmp_path / "pkg/loader.py").write_text(loader or textwrap.dedent("""
        AGENT_DEFAULT_SECTION = "agent_default"


        def load(doc):
            return doc.get(AGENT_DEFAULT_SECTION)
        """).lstrip())
    (tmp_path / "kinemata.toml").write_text(
        textwrap.dedent(CONFIG.format(distinct=textwrap.dedent(distinct)))
    )
    return str(tmp_path / "kinemata.toml")


def check(path, capsys):
    status = main(["check", "--config", path])
    return status, capsys.readouterr().out


def test_two_facts_with_one_spelling_report_each_other_without_it(tmp_path, capsys):
    """The adopter's case measured: declaring the second fact doubles the finding."""
    status, out = check(project(tmp_path), capsys)
    assert status == 1
    assert 'pkg/templates.py:1  PACKAGED_AGENT_DEFAULT = "agent_default"' in out
    assert 'pkg/loader.py:1  AGENT_DEFAULT_SECTION = "agent_default"' in out


def test_declared_distinct_neither_definition_is_a_bypass(tmp_path, capsys):
    status, out = check(project(tmp_path, DISTINCT), capsys)
    assert status == 0, out


def test_a_third_literal_is_still_reported_against_both(tmp_path, capsys):
    """Nothing at an inline literal says which fact it means, so it stays a finding."""
    loader = textwrap.dedent("""
        AGENT_DEFAULT_SECTION = "agent_default"


        def load(doc):
            return doc.get("agent_default")
        """).lstrip()
    status, out = check(project(tmp_path, DISTINCT, loader), capsys)
    assert status == 1
    assert out.count('pkg/loader.py:5  return doc.get("agent_default")') == 2


@pytest.mark.parametrize(
    ("distinct", "refusal"),
    [
        ('[[distinct]]\nentries = ["PACKAGED_AGENT_DEFAULT"]', "at least two"),
        ('[[distinct]]\nentries = ["PACKAGED_AGENT_DEFAULT", "PACKAGED_AGENT_DEFAULT"]',
         "at least two"),
        ('[[distinct]]\nentries = ["PACKAGED_AGENT_DEFAULT", "NOBODY"]', "no registry declares"),
        ('[[distinct]]\nentries = "PACKAGED_AGENT_DEFAULT"', "one character at a time"),
        ('[[distinct]]\nentries = ["PACKAGED_AGENT_DEFAULT", "AGENT_DEFAULT_SECTION"]\nwhy = 1',
         "why"),
    ],
)
def test_a_declaration_that_would_do_nothing_is_refused(tmp_path, distinct, refusal):
    path = project(tmp_path, distinct)
    with pytest.raises(ConfigError, match=refusal):
        load(path)


def test_a_stale_declaration_is_refused_once_the_values_diverge(tmp_path):
    """What keeps the declaration honest: when the spellings part, it exempts
    nothing, and it is refused rather than left to sit inert."""
    loader = 'AGENT_DEFAULT_SECTION = "agent_base"\n'
    path = project(tmp_path, DISTINCT, loader)
    with pytest.raises(ConfigError, match="exempts nothing"):
        load(path)
