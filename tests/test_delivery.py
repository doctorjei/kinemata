"""The reminder half: constants as a registry, suppression, config, CLI."""

from __future__ import annotations

import textwrap

import pytest

from kinemata.adapters.constants import PythonConstants
from kinemata.bypass import scan, unused
from kinemata.cli import build_parser, main
from kinemata.config import ConfigError, load
from kinemata.contract import BaseRegistry, Entry
from kinemata.gates import enforced
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


def test_a_short_value_is_matched_only_as_a_whole_literal(tmp_path):
    """The GET/POST incident, which is what a foreign project exposed.

    httpie declares ``HTTP_GET = 'GET'`` and ``HTTP_POST = 'POST'`` on adjacent
    lines, and a lexer table writes both as literals two lines apart. POST was
    reported and GET was invisible, because three characters was under the
    threshold -- so one of two identical constructs was reported and a reader
    would reasonably conclude the other was fine.

    Anchoring gives the precise half of what the threshold was protecting
    against and drops the noisy half: ``GET`` is a finding when a literal *is*
    it, never when a literal merely contains it.
    """
    write(tmp_path, "consts.py", "HTTP_GET = 'GET'\nHTTP_POST = 'POST'\n")
    write(
        tmp_path,
        "lexer.py",
        """
        TYPES = {'GET': 1, 'POST': 2}
        label = "TARGET"
        """,
    )
    reg = PythonConstants([tmp_path / "consts.py"], root=tmp_path)
    found = {(h.entry_id, h.line) for h in scan(reg, tmp_path) if h.strength == "strong"}
    assert found == {("HTTP_GET", 1), ("HTTP_POST", 1)}
    # ...and the substring that made the threshold right in the first place.
    # `TARGET` contains `GET`; unanchored, this is what buried the real
    # findings, and the case matters -- an earlier version of this test used
    # `budget`, whose `get` is lowercase, so it passed without the anchors.
    assert not [h for h in scan(reg, tmp_path) if h.line == 2]


def test_two_characters_is_below_even_the_anchored_tier(tmp_path):
    """Set by measurement. At a floor of 2, kanibako-cli's settings package went
    from 14 strong findings to 31, and every one of the seventeen was
    ``RW_PATH = "rw"`` matching the unrelated mount-binding key in
    ``bindings["rw"]``. A two-character value collides across namespaces even as
    a whole literal."""
    write(tmp_path, "consts.py", "RW_PATH = 'rw'\nSEP = '/'\n")
    got = {e.id: e.antipatterns for e in PythonConstants([tmp_path / "consts.py"]).entries()}
    assert got["RW_PATH"] == ()
    assert got["SEP"] == ()


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


def test_a_registry_that_yields_no_entries_is_recorded_not_dropped(tmp_path):
    """The wrong adapter looks exactly like a clean tree.

    Every part of this declaration is individually valid: the module exists, it
    parses, the kind is known. It just holds nothing ``python-constants``
    recognizes, so the registry is empty and every check over it passes.

    This is not hypothetical -- it is what this project's own config did for six
    commits, over three of its own modules, because the codebase has no
    module-level string constants.

    **Load used to raise here**, which also stopped the documentation check on a
    project whose data model no adapter fits. The refusal moved to the command
    that would have done the scanning; see the CLI test for the other half.
    """
    write(tmp_path, "src/consts.py", "TIMEOUT = 30\nlowercase = 'box.yaml'\n")
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
    settings = load(tmp_path / "kinemata.toml")
    assert settings.registries == []
    assert len(settings.unfitted) == 1
    assert "no entries" in settings.unfitted[0]


def test_allow_empty_permits_a_deliberately_empty_registry(tmp_path):
    """The escape hatch, so the guard does not block bootstrapping.

    Declared per registry and visible in the config, which is the difference
    between an exemption someone chose and one the tool took silently.
    """
    write(tmp_path, "src/consts.py", "TIMEOUT = 30\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        allow_empty = true
        """,
    )
    (reg,) = load(tmp_path / "kinemata.toml").registries
    assert list(reg.entries()) == []


def test_a_registry_can_target_its_own_file_types(tmp_path):
    """A retired name is a registry, and it lives in prose.

    Widening the project's suffix list to reach documentation would point the
    value registries at it too, and a value registry matching prose is the
    over-reporting failure. So the override is per registry.
    """
    write(tmp_path, "doc.md", "Install traceface today.\n")
    write(tmp_path, "src/app.py", "name = 'traceface'\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."
        suffixes = [".py"]

        [[registry]]
        name = "retired"
        kind = "code-patterns"
        suffixes = [".md"]

          [[registry.entry]]
          id = "kinemata"
          antipatterns = ['\\btraceface\\b']
        """,
    )
    (reg,) = load(tmp_path / "kinemata.toml").registries
    assert reg.suffixes == (".md",)
    sites = scan(reg, tmp_path, suffixes=reg.suffixes)
    assert [site.path for site in sites] == ["doc.md"]


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


