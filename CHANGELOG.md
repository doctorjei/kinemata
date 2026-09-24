# Changelog

What changed between released versions, for a person reading it.

**An entry is a list of what changed.** The first release was a single line, on the stated
condition that this would grow when there was a reader for it to grow for — and there is one now:
a project outside this repository runs against kinemata and upgrades between published versions.

Commits are in `git log`; the reasoning behind a design decision stays in the document that
carries the decision. A changelog repeating either becomes a second carrier and goes stale.

## Unreleased

**New**

- `[[parity]] ordered` compares a list-valued cell **in order** instead of as a set, for a
  declaration whose sequence is the meaning — an authority cascade, a containment chain, a tier
  list. The set rule is unchanged and is still the default; what did not exist before was any way
  to state the other claim. Measured on an adopter's real manifest: an oracle printing the three
  access tiers reversed reported *agreeing on choices*, and neither printing the container nor
  addressing the list by index could say otherwise. Refused without a `field`, since membership
  compares identifiers and those are a set on both sides. A run whose cells are all scalars prints
  `ordered: 0`, because a key that quietly does nothing is what this tool reports about everyone
  else. It pins the order the **oracle** prints in, which nothing here can verify is the code's own
  order — positional rather than semantic, the caveat `[[count]] occurrence` already carries.
- `[[shape]] each_value_matches` claims a pattern of every **value** a field holds — a map's
  values, a list's items, or a scalar itself — so a field written as a scalar on some rows and as a
  mode-keyed map on others is one rule. `each_matches` reads a map as its **keys** and still does;
  changing it would silently re-read rules already written. Asked for by an adopter whose absence
  rule is legal only where every arm of a default is a whole-value `$VAR`: the scalar rows were
  expressible with `each_matches`, the mode-keyed ones with nothing. **An empty container fails**,
  because the same manifest declares `default: {}` on rows a vacuous pass would have certified.
- `[[registry]] defer_to` names the registries whose declared **values** are not this registry's
  vocabulary. A closed keyspace spotting *box.yaml* — a filename sharing a settings key's shape —
  at the line declaring it as another registry's constant used to call it undeclared; with
  `defer_to` it hands a candidate matching one of the named registries' values to them, and
  `undeclared` prints how many it handed over. **Declared, not inferred**: the adopter who reported
  it keeps key strings in the same constants registry as the filenames, so deferring to every
  declared value would have silenced a mistyped key constant. Narrow a mixed registry with `where`.
  Refused when it would do nothing — a string, an empty list, a name no registry answers to, the
  registry itself, a target declaring no values, or a registry with no candidates to hand over.
- `[[parity]] format = "json"` compares a field's values **as data**. The oracle prints each value
  as JSON and both sides are compared as values — a map equal whatever its key order, a list in
  order, and `1`, `"1"` and `true` three different things. The `text` form refuses any cell holding
  a map and stands the whole registry's value comparison down with it; an adopter measured 18 of
  their 66 `default` rows as mode-keyed maps, reachable before only one arm at a time. Under JSON a
  column of scalars and maps is one comparison, and a declared `null` is a value that must meet a
  printed `null` rather than reading the same as a field the declaration does not carry. Output
  that is not JSON diverges on its own row. Refused without a `field`, beside `translate`, and
  beside `ordered`. **The `text` form, and so every parity written before the key, is unchanged.**
- **Shell, YAML and TOML are read the way `.py` is.** A comment is nothing, a literal that is a
  declared value is a strong finding, and a literal that merely contains it is weak — in
  `.sh`/`.bash`, `.yaml`/`.yml` and `.toml` as in Python. Before, every suffix but `.py` read raw
  lines and every hit was strong, so `# see box.yaml for the format` failed a build and `echo
  "restoring box.yaml.bak"` failed it as hard as a real bypass; an adopter named that as the reason
  one of its checks could not migrate. A shell word is a literal (it is a string there, so `cp
  box.yaml "$DEST"` stays strong); a heredoc, a block scalar and a multi-line string are one literal
  each; a `#` inside quotes, a heredoc, a block scalar or a URL stays content. `undeclared` and
  `clusters` read these files the same way. **What an existing config scanning these suffixes will
  see:** comment hits disappear, and a hit inside a longer literal stops failing.
