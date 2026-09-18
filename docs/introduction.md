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
pip install kinemata          # or kinemata[yaml] for kind = "yaml-mapping"
pip install -e ".[dev]"       # working on kinemata itself, from a clone
```

⚑ **Pin the version.** Final releases exist, so a plain install resolves to the newest one rather
than to a pre-release — pip skips pre-releases only while some other version satisfies the
requirement. The interfaces are still not settled — this is a `0.x` — and an unpinned dependency
changes meaning without changing spelling. The index says what is published; this sentence
deliberately does not.

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
# A bare fragment matches anywhere in a path, so "tests/" also drops
# docs/smoke-tests-design.md. A leading slash anchors at the root:
# exclude = ["/tests/"]            # this directory, not this substring
max_sites = 20                     # an antipattern matching more sites than
                                   # this is too generic to mean anything, and
                                   # is suppressed and listed rather than
                                   # reported. Negative turns suppression off,
                                   # exactly as `--max-sites` does; the flag
                                   # wins over this for one run

# Values: antipatterns derived from the constants themselves.
[[registry]]
name = "constants"
kind = "python-constants"
modules = ["src/pkg/constants.py"]

# One document, more than one view of it. `where` narrows a registry to the
# entries a selector keeps, using the same vocabulary a [[shape]] rule's `when`
# guard takes -- a table of operators, or a `module:attribute` naming a
# predicate of the project's own. It exists because an oracle that answers for
# part of a declaration otherwise pays an `unproduced` finding for every row
# outside it: measured on a 99-row manifest against an oracle covering 10,
# 93 findings became 9.
#
# It narrows the REGISTRY, so membership keeps meaning "and there is nothing
# else" over the set the view declares, and the scan, `undeclared`, `shape` and
# `unused` all see the same narrowing. A selector that keeps nothing is refused
# at load -- running a check is not the check answering -- and `where` cannot be
# combined with `closed`, which would call every identifier of an excluded row
# undeclared.
[[registry]]
name = "keyspace-modekeyed"
kind = "yaml-mapping"
source = "keyspace-manifest.yaml"
section = "keys"
where = { present = ["default", "primary"] }

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
source = "docs/bibliography.toml"   # [[entry]]: key, target, note, repository,
                                    # confirmed. An entry with `confirmed` is a
                                    # record, not a live pointer: the staleness
                                    # clock leaves it alone and `confirm`
                                    # re-checks it on request. `repository` is
                                    # required by the Px and Cx codes and
                                    # refused beside a local one

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
oracle_timeout = 600               # seconds an oracle may run before it is
                                   # killed and reported as a failure

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

# A document that carries its own history claims only in one place. `every`
# is the default and is right for a value restated across documents; `first`
# reads the first match in each document and treats what is below it as
# record rather than claim. Positional, not semantic -- a changelog written
# oldest-first would have its oldest heading read as the claim, which fails
# rather than passes.
[[count]]
label = "changelog version"
occurrence = "first"
pattern = '## (\d+\.\d+\.\d+[a-zA-Z0-9.]*)'
command = ["{python}", "-c", "print(version())"]
extract = 'version=(\S+)'

# What a registry declares, against the set the project's code actually
# produces. Same oracle form as `[[count]]`: `command` names it inline, `run`
# names a `[command]` one, never both. Group 1 of every `extract` match is one
# identifier, matched against the whole output -- anchor with an inline `(?m)`.
# One registry, one oracle: a second [[parity]] naming it is refused.
[[parity]]
registry = "constants"
command = ["{python}", "-m", "pkg.settings", "--keys"]
extract = '(?m)^([A-Z_]+)$'

# The same, comparing a value per entry as well as membership. `field` names a
# key the entry carries, group 2 of `extract` is what it must equal, and
# `authority` says which side is the claim -- required here, because a
# divergence with no authoritative side is a finding nobody can act on.
# Membership still runs: "and there is nothing else" stays part of the claim.
[[parity]]
registry = "keyspace"
command = ["{python}", "-m", "pkg.settings", "--defaults"]
extract = '(?m)^(\S+)=(.*)$'
field = "default"
authority = "declared"      # or "produced"; the code is on trial either way
                            # round, and this says which way

# `field` may also be a PATH, written as a list, for a declaration that states
# a value as a nested map -- `default: {primary: ..., named: ...}` -- with one
# oracle run per arm. A bare string is one key however many dots it holds and
# is never split: `extra` keys legitimately contain them, so splitting would
# resolve an ambiguity by guessing, and a guess that is wrong here compares the
# wrong cell and PASSES. The two spellings do not overlap.
#
# A path reaching nothing, or descending through a scalar, is "no value
# declared" rather than an error -- a table where some rows hold a map and some
# hold a scalar is the case this exists to read.
[[parity]]
registry = "modes"
command = ["{python}", "-m", "pkg.settings", "--defaults", "--mode", "primary"]
extract = '(?m)^(\S+)=(.*)$'
field = ["default", "primary"]
authority = "declared"

# At most one translation, on the declared side, so a reader of the config can
# see that a comparison is not literal. `map` or `pattern`/`replacement`,
# never both.
[parity.translate]
pattern = '/$'              # the manifest writes a directory prefix with a
replacement = ''            # trailing separator; the code carries none

# `relation` says what the two sets are claimed to be. Without it a parity
# means `equal`, which is what it has always meant. The others are weaker or
# inverted claims, spelled as what IS claimed rather than as a direction
# switched off -- membership otherwise means "and there is nothing else", and a
# reader has to be able to see that a particular parity is not closed-world.
#
#   equal              the same identifiers on both sides          (the default)
#   declared_contains  every identifier the code produces is declared;
#                      the declaration may name more
#   produced_contains  every identifier declared is produced;
#                      the code may produce more
#   disjoint           no identifier is on both sides -- for a declaration that
#                      says what the code must NOT emit
#
# A relation other than `equal` REFUSES a run whose oracle produced nothing:
# `declared_contains` and `disjoint` are both satisfied by an oracle with
# nothing to violate them, and a vacuous run reads exactly like a clean one.
# It also cannot be combined with `field` -- a value comparison pairs
# identifiers both sides carry, which is the thing a relation is about.
[[parity]]
registry = "denials"
relation = "declared_contains"
command = ["{python}", "-c", "import pkg; print(pkg.META_FILE)"]
extract = '(?m)^(\S+)$'

# Rules a declaration must satisfy about ITSELF -- the one check whose subject
# is the declared document rather than the code. A rule is a `name`, a guard
# (`when`, optional) and exactly one claim; one registry, one block.
[[shape]]
registry = "keyspace"

  # No guard: every entry. `present`/`absent` take the field's name; the value
  # operators (`equals`, `choices`, `matches`, `each_matches`, `contains`) take
  # `field` as well, and `id_matches` claims something about the identifier.
  [[shape.rule]]
  name    = "every row declares a type"
  present = "type"

  [[shape.rule]]
  name    = "a type is one of the declared vocabulary"
  field   = "type"
  choices = ["str", "int", "bool", "path"]

  # A declarative guard: the rule judges only the entries it selects, and the
  # run prints how many that was. A guard selecting NONE fails -- a rule that
  # checked nothing must not read like a rule that was satisfied.
  [[shape.rule]]
  name    = "an internal row carries a value instead of a default"
  when    = { field = "user_key", equals = false }
  present = "value"

  # Over the set rather than per entry: `exists` names ids that must be
  # declared, `keys_of`/`are` compares one field's keys to another's values
  # both ways, and `exhausts` fails a vocabulary member nothing uses.
  [[shape.rule]]
  name     = "no dead outcome token"
  field    = "outcome"
  exhausts = "outcomes"

  # The escape: a rule that is the project's own model of its own declaration.
  # Either half may be a `module:attribute`, and what it receives is one entry.
  [[shape.rule]]
  name  = "set: never iff the key is under meta."
  when  = "mypkg.rules:is_never_settable"
  holds = "mypkg.rules:is_meta_key"

# Watch a write funnel while the project's own suite runs, and fail the run on
# an identifier nothing declares. Inert until the project loads the plugin:
# `pytest_plugins = ["kinemata.pytest_plugin"]` in its conftest. `identify` is
# the project's own -- only it knows how one of its calls becomes an identifier.
[[interpose]]
registry = "keyspace"
target   = "mypkg.store:KeyStore.__setitem__"
identify = "mypkg.census:key_of"
record   = "build/census.jsonl"   # optional, and the only thing that survives
                                  # the process. Appended, never truncated, so a
                                  # suite sharded across processes is the union
                                  # of their rows. Every row is written, clean
                                  # ones included: a findings-only file cannot
                                  # be diffed and cannot answer "did this
                                  # identifier stop being written". Relative to
                                  # `[project] root`

# What the project's code must ACCEPT and REFUSE. The only check that calls the
# project's own code. `cases` is the project's -- only it knows what its
# allow-list holds and how it composes a key -- and the *reading* of the outcome
# is declared here rather than supplied by the project, so a project cannot hand
# back a verdict.
#
# A corpus carrying only one polarity FAILS. A refusal-only corpus is satisfied
# by a callable that refuses everything, and an acceptance-only one by a callable
# that accepts everything.
[[probe]]
name    = "whitelist"
target  = "mypkg.templates:check_whitelist"
cases   = "tests.support.probes:whitelist_cases"
outcome = "raises"                    # the target refuses by raising
refusal = "mypkg.errors:ScopeError"   # required, and never `Exception`: every
                                      # failure is one, so a renamed function
                                      # would read as a correct refusal
exact   = true                        # optional. `except` matches subclasses,
                                      # so a declared base admits all of them —
                                      # which is right where a base means "any
                                      # of these is a refusal", and wrong where
                                      # refusals are NAMED and a related error
                                      # must not stand in for the declared one

[[probe]]
name     = "keyspace"
target   = "mypkg.keyspace:key_validity"
cases    = "tests.support.probes:keyspace_cases"
outcome  = "returns"   # the target refuses by returning a complaint
accepted = "none"      # required; or `falsy` / `truthy`. The value's type is
                       # never inferred

# Checks that must run, and the file that must run them.
[[gate]]
command = "pytest -q"
where = [".github/workflows/checks.yml"]   # default: every workflow

# Ceiling on what a session loads.
[context]
include = ["docs/**/*.md"]         # must stay inside the tree; an absolute path
                                   # or a `..` escape is refused and told to use
                                   # `external`
external = ["/etc/pkg/built.md"]   # patterns that deliberately leave the tree,
                                   # for the assembled file no repository holds.
                                   # Refuses a contained pattern, so the two
                                   # keys cannot drift into meaning one thing
budget = 24064
strip = ["html-comments"]
```

