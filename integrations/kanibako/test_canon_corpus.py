"""The comment stripper, validated against a real canon rather than a fixture.

**This test exists only on the `kanibako` branch.** It depends on a canon
corpus, and canon is a kanibako concept; `main` carries the mechanism without
knowing the name of any harness's document system.
"""

from __future__ import annotations

import pytest

from kinemata.context import measure

CANON_CORPUS = "canon-files"


@pytest.mark.skipif(
    not (pytest.importorskip("pathlib").Path(__file__).resolve().parents[2]
         / CANON_CORPUS).exists(),
    reason="canon corpus not present",
)
def test_the_stripper_reproduces_a_measurement_taken_by_hand(request):
    """Validation against a recorded measurement rather than a fixture.

    A hand pass over one project's canon found HTML comments to be **46%** of
    its bytes -- an apparent 28 KB that was really 13 KB loaded. The corpus has
    moved since, so the assertion is a band rather than the figure: what is
    being checked is that the stripper still finds most of a document that is
    mostly comments, which a fixture written to pass could not tell us.
    """
    root = request.config.rootpath / CANON_CORPUS
    found = measure(root, ["**/*.md"], ceiling=10**9, strip=["html-comments"])
    assert found.raw > 20_000
    share = (found.raw - found.size) / found.raw
    assert 0.35 < share < 0.55, f"stripped {share:.0%}, expected roughly 44%"


