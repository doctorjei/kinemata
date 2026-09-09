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
kinemata init          # a starting config; --ci also writes a workflow and
                       # declares it as a gate. Refuses to overwrite either.
```

What `init` writes runs immediately, because it declares `[claims]` and nothing
else: **a config does not need a registry.** It needs at least one check —
`[[registry]]`, `[[count]]`, `[[gate]]`, `[claims]` or `[context]` — and a config
that declares none of them is refused, because every command it configures would
pass by doing nothing. A registry-shaped command run against a config with no
registry refuses too, rather than scanning nothing and exiting 0.

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
kinemata clusters    # advisory. Repeated text with no declared home.
kinemata undeclared  # the closed-world catch. Exits 1 on an identifier a
                     # closed registry does not declare; advisory while open.
kinemata unused      # advisory. Declared entries nothing mentions. Refuses
                     # unless something says where a declaration lives.
kinemata check       # the gate. Exits 1 on a strong finding. Run in CI.
kinemata claims      # the gate, for documentation. Exits 1 on a dead claim.
kinemata baseline    # what the gate already accepts. --record to change it.
kinemata context     # the gate, for what a session loads. Exits 1 over the ceiling.
kinemata init        # a starting config, and optionally the CI to run it.
```

A config found by walking **up** from the working directory says so on stderr.
The walk is convenience in one place and a leak in another — a role meant to see
one subtree picks up its parent's config and everything that config points at —
and the announcement is what makes the inherited case visible without narrowing
the walk for trees that are not repositories.

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
kinemata baseline --record --until 2026-12-01 --by "Jei" \
                  --note "pre-existing at adoption"
kinemata check               # green, and still red for anything new
```

**`--until` is required.** A baseline is an allowlist, and one that cannot lapse
is a decision nobody revisits — the same rule a promise follows, applied to the
mechanism that admits to being an allowlist in the next paragraph. On that date
`check` fails with nothing new, saying so: the exemptions are still in force and
nobody has looked at them since the day somebody said they would. Extend it
deliberately, or drive the list down. A note must be signed.

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

The companion guard is a number with an oracle. This suite is **237 tests**, and
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

## What the scan walks

Every check here walks the tree the same way, so a defect in the walk is a
defect in all of them. It **follows symlinked directories**, because
`Path.rglob` does not: measured on a real tree, 0 files through a link against
**130** on the real path, which meant a project whose source is reached that way
scanned as empty and passed every gate by being invisible.

Two consequences, both deliberate:

- **A link is followed once.** A cycle is not hypothetical — `os.walk` and
  `glob` both expand a self-referential link about forty deep before the
  operating system refuses, reporting three files 120 times. Directories are
  keyed on their real identity, which also collapses two links to one tree.
- **A link out of the project is announced**, on stderr, and `--quiet` does not
  suppress it: that is the scope of the check, not one of its findings. The
  root you point at is otherwise read as the bound on what was scanned, and
  here it is not one.

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

`kinemata claims` gates, unlike `clusters`: a missing file is a fact, not a
judgment. It prints the number of claims checked even when everything passes,
because "all resolve" and "nothing was looked at" otherwise read identically.

A claim it cannot settle is **named, not skipped** — run outside a git
repository, it reports that commit hashes went unchecked rather than passing
quietly.

### Paths a design has not built yet

Point this at a design document and it prints six errors. It prints them again
tomorrow, and next month, because the document mentions
`example/clause-index.json` and nobody will build that file until Phase 1. After the third run you stop reading
the output. Then somebody mistypes a path in the document, and that error prints
as a seventh line in a block you have trained yourself to skip.

So write down the names that do not exist yet, and the date each one stops being
excused:

```toml
[[promise]]
path = "example/clause-index.json"
until = "2026-12-01"
note = "Phase 1 output; deferred by the design review"
by = "Jei"
```

Now the run is clean, and the day someone mistypes a path it is the only line on
the screen. The claim is still counted — held open, not skipped.

**Three things end a promise, and all three fail the gate.** It exists now:

```
FAIL: 1 promised path(s) now exist and are still declared.
  KEPT: example/clause-index.json exists now -- remove the promise
```

Nothing cites it any more — usually a rename, where the new name fails loudly as
a dead claim while the old entry sits there protecting nothing:

```
  UNCITED: example/clause-index.json is promised, and no document names it
```

Or the date has passed:

```
  LAPSED: example/clause-index.json (deferred until 2026-12-01) -- decide again:
          extend the date, or drop the promise and let what it covered come back
