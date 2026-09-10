# kinemata

**Definition:** a lint-class tool that enforces *one declared place per fact*. It finds code
that re-derives information a registry already declares, and gates on it.

**Scope:** syntactic. It does not detect that two pieces of code do the same job.

---

## Requirements

| Item | Value |
|---|---|
| Python | ≥ 3.11 (`tomllib`) |
| Runtime dependencies | none in the core |
| Optional | `PyYAML>=6` — required only by `kind = "yaml-mapping"` |
| Config file | `kinemata.toml`, discovered upward from CWD; `-c` overrides |
| Baseline file | declared as `BASELINE_NAME` in `baseline.py`; `[project] baseline` overrides |

```bash
pip install -e ".[dev]"
```

---

## Core model

**Registry:** one declared place holding information used broadly across a project. Contents
are the project's choice — settings keys, error codes, event types, canonical helpers.

**Contract — one required method:**

```python
entries() -> Iterable[Entry]
```

`declared()`, `resolve()` and `detect()` have defaults derived from `entries()`. Override only
when the default is wrong for the data model.

**`Entry` fields:**

| Field | Type | Meaning |
|---|---|---|
| `id` | `str` | the declared identifier |
| `clauses` | `tuple[str, ...]` | text projected to agents |
| `antipatterns` | `tuple[str, ...]` | regexes whose match means the entry was bypassed |
| `home` | `tuple[str, ...]` | path fragments where the entry is defined; matches there are canonical use, not duplication |
| `extra` | `Mapping[str, Any]` | project payload, never interpreted |

**Antipattern examples:**

| Canonical thing | Spelling that means it was bypassed |
|---|---|
| `WORKSET_META_FILE = "workset.yaml"` | the literal `"workset.yaml"` |
| `run_or_die(...)` | an inlined `check=True` |
| `read_mode(dir, "vm")` | a hardcoded `mode = "vm"` |

**Effect:** a bypass forces a fork — reuse the entry, or *declare* a new one. Declaring is
visible in a diff.

---

## Configuration

```toml
[project]
root = "."
exclude = ["tests/", "build/"]     # gitignored paths are added automatically

# Values: antipatterns derived from the constants themselves.
[[registry]]
name = "constants"
kind = "python-constants"
modules = ["src/pkg/constants.py"]

# Code shapes: canonical helpers, declared by hand.
[[registry]]
name = "helpers"
kind = "code-patterns"

  [[registry.entry]]
  id = "run_or_die"
  antipatterns = ['check\s*=\s*True']
  home = ["pkg/_run.py"]

# Forbidden spellings (retired names, dialect) as declared data.
[[registry]]
name = "retired"
kind = "substitutions"
suffixes = [".md"]
case_sensitive = true
  [registry.words]
  oldname = "newname"

# Where the sources this project cites actually live. A citation carries a stamp
# and a reference key; the entry carries the volatile half.
[[registry]]
name = "sources"
kind = "bibliography"
source = "docs/bibliography.toml"   # [[entry]] tables: key, target, note

# How long a citation target can be and still read comfortably beside its key.
# Reported by `kinemata cite -v`, never enforced.
[citations]
accompany_max = 50

# Documentation claims.
[claims]
suffixes = [".md"]
historical = ["archives/"]         # records that cite what was true when written
external = true                    # check cited URLs; off by default, and the
                                   # number skipped is printed when it is off

# Something deferred, and the date the deferral lapses. `path` for a file the
# project will produce; `what` for anything else. `until` is required on both.
[[promise]]
path = "out/report.json"
until = "2026-12-01"
note = "Phase 1 output"            # a note must be signed
by = "Jei"

# A value in prose, and the command that settles it. A number is one kind of
# value; there is no second table for the others.
[[count]]
label = "test count"
pattern = '\*\*(\d+) tests?\*\*'
command = ["{python}", "-m", "pytest", "--collect-only", "-q"]
extract = '(\d+) tests collected'

# One oracle, several values: declare it once and name it.
[command]
lines = ["wc", "-l"]

[[count]]
label = "brief length"
pattern = 'the brief is \*\*(\d+) lines\*\*'
run = "lines"
args = ["docs/brief.md"]
extract = '(\d+)'

# Checks that must run, and the file that must run them.
[[gate]]
command = "pytest -q"
where = [".github/workflows/checks.yml"]   # default: every workflow

# Ceiling on what a session loads.
[context]
include = ["docs/**/*.md"]
budget = 24064
strip = ["html-comments"]
```

