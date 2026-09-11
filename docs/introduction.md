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
# and a reference key; the entry carries the volatile half. Add `.py` to
# `suffixes` if citations are written in docstrings as well as documents --
# without it the closed-world catch cannot see them.
[[registry]]
name = "sources"
kind = "bibliography"
suffixes = [".md", ".py"]
source = "docs/bibliography.toml"   # [[entry]]: key, target, note, foreign,
                                    # confirmed. An entry with `confirmed` is a
                                    # record, not a live pointer: the staleness
                                    # clock leaves it alone and `confirm`
                                    # re-checks it on request

# How long a citation target can be and still read comfortably beside its key.
# Reported by `kinemata cite -v`, never enforced.
[citations]
accompany_max = 50
provenance = true                  # every citation carries a stamp; an undated
                                   # one is a finding. Arming over an existing
                                   # tree reports all of them, so record a
                                   # baseline in the same commit
suffixes = [".py", ".md"]          # where the policy reaches. Defaults to the
                                   # claims scope; narrow it to keep stamps out
                                   # of user-facing prose while still checking
                                   # that prose for dead paths
resources = "docs/resources.toml"  # documents dated in a list rather than in
                                   # their own prose. [[resource]]: path, note,
                                   # confirmed. Every citation in a listed
                                   # document is dated by its entry; an entry
                                   # with no date covers nothing, and only
                                   # `kinemata confirm --write` writes one

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

**Per-registry options:** `suffixes`, `boundary`, `match_mode`, `machinery`, `case_sensitive`,
`allow_empty`, `source`, `modules`, `closed`, on `bibliography` — `interpreted` and
`standardized`, which **add to** the reserved type vocabulary rather than replacing it, and on
`import` — `target`, plus anything else the project's class takes. A closed built-in set with no
extension point is a defect this project has already shipped twice: once in that type
vocabulary, and once as `BUILDERS` itself.

The first four are **how a registry matches**, and each adapter's answer to them is a default
rather than a verdict: the adapter knows the shape its data model usually has, and only the
project knows what its identifiers are actually spelled like or which files they live in. They
are read on every kind.

On an `import` registry the loader keeps `name`, `kind`, `target`, `suffixes`, `machinery`,
`boundary`, `match_mode` and `allow_empty` for itself and hands **every other key** to the
class. The four matching options are in that list because they are contract attributes rather
than anything a `kind` invented — a project's own adapter gets them without taking a constructor
argument, and one that wants its own parameter of either name should read the attribute the
loader sets instead. `name` is the one option that behaves differently there: given, it wins as
it does everywhere; omitted, the class keeps the name it declares for itself rather than being
renamed to a default nobody wrote.

**`machinery`** names the files that *declare* a registry's entries rather than use them — a key
table, an inventory, the manifest. Only `unused` reads it, and only it or an entry `home`
satisfies that command: a project's `exclude` names build and test trees, is non-empty
everywhere, and accepting it as the answer would let the requirement pass while meaning nothing.

**`boundary`** is which characters may not abut an identifier for a match to count. Two rules are
declared and either can be asked for by name, so that a config never re-spells a character class
— two matchers disagreeing about what a word is was the finding that produced the second rule:

| `boundary` | Matches | For |
|---|---|---|
| `identifier` | the class holding `.` and `-` | identifiers that **contain** their separators — a dotted key, a hyphenated clause ID. The default for a registry that has not said |
| `name` | letters, digits and underscore | identifiers **reached through** a dot: `bootstrap.CHANNELS_PATH` is a use of `CHANNELS_PATH`. The default for `python-constants` and `code-patterns`, whose ids are names in code |

A project whose identifiers are neither writes the character class itself. `name` buys one false
positive knowingly: an attribute access spelled the same way on an unrelated object reads as a
mention, which text matching cannot tell apart without resolving the receiver. In `unused` that
*suppresses* a report rather than raising one, which is the right direction for a list a person
reads and the wrong one for any check that treats a mention as an accusation.