- `[[registry]] only` names the files a registry applies to, and no others — the inverse of
  `home`. An entry fired everywhere except where it was defined, so an import discipline (an
  adopter's bootstrap module kept free of imports) could only be run as a CI step narrowed to that
  file; a plain `check` fired it across the whole tree. `only` is read with the same whole-segment
  matcher as `exclude`, honored by `check`, `review`, `undeclared` and `unused` alike, and refused
  at load when a fragment matches no file the registry reads.

**What an existing config will see change**

- **`exclude` names whole path segments, and every check reads it the same way.** A fragment
  like *tests/* is a directory called *tests* at any depth, a bare name is exactly that name at any depth, a leading
  `/` anchors at the root, and nothing is ever matched inside a name. Before, a fragment was a
  substring and `claims`, `confirm` and `stale` stripped its trailing slash while the scans did
  not — so `exclude = ["tests/"]` removed a document called `smoke-tests-design.md` from `claims`
  and left it in `check`, which cost an adopter two documentation claims without a word. The same
  rule now governs `machinery` and `[claims] historical`. **What changes for an existing config:**
  documents a slash-stripped fragment used to skip by accident are checked, and a fragment written
  to match part of a name removes nothing — which `check` and `review` report on every run.
- A flag in `kinemata.toml` that is not a boolean is refused rather than coerced. A registry
  declaring `closed = "false"` loaded as **closed** — every non-empty string is true — so a project
  could arm the closed-world gate while reading the opposite off its own line, and with `syntax`
  declared nothing would have said so. `allow_empty`, `case_sensitive`, `include_private`,
  `[claims] external` and `[[probe]] exact` all coerced the same way; `[citations] provenance`
  already refused, and its refusal is now the one every flag shares. **A config spelling its flags
  as TOML booleans is unaffected**; what breaks is a line that never meant what it said.
- A list-typed key in `kinemata.toml` given as a string is refused instead of being read one
  character at a time. `suffixes = ".py"` on a registry meant the suffixes `.`, `p` and `y`, and
  its `check` went from one bypass to exiting 0 having reported nothing; a code-patterns
  `home = "pkg/_run.py"` became one-letter fragments every path contains, so every bypass read as
  canonical use; `[[shape]] choices = "str"` accepted `"s"` and refused `"str"`. `command` was
  fixed for this in `0.1.0` and the rest were not — every list key now goes through one reader,
  including the ones read inside the code-patterns adapter. **A config spelling its lists as
  lists is unaffected.**
- A `[[shape]]` pattern rule (`matches`, `each_matches`) was satisfied by an entry that did not
  carry the field at all, or carried a null there, whenever the pattern happened to fit the word
  `None` — which is what a missing value was matched as. `matches = "^N"` passed every entry
  without the field. A missing or null value now matches no pattern; whether a field must be there
  is still `present`'s claim to make.
- `kinemata ids` no longer prints a registry's projection again when every line of it is already
  listed under another registry. It prints that registry's header with a pointer instead. A project
  comparing several fields of one declaration declares a `where` view per field, and every view
  used to project the same identifiers again. On an adopter's 99-row manifest, three views printed
  243 lines and now print 102. `ids -r NAME` still prints a view in full, and each registry's
  budget is still checked whether or not its lines were printed. A registry that only partly
  overlaps another is printed in full as before.

**Fixed**

- The reference sheet's list of clause boundaries was short by one. A **sentence end** has bounded a
  negation since before `0.1.0` and the list never said so, which understates how narrowly a
  negation reaches — the difference between *"there is no `a.py`. The loader is `b.py`"* withdrawing
  one claim and withdrawing two. It also now says that a markdown table's `|` is deliberately not a
  boundary, which is a documented decision rather than an omission.
- A `kind = "import"` class that satisfies the `Registry` protocol without subclassing
  `BaseRegistry` now works under every command, instead of loading as valid and then dying on an
  `AttributeError`. `ids`, `unused`, `review`, `check`, `undeclared` and `baseline` each read a
  member the protocol never asks for — a projected line, a budget, a file set, the declaring
  machinery, whether mentions are uses — and a class carrying only the protocol failed on six of
  them one command at a time. Each is now read with the base's default where the class does not
  carry one. **The protocol is unchanged**, so no class that satisfied it stops satisfying it.
  An open class with no `candidates()` also gets `undeclared`'s refusal instead of a traceback.
- `undeclared`'s refusal said it needed *"kind = yaml-mapping with `syntax`"* while a bibliography,
  a `toml-value` given a `syntax` and a project's own `import` class all answered. It now names the
  method — a registry that implements `candidates()`, which every closed registry must.
- A registry refused for being empty or for not being closable was named `'?'` when the config
  gave no `name`, even where the registry had one — an `import` class carrying its own, or a
  kind's default. Those refusals come after the registry is built, and now use its name.

## 0.3.0

**New**

- `claims -v` names what withdrew each path claim, not only where it happened: the negation word,
  whether it sat before the claim, after it, or on the line above, and whether it had to cross a
  markdown table cell to reach it. The sites alone made this evidence gatherable and did not make
  it cheap — a project with a large `negated:` count had to open every one of 336 sites in its own
  files to sort the right withdrawals from the wrong, and found 7 real defects and 103 assertions
  that were true and checked by nothing. No verdict changes; the negation rule is exactly as it
  was.
- A `negated:` summary carries a second line counting the withdrawals where the negation was in
  **another cell of the same table row**, or in the row above. `CLAUSE_BOUNDARY` holds `;`, `:`, a
  sentence end and the contrastive conjunctions, and a `|` is not among them, so a
  `Loaded at start? | No` column withdraws the path named beside it. This is the likeliest false
  suppression there is, because a table is where a project puts its path inventory — and it is
  **reported rather than repaired**, on measurement: adding `|` to the boundary is inert on this
  repository and, on the two corpus trees where it fires, most of what it recovers is a layout
  description whose paths were never claims about that tree. The reference sheet's § Known limits
  carries the disposition and what would change it.
- Every command that reads the baseline says when a new finding is an **accepted record whose line
  was edited**, naming the record and the text it used to hold. Repairing one finding by reflowing
  a paragraph moves the words of a *neighboring* baselined line; the record stops matching, the run
  reddens with what presents as a new finding, and the accepted count drops by one with nothing
  said. Those are two different events and they were one piece of output. The verdict is
  deliberately unchanged — a fingerprint holds the line's text so that a rewrite is a new finding,
  and a match loose enough to forgive one would hold an exemption open across the edit that changed
  what was exempted. Reported by a project that hit it, which asked for the naming rather than for
  the looser match.
- `[[parity]] translate_identifier`: a second declared translation, for the identifiers, in a run
  that also compares values. `translate` lands on whichever side the parity compares — the values
  when a `field` is named — so a declaration whose keys are spelled one way and whose values
  another had no form for the first, and membership runs in every parity, so both spellings came
  back as findings. The only way to make such a run green was to have the *oracle* re-key its own
  output, which puts the hop where no reader of the config can see it: the thing `translate` exists
  to prevent. Refused alongside a bare `translate` when no `field` is named, where there is one
  side and two keys naming it would be a declaration saying the same thing twice.

**What an existing config will see change**

- Nothing about any verdict, and no new findings: the negation rule, the window and the boundary
  set are untouched, so the same claims are withdrawn as before and the gate's exit status cannot
  move because of this.
- Two lines of output do change, which matters only to something parsing them. Each `-v` withdrawal
  line gains a ` -- "word" direction` suffix after the path, and a project whose documents hold
  markdown tables gains one indented line under `negated:`. A project with no tables sees no second
  line at all.
- A run in which an accepted finding's line was edited gains the lines naming it. No exit status
  moves: the same findings are new, the same records are stale, and both are still reported where
  they were.
- 🛑 **A command given a path inside the project now reports different things, and this is the half
  an upgrader cannot discover any other way.** If any step runs `kinemata check <subdir>` or the
  like, its result changes: findings are spelled relative to the project root rather than to the
  argument, so accepted baseline records match where they could not before — a step that was red
  for that reason goes green — and the project's `exclude` applies where it had silently stopped,
  so a step that was reporting vendored or generated code stops. A step naming a single **file**
  scanned nothing at all before and scans it now, which can turn a green step red on a finding that
  was always there. **A step that scans from the project root is unaffected**, and so is one
  pointed at a tree outside the project. See *Fixed* for why each of those was wrong.

**Fixed**

- A path argument now narrows a scan instead of re-rooting it. `kinemata check src` is advertised
  as *limit the scan to this path* and was implemented as *make this the scan root*, which is a
  different thing and was wrong twice over. Every path the run reported was spelled relative to the
  argument, so **no accepted baseline record could match one**: a tree green from its root went red
  under a subtree scan, reporting its own exemptions as new findings — a ratchet producing the
  churn it exists to prevent, from the inside. And the project's **`exclude` stopped applying**, for
  the same reason: a fragment naming a vendored directory under the project root cannot match the
  same file spelled from inside it, so narrowing quietly *widened* what was reported. Both measured on a scratch tree, both fixed by keeping the
  project root as the root and reading only the named subtree. A path **outside** the project is
  unchanged and still means another tree, which is a real thing to ask for; containment decides,
  the way `[context]` already splits a contained `include` from a declared `external`. Affects
  every command that takes a path.
- Naming a single **file** as the path reads that file. It was walked as a directory, which yields
  nothing — so a narrowed run over a file holding a finding nobody had accepted printed a clean
  result and exited 0. Nothing is the answer that looks like success, and a check quietly not
  checking is the failure this package exists to report. One test had been passing off that
  behavior without saying so, and now asserts what its own docstring claims.
- `parity` now prints `set-valued: N` for declared cells that held a list, on every run, clean or
  failing. A list is compared as a set on purpose — a reorder is not a finding, and that rule is
  unchanged — but nothing said so, so a declaration pinning an enum's `choices` against the code's
  own tuple reported `agreeing on choices` while an oracle listing the same three values in reverse
  agreed with it. Measured against a real adopter manifest, not constructed. This was the last
  suppression in the tool that reported nothing; the others each gained a line earlier, `negated:`
  most recently. The count is deliberately not a list of sites: a list cell is a suppression the
  project declared by writing a list and can see in its own file, where a negation is one the tool
  inferred from prose nobody wrote for it.

## 0.2.0

**Fixed**

- `claims` now prints `negated: N` for path claims a negation withdrew. This was the only
  suppression in the tool that reported nothing — illustrations, inert suffixes and unread
  f-strings all had a line — so a run that quietly stopped checking a claim looked exactly like a
  clean one. An adopter found it sideways: their sentence ended *"and needs no edit"*, where the
  `no` governs `edit` and exempted two paths before it, and they noticed only because editing an
  unrelated token on the same line changed which claims fell inside the window. The rule is
  unchanged and still right far more often than not; what changed is that you can see what it
  took.
- `claims -v` lists the withdrawn sites. An illustration is a suppression you declared, so the
  count is the whole reading; a negation is one the tool inferred from prose you did not write for
  it, and you may not know it happened — so the sites are the only way to judge whether it was
  right. Tuning the negation word list was considered and measured first: no word is reliably
  wrong across trees, `had` withdrawing four claims in one tree that all named resolving paths and
  four in another that named none. Listing is what makes that evidence gatherable at all.
- A refused `section` or `path` that is a dotted string now names the list form, when splitting it
  on dots would have resolved: `section = ["policy", "seed_whitelists"]`. The rule is unchanged —
  a string is one key however many dots it holds, because a key may legitimately contain one — but
  the old message listed what the level held, which answers a typo and not the question somebody
  who wrote the dotted form is actually asking. A dotted string that would *not* resolve still
  gets the old message.

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