**Adapters (`kind`):**

| `kind` | Entries come from | Antipatterns |
|---|---|---|
| `python-constants` | module-level constants in named `modules` | derived from the values |
| `yaml-mapping` | a YAML mapping file (`source`) | derived from the values |
| `code-patterns` | hand-declared `[[registry.entry]]` tables | declared |
| `substitutions` | `[registry.words]` or an external `source` TOML | the forbidden spelling |
| `bibliography` | `[[entry]]` tables in an external `source` TOML | none — a citation *accompanies* its target by default, so a target spelled beside its key is the readable half of a declared citation rather than a re-derivation of it |
| `import` | a registry class the project wrote, named as `target = "module:Class"` | whatever that class declares |

**`import` is the extension point**, and the list above is not the boundary of what a registry can
be. A project whose data model no built-in adapter fits writes the adapter itself — most usefully
the `declared()` override, for a keyspace that is closed but not flat and whose membership only
the project can answer — and names it from `kinemata.toml`:

```toml
[[registry]]
name = "keyspace"
kind = "import"
target = "mypkg.registries:KeyspaceRegistry"
sections = ["core", "vault"]     # any further key goes to the class as a keyword argument
```

The target is explicit: one module, one attribute in it, no discovery. The class must be
importable by the interpreter running kinemata — nothing is added to `sys.path` on the project's
behalf, because a config able to inject import paths could shadow a stdlib module from a line of
TOML. Subclass `kinemata.contract.BaseRegistry` and everything but `entries()` is derived.

⚑ **This makes the config name code that gets executed.** That line was already crossed by
`[[count]]`, whose oracles are shell commands run through `subprocess`. kinemata still reads the
code it *checks* with `ast` and never executes it; the count oracle and a named adapter are the
two exceptions, both explicit in the config file.

A config needs **at least one check** — a registry, a count, a gate, `[claims]` or `[context]` —
and is refused if it declares none. It does **not** need a registry: `claims` and `context` run
on a config that declares no registry at all, and a registry-shaped command refuses rather than
scanning nothing.

**Per-registry options:** `suffixes`, `case_sensitive`, `match_mode`, `allow_empty`, `source`,
`modules`, `closed`, `machinery`, on `substitutions` — `boundary`, on `bibliography` —
`interpreted` and `standardized`, which **add to** the reserved type vocabulary rather than
replacing it, and on `import` — `target`, plus anything else the project's class takes. A closed
built-in set with no extension point is a defect this project has already shipped twice: once in
that type vocabulary, and once as `BUILDERS` itself.

On an `import` registry the loader keeps `name`, `kind`, `target`, `suffixes`, `machinery` and
`allow_empty` for itself and hands **every other key** to the class. `name` is the one option
that behaves differently there: given, it wins as it does everywhere; omitted, the class keeps
the name it declares for itself rather than being renamed to a default nobody wrote.

**`machinery`** names the files that *declare* a registry's entries rather than use them — a key
table, an inventory, the manifest. Only `unused` reads it, and only it or an entry `home`
satisfies that command: a project's `exclude` names build and test trees, is non-empty
everywhere, and accepting it as the answer would let the requirement pass while meaning nothing.

**Boundaries** (`substitutions` only): `prose` bounds a spelling with `\b`, which is right for a
word list and wrong for a name list; `identifier` bounds it with the class `contract` declares,
and reads code spans instead of blanking them. A retired `spec~box-vault` bounded as prose
matches inside the live `spec~box-vault-enable`.

**Match modes** (`match_mode`, selects a filter table):

| Mode | Applies to | Behavior |
|---|---|---|
| `strings` | default | string literals only |
| `code` | source | code with prose filtered |
| `prose` | `.md` | inline code spans exempt; fenced blocks **not** exempt |
| `raw` | anything | no filtering at all |

