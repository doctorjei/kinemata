"""The ratchet over Catch A, and the scope that keeps three checks off each
other's records.

Closing a registry used to be a cliff rather than a ratchet. A project with one
pre-existing undeclared identifier could leave the registry open and read an
advisory list nobody reads, or close it and fail every build until the last
identifier was declared. That is the position the citation catch was in before
it was given the shared baseline, and the argument is the same one
`test_claims_ratchet.py` opens with: a gate that only works on a clean tree is
a gate almost nobody turns on.

The hazard specific to *this* subject is the scope. One file holds the
exemptions for every check here, deliberately -- two lists eventually disagree
about what a project accepted -- but no command runs every check. `check` reads
source and produces bypasses; this produces strays. Tag a stray with a bare
registry name and `check` matches none of them, calls every one
:attr:`~kinemata.baseline.Split.stale`, and points the reader at `--prune`: a
command that would then delete live exemptions on the strength of a scan that
never looked for them. The tests below pin that from both directions.
"""

from __future__ import annotations

import textwrap
from datetime import date

from kinemata.baseline import Baseline, record
from kinemata.bypass import Stray, is_strays_scope, strays_scope
from kinemata.cli import main
from kinemata.config import load

#: Far enough out that these tests are about fingerprints, not expiry.
LATER = date(2099, 1, 1)


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def cfg(project):
    return str(project / "kinemata.toml")


def declare(tmp_path, *, closed=True, source='NAME = "app.name"\n'):
    """A project whose keyspace can answer, with one identifier declared."""
    write(tmp_path, "keys.yaml", """
        keys:
          app.name:
            spec: "§1"
        """)
    write(tmp_path, "src/a.py", source)
    write(tmp_path, "kinemata.toml", f"""
        [project]
        root = "."

        [[registry]]
        name = "keyspace"
        kind = "yaml-mapping"
        source = "keys.yaml"
        section = "keys"
        clause_field = "spec"
        closed = {str(closed).lower()}
        syntax = '\\bapp\\.[a-z_]+'
        """)
    return tmp_path


def found(tmp_path):
    """Catch A's gating findings, as the commands assemble them."""
    from kinemata.cli import _gating_strays, _strays

    class Args:
        registry = None
        #: What argparse supplies for every command that reaches this, and the
        #: double did not until the scan learned to narrow to part of a tree.
        #: `None` is an unnarrowed run, which is what these tests are about.
        path = None

    settings = load(tmp_path / "kinemata.toml")
    return _gating_strays(_strays(Args(), settings, tmp_path))


# -- the adoption cycle -------------------------------------------------------


def test_a_closed_registry_fails_on_an_undeclared_identifier(tmp_path):
    """The catch itself, guarded so the ratchet cannot be mistaken for it."""
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    assert main(["undeclared", "-c", cfg(tmp_path)]) == 1


def test_recording_turns_a_failing_closed_registry_green(tmp_path, capsys):
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    assert main(["undeclared", "-c", cfg(tmp_path)]) == 1
    assert "app.legacy" in capsys.readouterr().out

    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()
    assert main(["undeclared", "-c", cfg(tmp_path)]) == 0


def test_an_accepted_stray_leaves_the_listing_and_is_counted_instead(
    tmp_path, capsys
):
    """A reader of this output is looking for what to fix.

    Mixing the exempt with the live would make them cross-reference the
    baseline to tell which is which, so accepted findings are counted in a
    trailing line and not listed among the live ones.
    """
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    write(tmp_path, "src/a.py", """
        NAME = "app.name"
        OLD = "app.legacy"
        NEW = "app.missing"
        """)
    assert main(["undeclared", "-c", cfg(tmp_path)]) == 1
    out = capsys.readouterr().out
    assert "app.missing" in out
    assert "app.legacy" not in out
    assert "1 undeclared identifier(s) accepted as pre-existing" in out


# -- the scope, which is the part that would have failed silently -------------