def test_clusters_reports_repeated_text_and_stays_advisory(project, capsys):
    """The opposite question to review, and it never gates.

    Repeated text with no declared home is a judgment, not a violation -- two
    places may mean two ideas that coincide. It reports the fork, exit 0.
    """
    write(project, "src/one.py", 'msg = "could not reach the daemon"\n')
    write(project, "src/two.py", 'note = "could not reach the daemon"\n')
    code = main(["clusters", "-c", str(project / "kinemata.toml")])
    assert code == 0
    assert "could not reach the daemon" in capsys.readouterr().out


def test_clusters_does_not_repeat_what_the_registry_declares(project, capsys):
    """box.yaml is declared, so it is the bypass scan's finding, not this one."""
    write(project, "src/three.py", 'p = other / "box.yaml"\n')
    assert main(["clusters", "-c", str(project / "kinemata.toml")]) == 0
    assert "box.yaml" not in capsys.readouterr().out


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


def test_flags_work_before_the_subcommand_too(project):
    """The mirror of the test above, and its absence hid a real defect.

    The subcommand parses into a fresh namespace whose keys are then copied over
    the outer one, so every shared flag given *before* the subcommand was
    silently replaced by the subparser's default. `-c` was the one that bit:
    `kinemata -c canon.toml context` read the repository's config instead and
    reported that no ceiling was declared. The command ran; it just ran against
    something else.

    Only the "after" direction was covered, which is why nothing caught it --
    a test asserting half a contract reads exactly like one asserting all of it.
    """
    assert main(["-c", str(project / "kinemata.toml"), "-q", "ids"]) == 0


def test_no_shared_flag_is_dropped_before_the_subcommand(project):
    """Every flag on the shared parent, not just the one that was noticed."""
    argv = ["-c", str(project / "kinemata.toml"), "-r", "constants", "-q", "-v",
            "--max-sites", "7", "ids"]
    args = build_parser().parse_args(argv)
    assert args.config == str(project / "kinemata.toml")
    assert args.registry == "constants"
    assert (args.quiet, args.verbose, args.max_sites) == (True, True, 7)


def test_an_unflagged_run_still_gets_the_defaults(project):
    """`SUPPRESS` holds the subparser's defaults back; the top level supplies them."""
    args = build_parser().parse_args(["ids"])
    assert (args.config, args.registry, args.max_sites) == (None, None, None)
    assert (args.quiet, args.verbose) == (False, False)


def test_the_later_spelling_of_a_flag_wins(project):
    """Given both ways round, the one nearer the command is the one meant."""
    args = build_parser().parse_args(["-r", "outer", "ids", "-r", "inner"])
    assert args.registry == "inner"


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


def test_unused_refuses_when_nothing_says_where_a_declaration_lives(tmp_path):
    """The failure found by validating against a labeled incident, now refused.

    kanibako-cli ``d8037cf5`` records three declared keys with "no reader at
    all". This check missed all three, because each appears in the project's own
    key table -- a mention, not a reader, and text matching cannot tell them
    apart. Naming the declaring machinery is what makes the check mean anything.

    It used to return ``[]`` here, which is the inert signal: a clean-looking
    answer to a question that could not be asked. The exclusion was documented
    as "required in practice" while the signature defaulted it to empty, so the
    measured-0/3 configuration was what asking for nothing gave you.
    """
    write(tmp_path, "keys.py", 'KEY_TABLE = ["a.one", "a.two"]\n')
    write(tmp_path, "app.py", "value = resolve('a.one')\n")

    class Keys(BaseRegistry):
        name = "keys"

        def entries(self):
            yield Entry(id="a.one")
            yield Entry(id="a.two")

    with pytest.raises(ValueError, match="nothing says where"):
        unused(Keys(), tmp_path)
    # a project's build and test exclusions are not an answer to this question:
    with pytest.raises(ValueError, match="nothing says where"):
        unused(Keys(), tmp_path, exclude=["build/"])
    # naming the declaring machinery makes the check mean something:
    assert unused(Keys(), tmp_path, machinery=["keys.py"]) == ["a.two"]


