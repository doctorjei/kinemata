# kinemata

Keeping agent-run software projects from going astray.

Agents on a codebase fail in recognizable ways: they get **overwhelmed with
context**, they **miss issues**, and they **duplicate code that already exists**.
This is scaffolding against those failures — declare a fact in one place, then
give agents a way to find it and a way to be caught re-deriving it.

**Status: early.** Everything below is built, tested, and validated against
labeled incidents from real project history rather than fixtures — including
the parts that failed validation, which are named as such. The method the whole
thing follows is `docs/structure.md`.

---

## The distinction everything hangs on

Every mechanism here is either a **reminder** or a **catch**, and they are not
interchangeable.

|  | Reminder | Catch |
|---|---|---|
| When | before and during the work | after, on the artifact |
| Needs the agent's cooperation | yes — it can be ignored | **no** |
| Fails against a rogue agent | yes | no |
| Fails as a prompt | no | yes — the work is already done |

> **The test, for any mechanism:** *could a rogue agent disable this?*
> If yes, it is a reminder. File it as one, and do not count it for the rogue case.

That makes the box/host boundary the trust boundary. `review` and `check` below
run identical analysis and differ only in exit code and where they run — the
difference is deliberate, because two mechanisms that could disagree eventually
will.

## When *not* to build a mechanism

Mechanism costs code, CI time, and rigidity. Spending it where a written norm
already works is waste, and a structure that over-mechanizes becomes brittle —
its own way of going astray.

Three factors decide:

1. **Incentive** — does an agent gain anything by violating? (less work, faster)
2. **Visibility** — is the violation apparent in the artifact, or does it hide?
3. **Failure** — loud, or silent?

> Trust a written norm where compliance is cheap, violation is visible, and
> nothing is gained by defecting. Spend mechanism where violation is cheap,
> invisible, or rewarded.

Agents being unpleasant to each other fails all three tests for needing
mechanism — a sentence handles it. Landing code without a coverage tag passes
all three. Only the second gets machinery.

---

## Registries

A **registry** is one declared place holding information used broadly across a
project's code, so that information has a single source of truth. What it
*holds* is the project's choice — settings keys, error codes, event types,
canonical helpers. This defines only what a data model must **do** to serve the
role.

One required method:

```python
entries() -> [Entry]     # Entry needs only: id, clauses
```

`declared()`, `resolve()` and `detect()` have defaults derived from it, which a
registry overrides only when the default is wrong for its data model.

Each entry may declare **antipatterns** — the spelling that means somebody
re-derived it instead of routing through it:

| Canonical thing | Spelling that means it was bypassed |
|---|---|
| `WORKSET_META_FILE = "workset.yaml"` | the literal `"workset.yaml"` |
| `run_or_die(...)` | an inlined `check=True` |
| `read_mode(dir, "vm")` | a hardcoded `mode = "vm"` |

**It does not detect that two pieces of code do the same job.** That is
semantic, and a mechanism claiming it would be lying about its reach. What it
does is force a fork: reuse the entry, or *declare* a new one. Reuse is the
outcome you want; declaring is visible in a diff, which is where a reviewer asks
the only question that matters — did this need to exist?

## Usage

```bash
pip install -e ".[dev]"
```

Declare your registries in `kinemata.toml`:

```toml
[project]
root = "."
exclude = ["tests/"]

# Values: antipatterns are derived from the constants themselves.
[[registry]]
name = "constants"
kind = "python-constants"
modules = ["src/pkg/constants.py"]

# Code: canonical helpers, declared by hand.
[[registry]]
name = "helpers"
kind = "code-patterns"

  [[registry.entry]]
  id = "run_or_die"
  antipatterns = ['check\s*=\s*True']
  home = ["pkg/_run.py"]
```

Then:

