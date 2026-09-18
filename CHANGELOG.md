# Changelog

What changed between released versions, for a person reading it.

**An entry is a list of what changed.** The first release was a single line, on the stated
condition that this would grow when there was a reader for it to grow for — and there is one now:
a project outside this repository runs against kinemata and upgrades between published versions.

Commits are in `git log`; the reasoning behind a design decision stays in the document that
carries the decision. A changelog repeating either becomes a second carrier and goes stale.

## Unreleased

**New**

- `kind = "toml-value"`: a registry whose entries are the **values** a TOML file declares at a
  `path`, rather than the keys holding them. Every other adapter makes an identifier out of a
  name, which is exactly wrong when the fact being declared is the scalar. `tomllib` is stdlib,
  so this adds no dependency and no extra. A scalar becomes one entry, a flat list becomes one
  each; a table is refused with the keys that level holds, so an author who stopped a key short
  is told the way on.
- The claim it was built for, which needed no new mechanism: **the version a tree declares must
  not be one the index already carries**, as a `[[parity]]` with `relation = "disjoint"`. Between
  a release and the next bump, `pip install "pkg @ git+…@<sha>"` builds the metadata, sees that
  version already installed and **skips** — the install succeeds, the suite passes, and whoever
  was validating a fix reports back that it works having never fetched it. Two unrelated projects
  hit this independently. The reference sheet carries the recipe and the two things to get right:
  cache-busting the index read at both layers, and that this claim fails on a project that has
  never published.

## 0.1.2

**New**

- The illustration role is honored in markdown documents as well as docstrings. Two adopting
  projects needed it on the same day — one for a real file that lives outside the tree on
  purpose, one for a generic filename that must stay in backticks — and neither had any other
  permanent marking: a baseline lapses by construction and the fence cannot go mid-sentence.
- `claims` prints an `ungated:` line for each declared section no gate row runs. Declared
  `[[shape]]` blocks with gates for three other commands printed a green cover line while
  `shape` ran nowhere, because the count measures declared gates rather than declared checks.
  It warns rather than fails.

**Fixed**

- The reference sheet's pin advice named the version a plain install resolves to, which every
  release falsifies. It states the pip mechanism now and points at the index, as the README
  already did.

## 0.1.1

**New**

- A `[[probe]]` may declare `exact = true`, narrowing `raises` to the exception type it names.
  `except` matches subclasses, so a declared base admits every refusal beneath it — right where a
  base means *any of these is a refusal*, wrong where refusals are **named**: a closed keyspace that
  refuses an undeclared key by name, retired-key paths that refuse by name, a version skew and a
  capability limit that must not read as each other. Without it a probe tells accept from refuse but
  not *which* refusal, so a wrong-but-related error reports agreement. **Opt-in**, because the
  subclass reading is the published behavior and a deliberate one. A subclass then blocks the case,
  naming both types, rather than passing.

  Asked for by an adopter, on their own codebase's grounds, after we published the mutant that
  exposed it.

**Fixed**

- An **ignored directory removed files it does not name.** git's answer to *what is ignored here*
  is a real root-relative path, and it was handed to the exclusion machinery as a plain fragment —
  which matches anywhere in a path, by design, because a project's own `exclude` entry is a
  substring. So an untracked, ignored `.claude/` at the root dropped a tracked
  `packages/.../home/.claude/settings.json` from every file index, and a citation of that tracked
  file reported `path does not resolve`: a finding pointing at the prose rather than at the
  exclusion that removed the file. An **empty** directory was enough to do it, and a fresh clone
  has none — so the tool disagreed with itself between a developer's tree and CI, with the
  developer's tree the one that reds. git's paths are now anchored; a project's own `exclude`
  fragments are unchanged.

  Found and reproduced by an adopter against `0.1.0`, not here.

**What an existing config will see change**