def test_a_registry_can_carry_its_own_declaring_machinery(tmp_path):
    """``machinery`` is the declaration; ``exclude`` is the call-site argument.

    The incident needs the registry-level one. Those keys' ``home`` is the
    manifest they are declared in, while the table that mentions them is a
    module -- so ``home`` alone cannot answer, and a project should not have to
    re-supply the same list at every call site to get a meaningful answer.
    """
    write(tmp_path, "keys.py", 'KEY_TABLE = ["a.one", "a.two"]\n')
    write(tmp_path, "app.py", "value = resolve('a.one')\n")

    class Keys(BaseRegistry):
        name = "keys"
        machinery = ("keys.py",)

        def entries(self):
            yield Entry(id="a.one")
            yield Entry(id="a.two")

    assert unused(Keys(), tmp_path) == ["a.two"]


def test_a_registry_declaring_absence_is_not_asked_what_is_unused(tmp_path):
    """Found by dogfooding, and it reported success as failure.

    Run over this project's own ``spelling`` registry, ``unused`` returned 28
    American spellings -- every one of them a word the convention says should
    not appear, correctly absent. A page of findings that all mean the check
    passed is worse than no output, because a reader learns to skim it.
    """
    write(tmp_path, "doc.md", "Nothing retired here.\n")

    class Retired(BaseRegistry):
        name = "retired"
        mentions_are_uses = False
        machinery = ("words.toml",)

        def entries(self):
            yield Entry(id="traceface")

    with pytest.raises(ValueError, match="the convention being kept"):
        unused(Retired(), tmp_path, suffixes=[".md"])


def test_config_declares_the_machinery_on_the_registry(tmp_path):
    write(tmp_path, "src/consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]
        machinery = ["src/keys.py", "src/paths.py"]
        """,
    )
    (registry,) = load(tmp_path / "kinemata.toml").registries
    assert registry.machinery == ("src/keys.py", "src/paths.py")


def test_unused_reports_a_declared_thing_and_stays_advisory(project, capsys):
    """The mirror of ``scan``, over the same tree.

    ``scan`` catches a file that re-derives a declared value; this catches a
    declared value no file names. The fixture's ``app.py`` writes ``"box.yaml"``
    rather than routing through ``BOX_META_FILE``, so both fire on it -- one
    saying the constant was bypassed, the other saying nothing refers to it.
    Making ``app.py`` route properly silences both, which is the point.
    """
    write(project, "src/consts.py", 'BOX_META_FILE = "box.yaml"\nSPARE = "spare.yaml"\n')
    write(project, "src/app.py", "from .consts import BOX_META_FILE\np = root / BOX_META_FILE\n")
    assert main(["unused", "-c", str(project / "kinemata.toml")]) == 0
    out = capsys.readouterr().out
    assert "SPARE" in out
    assert "BOX_META_FILE" not in out
    assert "review list, never a cut list" in out


def test_unused_names_the_registries_that_could_not_answer(project, capsys):
    """Suppression is reported, never silent.

    A run that printed the answering registry's clean line and said nothing
    about the one it skipped would read as "this project has no unused
    declarations", which is the inert signal in its most persuasive form.
    """
    write(project, "docs/note.md", "Prose with no retired names.\n")
    write(
        project,
        "kinemata.toml",
        """
        [project]
        root = "."

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/consts.py"]

        [[registry]]
        name = "retired"
        kind = "substitutions"
        suffixes = [".md"]

          [registry.words]
          traceface = "kinemata"
        """,
    )
    assert main(["unused", "-c", str(project / "kinemata.toml")]) == 0
    captured = capsys.readouterr()
    assert "skipped: registry 'retired'" in captured.err
    assert "constants" in captured.out


def test_unused_refuses_when_no_registry_can_answer(tmp_path, capsys):
    """2, not 0. A question nobody could ask has no clean answer."""
    write(tmp_path, "doc.md", "Prose.\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [[registry]]
        name = "retired"
        kind = "substitutions"
        suffixes = [".md"]

          [registry.words]
          traceface = "kinemata"
        """,
    )
    assert main(["unused", "-c", str(tmp_path / "kinemata.toml")]) == 2
    assert "no declared registry can say what is unused" in capsys.readouterr().err