On a `substitutions` registry `boundary` is that same question asked of the matcher that kind
actually uses — which rule *builds* its patterns — and it takes `prose` or `identifier`: `prose`
bounds a spelling with `\b`, which is right for a word list and wrong for a name list;
`identifier` bounds it with the class above, and reads code spans instead of blanking them. A
retired `spec~box-vault` bounded as prose matches inside the live `spec~box-vault-enable`.

**Match modes** (`match_mode`, selects a filter table):

| Mode | Applies to | Behavior |
|---|---|---|
| `strings` | default | string literals only |
| `code` | source | code with prose filtered |
| `prose` | `.md` | inline code spans exempt; fenced blocks **not** exempt |
| `unfenced` | `.md` | fenced blocks exempt; inline code spans **not** exempt |
| `raw` | anything | no filtering at all |

`prose` and `unfenced` are not opposites and neither subsumes the other. `prose` exempts what a
document quotes inline; `unfenced` exempts what a document *displays*. A citation registry wants
the second, because a specification illustrating its own notation is showing the form rather than
using it — and a notation designed to be mechanically unambiguous cannot distinguish an
illustration of itself from a use of itself. A misspelling can, which is why the spelling registry
does not want this.

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
| `kinemata claims` | documentation gate, ratcheted; also verifies `[[gate]]` declarations | a dead claim the baseline does not already accept, a baseline past its `until` that exempts claims here, or a declared gate that does not run |
| `kinemata context` | session-load gate | measured bytes exceed `budget` |
| `kinemata baseline` | shows accepted findings; `--record --until`, `--prune` | — |
| `kinemata stamp` | mints a citation stamp, or decodes one; reads no config | the text given is not a stamp |
| `kinemata cite` | resolves a reference key — forward to its source, `--where` to every `file:line` citing it, bare for every key with its count | the key is malformed, or no entry declares it |
| `kinemata stale` | citations not confirmed within `stale_after`, scoped to kinds that cost a network request; a local claim is settled on every run, so a clock over it restates what the run already knows. A citation in a declared resource is clocked from its entry's date | never — refuses (exit 2) if `[citations] provenance` is not declared, because the citations carrying a stamp would then be an accident of who wrote them |
| `kinemata confirm` | **the only command that writes.** Dry run by default; `--write` re-dates the keyed citations it verified in that run, and the `[citations] resources` entries whose documents it settled entirely | never — the exit code is what a project wires into CI, and a writer that can fail a build is one that can be made to pass one |

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
- a `match_mode` that selects no filter table. An unknown one used to *work*: it landed on a
  table with no entry for the suffix, filtered nothing, and so behaved as `raw` by accident
- a `boundary` that is not a usable character class, **including both degenerate ends**. One
  matching every character that can sit beside an identifier leaves no legal neighbor, so the
  registry answers nothing about every tree it is pointed at; one matching none of them bounds
  nothing, so matching degrades to a substring search that reports a name inside a longer one. A
  bare word — `prose`, borrowed from the other table — lands in the second, which is why a typo
  is the likeliest way to arrive at one. A project that genuinely wants either sets `boundary`
  on a registry class of its own, where it is Python somebody wrote
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
- `[citations] suffixes` that is not a non-empty list of dotted file extensions, or that is
  declared without `provenance = true` — an empty list would turn the policy off while leaving it
  declared, and scoping a policy that is off narrows nothing while reading as a decision
- `[citations] resources` naming a file that is not there, declared without `provenance = true`,
  or holding a list with nothing in it
- a `[[resource]]` naming a path no file answers to, naming one already declared, carrying a
  `confirmed` that is not a date or that is in the future, or naming a document **the claims check
  does not read** — a document nothing extracts claims from would be dated by every run for having
  nothing to falsify it, which is a green entry certifying a document nobody checked
- an `import` registry whose `target` is malformed, names a module that will not import, names an
  attribute the module does not define, resolves to something that is not a class, or resolves to
  a class whose instances do not satisfy the `Registry` protocol — the refusal names the members
  it lacks, the target, and the config file that declared it, because a traceback from inside
  somebody else's package is not a usable error message
