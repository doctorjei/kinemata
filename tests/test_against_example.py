"""The contract against a real document it was not designed for.

``keyspace-manifest.yaml`` is kanibako's, supplied as an example. Nothing here
builds *to* its schema -- these tests exist to find out whether the contract
holds up against a real registry with heterogeneous sections, or whether it only
works on the shapes it was imagined against.

Skipped when the example is absent, so the suite still runs without it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

from kinemata import project, undeclared  # noqa: E402
from kinemata.adapters.mapping import MappingRegistry  # noqa: E402

MANIFEST = Path(__file__).resolve().parents[1] / "keyspace-manifest.yaml"
pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(), reason="example manifest not present"
)


@pytest.fixture(scope="module")
def manifest():
    return yaml.safe_load(MANIFEST.read_text())


@pytest.fixture(scope="module")
def keys(manifest):
    return MappingRegistry(
        manifest["keys"],
        name="keys",
        clause_field="spec",
        syntax=r"\b[a-z_]+(?:\.[a-z_<>*]+)+\b",
    )


def test_adapter_reads_every_key(keys, manifest):
    assert len(list(keys.entries())) == len(manifest["keys"]) == 99


def test_clause_linkage_survives_a_real_document(keys, manifest):
    # Every key in this manifest carries a spec reference; the contract should
    # surface all of them without knowing anything about the schema.
    linked = [e for e in keys.entries() if e.clauses]
    assert len(linked) == len(manifest["keys"])


def test_project_specific_fields_ride_along_untouched(keys):
    entry = next(e for e in keys.entries() if e.id == "config.data")
    assert entry.extra["type"] == "path"
    assert entry.extra["layer"] == 1


def test_detect_finds_declared_keys_in_a_line_of_source(keys):
    found = keys.detect("resolve('config.settings') or fall back to config.data")
    assert set(found) == {"config.settings", "config.data"}


def test_detect_is_not_fooled_by_a_longer_neighbour(keys):
    # config.data is declared; config.database is not. A substring match would
    # report the declared key and hide the undeclared one.
    assert keys.detect("config.database") == []


def test_real_projection_fits_a_16kb_budget(keys):
    p = project(keys)
    assert p.count == 99
    assert p.ok, [str(v) for v in p.violations]
    assert p.size < 16 * 1024


def test_heterogeneous_sections_do_not_break_the_adapter(manifest):
    # `pref` mixes dicts, strings, lists and a bool as records. A contract that
    # assumed uniform records would fall over here; this is the case that most
    # nearly did.
    pref = MappingRegistry(manifest["pref"], name="pref")
    entries = list(pref.entries())
    assert len(entries) == len(manifest["pref"])
    assert all(isinstance(e.extra, dict) for e in entries)


def test_not_keys_is_a_registry_too(manifest):
    # The manifest already tracks retired names. Same contract, different
    # meaning -- evidence the role generalizes past "settings keys".
    not_keys = MappingRegistry(manifest["not_keys"], name="not_keys")
    assert len(list(not_keys.entries())) == len(manifest["not_keys"])


def test_closure_finds_an_undeclared_identifier_in_realistic_text(keys):
    text = "cfg = get('config.settings'); tmp = get('config.scratchpad')"
    assert undeclared(keys, text) == ["config.scratchpad"]