```bash
kinemata ids         # the projection: what already exists. Budgeted, loadable.
kinemata review      # advisory. Always exits 0. Run in-box, during the work.
kinemata undeclared  # advisory. Repeated text with no declared home.
kinemata check       # the gate. Exits 1 on a strong finding. Run in CI.
kinemata claims      # the gate, for documentation. Exits 1 on a dead claim.
kinemata baseline    # what the gate already accepts. --record to change it.
kinemata context     # the gate, for what a session loads. Exits 1 over the ceiling.
```

A registry that produces **no entries is refused, not accepted quietly** — a missing
module, an unknown kind, or an adapter that recognizes nothing in the source you
pointed it at. All three look identical to a clean tree from the outside. Set
`allow_empty = true` on a registry you are deliberately bootstrapping.

See `examples/ci-github-actions.yml` — including why a workflow file alone is
still a reminder, and what promotes it to a catch.

## Adopting it on a codebase that already fails

A gate that only works on an empty tree is a gate almost nobody can turn on. A
mature codebase declaring its constants for the first time gets a wall of
findings for code nobody is touching, and the rational response is to switch the
gate off. Measured: pointing `check` at one 65k-line project's settings package
produces **42 strong findings** on the first run.

So record them and fail on *increase*:

```bash
kinemata baseline --record   # accept today's findings; commit the file
kinemata check               # green, and still red for anything new
```

`check` then reports only findings the baseline does not cover, and prints the
size of the exemption list **on every run, including clean ones**. `review` is
deliberately unaffected — the ratchet governs the gate, not the advice.

**A baseline is an allowlist, and allowlists rot.** Three properties exist
against that, each one because the vaguer alternative fails quietly:

- **Fingerprints, not a total.** A recorded count of 42 is satisfied by any 42
  findings, so fixing one and adding another nets to silence.
- **Multiplicity is recorded.** Three identical sites in a file are three
  exemptions; the fourth is an increase.
- **Readable records.** Entry, antipattern, path and matched text — not opaque
  digests. A reviewer who cannot see what is exempted cannot catch a baseline
  absorbing real findings.

Findings that disappear become *stale* rather than errors — removing a bypass
must never fail a build — and `kinemata baseline --prune` drops them, which is
the half of a ratchet that is easy to forget.

**What identifies a finding across commits** is entry, antipattern, path and the
matched text, with whitespace collapsed. The line number is deliberately
excluded: every edit above a finding shifts it, and churn reported as
regressions trains people to re-record, which absorbs whatever else arrived in
that commit. The path is deliberately included: a bypass in a new file is a new
site, and this project's founding incident was a tripwire that watched one
module while eight sites sat in six others.

That choice was measured, not argued, on 200 commits of real history — a
baseline recorded at one commit, `check` run at four later ones:

| window | commits | files changed | reported new | attributable to keying on text |
|---|---|---|---|---|
| 50 commits | 50 | 159 | 0 | 0 |
| 100 commits | 100 | 217 | 3 | 0 |
| 150 commits | 150 | 302 | 4 | 0 |
| 200 commits | 200 | 344 | 8 | **1** |

The last column is the difference against a text-free fingerprint, which is what
keying on the matched text costs: **one report in 200 commits**, against a
57-finding baseline. Inspected, that one is a constant renamed in place — the
line really had changed, and the coarser fingerprint would have absorbed it
silently. The other reports are sites that did not exist before.

**Honest reach.** An agent can silence a real finding by re-recording the
baseline. What makes that survivable is that it is a committed file change,
visible in the diff and routed to review — the same status as any other declared
exemption. This is a catch with an escape hatch, and claiming otherwise would be
claiming reach it does not have.

## Budgeting what a session actually loads

`kinemata ids` bounds the registry's own projection, which is the smallest thing
an agent reads. The instruction layer — the harness file, a project's policy
documents, the docs a session is told to open — is unbounded, and that is where
*overwhelmed with context* actually lives.