---

## Commands

| Command | Role | Exit 1 when |
|---|---|---|
| `kinemata init` | writes a starter config; `--ci` writes a workflow and declares it as a gate | the file it would write already exists |
| `kinemata ids` | the projection — what already exists, budgeted | over budget **and** `--strict` |
| `kinemata review` | advisory scan; frequency suppression | never |
| `kinemata clusters` | repeated text with no declared home | never |
| `kinemata undeclared` | the closed-world catch — an identifier a `closed` registry does not declare | a stray under a closed registry; refuses outright if no registry can recognize its own identifiers |
| `kinemata unused` | declared entries nothing mentions outside the files declaring them | never; refuses outright if no registry can say (needs `machinery` or entry `home`) |
| `kinemata check` | the gate | a strong finding not covered by the baseline, or a baseline past its `until` |
| `kinemata claims` | documentation gate; also verifies `[[gate]]` declarations | a dead claim, or a declared gate that does not run |
| `kinemata context` | session-load gate | measured bytes exceed `budget` |
| `kinemata baseline` | shows accepted findings; `--record --until`, `--prune` | — |
| `kinemata stamp` | mints a citation stamp, or decodes one; reads no config | the text given is not a stamp |
| `kinemata cite` | resolves a reference key — forward to its source, `--where` to every `file:line` citing it, bare for every key with its count | the key is malformed, or no entry declares it |

**Common flags:** `-c/--config`, `-r/--registry`, `-q/--quiet`, `-v/--verbose`, `--max-sites`.
Each is accepted **on either side of the subcommand** — `kinemata -c x.toml check` and
`kinemata check -c x.toml` are the same command, and given both, the later one wins.

**Defaults:** projection budget `16384` B. Frequency suppression at `20` sites per
(entry, antipattern).

**Constant values are matched in three tiers**, by length:

| Value length | Matched | Why |
|---|---|---|
| ≥ `min_length` (4) | anywhere in a literal | long enough that a substring match means something |
| 3 | **only as a whole literal** | `GET` inside `TARGET` is noise; a literal that *is* `GET` is not |
| ≤ 2, or generic | not at all | two characters collide across namespaces even anchored |

The middle tier exists because httpie declares `HTTP_GET` and `HTTP_POST` on adjacent lines, a
lexer writes both as literals two lines apart, and only POST was reported. The floor below it is
measured, not chosen: at 2, one 65k-line project's settings package went from 14 findings to 31,
and all seventeen were `RW_PATH = "rw"` matching an unrelated mount-binding key.

`review` and `check` print how many declared entries carry **no** antipattern, because an entry
nothing can be reported about otherwise reads as an entry being watched.

---

## Refusal semantics

A misconfigured check raises rather than passing. Green and inert are indistinguishable from
outside, so the following are `ConfigError`, not silent skips:

- a registry producing **zero entries** — an adapter that recognizes nothing at the path given.
  Recorded at load and raised by the commands that would scan (`review`, `check`, `ids`,
  `undeclared`, `unused`); `claims` and `context` run and report it, because a project whose
  data model no adapter fits should still get its documentation checked. `allow_empty = true`
  to bootstrap deliberately
- a missing module, or an unknown `kind` — raised at load, because those are typos rather than a
  statement that the adapter does not fit
- `[context]` missing `include` or `budget` — there is **no default ceiling**
- `[context] strip` naming an unknown transform
- `[[gate]]` with no `command`
- a registry that cannot recognize its own identifiers cannot be `closed`
- a config declaring **no check at all** — every command it configures would pass by doing nothing
- a `[[promise]]` with no `until`, an unparseable date, or a `note` with no `by`
- a `[[count]]` naming a `run` no `[command]` declares, or giving both `command` and `run`
- an unknown `boundary` on a `substitutions` registry
- a baseline with no `until`, or `--record` without one — and an unsigned `--note`
- a `bibliography` whose source is missing, declares no entries, misspells a field or a table,
  or holds a key of the wrong width. Two spellings of one key is the re-derivation this project
  exists to catch, so a short number is refused rather than padded
