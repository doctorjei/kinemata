"""The reminder half: constants as a registry, suppression, config, CLI."""

from __future__ import annotations

import textwrap

import pytest

from kinemata.adapters.constants import PythonConstants
from kinemata.bypass import scan, unused
from kinemata.cli import main
from kinemata.config import ConfigError, load
from kinemata.contract import BaseRegistry, Entry
from kinemata.report import review


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


# -- constants: antipatterns derived from the values themselves ---------------


def test_a_constants_value_is_its_own_antipattern(tmp_path):
    write(tmp_path, "consts.py", 'WORKSET_META_FILE = "workset.yaml"\n')
    (entry,) = PythonConstants([tmp_path / "consts.py"], root=tmp_path).entries()
    assert entry.id == "WORKSET_META_FILE"
    assert entry.antipatterns == (r"workset\.yaml",)
    assert entry.home == ("consts.py",)


def test_short_and_generic_values_get_no_antipattern(tmp_path):
    write(tmp_path, "consts.py", 'SEP = "/"\nFLAG = "true"\nREAL = "box_data"\n')
    got = {e.id: e.antipatterns for e in PythonConstants([tmp_path / "consts.py"]).entries()}
    assert got["SEP"] == ()      # too short: would match everything
    assert got["FLAG"] == ()     # generic
    assert got["REAL"] != ()


def test_private_constants_are_skipped_by_default(tmp_path):
    write(tmp_path, "consts.py", '_INTERNAL = "box_data"\nPUBLIC = "workset.yaml"\n')
    ids = {e.id for e in PythonConstants([tmp_path / "consts.py"]).entries()}
    assert ids == {"PUBLIC"}


def test_non_string_and_lowercase_assignments_are_not_entries(tmp_path):
    write(tmp_path, "consts.py", 'TIMEOUT = 30\nlower_case = "workset.yaml"\n')
    assert list(PythonConstants([tmp_path / "consts.py"]).entries()) == []


def test_a_definition_is_not_a_bypass_of_itself(tmp_path):
    """Regression: `home` and the scan path are anchored differently.

    `home` is recorded relative to the project root; the scan reports relative
    to whatever it was pointed at. When those differ, a naive substring test
    reports every constant as bypassing itself.
    """
    write(tmp_path, "src/pkg/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    reg = PythonConstants([tmp_path / "src/pkg/consts.py"], root=tmp_path)

    assert scan(reg, tmp_path, strings_only=True) == []       # scanned from root
    assert scan(reg, tmp_path / "src", strings_only=True) == []  # and from src/


# -- strong vs weak -----------------------------------------------------------


def test_a_whole_literal_match_is_strong_a_substring_is_weak(tmp_path):
    write(tmp_path, "consts.py", 'WORKSPACES_PATH = "workspaces"\n')
    write(
        tmp_path,
        "use.py",
        '''
        exact = "workspaces"
        other_namespace = "workset.workspaces"
        ''',
    )
    reg = PythonConstants([tmp_path / "consts.py"], root=tmp_path)
    hits = {h.strength: h for h in scan(reg, tmp_path, strings_only=True)}
    assert hits["strong"].line == 1
    assert hits["weak"].line == 2


def test_only_strong_signals_gate(tmp_path):
    write(tmp_path, "consts.py", 'WORKSPACES_PATH = "workspaces"\n')
    write(tmp_path, "use.py", 'k = "workset.workspaces"\n')
    report = review(PythonConstants([tmp_path / "consts.py"], root=tmp_path), tmp_path)
    assert report.weak and not report.strong
    assert report.clean


# -- suppression --------------------------------------------------------------


def test_a_domain_word_is_suppressed_and_reported(tmp_path):
    write(tmp_path, "consts.py", 'KIND_WORKSET = "workset"\n')
    body = "\n".join(f'x{i} = "workset"' for i in range(30))
    write(tmp_path, "app.py", body + "\n")

    reg = PythonConstants([tmp_path / "consts.py"], root=tmp_path)
    report = review(reg, tmp_path, max_sites=20)

    assert report.bypasses == ()
    assert len(report.suppressed) == 1
    assert report.suppressed[0].matches == 30
    assert "domain word" in str(report.suppressed[0])
    # Suppression is visible, never silent.
    assert "suppressed" in report.text()


def test_suppression_can_be_disabled(tmp_path):
    write(tmp_path, "consts.py", 'KIND_WORKSET = "workset"\n')
    write(tmp_path, "app.py", "\n".join(f'x{i} = "workset"' for i in range(30)))
    reg = PythonConstants([tmp_path / "consts.py"], root=tmp_path)
    assert len(review(reg, tmp_path, max_sites=None).bypasses) == 30


# -- config -------------------------------------------------------------------


def test_config_builds_a_working_registry(tmp_path):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", 'p = root / "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """,
    )
    settings = load(tmp_path / "kinemata.toml")
    (reg,) = settings.registries
    assert reg.name == "constants"
    assert len(review(reg, settings.root).strong) == 1


def test_a_missing_module_is_refused_not_skipped(tmp_path):
    """A registry that silently scans nothing is the inert-signal failure."""
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/nope.py"]
        """,
    )
    with pytest.raises(ConfigError, match="not found"):
        load(tmp_path / "kinemata.toml")