```

That is the difference between this and an ignore list. You deal with the entry
because the gate makes you, instead of leaving it there forever.

**`until` is required and nothing means "never".** A deferral that cannot lapse
is an ignore list with a better name: if the work is canceled, or just never
starts, the document goes on naming a file nobody will build and nothing is ever
red again. It is **not a delivery date** — it is when somebody looks at this
again. If the work is not ripe, move the date; that edit is a decision in a
commit, which is the entire point.

### Deferring something that is not a path

Every deferral in a project has the same shape, and most of them are not files:
a question left open, a threshold nobody has measured yet, a finding reviewed
and set aside. A tool that dates only the deferrals it can see for itself leaves
the rest as good intentions in prose. So a promise may name a `what` instead:

```toml
[[promise]]
what = "whether the note cap needs a number before Phase 2"
until = "2027-03-08"
note = "measured distribution first; a guessed cap is a number nobody chose"
by = "Jei"
```

Nothing in the tree can answer for that one, so the date is the whole mechanism —
which is why `until` is required on both kinds rather than only where nothing
else can check.

**A note must be signed.** `by` is required whenever there is a `note`, because
an unsigned reason is a reason with nobody behind it, and the person deciding
whether a deferral still holds needs to know whose call it was. A deferral is
somebody's decision or it is drift.

Two smaller decisions, both to stop the list becoming junk. The names are
**declared, not guessed from the prose** — reading English for future tense is
what once made this checker skip whole lines that carried real claims. And a
name matches **exactly**: a promise of `example/plan.md` that also covered every
other file of that name would hide claims nobody chose to defer.

(The real figures behind this: one design set, 6 of its 52 claims were this
class.)

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

**One oracle, several numbers.** `[[count]]` binds one command to one figure and
TOML cannot share a value, so a real integration ended up with eight inline
programs of which only four were distinct — the duplication this package exists
to report, forced by its own config format, and invisible to `check` because a
config is not source. Name the command once instead:

```toml
[command]
lines = ["wc", "-l"]

[[count]]
pattern = 'the brief is \*\*(\d+) lines\*\*'
run = "lines"
args = ["docs/brief.md"]
extract = '(\d+)'
```

`run` against a name no `[command]` declares raises, and so does a count giving
both `command` and `run` — two answers to one question is not a decision.

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

**A list of retired identifiers is a different job, and needs `boundary =
"identifier"`.** Two things go wrong otherwise, both measured on a real clause-ID
scheme:

- A retired `spec~box-vault` matches inside the live `spec~box-vault-enable`,
  because `-` supplies a word boundary. The report names the very site that
  proves the rename happened, and reads exactly like a real surviving
  reference. Hyphenated families are the natural way to name related things, so
  a project hits this at its first such rename.
- Identifiers are written in backticks, and prose mode blanks code spans — so
  the registry reports clean over documents that carry the retired name. That
  is not hypothetical: switching one real config to `identifier` turned a clean
  run into a finding on the first document it scanned.

```toml
[[registry]]
name = "retired"
kind = "substitutions"
suffixes = [".md"]
case_sensitive = true        # identifiers, where case carries meaning
boundary = "identifier"      # bounded by [A-Za-z0-9_.-], and code spans are read
```

The cost is stated rather than discovered later: a document narrating the rename
— "`old` is now `new`" — now reports the old name. That is what `exclude`,
`historical` and the baseline are for. A legitimate mention gets declared, not
guessed at.

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

Everything above needs the thing to be declared first. `clusters` asks the
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

`clusters` was measured the same way, against two more labeled commits — and
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
because that is what declaring is. Naming a project's declaring machinery is
what makes it mean anything, and for the life of the project that was
documented as required while the signature defaulted it to empty: the measured
0/3 configuration was what asking for nothing gave you. **That configuration
now raises**, the machinery is declared data (`machinery` on a registry), and
`kinemata unused` reaches it. Still a review list, never a cut list.

## Known gaps

- `review` and `check` detect only **re-derivation of something already
  declared**. Against 37 attributable commits from a six-repository corpus,
  duplication with nothing declared appeared **13 times**, and `clusters`
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

- `docs/introduction.md` — the whole tool on a few pages: every command, every
  config key, what each refusal is, and the measured results including the
  components that failed. Start here if you want the shape before the argument.
- `docs/structure.md` — the method: how to decide what mechanism to build, how
  to keep it from quietly rotting, and how to know whether it works. Applies
  beyond the mechanism shipped here.
- `docs/design.md` — the registry contract in full.

## License

GPL-3.0-only. See `LICENSE.md`.

Contributions involving generative AI tools: see `AIPOLICY.md`.