The incident this was built from was measured, not imagined. One agent harness
assembles a set of policy documents into the instruction file it loads, on every
load — a build output, regenerated each session, not a source. Session-start
records of that output survive, so what was actually loaded is measured rather
than estimated:

| Date | Loaded |
|---|---|
| 2026-09-02 | 12,973 B (four records, identical) |
| 2026-09-05 | 21,357 B |
| 2026-09-06 | 22,800 B |

**Seventy-six percent in four days**, on a project that was itself building
mechanisms against context overwhelm, and nothing noticed. Growth hides because every
individual addition is defensible; only the total is a problem, and nobody was
looking at the total.

Those records are a sample, not a census — not every session left one — so the
series carries a direction and a rate rather than a starting size.

**This measures the sources and models the assembly**, which is the only form
that works: the assembled file exists only after the harness has run, on a
machine where it has run, so a check that read it could not run in CI, on a clean
clone, or before the growth it exists to catch has already landed. The sources
are what persist and what a commit changes.

```toml
[context]
include = ["bible/**/*.md", "handbook/**/*.md", "notebook/directives/*.md"]
budget = 25600
strip = ["html-comments"]
```

`kinemata context` weighs it and fails over the ceiling; `-v` lists the files
largest-first, which is the part that tells you where to cut.

**Globs, not filenames.** A document added to a loaded directory has to be
counted without anyone remembering to list it — a filename list is an allowlist
that silently omits whatever arrives next.

**Set the ceiling by measuring**, not by taste. There is deliberately no default:
a number nobody chose, enforced as though somebody had, is worse than no ceiling.
Measure, set it at what you already carry, then drive it down.

**`strip` models the harness's flattening**, because measuring files on disk
over-reports whatever the assembler removes — in one real corpus, HTML comment
blocks held the original packaged text of every document, **44%** of its bytes
and none of it ever loaded. Transforms are a declared table; an unknown one is
refused rather than ignored.

Three limits, since a checker that overstates its reach is the problem it is
trying to solve:

- **Bytes are not attention.** This bounds size, never relevance. Twelve
  kilobytes of irrelevant material is worse than twenty of necessary material,
  and no byte count can tell them apart.
- **It measures what you declare is loaded.** If the declaration drifts from what
  the harness reads, this measures the wrong thing precisely.
- **Getting the *set* right is the hard half, not the stripping.** One real
  assembler compiles its instruction file by walking a reference graph **and**
  stripping comment blocks, over only the documents it treats as critical.
  Checked against it by probing each source file's own lines for presence in the
  output: **23,287 B modeled against 23,786 B produced**, the 2.1% residue being
  the compiler's own title, contents table and section numbering. Note the
  direction — with the set right this *under*-counts, so a ceiling wants headroom.
  The first attempt at that figure swept whole directories, counted deferred
  material that never loads, missed a file that does, and reported the difference
  as an error rate. **A set you did not verify is not a measurement.**
- **"What a session loads" is a decision, not a property of the tree** — the
  sharpest limit here. Documentation worth bounding is usually built for
  *deferred* loading: an entry point of pointers, detail fetched when a task
  needs it. Most of a corpus may never reach a session, and which parts do can
  differ per session and per person. Declaring a set declares an *intent* — this
  is what we mean to load up front — and the check bounds that intent. It cannot
  see what an agent actually opened.

## Declaring which checks must run

Every mechanism here dies the same way: not by failing, but by quietly ceasing
to run. This project has watched it happen three times — a registry over the
wrong adapter that scanned for nothing and exited 0 for six commits, a
predecessor checker whose exclusion list grew until it called a dirty tree
clean, and two numbers stated in prose that no oracle covered and that were both
wrong when finally measured. **Green and inert are indistinguishable from
outside.**

So declare the checks that must run, and let the tool verify the files meant to
run them:

```toml
[[gate]]
command = "kinemata check"
note = "the tool against its own source"

[[gate]]
command = "pytest -q"
where = [".github/workflows/checks.yml"]   # default: every workflow
```