- an `import` registry declaring a key its class will not accept. Swallowing the `TypeError`
  would build the adapter's default instead, which is a misspelled parameter staying green
  forever

Two more raise from the scan rather than at load, as `ClaimsError`, because only the caller of
`verify()` knows the root a relative declaration is measured from — the scanned tree is not always
the config's own root, so validating at load time would settle the wrong path:

- `[claims] resolve_in` naming something that is not a directory
- `[claims] commits_in` naming something that is not a directory, **or a directory that is not a
  git repository**. Only repositories are consulted for commit resolution, so either mistake used
  to disappear into that filter: the declaration contributed nothing, said nothing, and every
  commit it was meant to settle was judged against the scanned repository alone. The shape bites
  where it is least visible — a corpus checked out beside a developer's tree and gitignored in CI
  settles the citations locally and silently stops settling them where the gate runs

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

**One list, both gates.** `check` puts the code findings through it and `claims` puts the
documentation findings through it, each reading the half it scans. A second exemption list for
documentation was the alternative and is the failure mode: two lists eventually disagree about
what a project accepted, and the one nobody is reading is the one still exempting something
real. Records are tagged with the check that produced them, so neither gate reports the other's
as fixed — it names them instead, because silence about part of an exemption list reads exactly
like having accounted for all of it. `kinemata baseline` runs both, being the only command that
writes the file; a `--prune` that covered one half would delete the other's records on the
strength of never having looked.

The four failures `claims` reports that are **not** claims about a site — a declared oracle that
would not run, and a promise kept, uncited or past its date — are never offered to the ratchet.
They have no path and line to fingerprint, and accepting one would build the thing both
`[[promise]]` and the baseline refuse by construction: a deferral that never lapses.

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

**Documentation inside code is scannable.** `suffixes` accepts `.py`, and a Python file declared
there is reduced to its docstrings and comments before any extractor reads it — a path in a
default value, a fixture or an embedded template is a value the code uses, not an assertion
about the tree. Whether that is worth arming is a measurement each project has to take: a
codebase whose docstrings cite *other* projects' files and commits, as this one's do, produces
findings that are correct as written.

**A docstring marks an illustration with a role.** A markdown document says *this text is shown,
not spoken* with a fence; a docstring had no equivalent, and the gap was the largest single class
of finding when `.py` was first armed here — text that shows a shape rather than citing anything,
sitting inside a sentence where a block-level fence cannot go. Putting `:shown:` immediately
before the span exempts it:

| Written | Read as |
|---|---|
| ``docs/design.md`` | a claim; the file has to be there |
| `` :shown:`example.md` `` | an illustration; not read as a claim at all |

The marker sits **outside** the delimiters, so the token between them is unchanged — a stamp
placed inside backticks once changed the path it was attached to and the citation stopped
resolving. Only this one role suppresses. Skipping every role-prefixed span was measured and
rejected: it silenced nothing that this tree's 88 existing roles mark, and Sphinx's `:doc:` and
`:download:` take a path in the tree as their target, so the broad rule would quietly silence a
real citation the day one of those is written. A misspelled role is therefore not a silent
exemption — the span is still read, and a dead path still fails. Suppressed spans are **counted
on every run**, because a suppression nobody can count is an allowlist with a good story.

`.py` only, deliberately: a reStructuredText role renders as literal text in markdown, and
markdown's own answer is the fence, whose cost `claims` has already named and measured.

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
  registry is **closed as of 2026-09-10**, and what unblocked it is the reason it could not be
  before: closing it would have turned that example into a failing gate, until `match_mode =
  "unfenced"` taught the scan that a fenced block is display rather than use. So an undeclared
  reference key exits 1 here, which is this repository's first real closed-world catch.
- **~~Text a project carries but did not author can only be excluded.~~** A vendored licence or a
  policy adopted as received cannot carry a stamp, because stamping it means editing text that is
  not the project's to edit — so its citations were findings the project could never drive down,
  and `[project] exclude` was the only answer. **Partly closed 2026-09-11** by the resource list:
  a document declared under `[citations] resources` is dated in the list rather than in its own
  prose, which is exactly what text you may not edit needs. What survives is the choice, and it is
  a real one: `exclude` drops the file from every check, a resource entry keeps the claims check
  over it and relocates only the date. This repository still excludes its two verbatim documents,
  because a dead link inside a licence is not its to fix either.