- a reference key declared **twice anywhere in the project** — the key space is project-wide, not
  per file, so one key resolving to two sources is refused across every bibliography at once
- a `bibliography` entry naming a type code nothing declares, and a project redefining an
  **interpreted** code (`Wb`, `Pa`, `Cm`), whose meaning a check acts on. Redefining a
  **standardized** code is a warning instead: the tool never reads those, so refusing would
  enforce a convention it cannot act on
- `[citations] accompany_max` that is not a length in characters
- an `import` registry whose `target` is malformed, names a module that will not import, names an
  attribute the module does not define, resolves to something that is not a class, or resolves to
  a class whose instances do not satisfy the `Registry` protocol — the refusal names the members
  it lacks, the target, and the config file that declared it, because a traceback from inside
  somebody else's package is not a usable error message
- an `import` registry declaring a key its class will not accept. Swallowing the `TypeError`
  would build the adapter's default instead, which is a misspelled parameter staying green
  forever

Suppression is reported, never silent: `check` prints the exemption count on every run,
including clean ones, and `-q` does not suppress it.

---

## Adoption on a codebase that already fails

Measured first-run cost on one 65k-line project's settings package: **42 strong findings**.

```bash
kinemata baseline --record --until 2026-12-01 --by "Jei"   # accept today's
kinemata check               # green, and still red for anything new
kinemata baseline --prune    # drop findings that no longer exist; keeps the date
```

`--until` is required and has no default: on that date `check` fails with nothing
new, because the exemptions are still in force and nobody has revisited them. A
baseline carrying no date at all is refused rather than honored.

**Fingerprint:** entry + antipattern + path + matched text, whitespace-collapsed, with
multiplicity counted. Line numbers are excluded; path is included.

**Cost of keying on text**, measured over 200 commits against a 57-finding baseline:

| Window | Commits | Files changed | Reported new | Attributable to text keying |
|---|---|---|---|---|
| 50 | 50 | 159 | 0 | 0 |
| 100 | 100 | 217 | 3 | 0 |
| 150 | 150 | 302 | 4 | 0 |
| 200 | 200 | 344 | 8 | **1** |

`review` is unaffected by the baseline: the ratchet governs the gate, not the advice.

---

## The documentation gates

**`claims`** treats documentation as a registry of falsifiable assertions.

| Claim kind | Settled against |
|---|---|
| `path` | the filesystem |
| `link` | link targets |
| `commit` | `git cat-file` (skipped, and reported as skipped, outside a repository) |
| `url` | the web, **opt-in** via `external = true`. `404`/`410` fails; anything ambiguous — a timeout, a 5xx, a `403` from a bot-hostile host — is reported by name and never fails |
| `[[count]]` | the declared oracle command's output |
| `[[gate]]` | the text of the file declared in `where` |

**`[[count]]` settles a value, of which a number is one kind.** It is the one positive check
here: everywhere else a second spelling is the finding, while this one fails when the document
and the oracle *disagree*. The comparison is exact — edge whitespace is stripped from both
sides and nothing else is touched. Nothing is converted, coerced or rounded, so a document
saying "16 KB" is not settled by an oracle that emits the byte count; a project wanting both
spellings checked declares two entries, each with its own `pattern` and `extract`. That limit
is deliberate: a wrong normalization does not fail, it passes.

Negation is parsed: a claim inside a negated clause is a mention, not an assertion. Clause
boundaries are `;:`, `but`, `however`, `whereas`, `while` — commas deliberately excluded.

**Gate verification** rides on `claims` rather than being its own command: a check that
verifies other checks are wired up is worthless if nothing guarantees it runs. It fires on a
deleted step **and** on a commented-out one.

**`context`** models what a session loads: resolve `include` globs, apply declared `strip`
transforms, sum bytes, compare to `budget`. `-v` lists files largest-first.

---

## Measured results