def test_a_kind_that_cannot_recognize_identifiers_is_refused_when_closed(tmp_path):
    """``closed`` is a promise only one adapter can keep.

    Every kind accepts ``closed = true`` from configuration; only
    ``yaml-mapping`` implements ``candidates()``. A closed registry that cannot
    recognize an identifier answers nothing when asked what is undeclared, which
    reads exactly like a tree with nothing undeclared in it.

    ``BaseRegistry.__post_init_check__`` existed to ask this question and was
    called from nowhere in ``src/`` for the whole life of the mechanism, so the
    promise was checked by nothing. Found 2026-09-08 while auditing why the
    closed-world catch had no CLI surface.
    """
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "helpers"
        kind = "code-patterns"
        closed = true

          [[registry.entry]]
          id = "run_or_die"
          antipatterns = ['check\\s*=\\s*True']
        """,
    )
    with pytest.raises(ConfigError, match="cannot be closed"):
        load(tmp_path / "kinemata.toml")


def test_the_closure_guard_does_not_fire_on_an_open_registry(tmp_path):
    """The same declaration without ``closed`` loads.

    A guard that refused this would make the ratchet unusable: an open registry
    routes undeclared identifiers to a review list rather than a failure, which
    is how a legacy codebase adopts one at all.
    """
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
    assert [r.name for r in settings.registries] == ["helpers"]


def test_a_scan_leaving_the_tree_says_so_even_when_quiet(project, tmp_path, capsys):
    """Following a link out of the project is deliberate; doing it silently is
    not. The root would otherwise read as the bound on what was scanned.

    Reported through ``-q`` because this is the scope of the check rather than
    one of its findings, the same rule the exemption count follows.
    """
    outside = tmp_path.parent / "outside-the-project"
    outside.mkdir(exist_ok=True)
    (outside / "app.py").write_text('p = root / "box.yaml"\n')
    (project / "src" / "linked").symlink_to(outside)

    assert main(["check", "-c", str(project / "kinemata.toml"), "-q"]) == 1
    captured = capsys.readouterr()
    assert "src/linked" in captured.err
    assert str(outside.resolve()) in captured.err
    # and it is scanned, not merely announced
    assert "linked/app.py" in captured.out


def test_the_old_promised_key_says_where_it_went(tmp_path):
    """`[claims] promised` shipped in the morning and moved the same day, once
    it was clear a project defers questions as well as paths. A config carrying
    the old key is told where it went rather than having its promises silently
    ignored."""
    write(tmp_path, "consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [claims]
        promised = [{ path = "docs/plan.md", until = "2027-01-01" }]

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["consts.py"]
        """,
    )
    with pytest.raises(ConfigError, match=r"has moved to \[\[promise\]\]"):
        load(tmp_path / "kinemata.toml")


def test_a_config_that_only_checks_documents_needs_no_registry(tmp_path, capsys):
    """The cheapest adoption there is, and it used to require a fiction.

    The loader demanded a `[[registry]]`, so a project wanting `claims` alone
    had to invent one -- measured on a real integration, where exactly one
    registry existed to get past that line. The rule it came from is about an
    *empty* registry reading like a clean tree, which is a different thing from
    an absent one.
    """
    write(tmp_path, "doc.md", "See `src/app.py`.\n")
    write(tmp_path, "src/app.py", "x = 1\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [claims]
        suffixes = [".md"]
        """,
    )
    assert load(tmp_path / "kinemata.toml").registries == []
    assert main(["claims", "-c", str(tmp_path / "kinemata.toml")]) == 0


def test_a_scan_refuses_when_no_registry_is_declared(tmp_path, capsys):
    """The refusal moved, it did not disappear. Scanning nothing and exiting 0
    is the inert signal, and it reads exactly like a clean tree."""
    write(tmp_path, "doc.md", "Nothing to see.\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [claims]
        suffixes = [".md"]
        """,
    )
    # 2, not 1: a configuration error is not a finding, and a caller reading
    # exit codes should be able to tell "this tree is dirty" from "this tool
    # was asked something it cannot answer".
    assert main(["check", "-c", str(tmp_path / "kinemata.toml")]) == 2
    assert "no [[registry]] declared" in capsys.readouterr().err


def test_a_config_that_declares_no_check_at_all_is_refused(tmp_path):
    """What the old rule was reaching for. A config nobody can fail is not a
    configuration, and every command it defines would pass by doing nothing."""
    write(tmp_path, "kinemata.toml", '[project]\nroot = "."\n')
    with pytest.raises(ConfigError, match="declares no check at all"):
        load(tmp_path / "kinemata.toml")


def test_a_config_inherited_from_a_parent_says_so(tmp_path, capsys, monkeypatch):
    """The upward walk is convenience in one place and a blindness leak in
    another: a role meant to see one subtree, running a gate inside it, picks up
    the parent's config and everything it points at. The walk stays -- narrowing
    it to a repository boundary would break a tree that is not one -- but an
    inherited config announces itself, and a local one stays quiet."""
    write(tmp_path, "consts.py", 'BOX_META_FILE = "box.yaml"\n')
    write(
        tmp_path,
        "kinemata.toml",
        """
        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["consts.py"]
        """,
    )
    inside = tmp_path / "subtree"
    inside.mkdir()

    monkeypatch.chdir(inside)
    assert main(["review"]) == 0
    assert "above the current directory" in capsys.readouterr().err

    monkeypatch.chdir(tmp_path)
    assert main(["review"]) == 0
    assert "above the current directory" not in capsys.readouterr().err


