"""AST boundaries: actual Python import and call forms, never text guesses."""

from __future__ import annotations

import json
import textwrap

from kinemata.boundary import inventory, survey
from kinemata.cli import main
from kinemata.config import load


def write(root, name, body):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def config(root, text):
    return write(root, "kinemata.toml", text)


def test_import_policy_reads_relative_alias_lazy_and_type_only_imports(tmp_path):
    """Forms measured in kanibako's settings integration, not imagined syntax."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/settings/__init__.py", "")
    write(tmp_path, "pkg/consumer.py", """
        from typing import TYPE_CHECKING
        from .settings import api as public_api
        from .settings import internal as private_api

        if TYPE_CHECKING:
            from .settings import typing_only

        def load():
            from .settings import lazy as lazy_api
            return lazy_api
        """)
    settings = load(config(tmp_path, """
        [[boundary]]
        name = "settings-surface"
        kind = "imports"
        only = ["pkg/"]
        imports = ["pkg.settings"]
        allow = ["pkg.settings.api"]
        type_checking = "ignore"
        """))
    [rule] = settings.boundaries
    found = survey(tmp_path, rule)
    assert [(item.subject, item.line) for item in found.findings] == [
        ("pkg.settings.internal", 3),
        ("pkg.settings.lazy", 9),
    ]
    assert not found.unjudged


def test_call_policy_resolves_import_aliases_and_same_scope_aliases(tmp_path):
    """Direct os/shutil aliases and lazy aliases are statically provable calls."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/ops.py", "")
    write(tmp_path, "pkg/caller.py", """
        import os as operating_system
        from shutil import move as shift
        from .ops import remove as delete

        def run():
            from os import remove as local_remove
            local = local_remove
            operating_system.rename("a", "b")
            shift("a", "b")
            delete()
            local()
        """)
    settings = load(config(tmp_path, """
        [[boundary]]
        name = "mutators-home"
        kind = "calls"
        only = ["pkg/"]
        calls = ["os.rename", "os.remove", "shutil.move", "pkg.ops.remove"]
        homes = ["pkg/homes.py"]
        """))
    [rule] = settings.boundaries
    found = survey(tmp_path, rule)
    assert [item.subject for item in found.findings] == [
        "os.rename", "shutil.move", "pkg.ops.remove", "os.remove",
    ]
    assert not found.unsupported


def test_type_only_binding_does_not_resolve_a_runtime_call(tmp_path):
    """A type-only binding is not runtime data when a lazy import shadows its name."""
    write(tmp_path, "pkg/__init__.py", "")
    write(tmp_path, "pkg/type_ops.py", "")
    write(tmp_path, "pkg/runtime_ops.py", "")
    write(tmp_path, "pkg/caller.py", """
        from typing import TYPE_CHECKING
        if TYPE_CHECKING:
            from .type_ops import remove
        remove()

        def run():
            from .runtime_ops import remove
            remove()
        """)
    settings = load(config(tmp_path, """
        [[boundary]]
        name = "runtime-remove"
        kind = "calls"
        calls = ["pkg.type_ops.remove", "pkg.runtime_ops.remove"]
        homes = ["pkg/home.py"]
        """))
    found = survey(tmp_path, settings.boundaries[0])
    assert [(item.subject, item.line) for item in found.findings] == [
        ("pkg.runtime_ops.remove", 8)
    ]


def test_instance_method_without_dataflow_is_explicitly_unjudged(tmp_path):
    """`path.write_text` is not guessed to be pathlib.Path.write_text."""
    write(tmp_path, "pkg/caller.py", """
        def save(path):
            path.write_text("x")
        """)
    settings = load(config(tmp_path, """
        [[boundary]]
        name = "writes-home"
        kind = "calls"
        calls = ["pathlib.Path.write_text"]
        homes = ["pkg/writer.py"]
        """))
    found = survey(tmp_path, settings.boundaries[0])
    assert found.findings == ()
    assert [(item.expression, item.reason) for item in found.unsupported] == [
        ("path.write_text", "instance/data-flow receiver cannot be resolved statically")
    ]