`kinemata claims` then reports `gates: 2 of 2 declared check(s) run in …` and
fails when one is absent. A step that is deleted fails it; so does a step
**commented out**, which is how a gate most plausibly dies — someone silences it
to unblock a merge and never restores it.

It rides on `claims` rather than being a command of its own on purpose. A check
that verifies other checks are wired up is worthless if nothing guarantees *it*
runs, and a fifth command would have created exactly that regress.

**What it does not see**, since a checker that overstates its reach is the
problem it is trying to solve: a step disabled by `if:`, a job nothing triggers,
or a command that runs and checks nothing. It verifies that the text is present
and uncommented. It does not parse YAML — the core takes no runtime
dependencies — and it cannot tell a live step from a decorative one. By the
test above it is a **reminder**: an agent can edit the declaration and the
workflow in one commit. What it converts is silent removal into *stated*
removal, visible in a diff.

`where` accepts any file, not only a workflow, so a project whose checks are run
by hand can at least declare that the instruction to run them still exists. That
is a reminder about a reminder, and worth what it sounds like.

The companion guard is a number with an oracle. This suite is **175 tests**, and
`kinemata claims` settles that figure against `pytest --collect-only`, so a
suite that silently shrinks fails the gate rather than passing faster.

## Precision

Naive matching is unusable. On a 65k-line codebase, deriving antipatterns from
constants produces **1,537** matches; three constants whose values are ordinary
domain words account for 1,054 of them. Two filters, both forced by measurement:

- **Strong vs weak.** A whole string literal equal to the value is *strong*; the
  value inside a longer literal is *weak* and often a different namespace that
  merely shares characters. **Only strong findings gate.** 1,537 → 314.
- **Frequency suppression.** An antipattern matching more sites than
  `max_sites` (default 20) is a domain word, not a duplication signal. 314 → 43.
  **Reported, never silent** — a check that quietly stops checking is worse than
  no check.

## Documentation is a registry of claims

A document asserts facts about the tree it ships with: this file exists, that
link resolves, this commit made the change. Each has a source of truth
elsewhere in the repo, which makes it falsifiable — and a falsifiable claim
nobody falsifies is how documentation rots while reporting itself correct.

```toml
[claims]
suffixes = [".md"]
historical = ["archives/"]   # a record of what was true is not a stale claim
```

`kinemata claims` gates, unlike `undeclared`: a missing file is a fact, not a
judgment. It prints the number of claims checked even when everything passes,
because "all resolve" and "nothing was looked at" otherwise read identically.

A claim it cannot settle is **named, not skipped** — run outside a git
repository, it reports that commit hashes went unchecked rather than passing
quietly.

A number in prose can be settled too, by a command you name. Opt-in, because
that means running something from a config file:

```toml
[[count]]
pattern = '\*\*(\d+) tests\*\*'
command = ["{python}", "-m", "pytest", "--collect-only", "-q"]
extract = '(\d+) tests collected'
```

A declared oracle that cannot run **fails**, rather than printing a note and
passing — in CI those are the same thing.

**Retired names and spelling conventions are registries, not special cases.**
Both are one shape: forbidden spellings with a preferred replacement. Kept in a
checker's source they go unmaintained; kept as data they are checked like
anything else.

```toml
[[registry]]
name = "retired"
kind = "substitutions"
suffixes = [".md"]           # per registry, so value registries stay off prose

  [registry.words]
  "oldName()" = "newName()"

[[registry]]
name = "spelling"
kind = "substitutions"
source = "docs/american-english.toml"   # dozens of pairs belong in a file
suffixes = [".md", ".py"]
```

These match as **prose**: comments and docstrings are exactly where a spelling
matters, so they are not stripped. Inline code spans are, because a document
recording that a word was corrected has to spell the word.

