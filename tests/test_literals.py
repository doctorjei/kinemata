"""Undeclared repeated text: the reachable share of the greenfield gap.

The two incident-shaped tests here are the point of the file. Both come from
real history and both failed the first implementation -- see
``greenfield-gap.md``.
"""

from __future__ import annotations

import textwrap

from kinemata.literals import clusters


def write(tmp_path, rel, body):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(body).lstrip())
    return path


def values(entries):
    return {cluster.value for cluster in entries}


# -- the exact tier ----------------------------------------------------------


def test_the_same_text_in_two_files_is_reported(tmp_path):
    write(tmp_path, "a.py", 'msg = "could not reach the daemon"\n')
    write(tmp_path, "b.py", 'other = "could not reach the daemon"\n')
    found = clusters(tmp_path)
    assert values(found.strong) == {"could not reach the daemon"}


def test_text_repeated_inside_one_file_is_not_the_exact_tier(tmp_path):
    """One module repeating itself is usually a local idiom.

    The near tier deliberately does *not* share this rule; see the drift test.
    """
    write(tmp_path, "a.py", 'x = "could not reach the daemon"\ny = "could not reach the daemon"\n')
    assert clusters(tmp_path).strong == []


def test_a_declared_value_is_not_reported(tmp_path):
    """Already the bypass scan's business. Saying it twice in two voices is
    the failure this project is named after."""
    write(tmp_path, "a.py", 'msg = "could not reach the daemon"\n')
    write(tmp_path, "b.py", 'other = "could not reach the daemon"\n')
    found = clusters(tmp_path, declared=["could not reach the daemon"])
    assert found.strong == []


def test_single_word_and_short_text_are_not_clustered(tmp_path):
    write(tmp_path, "a.py", 'a = "workspace"\nb = "x/y"\n')
    write(tmp_path, "b.py", 'c = "workspace"\nd = "x/y"\n')
    assert clusters(tmp_path).strong == []


def test_text_in_too_many_files_is_suppressed_and_reported(tmp_path):
    for index in range(6):
        write(tmp_path, f"m{index}.py", 'enc = "utf 8 default encoding"\n')
    found = clusters(tmp_path, max_files=3)
    assert found.strong == []
    assert found.suppressed == [("utf 8 default encoding", 6)]


def test_a_type_annotation_is_not_repeated_text(tmp_path):
    """Forward references are quoted code, not values.

    Measured on kanibako-cli, annotations were the largest single source of
    false clusters.
    """
    body = '''
    def f(a: "Mapping[str, str]") -> "Mapping[str, str]":
        return a
    '''
    write(tmp_path, "a.py", body)
    write(tmp_path, "b.py", body)
    assert clusters(tmp_path).strong == []


# -- the incidents -----------------------------------------------------------


def test_a_composed_path_finds_the_path_it_was_built_from(tmp_path):
    """kanibako-cli 452f0451, which the exact tier missed 0/4.

    The sites were ``Path("/etc/kanibako/config_base.yaml")`` in one module and
    ``Path("/etc/kanibako") / BASELINE`` in another. No two of those strings are
    equal, so equality is the wrong test for this failure.
    """
    write(tmp_path, "config.py", 'p = Path("/etc/kanibako/config_base.yaml")\n')
    write(tmp_path, "baseline.py", 'd = Path("/etc/kanibako") / BASELINE\n')
    (cluster,) = clusters(tmp_path).composed
    assert cluster.value == "/etc/kanibako"
    assert "/etc/kanibako/config_base.yaml" in cluster.variants


def test_a_prefix_without_a_path_boundary_is_not_a_composition(tmp_path):
    """``/etc/kanibako-old`` extends the characters, not the path."""
    write(tmp_path, "a.py", 'p = "/etc/kanibako-old/thing.yaml"\n')
    write(tmp_path, "b.py", 'd = "/etc/kanibako"\n')
    assert clusters(tmp_path).composed == []


def test_two_spellings_of_one_message_are_reported_even_in_one_file(tmp_path):
    """kento-core e84b9504, which the first implementation missed twice over.

    The messages are f-strings, invisible to the literal extractor, and they sat
    28 lines apart in a single module -- so a distinct-file requirement misses
    them too. Two spellings have *already* drifted; that is the finding.
    """
    body = '''
    def a(namespace, name):
        print(f"Error: No {namespace} named '{name}'")

    def b(name):
        print(f"Error: no instance named '{name}'")
    '''
    write(tmp_path, "resolvers.py", body)
    (cluster,) = clusters(tmp_path).weak
    assert cluster.strength == "weak"
    assert len(cluster.variants) == 2
    assert all("named" in variant for variant in cluster.variants)


def test_unrelated_sentences_sharing_a_word_are_not_near_duplicates(tmp_path):
    body = '''
    def a(name):
        print(f"deleted the {name} workspace and its children")

    def b(name):
        print(f"refusing to mount {name} over an existing bind")
    '''
    write(tmp_path, "a.py", body)
    assert clusters(tmp_path).weak == []