- **Upgrading can report more, and the new findings are not new text.** Any tracked file that an
  ignored directory's name was removing is back in the index, so a scan, `claims`, `undeclared`,
  `unused` or the citation policy may now report sites that were always there and never visible. A
  project affected by this had a gate that was quietly looking at fewer files; expect to read the
  findings, then accept the ones you are not fixing into the baseline. **Nothing in this release
  reports less.**
- Whether you are affected is cheap to check: an ignored directory whose name also appears as a
  path segment anywhere under it. A project with no such collision sees no change at all.

## 0.1.0

**The first release that is not a pre-release.** What changes for an installer: while only
pre-releases existed, a plain `pip install kinemata` resolved to one, because pip skips a
pre-release only when some other version satisfies the requirement. One does now, so an unpinned
install moves here and stays on final versions from now on. The interfaces are still not settled
and the classifiers still say so.

**New**

- `kinemata probe` compares a declared corpus of inputs against what the project's own code
  accepts and refuses — a fact with no value on either side, which no oracle can print. The
  project supplies the target and the cases; how the answer is read is declared in the config,
  not supplied by the project. A corpus carrying only one polarity fails rather than passing:
  a refusal-only corpus is satisfied by a callable that refuses everything.
- **This is the first check that calls the project's own code.** kinemata still never runs the
  project's test suite or entry point, and never classifies an outcome by reading output.

- `[[registry]]` takes a `where` selector, narrowing a view to the entries it keeps. The vocabulary
  is a `[[shape]]` rule's guard — a table of operators, or a `module:attribute` naming a predicate
  of the project's own — reused rather than invented. It exists because an oracle answering for part
  of a declaration otherwise pays an `unproduced` finding for every row outside it: measured on a
  99-row manifest against an oracle covering 10, **93 findings became 9**, and the 9 are real.
  It narrows the **registry**, so membership keeps meaning *"and there is nothing else"* over the
  set the view declares, and the scan, `undeclared`, `shape` and `unused` see the same narrowing.
  A selector that keeps nothing is refused at load, and `where` may not be combined with `closed` —
  a closed subset would call every identifier of an excluded row undeclared.
- A `[[parity]]`'s `field`, and a `[[shape]]` rule's `field` / `present` / `absent`, may name a
  **path** into an entry written as a list: `field = ["default", "primary"]` reaches one arm of a
  nested map. A bare string is still exactly one key however many dots it holds, and is never
  split — `extra` keys legitimately contain them, so splitting would resolve an ambiguity by
  guessing, and a wrong guess here compares the wrong cell and passes rather than failing. A path
  that reaches nothing, or that descends through a scalar, reads as *no value declared* rather
  than as an error, so a table mixing scalar and nested rows stays readable.

- `[[parity]]` takes a `relation`, saying what the two sets are claimed to be:
  `equal` (the default, and what every parity meant before the key existed),
  `declared_contains`, `produced_contains`, or `disjoint`. Membership could previously claim only
  that the two sets were the same, so a declaration that legitimately names more than the code
  produces — a deny list, a set of rows the code must *not* emit — had to accept the difference
  into the baseline, which is an exemption list standing in for a claim and needs a re-record every
  time a row lands. Measured on a real conformance row: a deny block of eight against a code
  constant of one is **7 findings under `equal` and clean under `declared_contains`**.
  It is spelled as the claim rather than as a direction switched off, because membership otherwise
  means "and there is nothing else" and a reader has to be able to see that a parity is not
  closed-world. A relation other than `equal` **fails a run whose oracle produced nothing** —
  `declared_contains` and `disjoint` are both satisfied by an oracle with nothing to violate them —
  and cannot be combined with `field`, a value comparison needing identifiers on both sides.

**Changed**

- `kinemata review` and `kinemata check` report how many f-strings a `match_mode = "strings"`
  registry could not read. An f-string is dropped whole by the literal extractor — not merely
  its interpolated parts — so a registry matching on values is blind to every one of them and
  reports clean. The behavior is unchanged; it is no longer silent.

**Fixed**