**What a `cases` supplier returns.** A callable taking no arguments and returning `Case` objects.
The rows are the project's because only the project can build them — here from its own manifest and
its own spelling rule, so nothing is re-implemented in a config:

```python
# tests/support/probes.py
from kinemata.probe import Case

from mypkg.manifest import allow_entries, families, prefixes, spell

def keyspace_cases():
    for prefix, family in prefixes_x_families():
        yield Case(expect="accept", args=(spell(prefix, family),), kwargs={"agents": AGENTS})
    for prefix in prefixes():
        # One segment past a terminal family is data, not a key.
        yield Case(expect="refuse", args=(f"{spell(prefix, 'env')}.probe",), kwargs={"agents": AGENTS})
```

`label` is optional and is what a finding names the row by; without one the arguments stand in,
which reads well for scalars and badly for a constructed object.

**Adapters (`kind`):**

| `kind` | Entries come from | Antipatterns |
|---|---|---|
| `python-constants` | module-level constants in named `modules` | derived from the values |
| `yaml-mapping` | a YAML mapping file (`source`), optionally a `section` inside it — one key, or a list of keys to descend through | derived from the values |
| `toml-value` | the **values** a TOML file declares at `path` — a scalar, or a flat list of them. Every other kind makes an identifier out of a *name*; this one makes it out of the value | derived from the values |
| `code-patterns` | hand-declared `[[registry.entry]]` tables | declared |
| `substitutions` | `[registry.words]` or an external `source` TOML | the forbidden spelling |
| `bibliography` | `[[entry]]` tables in an external `source` TOML | none — a citation *accompanies* its target by default, so a target spelled beside its key is the readable half of a declared citation rather than a re-derivation of it |
| `import` | a registry class the project wrote, named as `target = "module:Class"` | whatever that class declares |

**A `yaml-mapping` can compose identifiers out of two key levels.** A matrix — an arriving kind,
an occupant relation, an outcome token — has no identifier per *cell*, so nothing could state a
rule about one. `flatten = 2` with a declared `separator` makes each cell an entry:

```toml
[[registry]]
name = "cells"
kind = "yaml-mapping"
source = "manifest.yaml"
section = ["policy", "cells"]
flatten = 2          # default 1, which is exactly the behavior without it
separator = "."      # required when flatten > 1; there is no default
```

`separator` has no default deliberately: it spells every identifier the registry produces, and the
identifier is what the baseline fingerprints, the oracle prints and the scan looks for. A project
that has to type it has read what it becomes. Two levels is what was measured; deeper is accepted
rather than capped, because an arbitrary ceiling is a rule with no reason behind it, and nothing
here claims more than what was measured.

⚑ **A composite identifier is a different kind of thing from a declared name, and two consumers
feel it.** A composite does not occur in the code — `create.parent_missing` is not a string anybody
writes — so a flattened registry pointed at `check` yields entries nothing can re-derive, and a
whole registry landing in the `silent:` line reads uncomfortably like a clean tree. Worse, `syntax`
written for *leaf* names against a composite-id registry makes `undeclared` report every leaf
mention in the code, and that gate is a closed registry going red for a reason having nothing to do
with the tree. **The answer is the idiom this project already has: declare a second `[[registry]]`
view of one data model** — a flat view feeding `check` and `undeclared`, a flattened view feeding
`shape` and `parity`. It is the same thing a `[[parity]]` refusal already tells a project to do
when it wants to check a second fact about one source.

⚑ **Turning `flatten` on for an existing registry changes every identifier under it**, so every
accepted finding keyed on one becomes unmatched: `--prune` deletes them as fixed and `--record`
re-records them under new ids. Do it in a commit of its own and re-record the baseline there, with
a note saying why the ids moved. ⚑ **The same no-migration rule is what a renumber looks like from inside.** A claim fingerprint
keys on the line's text, so inserting an item above ordinal-bearing claims reports each shifted
claim twice — once as new, once as no-longer-present. Measured 2026-09-16: one inserted item,
three shifted claims, six lines of report, zero real findings. **Do not re-record.** Edit the
baseline file's texts to the new ordinals directly: the finding is unchanged, only its address
moved, and `--record` would hand every accepted finding a fresh expiry lease for no measured
gain. A content hash would not survive this either — the text itself changed — so only
author-assigned stable ids would, and those tax all prose for a rare event with a three-line
recovery. This paragraph is the whole remedy, on purpose.

**A `toml-value` declares the values, not the keys holding them.** Every other kind makes an
identifier out of a name; this one makes it out of the scalar itself, which is what a claim about a
*value* needs on its declared side. `tomllib` is stdlib, so this adds no dependency and no extra.

```toml
[[registry]]
name = "tree-version"
kind = "toml-value"
source = "pyproject.toml"
path = ["project", "version"]     # a list of keys, or one key; never a dotted string
```

`path` reaches a scalar — one entry — or a **flat list** of them, one entry each. A table is
refused, and the refusal lists what that level holds so an author who stopped a key short can
finish the path. A nested list and a TOML date are refused for one reason: `str` of either is a
spelling no oracle prints by accident, which is the line `[[parity]]` already draws on the declared
side. An entry carries **no** `extra` — the value *is* the identifier, so a `{"value": …}` beside it
would be one fact spelled twice.

**The claim this was built for**, and the relation it uses was not built for it — `disjoint`
already answered both directions before the adapter existed:

```toml
# The version this tree declares must not be one the index already carries.
[[parity]]
registry = "tree-version"
relation = "disjoint"
command = ["{python}", "-c", "..."]   # prints one published version per line
extract = '(?m)^(\S+)$'
```

Between a release and the next version bump, a tree sits on a version that is already published —
and :shown:`pip install "pkg @ git+https://…@<sha>"` then **builds the metadata, sees that version
already installed, and skips**. The install succeeds, the suite passes, and the person validating reports
back that a fix works having never fetched it. Two unrelated projects hit this independently, which
is what moved it from an anecdote to a claim worth declaring.

⚑ **Two things to get right, and neither is the config.** The oracle reads an index over the
network, so it must defeat **both** caching layers — a `Cache-Control: no-cache` header *and* a
changing query parameter, since the header alone does not reach a CDN. A cached read makes this
gate pass wrongly, which is the failure it exists to prevent. And a relation other than `equal`
**refuses an oracle that produced nothing**, so this claim fails on a project that has never
published, until its first release.

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
`[[count]]`, whose oracles are shell commands run through `subprocess`.

⚑ **This used to add *"kinemata still reads the code it checks with `ast` and never executes it"*,
and `[[probe]]` falsified it** — a probe calls the callable under test, which is the whole
mechanism. **The surviving claim is about the scan, where it matters most: declaring a registry
never causes the scanned code to run.** See § Known limits for what a probe does and does not do
with the code it calls.

**The rule, and it is stated as one because the list keeps growing: wherever this config names a
command or a `module:attribute`, kinemata runs what it names — and nowhere else.** A declared
oracle (`[[count]]`, `[[parity]]`), a named adapter (`kind = "import"`), an interposition's funnel
and `identify`, a shape rule's guard or claim: every one of them is a line in this file, which is
where a reviewer reads them. ⚑ **Three documents enumerated the exceptions and all three were
already stale**, having missed the interposition a day before the shape check added another.

A config needs **at least one check** — a registry, a count, a parity, a gate, `[claims]`,
`[context]` or `[citations] provenance` — and is refused if it declares none. It does **not** need
a registry: `claims` and `context` run on a config that declares no registry at all, and a
registry-shaped command refuses rather than scanning nothing.

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
| `kinemata claims` | documentation gate, ratcheted; also verifies `[[gate]]` declarations | a dead claim the baseline does not already accept, a baseline past its `until` that exempts claims here, or a declared gate that does not run. Refuses outright (exit 2) if nothing declares anything for it to check — no `[claims]`, `[[gate]]`, `[[count]]`, `[[promise]]` or `[citations] provenance` |
| `kinemata parity` | membership gate, ratcheted — what a registry declares, against the set an oracle says the code produces. Both directions: produced and declared by nothing, declared and produced by nothing. With `field`, **also** each entry's declared value against what the oracle prints for it | a disagreement in any of the three directions that the baseline does not already accept, an oracle that could not answer, or a declared value no oracle could be expected to print. Refuses outright (exit 2) if no `[[parity]]` is declared |
| `kinemata shape` | declaration gate, ratcheted — the one check whose subject is a declaration rather than the code, so it reads no tree and takes no path. A rule is a **guard** and a **claim**, and either may be a predicate the project names | a rule an entry does not satisfy that the baseline does not already accept, a rule that could not be evaluated, or **a rule that examined no entry at all**. Refuses outright (exit 2) if no `[[shape]]` is declared |
| `kinemata probe` | behavior gate, ratcheted — a declared corpus of inputs against what the project's code **accepts and refuses**. The one check that calls the project's own code; it reads no tree and takes no path, because the corpus comes from the project | a case the code answers otherwise that the baseline does not already accept, a probe that could not be evaluated, or **a corpus carrying only one polarity**. Refuses outright (exit 2) if no `[[probe]]` is declared |
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

### The one check that is not a command

`[[interpose]]` has no subcommand, because it cannot have one: it has to be inside the project's
own test session to see anything. A project loads the plugin —

```python
# conftest.py
pytest_plugins = ["kinemata.pytest_plugin"]
```

— and every declared funnel is patched at `pytest_configure` and **restored before the process
ends, whatever else happened**. Each identifier crossing a funnel is judged against the registry
the declaration names; the session fails on one nothing declares, on a funnel that could not be
patched, or on a fault inside the collector, which means crossings went unrecorded.

**There is no `pytest11` entry point**, so installing kinemata does not put this in anyone's test
run. Loading a plugin that monkey-patches the project's own classes is a thing to ask for.

