# kinemata for kanibako

**This directory exists only on the `kanibako` branch.** `main` is deliberately
free of it: *canon* is a kanibako concept, not a kinemata one, and the tool has
no business knowing the name of any particular harness's document system.

The intended end state is that this material moves to kanibako as a project,
once kanibako has the rest of what it needs. Until then it lives here so the
integration is not lost and so the measurements behind `kinemata context` stay
attached to the system they were taken from.

## What is here

| File | What it is |
|---|---|
| `integrations/kanibako/canon-kinemata.toml` | The config that checks a box's canon: spellings, retired names, documentation claims across the notebook and workbook, the declared gate list, and the `[context]` ceiling on what a session loads. |
| `integrations/kanibako/test_canon_corpus.py` | The stripper validated against a real canon rather than a fixture. Skipped when the corpus is absent. |

## Why canon needs its own config at all

Canon is documentation like any other: it asserts paths, cites commits, states
test counts, and uses a project's spellings. Those are claims about a tree, so
they get falsified rather than proofread. `resolve_in` lets notes resolve paths
in the repository next door; `commits_in` lets them cite corpus repositories
they were written against.

## What the context ceiling is actually bounding

The compiled canon is **graph traversal plus comment stripping**, over only the
canon considered critical, and both halves matter:

- `procedures/` is **deferred by design** and is not compiled in. Sweeping whole
  tomes counts material that never reaches a session — 2,122 B of it, when this
  was first configured wrongly.
- Each tome's `*_CONTENTS.md` is replaced by the compiler's own table.
- `COLLECTION.md` **is** compiled in, and the first configuration missed it.
- The `<!--[STOCK] ... -->` blocks hold each document's original packaged text,
  preserved for review and never loaded. In one canon that was 44% of the bytes.

Verified by probing each source file's own lines for presence in the compiled
output: 23,287 B modeled against 23,786 B produced. The 2.1% residue is the
compiler's generated scaffolding — its title, table and section numbering.

**The model under-counts once the set is right**, because the compiler adds
structure of its own, so the ceiling wants headroom rather than trusting the
total.

## The one thing worth building next

The compiled instruction file is the ground truth for *how heavy a session's
load is as a whole*, which is what canon gets refined against. It is a build
output — regenerated every load, never a source — so a check that reads it works
only where the harness has run. Both modes are wanted for different questions:

| Question | Read | Runs where |
|---|---|---|
| How heavy is a session's load? | the compiled file | only where the harness has run |
| Is the corpus growing? | source globs | CI, a clean clone, before assembly |

Only the second is built. Reading the first needs `[context] include` to accept
a path outside the project root, since `measure()` resolves globs under `root`
and `Path.glob` refuses a non-relative pattern.
