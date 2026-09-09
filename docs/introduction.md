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

# A number in prose, and the command that settles it.
[[count]]
label = "test count"
pattern = '\*\*(\d+) tests?\*\*'
command = ["{python}", "-m", "pytest", "--collect-only", "-q"]
extract = '(\d+) tests collected'

# One oracle, several numbers: declare it once and name it.
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

A config needs **at least one check** — a registry, a count, a gate, `[claims]` or `[context]` —
and is refused if it declares none. It does **not** need a registry: `claims` and `context` run
on a config that declares no registry at all, and a registry-shaped command refuses rather than
scanning nothing.

**Per-registry options:** `suffixes`, `case_sensitive`, `match_mode`, `allow_empty`, `source`,
`modules`, `closed`, `machinery`, and — on `substitutions` — `boundary`.

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

**Common flags:** `-c/--config`, `-r/--registry`, `-q/--quiet`, `-v/--verbose`, `--max-sites`.

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
  with the jobs as required status checks, and bypass disallowed, is what promotes it from
  reminder to catch.
- **A dead external link is `404`/`410` and nothing else.** The `url` kind closed the gap where
  a scheme-carrying target was skipped entirely, but what replaced it is narrower than "the link
  works": a page that now redirects to a parking domain answers `200`, and a host that refuses
  an unfamiliar client answers `403`, which this reports as unchecked rather than dead. It
  settles *gone*, not *good*.
- **The catch cannot be dogfooded here.** kinemata's own registries are `code-patterns` and
  `substitutions`, neither closable, so `kinemata undeclared` refuses in this repository rather
  than reporting a false clean.
- **The tree walk follows symlinked directories and says so.** Each directory is entered once by
  real identity, and a link leaving the tree is announced on stderr. Before 2026-09-08 it did
  not follow them at all, and a project reached that way scanned as empty.
- **Run against two projects it did not grow up on** (`psf/requests`, `httpie/cli`), 2026-09-09.
  756 documentation claims, 5 reports, **none true**; one `check` finding on httpie, and
  `clusters` findings that were real. `requests` has no module-level string constants at all, so
  the default adapter bound to nothing and the registry was refused as empty. Seven defects came
  out of it, all boarded. **Two projects is not a survey** — both are widely-used Python
  libraries with careful documentation, which is the easy case for a claims checker.