⚑ **The terminal summary is one process's, and `record` is the only thing that outlives it.** The
plugin's state is per-process, so a suite run as one process per file — a shard, a chunked runner,
anything that is not a single invocation — produces a summary per process and no union at all. A
funnel declaring `record` appends its rows there instead: **one funnel line per process** carrying
the crossing count, whether the funnel was blocked and what faulted, then **one line per
identifier, the clean ones included.** The rows are what make a run diffable and what answers *did
this identifier stop being written*; the funnel line is the denominator, and three findings out of
three crossings is not the same run as three out of three thousand. Each process appends its whole
payload in one write, which is what keeps concurrent shards from interleaving — up to the size at
which the kernel splits a write, past which a project should give each shard its own path.
**A declared record that could not be written fails the run**, like any other declared thing that
did not happen.

A test that means to write an undeclared identifier says so, and the declaration is not an
exemption:

```python
@pytest.mark.kinemata_undeclared("box.meta", reason="drives the refusal path")
def test_refuses_an_unknown_key(): ...
```

Scoped to that one test — the same identifier written by anything else still fails. Exact — any
*other* undeclared identifier that test writes still fails. And **it must change a verdict**: a
declaration that excused nothing fails the run, so it cannot outlive its reason. That last property
is why this check has no baseline. A ratchet would be a scope `kinemata baseline` could never run,
so `--prune` would delete its records for never having looked — and the marker is the better
instrument anyway, being a deferral that expires by itself instead of one somebody must remember to
drive down.

⚑ **The site that made a crossing is recorded for the report and decides nothing.** An earlier
revision of the census this is drawn from excused writes by where they came from, matched by code
object; it hid roughly forty real violations. **An identifier is judged by what it is** — which is
also why an observation is keyed on the identifier alone and never on the site.

⚑ **A judgement that depends on the run's *other* identifiers reaches as far as one test, and
that is deliberate.** `identify` may keep state across crossings, and it may return a **deferred
callable** resolved when the test drains — so *"this path is structure because something was
written under it"* is expressible today, as a model of what an identifier is rather than as an
override of a verdict. What it cannot do is span tests, because the drain that ends each test
fixes that test's answers. 🛑 **Nor should it**: a verdict that turns on what a *different* test
wrote is not reproducible — run that test alone and it flips, and under one pytest process per
file it turns on which file the writes landed in. A project whose extractor accumulates across
tests already has this, and the same two writes in the other order give the other answer. **Reset
the accumulator per test.** Nothing here can detect one that is not reset; `identify` is the
project's code and this check cannot see inside it.

⚑ **If a call's *shape* changes what it means, that belongs in the identifier, and `identify` is
where it goes.** One path written both as a scalar and as an empty container is two facts, and a
project whose model says so returns two spellings — `identify` receives the whole crossing, the
return value included, so it has everything needed to choose. Two spellings are two rows, **two
verdicts**, and two markers that expire independently. The alternative shape, a discriminant
carried beside the identifier, would split the rows and not the verdicts: those come from
`declared(identifier)`, and a field beside the string does not reach it.

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
- **any table declaring a key it cannot mean**, the document root and `[[registry]]` included. Each
  table differences its own key set and the refusal names what the key could have been. TOML hands
  a bare key to the most recently opened table, so a `[[gate]]` written inside `[claims]` takes the
  `historical` after it and the suppression stops applying; where the swallowing table is an array
  of tables the refusal says so outright, because naming the key alone leaves its author reading an
  error under a heading they never associated with it. At the **root** the spelling that bites is a
  misspelled array — `[[gates]]` declares no gates at all, which disarms the inventory rather than
  decorating it, and a config with one registry beside it still declares a check. A `[[registry]]`
  is differenced against **its own kind's** vocabulary rather than the union of all of them, since
  `section` on a `python-constants` registry means exactly as little as a key no kind has ever had.
  `kind = "import"` is the one exception and checks its own vocabulary through its class, below
- `[context]` missing `include` or `budget` — there is **no default ceiling**
- `[context] strip` naming an unknown transform
- `[[gate]]` with no `command`
- a `yaml-mapping` `section` naming a key the document does not hold, landing on something that is
  not a mapping, given as an empty list, or given as neither a string nor a list. A missing segment
  names itself, what it was looked for under, and what that level actually held — "section not
  found" against a five-deep path is a refusal somebody has to go and locate by hand
- a `yaml-mapping` `flatten` that is not a positive whole number; `flatten > 1` with no
  `separator`, which has no default; a `separator` declared with no `flatten`, which composes
  nothing and so says something while doing nothing
- a `flatten` separator collision — two distinct key paths composing to one identifier. Refused at
  load naming both paths and the identifier, because one entry would silently shadow the other and
  the registry would report a smaller set that reads as correct
- a `flatten` level whose value is not a mapping — a matrix with one scalar row is a malformed
  matrix, and skipping it would make the registry quietly smaller
- a registry that cannot recognize its own identifiers cannot be `closed`
- a config declaring **no check at all** — every command it configures would pass by doing nothing
- a `[[promise]]` with no `until`, an unparseable date, or a `note` with no `by`
- a `[[count]]` naming a `run` no `[command]` declares, or giving both `command` and `run`
- a `[[count]]` whose `occurrence` is neither `every` nor `first` — a misspelling that fell back to
  the default would re-read the history the key exists to stop reading
- a `[[probe]]` missing `name`, `target` or `cases`; naming a `target`, `cases` or `refusal` that
  is not a `module:attribute`; or reusing a `name` another `[[probe]]` holds — two of one name
  would share a baseline scope, so a record could not say whose it was
- a `[[probe]]` whose `outcome` is neither `raises` nor `returns`. **There is deliberately no
  escape to a project predicate**: supplying the reading of an outcome is supplying the verdict,
  and a wrong classifier reports agreement between itself and a wrong declaration
- a `[[probe]]` declaring `outcome = "raises"` with no `refusal`, or `outcome = "returns"` with no
  `accepted`. Each mode's discriminator is **required rather than defaulted**, so a project that
  has not thought about the convention is refused instead of inheriting one
- a `[[probe]]` carrying the *other* mode's discriminator — a `refusal` beside `returns` reads to
  a human as a check that is switched on and is read by nothing
- a `[[probe]]` declaring `exact` beside `outcome = "returns"`, where there is no exception type to
  be exact about — the same reading, one key later
- an `accepted` outside `none` / `falsy` / `truthy`. The value's type is not inferred: a callable
  returning `0` for success and one returning `0` errors are the same bytes and the opposite sense
- a `[[parity]]` naming a `registry` no `[[registry]]` declares — refused at load rather than at
  the command, because a misspelled name and a project whose declaration and code agree produce
  the same silence, and only one of them is a mistake
- a `[[parity]]` giving both `command` and `run`, naming a `run` no `[command]` declares, or
  missing `registry`, `extract` or a command. `extract` has no default: whole lines would read a
  traceback or a shell warning as identifiers, and the disagreement would then be reported against
  the project's declaration
- a second `[[parity]]` naming a registry another already names. Two would compare membership
  twice, so one disagreement would be reported and recorded as two, and a baseline whose counts
  come from the config's shape cannot be audited against a scan. To check a second fact about one
  data model, declare a second `[[registry]]` view of it
- a `[[parity]]` with a `field` and no `authority`, or an `authority` outside `declared` /
  `produced`. Which side is the claim is a property of the row rather than a convention, and a
  value divergence that does not say it is a finding nobody can act on. `authority` **without** a
  `field` is allowed and shapes the message: the membership directions already name their own side
- an `[[interpose]]` missing `registry`, `target` or `identify`; naming a registry no
  `[[registry]]` declares; spelling either target as something other than `module:attr`; or
  watching a callable another `[[interpose]]` already watches — two patches on one callable would
  count a single call twice, and the second uninstall would restore the *first wrapper* rather than
  the original, leaving the project's own class patched after the run.
  ⚑ **The target is checked for shape here and resolved later**, when the plugin installs it.
  Importing the project's own modules belongs in the project's own test session, not in every
  `kinemata check` — and a module that imports there but not here would otherwise make a config
  unloadable for a reason having nothing to do with the file. A target that cannot be resolved
  fails the **session**
- a `[parity.translate]` declaring both `map` and `pattern`, declaring neither, giving a `pattern`
  with no `replacement`, an empty `map`, or a pattern that will not compile. The replacement is
  never defaulted from the pattern's presence: an empty one is a legitimate translation, so
  guessing it would silently delete text on a mistyped key
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
  **interpreted** code (`Wb`, `Pa`, `Cm`, `Px`, `Cx`), whose meaning a check acts on. Redefining a
  **standardized** code is a warning instead: the tool never reads those, so refusing would
  enforce a convention it cannot act on
- a `bibliography` entry whose code and `repository` field disagree: an **external** code (`Px`,
  `Cx`) with no repository names a source it cannot point at, and a repository beside a local code
  says one thing to a reader and another to every check
- `[project] max_sites` that is not a whole number — the threshold is compared against a count, so
  a string crashes from three modules away and `true` compares as a threshold of 1, which
  suppresses very nearly everything while reading as a setting somebody chose
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

**One list, every gate that ratchets.** `check` puts the code findings through it, `claims` puts
the documentation findings through it, `undeclared` puts a closed registry's strays through it,
`parity` puts the disagreements between a declaration and its oracle through it, and `shape` puts
the rules a declaration does not satisfy through it — each reading the part it scans, and each
record carrying the scope that produced it. A second exemption list was the alternative and is the failure
mode: two lists eventually disagree about what a project accepted, and the one nobody is reading
is the one still exempting something real. Records are tagged with the check that produced them,
so no gate reports another's as fixed — it names them instead, because silence about part of an
exemption list reads exactly like having accounted for all of it. `kinemata baseline` runs every
one of those scans, being the only command that writes the file; a `--prune` covering some of
them would delete the rest's records on the strength of never having looked.

⚑ **A shape rule brings a second way not to have answered, and it stalls a rewrite too.** A rule
that examined no entry *ran*, and judged nothing — so pruning its records would drop them on the
authority of a run that examined none of them. Blocked and vacuous rules both appear in the
refusal below. **The test is the count, not the guard**: a rule with no `when` over a registry
that produced nothing is as vacuous as one whose guard matched nothing, and so is a set operator
that selected nothing.