| Subject | Result |
|---|---|
| Bypass recall, labeled incident in the corpus (tree reconstructed at the parent commit) | **9/9** |
| Bypasses the incident's manual fix missed | **3** (one still live on `main`) |
| Precision, same run | 1,537 raw → 314 strong/weak → **43** after frequency suppression |
| Second corpus, before `code-patterns` adapter | **0 findings** — a missing adapter, not a broken mechanism |
| Second corpus, after | 6 live bypasses |
| `clusters`, first validation | **0/4** (compared literals for equality; the sites were composed paths) |
| `clusters`, after containment tier + f-string skeletons | **4/4**; precision 174 → 154 → 101 on a 65k-line tree |
| `context` model vs. the artifact a harness actually loaded | over by **7.7%**, in the safe direction |
| Clone detection | **0 recall** at 187 findings — built, measured, **not shipped** |
| `unused()` | **failed 0/3.** Detects mention, not use; the failing configuration now refuses |

---

## Known limits

- **Semantic duplication is out of reach by design.** Rules enforced twice in dissimilar code
  are not detectable syntactically.
- **Greenfield coverage: 4 of 13 instances** across 37 attributable commits (31%). Split:
  5 literal / 4 code / 4 semantic.
- **Drift defeats shape matching.** The copies worth catching are the drifted ones; drift
  removes the signal. This is why clone detection was not shipped.
- **`unused()` detects mention, not use.** Every declared entry is mentioned by construction, so
  it needs `machinery` or an entry `home` to mean anything and refuses without either. Review
  list, never a cut list — and it does not apply at all to a registry whose entries are declared
  to be *absent*, which it says rather than answering.
- **A baseline is an allowlist.** An agent can silence a finding by re-recording it. What makes
  that survivable is that it is a committed file change, visible in review.
- **`[[gate]]` verifies text presence, not execution.** Blind to a step disabled by `if:`, a
  job nothing triggers, or a command that runs and checks nothing. It does not parse YAML.
- **`context` bounds bytes, not attention.** It measures what you *declare* is loaded; the
  flattening is a model of a harness, not the harness.
- **A CI workflow in the repository is editable by the agent it constrains.** Branch protection
  with the jobs as required status checks, and bypass disallowed, narrows this — but it catches
  a required job that **disappears or is renamed**, not one that still runs and checks nothing.
  `[[gate]]` has the mirror-image hole. Neither is a guarantee, and where the agent has no push
  credential at all, the credential's absence is already the stronger boundary.
- **A dead external link is `404`/`410` and nothing else.** The `url` kind closed the gap where
  a scheme-carrying target was skipped entirely, but what replaced it is narrower than "the link
  works": a page that now redirects to a parking domain answers `200`, and a host that refuses
  an unfamiliar client answers `403`, which this reports as unchecked rather than dead. It
  settles *gone*, not *good*.
- **The catch is dogfooded here only through the bibliography.** `code-patterns` and
  `substitutions` cannot recognize their own identifiers and so cannot be closed; until a
  bibliography was declared, `kinemata undeclared` refused in this repository rather than
  reporting a false clean. A reference key *is* recognizable — that is what the stamp's
  delimiters buy — so the bibliography answers, and the one finding it reports is real:
  `docs/citations.md` illustrates the form with a key this project has no entry for. The
  registry is deliberately left open, because closing it would turn an example inside a
  specification into a failing gate.
- **The tree walk follows symlinked directories and says so.** Each directory is entered once by
  real identity, and a link leaving the tree is announced on stderr. Before 2026-09-08 it did
  not follow them at all, and a project reached that way scanned as empty.
- **Run against two projects it did not grow up on** (`psf/requests`, `httpie/cli`), 2026-09-09.
  756 documentation claims, 5 reports, **none true**; one `check` finding on httpie, and
  `clusters` findings that were real. `requests` has no module-level string constants at all, so
  the default adapter bound to nothing and the registry was refused as empty. Seven defects came
  out of it, all boarded. **Two projects is not a survey** — both are widely-used Python
  libraries with careful documentation, which is the easy case for a claims checker.

### Found by the first outside audit, 2026-09-09

An adopting project ran this over three of their repositories and inventoried their existing
conformance suite against it. Everything below was **re-verified here** before being written
down, and the two shapes at the end are the findings that matter most.

**What the model does not reach:**