- **A resource entry dates a whole document, not a citation.** A citation added after the last
  confirmation sits under a date that predates it. The unit was chosen deliberately — citation- or
  target-level entries would copy into a registry the facts the documents already state, which is
  the duplication this tool reports — and the cost is bounded rather than absent: the claims check
  settles every citation in those documents on every run, so the entry records a verification and
  is not what keeps the citations true. Requiring the entry's date to be no older than the file's
  last commit would close it and was rejected: every documentation commit would then demand a
  re-confirmation, including the ones that touch no citation.
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
- **~~`match_mode` is not settable from TOML.~~** True until 2026-09-10: `config.py` passed
  `suffixes` and `machinery` through and nothing else, so a project could not ask for `raw` or
  override `code`/`strings`. Closed together with the boundary below, since both are one
  question — whether matching behavior is a property of the adapter class or something a project
  declares — and the answer is that the adapter supplies the default and the project overrides
  it. Both are refused rather than defaulted when they cannot mean anything.
- **Registry scoping is inverted, with no exception.** Entries fire everywhere except `home`;
  there is no "fires only inside this one file", which is what an import-discipline check needs.
- **A `yaml-mapping` registry contributes nothing to `check`.** Its entries carry no
  antipatterns, so a green `check` over a mapping registry is not coverage of the mapping.
- **~~`PythonConstants` reads `ast.Assign` only.~~** True until 2026-09-09: a module-level
  `NAME: Final[str] = "..."` is an `ast.AnnAssign` and was invisible, which in that project hid 32
  annotated constants against 195 readable ones — concentrated in the module they most wanted to
  declare. Annotated assignments are read now. **Tuple targets and enum members are still
  invisible, deliberately**: a partial recognizer that reports clean over what it missed is the
  failure, so the gap is written here rather than half-closed.
- **~~`contract._BOUNDARY` contains `.`~~**, so a module-qualified use was invisible to
  `detect()`: `bootstrap.CHANNELS_PATH` yielded nothing where bare `CHANNELS_PATH` yielded the
  entry, and four of that project's constants were reported as unmentioned on the strength of
  it. The `.` is right for dotted keyspace identifiers and wrong for Python constants reached
  through their module — **the two registry kinds want different boundaries** — so the boundary
  became a registry attribute on 2026-09-09 and a declaration on 2026-09-10. `code-patterns` was
  left on the dotted default that first day and had the same exposure, its ids being names in
  code; `helpers.run_or_die(cmd)` detected nothing, so the one site routing through the helper
  correctly was the site `unused` could not see. Fixed by changing that adapter's default, which
  moved nothing in this repository's own `check`, `review`, `unused` or `undeclared` output.
  `unused` still carries its own weakness underneath, which none of this touches.
- **`[[gate]]` cannot express ordering** — only that a command's text is present and uncommented.

**Where `claims` is narrower than its knobs suggest:**

- **The extractors are markdown-syntax-bound, and `suffixes` does not say so.** A format that
  does not share it — YAML, plain text — is read and contributes **zero claims**; a declared
  suffix that settles nothing is now named on stderr rather than passing in silence.
  **~~A format that shares it worked by coincidence.~~** True until 2026-09-10: reStructuredText
  spells an inline literal as a doubled delimiter, whose inner pair is itself a markdown span,
  so the token inside fell out of a single-backtick pattern. The delimiter run is matched
  deliberately now, and `.py` is a supported suffix rather than an accident.