⚑ **Running a scan is not the same as the scan answering, and `--record` and `--prune` refuse
(exit 2) while any declared oracle is blocked.** An oracle that is not installed on this machine
produces no findings, which is indistinguishable from a tree where it found none — so a rebuild
from that run drops every record it was covering, and the message says the findings are no longer
present. Measured rather than reasoned about: a parity oracle pointed at a command that does not
exist dropped a recorded exemption and reported it as fixed. The cost is that a machine missing a
declared command cannot re-record; that is the intended trade, because the alternative is losing
an exemption list to an absent binary. Parity's records are
tagged `parity:<registry>:undeclared` and `parity:<registry>:unproduced`, and **both scopes are
reported as judged on every run, including the empty ones** — a direction that found nothing is
still a direction that looked. A declaration comparing values adds a third,
`parity:<registry>:divergent`, and that one is reported as judged **only by a run that compared
them**: the same rule read the other way, since a membership-only run has not looked at value
records and must not be counted as having found them gone. A divergence record fingerprints both
values, so a disagreement that turns into a different disagreement is a new finding rather than
one resting under a record written for the old one.

⚑ **Catch A joined the list 2026-09-13, and until then closing a registry was a cliff.** A
project with one pre-existing undeclared identifier had to choose between an open registry whose
advisory list nobody reads and a closed one that fails every build until the last identifier is
declared. Strays are tagged `undeclared:<registry>` rather than with the registry's bare name,
which is not cosmetic: under a bare name `check` would find no matching record, call every one of
them stale and recommend a prune — deleting the exemptions holding a *closed* registry green.

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

**`[[count]]` settles a value, of which a number is one kind.** It is the one claim kind that
fails on a *disagreement*: everywhere else in this table a missing or dead thing is the finding,
while this one fails when the document and the oracle say different things. The comparison is
exact — edge whitespace is stripped from both sides and nothing else is touched. Nothing is
converted, coerced or rounded, so a document
saying "16 KB" is not settled by an oracle that emits the byte count; a project wanting both
spellings checked declares two entries, each with its own `pattern` and `extract`. That limit
is deliberate: a wrong normalization does not fail, it passes.

**Every match is a claim, unless the document carries its own history.** `occurrence = "first"`
reads the first match in each document and treats everything below it as record rather than
assertion — a changelog, where the newest heading names the version being shipped and the entries
under it are permanent records of releases that already happened. It is **positional, not
semantic**: a changelog written oldest-first has its oldest heading read as the claim, which fails
rather than passes, since that heading names a version that is not the one shipping.

**A count that matches nothing fails.** The oracle answered and nothing asked it, which is the
same failure as an oracle that could not run — the check is not running — and the quieter of the
two, since an unreachable oracle at least says so while a pattern matching nothing just
contributes no claims to a total nobody audits. Reachable two ways, both silent before this was
caught: a pattern that never matched, and one whose only sites sit in a document the scan stopped
reading after a suffix was dropped or an `exclude` widened.

**One oracle discipline, and `[claims]` is where it is declared for all of it.** `kinemata parity`
runs declared commands too, and inherits the rule above rather than restating it — edge whitespace
stripped from the oracle's output, nothing else normalized. `oracle_timeout` is read from
`[claims]` and bounds **every** declared oracle this package runs, a parity oracle as much as a
count's: one that never returns has to fail rather than hang the gate, and expiry is reported the
way any other unreachable oracle is.

**The exit status is the one thing the two do not share, and the difference is deliberate.** A
`[[count]]` oracle may fail and still be believed, because `extract` is the guard: it pulls a
single value out of the output and reports *produced no value* when it cannot, so a command that
died settles nothing either way — while a test runner with a red suite exits non-zero and still
prints how many it collected, which is exactly the question asked. A `[[parity]]` oracle has no
such guard, because it extracts a **set** and matching nothing is a well-formed answer meaning
*the code produces none of these*. There a failed run and an empty world are the same text, so a
non-zero exit **blocks**. An oracle that legitimately exits non-zero has to absorb that in its own
command.

Negation is parsed: a claim inside a negated clause is a mention, not an assertion. Clause
boundaries are `;:`, `but`, `however`, `whereas`, `while` — commas deliberately excluded.

**Documentation inside code is scannable.** `suffixes` accepts `.py`, and a Python file declared
there is reduced to its docstrings and comments before any extractor reads it — a path in a
default value, a fixture or an embedded template is a value the code uses, not an assertion
about the tree. Whether that is worth arming is a measurement each project has to take: a
codebase whose docstrings cite *other* projects' files and commits, as this one's do, produces
findings that are correct as written.

**A span marks itself an illustration with a role.** A markdown document says *this text is shown,
not spoken* with a fence; a docstring had no equivalent, and the gap was the largest single class
of finding when `.py` was first armed here — text that shows a shape rather than citing anything,
sitting inside a sentence where a block-level fence cannot go. The same gap has since been
measured in markdown itself (2026-09-16, two adopting projects), where the fence is equally
unavailable mid-sentence. Putting `:shown:` immediately
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

Honored in `.py` **and `.md`**. The role began docstring-only, deliberately: a reStructuredText
role renders as literal text in markdown, so honoring it there puts checker syntax in front of a
human reader. Two adopting projects falsified the refusal on the same day in 2026-09-16 — one
naming a real file that lives outside the tree on purpose, one a generic filename that must stay
in backticks — and neither has any other permanent marking: a baseline lapses by construction,
de-backticking spends formatting on compliance, and a fence cannot go mid-sentence. The render
cost stands; spending it is the author's per-span choice.

**Gate verification** rides on `claims` rather than being its own command: a check that
verifies other checks are wired up is worthless if nothing guarantees it runs. It fires on a
deleted step **and** on a commented-out one. Beside the cover line it prints a second one the
cover line made necessary: a declared section no gate row runs — five `[[shape]]` blocks and
gates for three other commands still printed `3 of 3`, because the count measures declared
gates, not declared checks. `ungated:` names each such section. It warns rather than fails: the
declaration may be run by hand, and failing would force either real CI wiring or deleting the
declaration to satisfy its inventory. Advisory readers (`review`, `clusters`, `unused`, `ids`)
never count, and neither do sections `claims` itself exercises (`[[count]]`, `[[promise]]`,
`[claims]`) — a running `claims` covers those by definition.

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

**This section is what the mechanisms do not reach *today*.** It is not a list of things nobody
will ever address, and it has no standing to be one: a document can describe what a tool does, but
what gets built next is a decision somebody makes later rather than a property of the code.

**Every entry carries a disposition, and the two say different things to someone deciding whether
to adopt this.**

- **boundary** — **this instrument cannot reach it**, and no amount of work on *this* one will.
  Getting there needs a different instrument. A statement about the mechanism, never about intent.
- **accepted** — **not a wall, just undone.** Real, contingent, revisitable; more work moves it,
  and some of it is work this project intends to do.

⚑ **`boundary` read "and none is planned — read these as permanent" until 2026-09-13, and three
entries falsified that in a single day.** *"Nothing here observes a running program"* was marked
permanent and became `accepted` the same morning somebody asked whether a run-time hook was ever
coming. `unused()`'s boundary turned out to belong to **mention scanning** rather than to the
question, once an oracle could answer the question directly. And Catch A's dependence on an
identifier recognizer stopped being the only route, on the same day. **Not one of the three moved
because the model changed. Each moved because an instrument appeared** — which is the thing the old
wording promised would not happen.
⚑ **The first of the three closed outright the next day**, when `[[interpose]]` was built: an entry
this list had published as permanent went from *never* to *shipped* in about thirty hours, and the
only thing that changed in between was that somebody asked.
⚑ **So a disposition says what it would take, never whether anyone will.** The failure direction is
the bad one: an adopter reading *permanent* scopes their own work around a limit that one
conversation would have removed, and that came within a day of happening to the project this tool
was built alongside.

⚑ **The marks were added 2026-09-13 and are the point of the list, not decoration.** Until then
every entry read the same way, so a permanent property of the data model and a sample size nobody
had extended were published in one voice — and a reader had no way to tell which of the two they
were looking at. A limits list that cannot distinguish those understates a tool to the people most
carefully reading it.

⚑ **Nothing mechanical checks these marks.** They are not falsifiable claims, so `kinemata claims`
cannot see them; a mark that goes wrong goes wrong silently. **Re-read this section whenever a
limit is closed, in the same commit that closes it.**

- **accepted** · **One `exclude` line means two things, depending on which check reads it.** The
  documentation scan strips a fragment's trailing slash before matching and the registry scans do
  not, so `exclude = ["tests/"]` removes `docs/smoke-tests-design.md` from `kinemata claims` and
  leaves it in `kinemata check`. Found by an adopter 2026-09-14, who lost two claims and an
  external link to it. **Not repaired in place**, because narrowing the old spelling would silently
  change what every config already written removes — the class of defect being fixed. The anchored
  form (`/tests/`) is exact in both, and `check` and `review` now report any fragment that removed
  nothing, or removed a path only as a substring. Unifying the two preparations is the work this
  entry is waiting on, and it needs a deprecation rather than an edit.
- **boundary** · **Semantic duplication is out of reach by design.** Rules enforced twice in
  dissimilar code are not detectable syntactically.
- **boundary** · **Greenfield coverage: 4 of 13 instances** across 37 attributable commits (31%).
  Split: 5 literal / 4 code / 4 semantic. ⚑ **The ceiling is derived, not asserted — and the
  derivation names three reasons, not the two this entry published until it was audited.** Four of
  the nine out of reach are semantic and four are drifted copies, each a boundary in its own right
  immediately above and below; **the ninth is out of reach by locus** — both of its carriers live
  in a configuration file another tool writes, and nothing here reads outside the source tree it is
  pointed at. The third reason is the one worth keeping, because it says reach is decided by
  resemblance **and** by where the carriers sit, and exactly one measured instance separates them.
  So this figure is what the instrument can do rather than how far it has got — which is why it is
  marked permanent while being a measurement rather than a property.
- **boundary** · **Drift defeats shape matching.** The copies worth catching are the drifted
  ones; drift removes the signal. This is why clone detection was not shipped.