def test_an_unresolvable_receiver_counts_rather_than_failing_the_gate(tmp_path, capsys):
    """Failing here made the rule impossible to pass, so nobody keeps it.

    Measured on an adopter's tree: a family of module functions gave 59 real
    findings beside 71 unknown-receiver sites, because `tmp.replace` shares its
    last segment with `os.replace` and `str.replace` is everywhere. The gate
    counts them; the *writer* still refuses, because an unmeasured call cannot
    earn an accepted finding.
    """
    write(tmp_path, "pkg/caller.py", """
        import os

        def rewrite(tmp, dst):
            os.replace(tmp, dst)
            return tmp.replace("a", "b")
        """)
    cfg = config(tmp_path, """
        [[boundary]]
        name = "mutators-home"
        kind = "calls"
        only = ["pkg/"]
        calls = ["os.replace"]
        homes = ["pkg/files.py"]
        """)
    assert main(["boundary", "-c", str(cfg)]) == 1
    out, err = capsys.readouterr()
    assert "pkg/caller.py:4: os.replace" in out       # the real finding
    assert "unjudged: 1 call(s)" in out               # counted, not failed
    assert "tmp.replace" in err                       # and named, with a reason
    # The same run may not author evidence for what it could not measure.
    assert main(["boundary", "-c", str(cfg), "--rule", "mutators-home",
                 "--record"]) == 2