# -- init: the first minute of adoption ---------------------------------------


def test_init_writes_a_config_that_runs_immediately(tmp_path):
    """Measured friction, not imagined: gating one real artifact set by hand
    took a config written from scratch against knowledge of which adapters
    exist. The starter declares `[claims]`, which needs no registry, so the
    first command a project runs works before it has decided anything."""
    assert main(["init", str(tmp_path)]) == 0
    config = tmp_path / "kinemata.toml"
    assert load(config).registries == []
    assert main(["claims", "-c", str(config)]) == 0


def test_init_ci_declares_the_gates_its_workflow_runs(tmp_path):
    """The scaffold is checked by our own gate. `claims` verifies that every
    declared gate appears in the file meant to run it, so a generated pair that
    drifts apart fails rather than reassures."""
    assert main(["init", str(tmp_path), "--ci"]) == 0
    assert (tmp_path / ".github/workflows/kinemata.yml").is_file()

    settings = load(tmp_path / "kinemata.toml")
    inventory = enforced(tmp_path, settings.gates)
    assert inventory.declared == 2
    assert not inventory.absent


def test_init_refuses_to_overwrite(tmp_path):
    """A scaffold that silently replaced a config someone tuned would be the
    worst possible first impression for a tool arguing that declarations should
    be true."""
    write(tmp_path, "kinemata.toml", "# mine\n")
    assert main(["init", str(tmp_path)]) == 2
    assert (tmp_path / "kinemata.toml").read_text() == "# mine\n"


# -- what running over somebody else's code exposed ---------------------------


def test_the_scanned_project_s_syntax_warnings_are_not_ours(tmp_path, recwarn):
    """httpie has invalid escape sequences in its own source, and ten warning
    lines landed in the middle of a report about httpie's duplication.

    The warning is attributed to whoever called ``parse``, which is us. A
    foreign project's lint is not our finding, and this is not a compiler.
    """
    write(tmp_path, "consts.py", 'PATTERN = "ok"\nBAD = re.compile("\\d+")\n')

    class Consts(BaseRegistry):
        name = "consts"

        def entries(self):
            yield Entry(id="PATTERN", antipatterns=("ok",), home=("consts.py",))

    scan(Consts(), tmp_path)
    assert not [w for w in recwarn if issubclass(w.category, SyntaxWarning)]


def test_declared_entries_nothing_can_report_on_are_counted(project, capsys):
    """The silence had no voice, which is the same failure as an unprinted
    exemption list.

    httpie declares ``HTTP_GET = 'GET'`` and ``HTTP_POST = 'POST'`` on adjacent
    lines and a lexer writes both as literals two lines apart. ``check``
    reported POST and said nothing about GET, because three characters is under
    the minimum value length -- and 18 of its 21 declared entries were in that
    position. The threshold is not the defect; the invisibility was.
    """
    write(project, "src/consts.py", 'BOX_META_FILE = "box.yaml"\nMODE = "vm"\n')
    main(["review", "-c", str(project / "kinemata.toml")])
    assert "silent: 1 of 2 declared entry(s) carry no antipattern" in capsys.readouterr().out


def test_a_registry_that_fits_nothing_does_not_block_the_documentation_check(tmp_path, capsys):
    """`requests` declares its canonical things as code shapes and numbers, so
    `python-constants` bound to nothing -- and refusing at load stopped its
    documentation from being checked as well.

    The refusal moves to the command that would have done the scanning. Nothing
    is lost from CI, which runs both.
    """
    write(tmp_path, "src/app.py", "value = 1\n")
    write(tmp_path, "doc.md", "The entry point is `src/app.py`.\n")
    write(
        tmp_path,
        "kinemata.toml",
        """
        [project]
        root = "."

        [claims]
        suffixes = [".md"]

        [[registry]]
        name = "constants"
        kind = "python-constants"
        modules = ["src/app.py"]
        """,
    )
    config = str(tmp_path / "kinemata.toml")
    assert main(["claims", "-c", config]) == 0
    assert "produced no entries" in capsys.readouterr().err
    # ...and the command that would scan for nothing still refuses.
    assert main(["check", "-c", config]) == 2
    assert "produced no entries" in capsys.readouterr().err