def test_an_unknown_kind_is_refused(tmp_path):
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "x"
        kind = "telepathy"
        """,
    )
    with pytest.raises(ConfigError, match="unknown kind"):
        load(tmp_path / "kinemata.toml")


# -- CLI: same analysis, two consequences -------------------------------------


@pytest.fixture
def project(tmp_path):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", 'p = root / "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """,
    )
    return tmp_path


def test_review_advises_and_always_exits_zero(project, capsys):
    code = main(["review", "-c", str(project / "kinemata.toml")])
    assert code == 0
    assert "BOX_META_FILE" in capsys.readouterr().out


def test_check_gates_on_the_same_finding(project, capsys):
    assert main(["check", "-c", str(project / "kinemata.toml")]) == 1
    assert "FAIL" in capsys.readouterr().err


def test_check_passes_when_nothing_is_re_derived(tmp_path, capsys):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(tmp_path, "src/app.py", "from consts import BOX_META_FILE\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        """,
    )
    assert main(["check", "-c", str(tmp_path / "kinemata.toml")]) == 0


def test_ids_prints_the_projection(project, capsys):
    assert main(["ids", "-c", str(project / "kinemata.toml")]) == 0
    assert capsys.readouterr().out.strip() == "BOX_META_FILE"


def test_flags_work_after_the_subcommand(project):
    # `kinemata ids -c X` must work, not only `kinemata -c X ids`.
    assert main(["ids", "-c", str(project / "kinemata.toml"), "-q"]) == 0


def test_a_relative_path_resolves_against_the_project_root(project, capsys):
    """Regression: it resolved against the CWD and scanned a different tree."""
    assert main(["check", "-c", str(project / "kinemata.toml"), "src"]) == 1
    assert "app.py" in capsys.readouterr().out


def test_a_missing_config_is_an_error_not_a_pass(tmp_path, capsys):
    assert main(["check", "-c", str(tmp_path / "absent.toml")]) == 2
    assert "error" in capsys.readouterr().err


# -- code-patterns: canonical things that are code, not values ---------------


def test_code_patterns_matches_a_code_shape_not_a_literal(tmp_path):
    write(tmp_path, "run.py", "def run_or_die(cmd):\n    pass\n")
    write(tmp_path, "app.py", "subprocess.run(cmd, check=True)\n")

    from kinemata.adapters.patterns import CodePatterns

    reg = CodePatterns(
        [{"id": "run_or_die", "antipatterns": [r"check\s*=\s*True"], "home": ["run.py"]}]
    )
    assert reg.match_mode == "code"
    (hit,) = scan(reg, tmp_path)
    assert hit.entry_id == "run_or_die"
    assert hit.path == "app.py"


def test_the_registry_chooses_its_own_match_mode(tmp_path):
    """A value registry must not match identifiers; a code registry must."""
    write(tmp_path, "consts.py", 'BOX_DATA = "box_data"\n')
    write(tmp_path, "app.py", "box_data = compute()\n")
    # match_mode defaults to "strings", so the identifier is not a hit.
    reg = PythonConstants([tmp_path / "consts.py"], root=tmp_path)
    assert scan(reg, tmp_path) == []


def test_an_entry_with_no_antipattern_is_refused(tmp_path):
    from kinemata.adapters.patterns import CodePatterns

    with pytest.raises(ValueError, match="invisible to every check"):
        CodePatterns([{"id": "orphan"}])


def test_code_patterns_ignores_prose(tmp_path):
    write(tmp_path, "app.py", '"""Do not use check=True here."""\nx = 1\n')
    from kinemata.adapters.patterns import CodePatterns

    reg = CodePatterns([{"id": "run_or_die", "antipatterns": [r"check\s*=\s*True"]}])
    assert scan(reg, tmp_path) == []


def test_config_builds_code_patterns(tmp_path):
    write(tmp_path, "app.py", "subprocess.run(cmd, check=True)\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "helpers"
        kind = "code-patterns"

          [[registry.entry]]
          id = "run_or_die"
          antipatterns = ['check\\s*=\\s*True']
        """,
    )
    settings = load(tmp_path / "kinemata.toml")
    (reg,) = settings.registries
    assert len(review(reg, settings.root).strong) == 1


def test_code_patterns_needs_at_least_one_entry(tmp_path):
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "helpers"
        kind = "code-patterns"
        """,
    )
    with pytest.raises(ConfigError, match="at least"):
        load(tmp_path / "kinemata.toml")


# -- unused: detects mention, not use ----------------------------------------


def test_unused_is_vacuous_without_excluding_the_declaring_machinery(tmp_path):
    """The failure found by validating against a labelled incident.

    kanibako-cli ``d8037cf5`` records three declared keys with "no reader at
    all". This check missed all three, because each appears in the project's own
    key table -- a mention, not a reader, and text matching cannot tell them
    apart. Excluding the declaring machinery is what makes the check mean
    anything.
    """
    write(tmp_path, "keys.py", 'KEY_TABLE = ["a.one", "a.two"]\n')
    write(tmp_path, "app.py", "value = resolve('a.one')\n")

    class Keys(BaseRegistry):
        name = "keys"

        def entries(self):
            yield Entry(id="a.one")
            yield Entry(id="a.two")

    # a.two has no reader, but the key table mentions it:
    assert unused(Keys(), tmp_path) == []
    # excluding the declaring machinery makes the check mean something:
    assert unused(Keys(), tmp_path, exclude=["keys.py"]) == ["a.two"]