def test_a_clean_run_with_no_unjudged_sites_reports_the_plain_result(tmp_path, capsys):
    """The `unjudged:` line is on every run that has them, and only those."""
    write(tmp_path, "pkg/caller.py", "import os\n")
    cfg = config(tmp_path, """
        [[boundary]]
        name = "mutators-home"
        kind = "calls"
        only = ["pkg/"]
        calls = ["os.replace"]
        homes = ["pkg/caller.py"]
        """)
    assert main(["boundary", "-c", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "policy holds" in out
    assert "unjudged:" not in out


def test_adding_one_comment_line_above_a_finding_does_not_fail_the_rule(tmp_path, capsys):
    """Reported by an adopter on the dev wheel, 2026-10-12: one comment line at
    the top of a module left only 37 of 110 accepted findings matching, and the
    rule failed.

    Every edit above a finding shifts its line, so keying on one makes an
    unrelated change look like new debt — and re-recording on every unrelated
    edit is how a ratchet gets waved through. The enclosing scope takes the
    line's place: a lazy import inside `def resolve` stays inside `resolve`
    however far the code above it moves.
    """
    write(tmp_path, "pkg/m.py", "import alpha\nimport beta\n")
    cfg = config(tmp_path, RULE.format(
        extra="", until="2099-01-01",
    ).replace('imports = ["private_layer"]',
              'imports = ["alpha", "beta", "gamma"]').replace(
        "private-layer", "layer"))
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert main(["boundary", "-c", str(cfg), "--rule", "layer", "--record"]) == 0
    capsys.readouterr()

    write(tmp_path, "pkg/m.py", "# a comment\nimport alpha\nimport beta\n")
    assert main(["boundary", "-c", str(cfg)]) == 0
    assert "policy holds" in capsys.readouterr().out


def test_a_second_occurrence_in_one_scope_is_an_increase_not_a_duplicate(tmp_path):
    """A set cannot tell the second occurrence from the first.

    The same import twice in the same scope has to read as a count, or removing
    one and adding one is invisible -- which is the difference between a ratchet
    and a snapshot.
    """
    write(tmp_path, "pkg/m.py", "import alpha\nimport alpha\n")
    cfg = config(tmp_path, """
        [[boundary]]
        name = "layer"
        kind = "imports"
        imports = ["alpha"]
        [boundary.ratchet]
        until = "2099-01-01"
        """)
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert main(["boundary", "-c", str(cfg), "--rule", "layer", "--record"]) == 0
    recorded = json.loads(
        (tmp_path / ".kinemata/ratchets/layer.json").read_text()
    )["findings"]
    assert len(recorded) == 1
    assert list(recorded.values()) == [2]      # one key, counted twice


def test_the_same_import_in_two_functions_is_two_sites(tmp_path):
    """The scope replaces the line, so it has to actually distinguish."""
    write(tmp_path, "pkg/m.py", "def a():\n    import alpha\n\ndef b():\n    import alpha\n")
    cfg = config(tmp_path, """
        [[boundary]]
        name = "layer"
        kind = "imports"
        imports = ["alpha"]
        [boundary.ratchet]
        until = "2099-01-01"
        """)
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert main(["boundary", "-c", str(cfg), "--rule", "layer", "--record"]) == 0
    recorded = json.loads(
        (tmp_path / ".kinemata/ratchets/layer.json").read_text()
    )["findings"]
    assert sorted(recorded.values()) == [1, 1]  # each keyed on its own function


def test_a_finding_moved_to_another_function_is_a_new_site(tmp_path):
    """The scope replaces the line, so it must actually distinguish."""
    write(tmp_path, "pkg/m.py", "def a():\n    import alpha\n")
    cfg = config(tmp_path, """
        [[boundary]]
        name = "layer"
        kind = "imports"
        imports = ["alpha"]
        [boundary.ratchet]
        until = "2099-01-01"
        """)
    assert main(["boundary", "-c", str(cfg), "--rule", "layer", "--record"]) == 0
    write(tmp_path, "pkg/m.py", "def b():\n    import alpha\n")
    settings = load(cfg)
    [rule] = settings.boundaries
    from kinemata.boundary import survey
    assert survey(tmp_path, rule, settings.exclude).unjudged is False


RULE = """
    [[boundary]]
    name = "private-layer"
    kind = "imports"
    imports = ["private_layer"]
    {extra}
    [boundary.ratchet]
    until = "{until}"
    """


def _recorded(root, cfg, capsys):
    """Record one rule's ratchet and hand back its sidecar path."""
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--record"]) == 0
    capsys.readouterr()
    return root / ".kinemata/ratchets/private-layer.json"


def test_a_weakened_rule_cannot_inherit_the_old_ratchets_findings(tmp_path, capsys):
    """Widening the allowed surface must not silently accept what the rule forbade.

    The ratchet is keyed on a fingerprint of the *policy*, not of its findings,
    precisely so that editing the declaration is an act somebody repeats
    deliberately rather than an exemption granted by a diff.
    """
    write(tmp_path, "pkg/consumer.py", "import private_layer\n")
    cfg = config(tmp_path, RULE.format(extra="", until="2099-01-01"))
    _recorded(tmp_path, cfg, capsys)

    weakened = config(tmp_path, RULE.format(
        extra='allow = ["private_layer"]', until="2099-01-01"
    ))
    assert main(["boundary", "-c", str(weakened)]) == 1
    assert "rule fingerprint differs" in capsys.readouterr().err


def test_a_narrowed_source_scope_cannot_inherit_the_old_ratchets_findings(tmp_path, capsys):
    """Coverage narrowing is caught by the declaration, and `only` is in it."""
    write(tmp_path, "pkg/consumer.py", "import private_layer\n")
    write(tmp_path, "other/consumer.py", "import private_layer\n")
    cfg = config(tmp_path, RULE.format(extra="", until="2099-01-01"))
    _recorded(tmp_path, cfg, capsys)

    narrowed = config(tmp_path, RULE.format(
        extra='only = ["pkg/"]', until="2099-01-01"
    ))
    assert main(["boundary", "-c", str(narrowed)]) == 1
    assert "rule fingerprint differs" in capsys.readouterr().err


def test_a_new_module_does_not_block_a_gate_and_a_deleted_one_is_stale(tmp_path, capsys):
    """The source population is data, not declaration, and moves on its own.

    Holding an opaque hash over the examined file list made every added module
    block the gate, so a routine commit turned red. A file *leaving* is equally
    ordinary: its records are stale, reported, and dropped by an explicit prune.
    """
    write(tmp_path, "pkg/one.py", "import private_layer\n")
    cfg = config(tmp_path, RULE.format(extra='only = ["pkg/"]', until="2099-01-01"))
    _recorded(tmp_path, cfg, capsys)

    # A clean new module: the population grew, and nothing about the ratchet
    # changed. Under the old opaque scope hash this was a BLOCKED failure.
    write(tmp_path, "pkg/clean.py", "import os\n")
    assert main(["boundary", "-c", str(cfg)]) == 0

    (tmp_path / "pkg/one.py").unlink()
    assert main(["boundary", "-c", str(cfg)]) == 0
    out = capsys.readouterr().out
    assert "not examined now: pkg/one.py" in out


def test_prune_drops_records_whose_file_left_and_keeps_the_rest(tmp_path, capsys):
    write(tmp_path, "pkg/one.py", "import private_layer\n")
    write(tmp_path, "pkg/two.py", "import private_layer\n")
    cfg = config(tmp_path, RULE.format(extra='only = ["pkg/"]', until="2099-01-01"))
    sidecar = _recorded(tmp_path, cfg, capsys)
    before = json.loads(sidecar.read_text())
    assert len(before["findings"]) == 2

    (tmp_path / "pkg/one.py").unlink()
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--prune"]) == 0
    after = json.loads(sidecar.read_text())
    assert len(after["findings"]) == 1
    # Pruning drops findings that went away; it does not renew the decision.
    assert after["until"] == before["until"]
    assert after["rule"] == before["rule"]


def test_an_expired_ratchet_fails_only_its_own_rule(tmp_path, capsys):
    """A lapsed date is somebody's decision to renew, and it stops mattering."""
    write(tmp_path, "pkg/consumer.py", "import private_layer\n")
    cfg = config(tmp_path, RULE.format(extra="", until="2000-01-01"))
    _recorded(tmp_path, cfg, capsys)
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert "expired" in capsys.readouterr().err


def test_a_rule_that_examines_nothing_fails_and_cannot_be_recorded(tmp_path, capsys):
    """Zero violations is a clean rule; zero files examined is a rule that never ran."""
    write(tmp_path, "pkg/consumer.py", "pass\n")
    cfg = config(tmp_path, RULE.format(extra='only = ["nowhere/"]', until="2099-01-01"))
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert "VACUOUS" in capsys.readouterr().err
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--record"]) == 2
    assert not (tmp_path / ".kinemata/ratchets/private-layer.json").exists()


def test_unparseable_source_blocks_its_rule_rather_than_scanning_around_it(tmp_path, capsys):
    """A file the rule cannot read is a blocked rule, never a silently smaller one."""
    write(tmp_path, "pkg/consumer.py", "import private_layer\n")
    write(tmp_path, "pkg/broken.py", "def (:\n")
    cfg = config(tmp_path, RULE.format(extra='only = ["pkg/"]', until="2099-01-01"))
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert "BLOCKED" in capsys.readouterr().err
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--record"]) == 2
    assert not (tmp_path / ".kinemata/ratchets/private-layer.json").exists()


def test_boundary_refuses_a_config_that_declares_no_policy(tmp_path, capsys):
    """Running against nothing would be the answer that looks like success.

    The general "declares no check at all" refusal catches the empty config first;
    this is the case that reaches the command and names what it wanted.
    """
    empty = config(tmp_path, "[project]\nroot = \".\"\n")
    assert main(["boundary", "-c", str(empty)]) == 2
    cfg = config(tmp_path, """
        [project]
        root = "."
        [[count]]
        label = "a declared count nobody is running here"
        pattern = "def main"
        command = ["{python}", "-c", "print(0)"]
        extract = '(\\d+)'
        """)
    assert main(["boundary", "-c", str(cfg)]) == 2
    assert "no [[boundary]] declared" in capsys.readouterr().err


def test_a_writer_needs_its_owner_named(tmp_path, capsys):
    """A rule-owned artifact is never written by a run that has not picked one."""
    write(tmp_path, "pkg/consumer.py", "import private_layer\n")
    cfg = config(tmp_path, RULE.format(extra="", until="2099-01-01"))
    assert main(["boundary", "-c", str(cfg), "--record"]) == 2
    assert "--rule" in capsys.readouterr().err


def test_rule_owned_record_and_prune_never_touch_the_project_baseline(tmp_path, capsys):
    """A sidecar records one selected policy, not another gate's shared baseline."""
    write(tmp_path, "pkg/consumer.py", "import private_layer\n")
    baseline = write(tmp_path, ".kinemata-baseline.json", "the global baseline is not ours\n")
    cfg = config(tmp_path, """
        [[boundary]]
        name = "private-layer"
        kind = "imports"
        imports = ["private_layer"]
        [boundary.ratchet]
        until = "2099-01-01"

        [[boundary]]
        name = "other-layer"
        kind = "imports"
        imports = ["other_layer"]
        [boundary.ratchet]
        until = "2099-01-01"
        """)
    original = baseline.read_text()
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--record"]) == 0
    sidecar = tmp_path / ".kinemata/ratchets/private-layer.json"
    assert sidecar.is_file()
    assert baseline.read_text() == original
    # A selected writer does not inspect the other rule's absent sidecar.
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--prune"]) == 0
    write(tmp_path, "pkg/consumer.py", "pass\n")
    assert main(["boundary", "-c", str(cfg), "--rule", "private-layer", "--prune"]) == 0
    assert json.loads(sidecar.read_text())["findings"] == {}
    assert baseline.read_text() == original
    assert "Recorded" in capsys.readouterr().out


def test_full_run_inventories_orphans_and_writer_refuses_unjudged_scan(tmp_path, capsys):
    """A stale artifact or unknown receiver cannot become invisible accepted state."""
    write(tmp_path, "pkg/caller.py", "def save(path):\n    path.write_text('x')\n")
    cfg = config(tmp_path, """
        [[boundary]]
        name = "writes-home"
        kind = "calls"
        calls = ["pathlib.Path.write_text"]
        homes = ["pkg/writer.py"]
        [boundary.ratchet]
        until = "2099-01-01"
        """)
    assert main(["boundary", "-c", str(cfg), "--rule", "writes-home", "--record"]) == 2
    assert not (tmp_path / ".kinemata/ratchets/writes-home.json").exists()
    orphan = tmp_path / ".kinemata/ratchets/orphan.json"
    orphan.parent.mkdir(parents=True)
    orphan.write_text("{}\n")
    assert main(["boundary", "-c", str(cfg)]) == 1
    assert "ORPHANED" in capsys.readouterr().err
    assert inventory(tmp_path, load(cfg).boundaries)


def test_a_rule_reads_the_project_and_not_vendored_or_corpus_python(tmp_path):
    """Walking `rglob("*.py")` reported other people's imports as ours.

    An importing boundary with no `only` picked up `.venv/` and every gitignored
    corpus, and its coverage fingerprint moved whenever a vendored library did --
    so a data change under a dependency read as this rule's coverage narrowing,
    which is the opposite of what the lock is for.
    """
    write(tmp_path, "pkg/consumer.py", "import os\n")
    write(tmp_path, ".venv/lib/vendored.py", "import os\n")
    write(tmp_path, "corpus/other/peer.py", "import os\n")
    (tmp_path / ".gitignore").write_text(".venv/\ncorpus/\n")
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    settings = load(config(tmp_path, """
        [project]
        root = "."
        [[boundary]]
        name = "stdlib-off-limits"
        kind = "imports"
        imports = ["os"]
        """))
    found = survey(tmp_path, settings.boundaries[0], settings.exclude)
    assert found.files == ("pkg/consumer.py",)
    assert [str(item) for item in found.findings] == [
        "pkg/consumer.py:1: os  import 'os' is outside the declared surface"
    ]


def test_a_src_layout_package_is_named_as_it_is_imported(tmp_path):
    """The gate dogfooding this rule read green over a planted violation.

    Joining the path relative to the *project* root spelled every module in a
    `src/` layout as `src.pkg.mod`, so a rule naming `pkg.other` could not match
    the very import it forbids. This repository has that layout, so its own
    declared boundary was matching nothing while reporting "policy holds" —
    a green gate that had demonstrated nothing.
    """
    write(tmp_path, "src/pkg/__init__.py", "")
    write(tmp_path, "src/pkg/consumer.py", """
        from pkg import other
        from . import sibling
        from .deep import leaf
        """)
    write(tmp_path, "src/pkg/other.py", "")
    settings = load(config(tmp_path, """
        [[boundary]]
        name = "pkg-closed-world"
        kind = "imports"
        only = ["src/pkg/"]
        imports = ["pkg"]
        allow = ["pkg.consumer"]
        """))
    found = survey(tmp_path, settings.boundaries[0])
    assert [(item.subject, item.line) for item in found.findings] == [
        ("pkg.other", 1), ("pkg.sibling", 2), ("pkg.deep.leaf", 3),
    ]


def test_boundary_config_refuses_mixed_kind_keys_and_unusable_owner(tmp_path):
    """A policy that names an irrelevant key is configuration, not a no-op."""
    bad = config(tmp_path, """
        [[boundary]]
        name = "not a filename"
        kind = "imports"
        imports = ["pkg"]
        calls = ["os.remove"]
        """)
    try:
        load(bad)
    except Exception as exc:
        assert "name" in str(exc)
    else:  # pragma: no cover - the assertion above should always be reached
        raise AssertionError("malformed boundary loaded")