- **The registry mechanism is purely negative.** It expresses *"this value must not be re-spelled
  outside its home"*. Its natural twin — *"and here is the fact, which must **equal** what the
  code produces"* — is not expressible, and under negative polarity agreement produces a finding
  while disagreement produces silence. Of 326 conformance checks in that project's suite, **291
  were not expressible (89%)**, and this shape was the single largest reason.
- **Everything here is static.** Checks about what a program *does at run time* — a session-wide
  interposition on a write funnel, for instance — are outside the tool by construction. This is a
  real boundary and `structure.md` does not currently draw it: "reminder vs catch" says nothing
  about static vs dynamic, and the second is the harder wall.

**Where a declaration cannot say what a project means:**

- **~~A project cannot supply its own registry adapter from `kinemata.toml`.~~** True until
  2026-09-09, and the first thing the first outside audit found: `config.BUILDERS` was a fixed
  table of kinds with no plugin path, so the `declared()` override the contract invites was
  reachable only by importing kinemata as a library. Closed the same day by `kind = "import"`,
  which names a `module:Class` target. What is left of the limit: the class has to be importable
  by the interpreter running kinemata — nothing is put on `sys.path` for it — so a project whose
  package is not installed gets a refusal rather than a search. See `design.md` §4.2.
- **`match_mode` is not settable from TOML.** `config.py` passes `suffixes` and `machinery`
  through and nothing else, so a project cannot ask for `raw`, or override `code`/`strings`.
- **Registry scoping is inverted, with no exception.** Entries fire everywhere except `home`;
  there is no "fires only inside this one file", which is what an import-discipline check needs.
- **A `yaml-mapping` registry contributes nothing to `check`.** Its entries carry no
  antipatterns, so a green `check` over a mapping registry is not coverage of the mapping.
- **`PythonConstants` reads `ast.Assign` only.** A module-level `NAME: Final[str] = "..."` is an
  `ast.AnnAssign` and is invisible; so are tuple targets and enum members. In that project, 195
  bare-assign constants were readable and 32 annotated ones were not.
- **`contract._BOUNDARY` contains `.`**, so a module-qualified use is invisible to `detect()`:
  `bootstrap.CHANNELS_PATH` yields nothing where bare `CHANNELS_PATH` yields the entry. The `.`
  is right for dotted keyspace identifiers and wrong for Python constants reached through their
  module — **the two registry kinds want different boundaries.** `unused` inherits this on top
  of its own weakness.
- **`[[gate]]` cannot express ordering** — only that a command's text is present and uncommented.

**Where `claims` is narrower than its knobs suggest:**

- **The extractors are markdown-syntax-bound, and `suffixes` does not say so.** A format that
  happens to share the syntax works by coincidence (an RST double-backtick literal contains a
  markdown span); one that does not — YAML, plain text — contributes **zero claims, silently**,
  with no warning that a declared suffix found nothing.
- **`resolve_in` fails open.** A directory that does not exist produces byte-identical output and
  **no warning on stderr**. In CI, where a sibling tree is usually not checked out, every claim it
  was resolving goes unreported and the run still looks clean. It also resolves against disk
  before the gitignore-filtered index, so a stale `build/` copy of a package can keep a deleted
  module resolving.
- **`~`-prefixed paths are skipped entirely.** For a documentation tree that writes cross-tree
  pointers as `~/...` — which canon-style trees do — most pointers are invisible, so a clean run
  is a floor rather than a measure.
- **`FILE_SUFFIXES` is a closed set of 14 with no config knob.** A repository whose content files
  are `Containerfile.x` and `tmux.conf` is structurally unseeable; the scan comes back nearly
  green because it could not look.
- **`NEGATION` is missing `neither`, `dead` and `former`** (`formerly` is present, the bare
  adjective is not), and **`_SHA` matches any backticked run of 7–12 hex characters**, so an
  all-digit byte count in backticks is reported as a dead commit.
- **`historical` is a path axis, but a changelog's currency varies by section.** A live
  `[Unreleased]` entry and an honest historical record in one file cannot be separated by config.
- **`[context] include` accepts absolute paths, absolute globs and `../` escapes** — but by
  accident of two library behaviors rather than by contract, and nothing validates containment.
  Useful (it is how you would read a compiled artifact directly) and undesigned.
