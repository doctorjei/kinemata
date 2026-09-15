# Changelog

What changed between released versions, for a person reading it.

**An entry is a list of what changed.** The first release was a single line, on the stated
condition that this would grow when there was a reader for it to grow for — and there is one now:
a project outside this repository runs against kinemata and upgrades between published versions.

Commits are in `git log`; the reasoning behind a design decision stays in the document that
carries the decision. A changelog repeating either becomes a second carrier and goes stale.

## Unreleased

Not published. Kept current as the work lands, rather than reconstructed at the next release from
a commit range — which is how the entries below were nearly written. The heading carries no
version deliberately: `[[count]] changelog version` reads the newest **versioned** heading, so
this one is invisible to it until it is renamed.

**New**

- `kinemata probe` compares a declared corpus of inputs against what the project's own code
  accepts and refuses — a fact with no value on either side, which no oracle can print. The
  project supplies the target and the cases; how the answer is read is declared in the config,
  not supplied by the project. A corpus carrying only one polarity fails rather than passing:
  a refusal-only corpus is satisfied by a callable that refuses everything.
- **This is the first check that calls the project's own code.** kinemata still never runs the
  project's test suite or entry point, and never classifies an outcome by reading output.

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