- The advice printed for an `exclude` fragment that matched by substring suggested an anchored
  spelling derived from the fragment, which for a directory below the repository root reaches
  none of the paths printed beside it. Following it would have silently stopped excluding whole
  subtrees. The two cases are now told apart and the suggested spellings are derived from the
  paths that actually matched.
- A `[[parity]]` comparing values threw away the membership result when a cell held a container
  it could not render. The value half still blocks, as it must; the membership half is reported.
- An inline `command` or `args` written as a string — `command = "python -m tool"` — was iterated
  into one argument per character instead of being refused. The run then failed on the first
  letter and was reported as *the oracle could not be run*, blaming the project's command for a
  defect in the config; and because a blocked parity oracle stops `kinemata baseline --record`,
  the typo disarmed the writer as well. The `[command]` table already refused this; the inline
  spellings on `[[count]]` and `[[parity]]` now do too. Note that `[[gate]]` takes a string
  deliberately, so the key's name does not tell you which form it wants.
- A claim or citation was dropped without a word when a negation appeared on the line above it, or
  in the sentence before it. Two bounds were wrong. The window limiting how far back a negation
  reaches was measured separately on each line and the two were concatenated, so a 45-character
  rule looked back as far as 91; and a full stop did not end a negation's clause, so "there is no
  compatibility read. The loader is `a.py`" stopped checking `a.py`. Both are fixed, and an
  abbreviation — `e.g.`, `etc.` — is not read as the end of a sentence.
  **This makes the documentation and citation checks report more, not less.** A tree that was
  green may now have findings, and they are not new text: they were always there and never
  visible, because a dropped claim makes a check pass. On this repository the claims check went
  from 99 to 113 and six citations came out from under it, all pre-existing. Expect to accept them
  into your baseline rather than to fix them.

## 0.1.0a2.dev1

Mechanisms that did not exist in the first release, and changes an existing config can observe.

A dev build of the coming `0.1.0a2`, published to get these in front of the one project upgrading
against them. `0.1.0.dev1` would have been the obvious spelling and is the wrong one: under
PEP 440 it sorts *behind* the published `0.1.0a1`.

**New**

- `kinemata parity` compares a registry's declaration against the set the project's own code
  prints — both membership directions, and, where an entry declares a field, each entry's value
  against what the oracle prints for it.
- `[[interpose]]` watches a declared funnel while the project's own test suite runs, as a pytest
  plugin the project loads for itself. Installing kinemata patches nothing on its own. What
  crossed the funnel is recorded, clean rows included.
- `kinemata shape` asks whether a declaration is the shape it says it is — the first check here
  whose subject is the declared document rather than the code.

**Changed, and visible to a config written for the first release**

- Every config table refuses a key it cannot mean. TOML gives a bare key to the most recent
  table, so a stanza written in the wrong place used to be absorbed silently; a top-level gate
  stanza declared zero gates and disarmed the inventory rather than decorating it.
- `kinemata claims` refuses when nothing is declared for it to check, instead of checking
  nothing and passing.
- A negative `max_sites` in the config means *off*, as it already did as a flag. It used to
  suppress every site and exit clean.
- An `exclude` fragment can be anchored with a leading slash, and a fragment that removed
  nothing is reported.
- A `[[count]]` can say `occurrence = "first"`, reading only the first match in each document
  and treating what is below it as that document's own history. `every` remains the default, so
  no existing declaration changes meaning.

**Fixed**

- A `[[count]]` whose pattern matched no line passed silently: the oracle answered, nothing was
  compared, and the run stayed green while a declared check was not running.
- `kinemata confirm --write` corrupted the resource list it re-dated, joining the following
  field onto the line it rewrote.
- A baseline rewrite treated an oracle that crashed as an oracle that found nothing, and
  deleted its accepted findings as fixed.

## 0.1.0a1

First release. Registry declarations, the duplication and closed-world catches, documentation
checked as claims, the citation layer, and a shared ratchet across the gates — published as an
alpha to exercise the release path, not because the interfaces are settled.