That is the ordinary machinery aimed at documentation. This project's own
design doc went on naming a method the code had already renamed, for three
commits, and a careful reader did not catch it; with the entry above, CI would
have failed on the first.

Note what happened when that entry was added: it fired on this README, which
had spelled the dead name while explaining the incident. Prose that *discusses*
a retirement is not a stale use of it. Either put the documents entitled to
record it in the entry's `home`, or say it without the name — but decide
deliberately, because an allowlist that grows to accommodate prose is how a
check quietly stops checking.

## Text with no declared home

Everything above needs the thing to be declared first. `undeclared` asks the
opposite question: what repeats with nothing declaring it? Three tiers, most
precise first — on a 65k-line codebase they report **6**, **111** and **222**.

- **composed** — a path built by spelling out a shorter path that also appears
  on its own: `Path("/etc/pkg/config.yaml")` here, `Path("/etc/pkg") / NAME`
  there. Equality would miss it; those two strings are not equal.
- **same text, several files** — byte-identical, and not something a registry
  already declares.
- **near-identical, already drifted** — compared as *skeletons*, so
  `f"Error: No {kind} named '{name}'"` and `f"Error: no instance named
  '{name}'"` land together. Two spellings of one message have already drifted,
  which is why this tier alone does not require two files.

**It never gates, by design.** Re-deriving a declared thing is a violation;
text repeating with no declared home is a *judgment* — the same words in two
places may be two ideas that coincide. So it reports the fork and leaves it.

## What it was validated against

Not synthetic fixtures. Labeled incidents from real project history, where a
commit message names the sites a human found by hand:

- **9/9 recall** reconstructing the tree before a documented cleanup commit.
- **3 real bypasses that the manual fix missed**, one still on `main`.
- On a second, unrelated codebase it initially found **nothing** — correctly
  diagnosing a missing adapter rather than a broken mechanism. With
  `code-patterns` it finds 6 live bypasses there.

`undeclared` was measured the same way, against two more labeled commits — and
its **first implementation scored 0/4**, because it compared literals for
equality and the incident's sites were composed paths that are not equal. A
second miss followed: the other incident's messages were f-strings, invisible
to a literal extractor, sitting in one file rather than two. Both misses were
found by running against history rather than fixtures, and both are now
regression tests. With the composed and skeleton tiers it scores **4/4** and
finds the message pair exactly.

And a failure worth publishing: `unused()` **failed** its validation, 0/3
against an incident recording three declared keys with "no reader at all". It
detects *mention*, not *use* — and every declared entry is mentioned somewhere,
because that is what declaring is. It is labeled known-weak in its own
docstring and requires excluding a project's declaring machinery to mean
anything.

## Known gaps

- `review` and `check` detect only **re-derivation of something already
  declared**. Against 37 attributable commits from a six-repository corpus,
  duplication with nothing declared appeared **13 times**, and `undeclared`
  reaches **4 of them**. The other nine are duplicated code blocks (a clone
  detector scored 0 on a labeled incident at any usable precision — the copies
  worth finding are the ones that have drifted, and drift removes the signal)
  and two implementations of one rule sharing no text, which nothing syntactic
  can see.
- **31% coverage of that gap, not the 62% a partial sample suggested.** The
  first 13 commits classified were the ones that looked most promising, and
  finishing the other 34 halved the figure.
- A CI workflow lives in the repo, so an agent can edit it. Branch protection
  with the job as a *required status check* is what makes it a catch.
- Validated on two codebases by one author. The categories held across both;
  they have not been tested against an unrelated project.

## Documentation

- `docs/structure.md` — the method: how to decide what mechanism to build, how
  to keep it from quietly rotting, and how to know whether it works. Applies
  beyond the mechanism shipped here.
- `docs/design.md` — the registry contract in full.

## License

GPL-3.0-only. See `LICENSE.md`.

Contributions involving generative AI tools: see `AIPOLICY.md`.