- **Docstrings are scannable and this repository does not scan them.** Measured 2026-09-10 by
  adding `.py`: 95 claims, 24 unresolved, and the **two** real dead references it found — both in
  module docstrings pointing at a design document that had moved — are the whole yield. They were
  fixed by hand. The rest are correct as written: 7 short hashes belonging to the corpus
  repositories this project validated against, a dozen paths naming another project's files or
  teaching a shape, and one illustration of markdown link syntax. That is a property of *these*
  docstrings, whose convention is to name the outside incident that forced a design, so the
  evidence they cite is mostly not in this tree; a project whose docstrings assert things about
  its own tree gets a working check from the same knob.

  **Re-measured 2026-09-11**, after the illustration role: 18 unresolved claims under `src/`
  become **10**, and the 8 that went away were all illustrations rather than assertions. What is
  left is the part a marker cannot fix — 3 paths and 7 short hashes naming files and commits in
  the corpus repositories this project validated against. Those are true citations to trees that
  are gitignored here and absent from a clean clone, so the suffix stays **off**, with a residue
  of 10 and a named reason instead of a vague one.

  **That residue is what the claims ratchet was built for**, and it now exists: the 10 are
  accepted once and a new dead reference fails. Demonstrated on a scratch copy of this
  repository with the suffix armed — 11 findings (the 10, plus one test count this session made
  stale), recorded, green, then red on a single new dead docstring reference. Arming it here is
  a separate decision and has not been taken; the residue is genuine evidence of other people's
  trees, and whether to accept it or to reach that evidence some other way is the open question.
- **`suffixes` reaches `[[count]]` as well.** It was the sharper reason not to arm it here: the
  docstring explaining the test-count oracle recounts the numbers this project's notes once
  claimed, and the oracle reported every one of them against the current suite — the fourth time
  here that a document about a mechanism tripped that mechanism, and unlike the others it could
  not be reworded, because the stale numbers *are* the record. It is now marked with the
  illustration role, which reaches counted claims for exactly this reason: honoring a declared
  suffix for paths while reading the same file raw for values would let a number be shown in one
  sentence and asserted in the next.
- **~~`resolve_in` fails open.~~** True until 2026-09-09. A directory that did not exist produced
  byte-identical output and **no warning on stderr**; in CI, where a sibling tree is usually not
  checked out, every claim it was resolving went unreported and the run still looked clean. It
  refuses now. ⚑ **`commits_in` had the identical hole and kept it two days longer** — fixed
  2026-09-11, and it refuses a directory that is present but is not a *repository* as well, since
  only repositories are consulted and a merely-present path disappears into the same filter an
  absent one does. Finding a fixed defect still live in its twin is the argument for fixing a
  shape rather than a site.
  **What is left of the limit, and it is not fixed:** resolution still consults disk before the
  gitignore-filtered index, so a stale `build/` copy of a package can keep a deleted module
  resolving. Left deliberately — the "ignored and present" signal cannot separate a stale build
  copy from a deliberately-uncommitted corpus, and guessing wrong in either direction is worse
  than the rot.
- **`~`-prefixed paths are skipped entirely.** For a documentation tree that writes cross-tree
  pointers as `~/...` — which canon-style trees do — most pointers are invisible, so a clean run
  is a floor rather than a measure.
- **~~`FILE_SUFFIXES` is a closed set of 14 with no config knob.~~** True until 2026-09-09: a
  repository whose content files were `Containerfile.x` and `tmux.conf` was structurally
  unseeable, and the scan came back nearly green because it could not look. `[claims]
  file_suffixes` adds to the set rather than replacing it. **The default is still fourteen names
  chosen here**, so a project that declares nothing still gets that floor.
- **~~`NEGATION` is missing `neither`, `dead` and `former`~~**, and **~~`_SHA` matches any
  backticked run of 7–12 hex characters~~**, so an all-digit byte count in backticks was reported
  as a dead commit. Both true until 2026-09-09; the words are in the vocabulary and an all-digit
  run is skipped, because git does not mint all-decimal short hashes often enough to be worth the
  class of finding it produced.
- **`historical` is a path axis, but a changelog's currency varies by section.** A live
  `[Unreleased]` entry and an honest historical record in one file cannot be separated by config.
- **`[context] include` accepts absolute paths, absolute globs and `../` escapes** — but by
  accident of two library behaviors rather than by contract, and nothing validates containment.
  Useful (it is how you would read a compiled artifact directly) and undesigned.