def test_check_reports_a_stray_record_as_unscanned_rather_than_stale(
    tmp_path, capsys
):
    """The defect a bare registry name would have introduced.

    `check` produces bypasses and never strays, so under a shared scope it
    would match none of these records, call them stale, and recommend a prune
    that deletes exemptions holding a *closed* registry green -- the gate
    nobody can reopen without editing the config.
    """
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    assert main(["check", "-c", cfg(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "undeclared:keyspace" in out
    assert "--prune" not in out


def test_claims_does_not_claim_a_stray_record_either(tmp_path, capsys):
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    # A documentation scope, so the command has something of its own to check.
    # Without one this config declares nothing `claims` looks at and is refused
    # at exit 2 -- which is a different behavior from the one under test here.
    with open(tmp_path / "kinemata.toml", "a") as handle:
        handle.write('\n[claims]\nsuffixes = [".md"]\n')
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    assert main(["claims", "-c", cfg(tmp_path)]) == 0
    assert "--prune" not in capsys.readouterr().out


def test_a_stray_scope_is_namespaced_per_registry(tmp_path):
    """Two closed registries do not share one bucket.

    The registry name travels with the finding for the reason `_strong` carries
    it: a reviewer reading the exemption file needs to know which closed world
    accepted an identifier, and two registries can fail to declare the same one.
    """
    assert strays_scope("keyspace") == "undeclared:keyspace"
    assert is_strays_scope("undeclared:keyspace")
    assert not is_strays_scope("keyspace")
    assert not is_strays_scope("claims")


# -- what counts as the same stray --------------------------------------------


def test_a_stray_that_moved_down_the_file_is_still_the_same_stray(tmp_path):
    """The churn case. Every edit above a finding shifts its line, and a
    ratchet that reported those as new would be re-recorded reflexively -- and
    a re-record absorbs whatever else arrived in that commit."""
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    before = record(tmp_path / "b.json", found(tmp_path), until=LATER)
    assert before.size == 1

    write(tmp_path, "src/a.py", """
        NAME = "app.name"

        # A comment that did not exist before.

        OLD = "app.legacy"
        """)
    assert before.split(found(tmp_path),
                        scope=[strays_scope("keyspace")]).new == ()


def test_the_same_identifier_in_another_file_is_a_new_stray(tmp_path):
    """The path is in the key deliberately. A catch scoped to one module is not
    a catch, and an undeclared identifier that spread to a second file
    spread."""
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    before = record(tmp_path / "b.json", found(tmp_path), until=LATER)

    write(tmp_path, "src/b.py", 'AGAIN = "app.legacy"\n')
    split = before.split(found(tmp_path), scope=[strays_scope("keyspace")])
    assert len(split.new) == 1
    assert split.new[0][0] == strays_scope("keyspace")


def test_rewriting_the_line_is_a_new_stray(tmp_path):
    """The boundary from the other side: a record does not outlive the line it
    was granted against."""
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    before = record(tmp_path / "b.json", found(tmp_path), until=LATER)

    write(tmp_path, "src/a.py", """
        NAME = "app.name"
        RENAMED_CONSTANT = "app.legacy"
        """)
    split = before.split(found(tmp_path), scope=[strays_scope("keyspace")])
    assert len(split.new) == 1
    assert len(split.stale) == 1


# -- what is deliberately not ratcheted ---------------------------------------


def test_an_open_registry_contributes_nothing_to_the_baseline(tmp_path):
    """An open registry advises and exits 0, so recording its findings would be
    an allowlist against a check that was never going to fail."""
    declare(tmp_path, closed=False,
            source='NAME = "app.name"\nOLD = "app.legacy"\n')
    assert found(tmp_path) == []
    assert main(["undeclared", "-c", cfg(tmp_path)]) == 0


def test_baseline_record_includes_strays(tmp_path):
    """The writing command runs every check that feeds the list.

    A source `--record` does not run is a set of records `--prune` then deletes
    in silence, and for this source the deletion re-fails a closed registry.
    """
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])

    loaded = Baseline.load(tmp_path / ".kinemata-baseline.json")
    assert [item.registry for item in loaded.accepted] == ["undeclared:keyspace"]
    assert loaded.accepted[0].entry_id == "app.legacy"


def test_a_pruned_stray_is_dropped_once_it_is_declared(tmp_path, capsys):
    declare(tmp_path, source='NAME = "app.name"\nOLD = "app.legacy"\n')
    main(["baseline", "-c", cfg(tmp_path), "--record", "--until", "2099-01-01"])
    capsys.readouterr()

    write(tmp_path, "src/a.py", 'NAME = "app.name"\n')
    main(["baseline", "-c", cfg(tmp_path), "--prune"])
    assert "Dropped 1 record(s)" in capsys.readouterr().out


# -- the record a human reads -------------------------------------------------


def test_a_stray_record_does_not_claim_something_was_bypassed(tmp_path):
    """"bypasses" is the wrong verb for a stray -- nothing was bypassed, the
    identifier is declared nowhere -- and the one reader who should not have to
    translate is the one auditing an exemption list."""
    stray = Stray(path="src/a.py", line=2, identifier="app.legacy",
                  text='OLD = "app.legacy"')
    accepted = record(
        tmp_path / "b.json", [(strays_scope("keyspace"), stray.finding())],
        until=LATER,
    ).accepted[0]
    rendered = str(accepted)
    assert "app.legacy declared by nothing" in rendered
    assert "bypasses" not in rendered


def test_a_strays_fingerprint_keeps_the_line_text(tmp_path):
    """Keyed on the identifier alone, every use in a file would collapse into
    one record and the fourth would stop being an increase. `Claim` learned the
    same lesson from an empty fingerprint."""
    stray = Stray(path="src/a.py", line=2, identifier="app.legacy",
                  text='OLD = "app.legacy"')
    assert 'OLD = "app.legacy"' in stray.finding().text