- **boundary** · **`unused()` detects mention, not use.** Every declared entry is mentioned by
  construction, so it needs `machinery` or an entry `home` to mean anything and refuses without
  either. Review list, never a cut list — and it does not apply at all to a registry whose entries
  are declared to be *absent*, which it says rather than answering.
  ⚑ **It asks a positive question with a negative, static instrument**, which is why no amount of
  tuning fixes it: separating a reader from a mention needs dataflow. Two complements are
  published instead. A project that needs the real answer at run time asserts it against the same
  declaration during its own test run, through `kinemata.access`. A project whose code can
  **print** the set it produces declares a `[[parity]]` instead, and the `unproduced` direction is
  the question this entry approximates, answered from an oracle rather than from a mention: no
  search, so nothing to mistake.
  ⚑ **Measured, and worth knowing before turning it on: no true positive is recorded anywhere.**
  0/3 against the labeled incident, four reports at the first adopter and all four false, and six
  in this repository today with none of them defects — two of those six carry declarations saying
  they are correct, and four are bibliography keys, where uncited means *ready* rather than dead.
  ⚑ **The mark stays, and it is now scoped to this instrument rather than to the question.**
  Mention scanning cannot separate a reader from a mention, which is permanent; but *"this
  declared entry must be produced"* stopped being unexpressible on 2026-09-13, when `kinemata
  parity` began answering it for a registry whose project can print its set. So the boundary is
  `unused()`'s, not the tool's — and where a set can be printed, `unused` is the weaker of two
  instruments and should not be the one a project relies on. Where nothing can print it, this is
  still all there is.
- **boundary** · **Parity reaches only a set the project can print, and it trusts the oracle.**
  The comparison is against what a declared command prints, so a registry whose membership nothing
  can produce is out of reach — not for want of work here, but because there is no oracle to ask.
  And the oracle is a **reminder** in the sense `docs/structure.md` §1 uses: the config naming the
  command and the command itself both live in the tree the constrained agent writes, so a
  disagreement can be made to go away by editing either one. What makes that survivable is what
  makes the baseline survivable — it is a visible file change. The one thing it will not accept
  quietly is an oracle that cannot answer: not installed, killed on timeout, exited non-zero, or an
  `extract` with no capture group is a **failure**, never a skip. An oracle that *succeeds* and
  matches nothing is a different thing — an empty set, which is a real answer and usually a
  finding.
  ⚑ **A value comparison adds one more refusal and one structural guard.** A declared value that is
  not a scalar or a flat list of them **blocks**: a nested container has an internal order and a
  spelling no two sides agree on by accident, so rendering it would be a normalization that does not
  fail. And membership runs whether or not a `field` is named, so *"and there is nothing else"* is
  part of the shape rather than a discipline — the alternative, comparing values only for the
  identifiers both sides happen to mention, reports agreement when the oracle prints nothing.
  ⚑ **The failure that matters is not a hostile oracle but a permissive one, and it is inverted:
  a too-permissive oracle reports agreement.** An oracle that derives its answer from the
  declaration — reading the manifest it is supposed to be checked against, or reporting whatever it
  was asked about — makes the comparison vacuous, and a vacuous parity run is indistinguishable
  from a clean one at the output. The adopting project ruled a manifest-sourced oracle out on
  exactly this ground on 2026-08-23, before this mechanism existed: a conformance instrument whose
  failure mode is *looking clean* is worse than none. **The rule that avoids it is the one
  inherited rather than invented — the oracle prints what the code does, and the declaration is a
  separate statement about it.** Nothing here can check which of the two an oracle really did.
- **accepted** · **~~A parity comparison has no place to put a declared translation.~~ It has one
  place, and one is the limit.** Closed 2026-09-13 with the per-entry value form:
  `[parity.translate]` takes a `map`, or a `pattern`/`replacement`, applied to the **declared** side
  of whatever the comparison is — the identifiers when no `field` is named, the values when one is.
  The capability was never missing; an oracle can always print whatever the declaration spells.
  What was missing is that there it is invisible, and a reader of the config cannot see that a
  comparison is not literal.
  ⚑ **“Exact after at most one declared, single-purpose translation” is withdrawn as a
  characterization of real rows** (2026-09-14). It was that adopting project's own phrase, reached
  over **three rows they had chosen as worked examples**, and this entry generalized it to what
  projects need. They then diffed a whole declaration of theirs — **89 identifiers composed from
  the code against 100 rows in the manifest: 74 agree, 15 code-only, 26 manifest-only** — and
  withdrew it themselves. **The 41 is the symmetric difference, 15 + 26**, and the two denominators
  are 89 and 100; it is not a share of anything, and in particular not of the 125 functions
  measured elsewhere, which counts test functions rather than identifiers. Their reproduction
  command is published with the measurement.
  ⚑ **There is no declarable form for 41**, and hiding them inside the oracle command is precisely
  what the paragraph above says a reader cannot see. So the limit is not *one translation instead
  of two* but **one translation instead of a spelling convention**: their divergences are a scope
  prefix the manifest writes and the code does not, a discriminated leaf the manifest spells out,
  and families the code recognizes by regex rather than enumerating.
  ⚑ **A fourth cause is not a spelling divergence at all** and is worth separating, because no
  translation form whatever would reach it: a **parametric row with no code-side member**. That one
  is the registry's addressing, not the comparison's notation.
  ⚑ **And the sharpest consequence is structural rather than a matter of degree.** The translation
  has one target, chosen by whether `field` is declared — so a comparison that names a `field`
  translates the **values** and compares the **identifiers raw**. Membership runs either way and is
  not made optional by a value declaration, which is deliberate; but it means a declaration whose
  identifiers need a spelling map and whose values need comparing has **no form for the first
  one at all**.
  ⚑ **“No real row has needed two” was already false when it was published**, by a measurement in
  this project's own records rather than by the one above: of an adopting project's five translated
  rows, one needs two — a reference hop *and* a segment substitution — and the characterization
  held for four of the five. Two measurements, different units, falsifying one sentence from two
  directions.
  **What it would take:** a form in which a declaration can carry more than one translation without
  becoming a pipeline nobody can read, or a project-supplied normalization named the way
  `[[shape]]` and `[[interpose]]` already let a project name a predicate — visible in the config as
  a target, which is the property the oracle-command workaround gives up. What it would **not**
  take is fuzzy matching, which remains refused: the failure that matters here is the permissive
  comparison, and every loosening is a step toward one.
- **accepted** · **Parity records which side is authoritative and cannot enforce it.**
  ⚑ **Half-closed 2026-09-13.** A `[[parity]]` comparing values must declare `authority`, and a
  divergence says what it means — *the declaration is the expected value and the code is on trial*,
  or the reverse. That was the missing half: for some rows this is a real property rather than a
  convention, and where a manifest cell is the expected value a divergence is an approved-breakage
  question. **What no declaration can do is stop the authoritative side being edited to make the
  finding go away.** That is a *reminder* in the sense `docs/structure.md` §1 uses, with the same
  answer the baseline has — it is a visible change to a committed file, and a form that lets either
  side be quietly fixed to match the other has lost what the check existed for.
- **accepted** · **A cell holding a container blocks the value comparison for the whole registry,
  not for its row.** A dict or a nested list has an internal order and a spelling no two sides agree
  on by accident, so it is refused rather than rendered — and refusing only the row would leave a
  run reporting divergences for everything else while silently not checking that one, which is the
  failure this package is about. **Measured cost, from an adopter: 18 of their 66 rows hold a
  dict**, so a single one of them stands the whole value half down.
  ⚑ **What it no longer costs is the membership answer.** Until 2026-09-14 the blocked return threw
  that away too, contradicting this project's own rule that a value comparison runs *on top of*
  membership and never instead of it. Membership now rides along with the block.
  **What it would take:** a declared rendering for containers — an order and a separator the
  declaration states rather than the tool guessing — which is a form question, not a missing
  capability.
- **accepted** · **~~`field` is a single-key lookup, so a nested cell cannot be named.~~**
  **Closed 2026-09-15**, in the form this entry specified: `field = ["default", "primary"]` is a
  path, and a bare string stays exactly one key however many dots it holds. The same spelling reaches
  a `[[shape]]` rule's `field`, `present` and `absent`. **A path descending through a scalar, or
  reaching nothing, reads as *no value declared* rather than raising** — a table mixing scalar and
  nested rows is the case it exists to read, and 47 of the adopter's 99 manifest rows are the scalar
  half against 18 that are mode-keyed.
  ⚑ **What is left is the half a path does not touch:** the flat reading of a dotted string is still
  not obvious from the spelling, and a config written as `field = "default.primary"` against a nested
  cell still reports every identifier as declaring no value rather than refusing. **That is
  deliberate, not an oversight** — the two spellings are kept independent so a declaration written
  before paths existed cannot change meaning under one.
- **accepted** · **An absent field and a field declared null are indistinguishable**, so *"this is
  an absence on both sides"* cannot be stated. Both read as the entry declaring no value, and an
  adopter whose manifest uses an explicit `null` to mean *this arm is deliberately nothing* has no
  way to say it. **What it would take:** reading presence rather than value on the declared side,
  and a spelling for *the oracle printed nothing here* on the other.
- **accepted** · **One registry, one `[[parity]]`**, so a project comparing three fields of one
  declaration needs three registry views of it. Refused rather than allowed because two oracles on
  one registry share a baseline scope and their records could not be told apart. **Measured cost,
  from an adopter: one extra view added 101 lines to `ids`.** **What it would take:** a scope that
  names the field as well as the registry and the direction, which the value direction already
  half-does.
  ⚑ **`where` makes a view cheap to *declare* and does not make it cheap to *carry*** (2026-09-15).
  The projection cost above is unchanged, and this limit is not closed by it — a project comparing
  three fields still declares three views, it just no longer has to hand-build each one.
- **accepted** · **~~Membership cannot be filtered.~~** **Closed 2026-09-15** with `[[registry]]
  where`, in the form this entry named: the `[[shape]]` guard vocabulary, `Condition` or project
  predicate, selecting which entries a view carries. Measured on an adopter's 99-row manifest
  against an oracle covering 10 of them: **93 findings to 9**, and the 9 that remain are rows that
  view really does declare and that oracle really does not produce.
  ⚑ **It narrows the registry, not the check** — so membership keeps its exact meaning (*the
  registry is the set*) and the scan, `undeclared`, `shape` and `unused` all see the same view.
  Putting it on `[[parity]]` was weighed and refused: it would make *"and there is nothing else"*
  subset-relative for every adopter, and two narrowed parities would share
  `parity:<registry>:<direction>`, so one's `--prune` would delete the other's records.
  ⚑ **What is left, and it is the cost rather than an oversight:** a project now states several
  views of one document, and **nothing checks that they agree with each other**. `where` is also
  refused alongside `closed` — a closed subset would call every identifier of an excluded row
  undeclared — so a project wanting both must close the whole view.
- **boundary** · **A baseline is an allowlist.** An agent can silence a finding by re-recording
  it. What makes that survivable is that it is a committed file change, visible in review.
- **boundary** · **`[[gate]]` verifies text presence, not execution.** Blind to a step disabled by
  `if:`, a job nothing triggers, or a command that runs and checks nothing. It does not parse
  YAML.
  ⚑ It is also the only declaration available for *"this command must still work"*, which is a
  different claim from *"this check must run"* and is counted in the same number. Deliberate — the
  inventory asks whether every declared command is still run here, and that question is the same
  for both — but a reader of `gates: N of N` should know the count mixes them.
  ⚑ **And the count measures declared *gates*, never declared *checks*** — numerator and
  denominator come from the same place, so a section kind with no gate row runs nowhere while the
  line reads green. Reported by an adopter 2026-09-16, whose five `[[shape]]` blocks and three
  unrelated gates printed `3 of 3`. **The `ungated:` line beside it is the cover**, and it is a
  warning rather than a failure: the declaration may be run by hand, and failing would force
  either real CI wiring or deleting the declaration to satisfy its own inventory.
  ⚑ **Reading what a step *does* is a different instrument** — a YAML parse plus a model of the
  runner, which would then be a second model of CI that drifts from the real one. Declined on that
  basis rather than on cost, and the mirror-image hole in branch protection is the entry below.
- **boundary** · **`context` bounds bytes, not attention.** It measures what you *declare* is
  loaded; the flattening is a model of a harness, not the harness.
- **boundary** · **A CI workflow in the repository is editable by the agent it constrains.**
  Branch protection
  with the jobs as required status checks, and bypass disallowed, narrows this — but it catches
  a required job that **disappears or is renamed**, not one that still runs and checks nothing.
  `[[gate]]` has the mirror-image hole. Neither is a guarantee, and where the agent has no push
  credential at all, the credential's absence is already the stronger boundary.
- **boundary** · **A dead external link is `404`/`410` and nothing else.** The `url` kind closed the gap where
  a scheme-carrying target was skipped entirely, but what replaced it is narrower than "the link
  works": a page that now redirects to a parking domain answers `200`, and a host that refuses
  an unfamiliar client answers `403`, which this reports as unchecked rather than dead. It
  settles *gone*, not *good*.
- **boundary** · **The catch is dogfooded here only through the bibliography.** ⚑ The mark covers
  the *scope statement* below — Catch A reaches registries whose entries are members of a
  describable namespace — which is permanent. It does **not** cover `python-constants`, which the
  same entry calls a deliberately unclosed gap; that one is **accepted**, and a project that
  declared a narrowing would close it. Two dispositions in one entry, said out loud rather than
  averaged into one mark. `code-patterns` and
  `substitutions` cannot recognize their own identifiers and so cannot be closed; until a
  bibliography was declared, `kinemata undeclared` refused in this repository rather than
  reporting a false clean. A reference key *is* recognizable — that is what the stamp's
  delimiters buy — so the bibliography answers, and the one finding it reports is real:
  `docs/citations.md` illustrates the form with a key this project has no entry for. The
  registry is **closed as of 2026-09-10**, and what unblocked it is the reason it could not be
  before: closing it would have turned that example into a failing gate, until `match_mode =
  "unfenced"` taught the scan that a fenced block is display rather than use. So an undeclared
  reference key exits 1 here, which is this repository's first real closed-world catch.

  ⚑ **Settled 2026-09-13, because "cannot be closed" had sat here as an open gap while two of the
  three cases are permanent.** Catch A asks a *membership* question — is this identifier one of
  the namespace's members? — and answering it needs a namespace with recognizable syntax plus an
  authoritative membership list.

  * **`code-patterns` and `substitutions` are a boundary, not a gap.** Both are **negative**
    registries: they declare what must *not* appear — a shape to avoid, a spelling to replace —
    and the complement of "not a forbidden spelling" is every other string in the language. There
    is nothing to enumerate, so there is no membership question to ask. Their entry ids are names,
    and a syntax over those names would recognize the wrong thing: an entry names a value's
    canonical *home*, while what the scan matches is the value. **Neither will ever be closable,
    and that is a property of the data model rather than a missing feature.**
  * **`python-constants` is a gap, and a deliberately unclosed one.** A constant name is
    recognizable, so `candidates()` could be implemented. The namespace is what stops it:
    SCREAMING_CASE is shared with the standard library, every dependency, and every module the
    registry does not list, so closing it would report `os.O_RDONLY` and an enum member in an
    undeclared file. This project already measured what that costs — the permissive keyspace
    syntax on kanibako-cli gave 48,685 findings raw and 7,266 in string literals, **neither a
    usable gate.** A project wanting it closed would have to declare a narrowing, and none has
    asked.

  So the honest scope of Catch A: **registries whose entries are members of a namespace the
  project can describe.** Keys and reference keys are; code shapes and forbidden spellings are not.

  ⚑ **A recognizer stopped being the only route on 2026-09-13.** The membership question is also
  what `kinemata parity` asks, and an oracle needs no `candidates()` because it does no searching
  — so the *dependence on a recognizer* is a property of the static catch rather than of the
  question. No disposition above moves, and the reasons differ: `code-patterns` and
  `substitutions` stay a **boundary**, since a negative registry has no membership list for a
  command to print either; `python-constants` stays a deliberately unclosed **gap in the static
  catch**, because the shared namespace is what makes scanning a tree for stray SCREAMING_CASE
  unusable and parity never scans the tree. What a project gets for `python-constants` today is
  the other question — *does this declaration equal the set the code produces* — answerable
  without closing the registry at all.
- **accepted** · **~~Text a project carries but did not author can only be excluded.~~** A vendored licence or a
  policy adopted as received cannot carry a stamp, because stamping it means editing text that is
  not the project's to edit — so its citations were findings the project could never drive down,
  and `[project] exclude` was the only answer. **Partly closed 2026-09-11** by the resource list:
  a document declared under `[citations] resources` is dated in the list rather than in its own
  prose, which is exactly what text you may not edit needs. What survives is the choice, and it is
  a real one: `exclude` drops the file from every check, a resource entry keeps the claims check
  over it and relocates only the date. This repository still excludes its two verbatim documents,
  because a dead link inside a licence is not its to fix either.
- **accepted** · **A resource entry dates a whole document, not a citation.** A citation added after the last
  confirmation sits under a date that predates it. The unit was chosen deliberately — citation- or
  target-level entries would copy into a registry the facts the documents already state, which is
  the duplication this tool reports — and the cost is bounded rather than absent: the claims check
  settles every citation in those documents on every run, so the entry records a verification and
  is not what keeps the citations true. Requiring the entry's date to be no older than the file's
  last commit would close it and was rejected: every documentation commit would then demand a
  re-confirmation, including the ones that touch no citation.
- **boundary** · **The tree walk follows symlinked directories and says so.** Each directory is
  entered once by real identity, and a link leaving the tree is announced on stderr. Before
  2026-09-08 it did not follow them at all, and a project reached that way scanned as empty.
- **accepted** · **Run against two projects it did not grow up on** (`psf/requests`,
  `httpie/cli`), 2026-09-09. 756 documentation claims, 5 reports, **none true**; one `check`
  finding on httpie, and `clusters` findings that were real. `requests` has no module-level string
  constants at all, so the default adapter bound to nothing and the registry was refused as empty.
  Seven defects came out of it, all boarded. **Two projects is not a survey** — both are
  widely-used Python libraries with careful documentation, which is the easy case for a claims
  checker.
  ⚑ **This is the one entry on the list that more work would simply fix**, and it is marked
  `accepted` rather than `boundary` for exactly that reason: nothing about the model limits the
  sample, only effort has. The corpus is kept so the run can be repeated. **Treat every figure
  above as measured on the easy case** — a project with sparse or stale documentation is the case
  nobody here has run, and the claims checker is the mechanism most likely to behave differently
  on it.

### Found by the first outside audit, 2026-09-09

An adopting project ran this over three of their repositories and inventoried their existing
conformance suite against it. Everything below was **re-verified here** before being written
down, and the two shapes at the end are the findings that matter most.

**What the model does not reach:**

- **accepted** · **~~The registry mechanism is purely negative.~~ The registry *scan* is.**
  ⚑ **Marked `accepted`, not `boundary`** — the polarity is a property of *that mechanism*, not of
  the tool, and the twin was reachable by an instrument nobody had built rather than by one that
  cannot exist. Marking it permanent is the mistake this whole section was corrected for on
  2026-09-13; the instrument was built the same day, which is the argument for the mark rather
  than a coincidence beside it.
  The scan expresses *"this value must not be re-spelled
  outside its home"*, and under negative polarity agreement produces a finding while disagreement
  produces silence. Of 326 conformance checks in that project's suite, **291 were not expressible
  (89%)**, and this shape was the single largest reason — 125 test functions across four
  manifest-parity files.
  🛑 **That share is dated 2026-09-09.** It predates `parity`, `[[interpose]]`, `shape`, the adapter
  widening and `[[probe]]`, several of which closed reasons listed in this very section. **Read it
  as what that audit found, not as what this tool cannot express today** — the entries below carry
  the current state, each marked where it moved.
  ⚑ **A newer inventory by the same adopter exists, dated 2026-09-14** — 378 test functions in 213
  check-families against a later build — and **they ask that the two not be compared**: the
  denominator changed, the corpus boundary was drawn fresh, and the buckets differ. A successor, not
  a replacement, and not a before-and-after in either direction.
  ⚑ **The 125 named in the sentence above have been re-measured, and they are the one population
  this project holds: 103 of 125 (82%) are expressible as things stand**, against 53 (42%) on the
  morning of 2026-09-14 — the movement being `shape`, the widened adapter, `[[probe]]`, and then a
  path-valued `field`, `[[registry]] where` and `[[parity]] relation` on 09-15. **Reach, not
  adoption** — it says what could be expressed, never what anyone has declared, and this adopter
  has declared none of the last four.
  ⚑ **The twin is expressible for a value a document states, and was already** when this entry
  said it was not: a `[[count]]` declares the pattern, an oracle command and an exact comparison.
  ⚑ **Partly closed 2026-09-13. This entry said the twin aimed at declared data had no expression
  — "the empty quadrant" — and the cell it meant was the one `[[count]]` was already sitting in.**
  `kinemata parity` now sits there too: a registry's declared identifiers against the set an
  oracle says the code produces, both directions, gating on either. **What it closed first is
  membership**, the half of that project's 125 manifest-parity test functions needing no new
  surface on `Entry`.
  ⚑ **Narrowed again 2026-09-15 by `[[parity]] relation`.** *"Both directions, gating on either"*
  was the only claim membership could make, so a declaration that legitimately names more than the
  code produces, or that says what the code must **not** emit, could be run only by accepting the
  difference into the baseline — an exemption list standing in for a claim. `declared_contains`,
  `produced_contains` and `disjoint` say it instead. **What is still out of reach is a comparison
  that is neither equality nor membership**: an **ordering** (a list is compared as a set, on
  purpose), an **inequality**, and a second declared **translation**. Three conformance rows in the
  measured population, one each.
  ⚑ **The other half — a declared entry's *field* against what the code prints for it — landed the
  same day**, with the translation and the authority marker the same project's worked rows asked
  for. **The entry stays open and `accepted`**, and what is left is of two different kinds. One is
  a row whose fact is *the outcome of an execution*, reachable only by constructing inputs through
  that suite's own fixtures; there is no product-only command that prints it, so it belongs to the
  run-time entry below rather than to this one. ⚑ **The other is a missing declaration form after
  all** — this clause said it was not, on the strength of the same three worked rows, and the
  translation entry above carries the measurement that corrected it.
  `docs/structure.md` § The second axis is where the mechanism is classified.
  ⚑ **How much of the 125 that is, is measured as of 2026-09-14: seven functions, 5.6%** — every
  one of them classified, not sampled. This entry said the figure had not been measured, which was
  true for a day. **It is the smallest of the three classes that measurement found and the most
  expensive to reach**, and the largest — rules a declaration states about *itself* — was not on
  this list at all until the same measurement put it there, two entries below.
- **accepted** · **~~Nothing here observes a running program.~~ One thing does, and it sees one
  declared funnel.** Closed 2026-09-14 by `[[interpose]]`: a callable the project names is patched
  for the length of its own test session, every identifier crossing it is judged against a declared
  registry, and an identifier nothing declares fails the run. The mark stays `accepted`, and what it
  now covers is everything *else* a running program does — what a request handler emits under load,
  what an ordering constraint holds to, anything not funnelled through a single call a project can
  name. **This mechanism observes; it does not arrange.** It cannot construct the inputs that make a
  fact exist, so a conformance row whose fact is the outcome of an execution reachable only through
  a test's own fixtures is still out of reach — and that is one of the three worked rows an adopting
  project supplied.
  ⚑ **Narrowed 2026-09-14 by `[[probe]]`, which does not arrange either but is *handed* its cases.**
  A fact needing constructed inputs is reachable when the project's own case supplier can build
  them; what stays out of reach is the arrangement that cannot leave the test module. See that
  entry below for the measured size of what is left.
  ⚑ **It is a reminder, not a catch**, in the sense `docs/structure.md` §1 uses: the plugin is
  loaded by the adopting project's own test configuration and the funnel is named in its own
  `kinemata.toml`, both editable by the agent being constrained. What it buys is **reach** — over an identifier assembled
  internally, which never appears as a literal and crosses no boundary a static check guards — and
  not enforcement against someone determined to remove it.
  ⚑ **Two of its ways of looking clean are reported rather than assumed away.** A funnel that could
  not be patched **fails**, the blocked-oracle rule. A funnel nothing crossed does **not** fail —
  running one test file is ordinary, and failing it would teach people to unload the plugin — but
  the crossing count is always printed, because a run that observed nothing must not read like a run
  that found nothing. **The check's coverage is the suite's coverage**, which is a real limit and
  belongs to whoever reads its output.
  ⚑ **A set-level judgement reaches one test, and a cross-test one is refused rather than
  unbuilt** (2026-09-14). An adopting project asked for a hook consulted before findings, handed
  the whole judged set — their case being a container rescued by what was written under it. Within
  a test that is already expressible and was not known to be: `identify` may keep state and may
  defer its answer to the drain, so the judgement is written as a model of what an identifier *is*
  rather than as an override of a verdict, which is the distinction that decided this. **Across
  tests it is not expressible, and a verdict that turns on what another test wrote is not a verdict
  a run can reproduce** — run that test alone and it flips, and under one process per file it turns
  on which file the writes landed in. ⚑ **The hazard is live without any new surface**: an
  extractor whose state outlives a test gives the same two writes different answers in different
  orders, measured both ways. **Nothing can detect it** — `identify` is the project's code — so it
  is published here and stated beside the key rather than checked.
  ⚑ **Marked `accepted` rather than `boundary` on 2026-09-13**, the day before it closed. An adopting
  project asked directly whether an execution-time mechanism was ever coming, and the answer was that
  one **can certainly be added** (user, 2026-09-13). **The mark this entry carried before that said
  the opposite**, `boundary` having then been defined as permanent — which is the entry that started
  the definitions above being rewritten, and the clearest case this list has that a disposition is
  about instruments rather than about the model.
  ⚑ **This entry said *"everything here is static"* until 2026-09-13 and that was never true of
  the whole tool.** `claims` runs `git`, reaches the network, and runs whatever command a
  `[[count]]` declares — since 2026-09-05, four days before the audit that reported the tool as
  entirely static. It was taken on report rather than measured. `structure.md` § The second axis
  now classifies each mechanism by polarity and by what it observes, and that classification is
  **selectable by a project, not a ceiling on the tool.**

- **accepted** · **~~A fact that is an acceptance or a refusal, rather than a value, has no
  expression here.~~ `[[probe]]` expresses it, as of 2026-09-14.** Measured across the same 125
  functions, **15 of them assert nothing else**: a predicate refuses a denied entry, a key one
  segment past its family is not a key, an uncovered destination raises. No oracle reaches these,
  because there is no value to print — the fact *is* the outcome. A probe declares a target, a
  corpus of cases the project supplies, and how the answer is read; kinemata calls the target and
  compares the observed polarity to the declared one.
  ⚑ **It moved a boundary this project had stated**, and the sentence is worth naming because it was
  shipped: *kinemata executes oracles about a project and never the project under observation.*
  A probe **calls the subject directly**. `docs/structure.md` § The second axis carries the column
  that added. What survives is narrower and is the part that was load-bearing: kinemata never runs
  the project's suite or entry point, and it never classifies an outcome by reading output.
  ⚑ **There is deliberately no escape to a project-supplied predicate for reading an outcome**,
  though `[[shape]]` has one for describing a row. A shape predicate supplies a model of what a row
  *is*; an outcome predicate supplies *the judgement*, and a wrong classifier reports agreement
  between itself and a wrong declaration. **So an outcome convention neither `raises` nor `returns`
  can read stays in the project's own tests** — that is the cost, stated rather than papered over.
  ⚑ **A corpus carrying one polarity fails**, which is the property the mechanism is for: a
  refusal-only corpus is satisfied by a callable that refuses everything. kinemata counts the
  polarities on the rows it was handed, so the count is never self-reported. It is also not a
  finding the baseline can accept — a run that could not discriminate has not earned a `--prune`.
  ⚑ **Which refusal, not only whether — `exact`, since 2026-09-15.** `except` matches subclasses, so
  a declared base admits every refusal beneath it. That is the right reading where a base means *any
  of these is a refusal*, and the wrong one where refusals are **named and load-bearing**: an
  adopter's closed keyspace refuses an undeclared key by name, their retired-key paths refuse by
  name, and a version skew and a capability limit are different refusals that must not read as each
  other. Without it a probe tells accept from refuse but not *which* refusal, so a wrong-but-related
  error reports agreement — the permissive-oracle hazard the two modes exist to prevent, one level
  down. **Opt-in, because the subclass reading is the published behavior and a deliberate one**; a
  subclass then blocks the case by name rather than passing quietly.
  ⚑ **It is a reminder, not a catch.** An agent can edit a case list and the code it probes in one
  commit. And **its reach is exactly its corpus** — a probe says nothing about an input nobody
  wrote a case for, where the interposition says something about whatever crossed. Neither
  subsumes the other.
- **accepted** · **How broad a `refusal` may be is the project's judgement, and only the root is
  policed.** `except` matches subclasses, so a `refusal` naming a base class reads every subclass as
  a refusal — measured on an adopting project's tree, where a base two levels above the real error
  still passed every case. `Exception` and `BaseException` are refused outright, because at the root
  it stops being a judgement: every failure is one, so a renamed function or a broken import would
  read as the code correctly refusing. **Anything narrower is not checked**, and a project that
  declares a base wider than it means gets a weaker probe with no warning.
- **accepted** · **A probe arranges nothing; it is handed what to pass.** The construction lives in
  the project's case supplier, which is right — only the project can build its own objects — but it
  means a fact that exists only inside a test's own fixtures, with no way to rebuild the inputs
  outside that test, is still out of reach. ⚑ **This narrows the entry above rather than repeating
  it**: the interposition cannot construct inputs *at all*, where a probe's project-supplied corpus
  can, so the shape still unreached is the one whose arrangement cannot leave the test module.
  Measured at **7 of 125** functions in the suite this was drawn from — the smallest class in it,
  and the most expensive to reach.

**Where a declaration cannot say what a project means:**

- **accepted** · **~~Nothing checks a declaration against its own shape.~~ `[[shape]]` does, as of
  2026-09-14 — and this limit was never on this list until the measurement that closed it.** An
  adopting project's registry is a hand-maintained YAML whose rows agents edit, and **31 of their
  125 manifest-parity functions — the largest class of the lot — assert things about that document
  rather than about the code**: an entry's field set, a value against a declared vocabulary, an
  axis that must stay a cross product, a flag required only when another field says so. None of it
  was expressible here. `kinemata shape` states each as a rule with a **guard** and a **claim**,
  either of which may be a predicate the project names.
  ⚑ **It is a reminder, not a catch**, in the sense `docs/structure.md` §1 uses, and for the same
  reason `[[gate]]` is one: the rule and the row it governs are both editable by the agent being
  constrained, in one commit. What it buys is **reach** over a mistake nothing else here can see,
  not enforcement against someone determined to remove it.
  ⚑ **A predicate that answers True for everything is undetectable, and saying so is the honest
  half.** What *is* detected is a rule that examined **no entry**, which fails rather than
  passing — the group is this tool's to count, so vacuity there is caught here instead of being
  self-reported by the code under examination. The verdict is the project's, and a rule that never
  judges anything false looks exactly like a declaration in good order. `test_shape.py` asserts
  that limit rather than papering over it.
  ⚑ **What the rule language does not reach is the *addressing*, not the rules.** A rule can only
  speak about entries a registry produces: of the 31, **9 were addressable when the adapter took
  one top-level section, a section path reaches 18, and a two-level flatten 28.** The last 3 are
  not shape rules at all — they ask whether a section exists, which declaring the registry already
  answers, because a missing section is refused at load. **That is an adapter limit and it is
  measured**, not a guess about what adopters will want.
  ⚑ **Closed as of 2026-09-14, both halves.** `section` takes a path — a list of keys, not a dotted
  string, since a dotted string cannot express a key containing a dot and the loader would be
  guessing which of two splits the project meant over a file it did not write. And `flatten` with a
  declared `separator` composes an identifier out of two key levels, so a cell of a matrix is an
  entry a rule can speak about. **What that costs every consumer of a registry is documented where
  the key is introduced**, and it is not nothing: a composite identifier does not occur in the code.
  ⚑ **One residual is the rule language rather than the adapter, and it has its own entry below.**
  Recorded separately rather than quietly reclassified, because the adapter reaches exactly what the
  measurement said it would.
- **accepted** · **A rule speaks about the selected set, not about each group within it.** With a
  flattened registry every cell of a matrix is an entry, so a rule can claim something about *all*
  cells. *"Every row's columns are exactly the relations axis"* is a claim about **each first-level
  key's group**, and there is no per-group set operator: a rule has one guard and one claim over
  whatever the guard selected.
  ⚑ **Measured rather than estimated, because the number decides whether it is worth building: of
  the 10 rules needing a flattened view, exactly one needs grouping** —
  `test_every_row_carries_exactly_the_relation_columns`, which is parametrized per row and asserts
  the row's column set equals a declared axis. One of the 28 reachable rules overall.
  **All ten were read in source**, not classified from a summary line; the first pass here read two
  and inferred the rest, which is the sampling error that once turned 62% into 31%.
  ⚑ **What the full read added: three of the ten are *cross-section*** — a claim about cells
  checked against a list of refusals elsewhere in the same document. Those are reachable, but
  through the project-supplied predicate rather than the rule language, which is a weaker thing to
  be able to say and is said here rather than rounded up.
  ⚑ **The near-miss is worth naming, because it looks like a second case and is not.**
  *"`append` appears on copy rows only, and somewhere"* collects the first-level keys of every cell
  holding one value and asks whether they sit inside a named set. That is a claim about each
  entry's identifier plus a non-emptiness claim, both of which a rule states today — the second
  being exactly the anti-vacuity check `shape` already performs.
  ⚑ **So this is undone rather than unreachable, and deliberately undone at one measured rule.**
  What it would take is a way to partition the selected entries and apply the claim per partition,
  with vacuity counted per group rather than once — the group key coming from a project-supplied
  predicate, on the precedent the tier-4 escape already sets, rather than from an expression
  language this package has refused once already.
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
- **accepted** · **Registry scoping is inverted, with no exception.** Entries fire everywhere
  except `home`; there is no "fires only inside this one file", which is what an import-discipline
  check needs. Nothing about the model prevents the inverse scope. ⚑ **"Nobody has needed it
  enough" until 2026-09-13**, when an adopting project named the check it needs one for — that
  their bootstrap module stays import-free. One named need is not a queue, so the mark does not
  move; what changed is that this entry can no longer justify itself by saying nobody asked.
- **boundary** · **A `yaml-mapping` registry contributes nothing to `check`.** Its entries carry
  no antipatterns, so a green `check` over a mapping registry is not coverage of the mapping.
  **Declared data has no shape to re-derive** — that is a property of the kind, not a gap.
- **accepted** · **Precision is Python-shaped, and declaring a suffix does not say so.** The
  filters and the literal extractors in `prose.py` are keyed by suffix, and `.py` is the only key
  any of them carries. A registry pointed at `.yaml`, `.sh` or `.toml` therefore gets raw line
  matching — no comment stripping, nothing that knows where a string literal ends. Scanning an
  unknown language whole over-reports rather than under-reports, which is the safe direction for a
  catch and is deliberate. **What is not obvious from the knob is the second half: the strong/weak
  split is computed only on the path where an extractor ran**, so on every other suffix a match
  takes the default strength, and the default is `strong`. The weak tier does not exist outside
  `.py` — a substring hit in a YAML comment is a gating finding, and `suffixes` gives a project no
  way to say otherwise. Reported by an adopting project 2026-09-13 against the published package
  and confirmed here.
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
- **boundary** · **`[[gate]]` cannot express ordering** — only that a command's text is present
  and uncommented. The same root as the `[[gate]]` entry above: reading what a workflow *does*
  needs a model of the runner, which would be a second model of CI.

**Where `claims` is narrower than its knobs suggest:**

- **accepted** · **The extractors are markdown-syntax-bound, and `suffixes` does not say so.** A format that
  does not share it — YAML, plain text — is read and contributes **zero claims**; a declared
  suffix that settles nothing is now named on stderr rather than passing in silence.
  **~~A format that shares it worked by coincidence.~~** True until 2026-09-10: reStructuredText
  spells an inline literal as a doubled delimiter, whose inner pair is itself a markdown span,
  so the token inside fell out of a single-backtick pattern. The delimiter run is matched
  deliberately now, and `.py` is a supported suffix rather than an accident.
- **~~Docstrings are scannable and this repository does not scan them.~~** True until 2026-09-11,
  when `[claims] suffixes` gained `.py` here. ⚑ **This entry went on asserting the opposite for a
  day, in four separate sentences** — the headline, "the suffix stays off", "arming it here has not
  been taken", and a residue of 10. Measured 2026-09-12: `claim_suffixes` is `('.md', '.py')` and
  `kinemata claims` reports **78 claims, all resolving, with zero accepted in the baseline** — so
  the residue is not 10 but **none**, and the open question below was answered rather than left.
  **The sixth stale entry found in this section**, and the reason the list is re-read whenever a
  limit closes: nothing can catch these, because a limit is not a falsifiable claim, and the
  failure direction is the bad one — it understates the tool to the adopter reading it to decide
  what kinemata can express.

  **What closed it** was not a decision to accept the residue. The ten unresolved were real
  citations of other projects' trees, absent from a clean clone; nine are now declared in
  `docs/bibliography.toml` under the `Px`/`Cx` codes with the owning repository named, and the
  tenth was not evidence at all. That is the *"reach that evidence some other way"* branch below,
  taken.

  The measurement that made the case is kept because it is the argument, not the state. Measured
  2026-09-10 by
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
  are gitignored here and absent from a clean clone, which was the reason the suffix stayed off
  while it did.

  **The claims ratchet was built for that residue** and was demonstrated on a scratch copy — 11
  findings recorded, green, then red on a single new dead docstring reference. ⚑ **It was not
  needed in the end, and that is the better outcome:** declaring the nine citations resolved the
  residue to zero, so the suffix is armed here with **no exemptions at all**. An accepted set of
  zero is the stronger position, because every exemption is a thing a later reader has to
  re-derive the reason for.
- **accepted** · **`suffixes` reaches `[[count]]` as well**, which was the sharper reason not to arm it *before
  the illustration role existed*. ⚑ **Corrected 2026-09-12 with the entry above: the suffix is
  armed, so this reads as a live objection when it is a settled one.** The case was: the
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
- **accepted** · **`~`-prefixed paths are skipped entirely.** For a documentation tree that writes
  cross-tree pointers as `~/...` — which canon-style trees do — most pointers are invisible, so a
  clean run is a floor rather than a measure. Expanding them is buildable; what stops it is that a
  `~` path resolves differently for every reader, so a claim about one is not a claim about the
  tree.
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
- **accepted** · **`historical` is a path axis, but a changelog's currency varies by section.** A
  live `[Unreleased]` entry and an honest historical record in one file cannot be separated by
  config. A finer axis is buildable and nobody has needed it; this project's own changelog is one
  line per release, which does not reach the problem.
- **~~`[context] include` accepts absolute paths, absolute globs and `../` escapes~~** — but by
  accident of two library behaviors rather than by contract, and nothing validates containment.
  **Decided and contracted 2026-09-13**, in the direction of keeping the capability rather than
  refusing it: an adopter had a real, measured use for the escape — weighing an assembled
  instruction file that lives outside any repository — and an assembled file is exactly what a
  ceiling most wants to weigh; a `context` that cannot see it is measuring the wrong thing.
  ⚑ **The byte figure that used to sit in this sentence has been withdrawn by the party who
  measured it** (2026-09-13): it came from a session whose artifact is no longer available, so it
  is **re-derived if it is ever wanted again, never re-quoted.** The decision never rested on the
  size — only on the file existing and being outside the tree — so the argument is unchanged and
  the number is gone rather than updated. *A number that has stopped being measured is not a
  number*, which is their formulation and a better one than this project's own rule about counts
  with no oracle.
  **`include` is now contained and refuses an escape; `[context] external` is the escape and
  refuses a contained pattern.** Both refusals are symmetric, because a one-way rule would leave
  `external` accepting in-tree patterns and the report calling bytes that never left "outside".
  The check is **syntactic** — absolute, or carrying a `..` segment — so it is decidable when the
  config loads and verifiable by anyone reading the line; resolving first would accept
  `/home/me/project/docs` on one machine and refuse it on another.
  ⚑ **Two things this does *not* close, stated because the gap is narrower than the fix looks.**
  A relative pattern reaching a **symlinked directory that leaves the tree** is not refused, and
  must not be — following symlinks is what fixed an under-count this ceiling already had. Such a
  file is labeled from its resolved path instead, so the bytes are reported honestly while the
  declaration still looks contained. And an absolute pattern in `external` may resolve back
  *inside* the root; that is allowed, and the label is measured rather than assumed for exactly
  this reason. **The report says how many bytes came from outside and deliberately does not say
  which key declared them** — it claimed `[context] external` and was wrong the first time a
  symlink was pointed at it.
