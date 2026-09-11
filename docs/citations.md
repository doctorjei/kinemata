# Citation stamps

A citation names a place. It rarely names a *time*, and without one it cannot be judged.

This document specifies the stamp that supplies the missing coordinate, and records what
settled each choice. Every value below was measured rather than assumed; where a number
appears, the method that produced it appears with it.

---

## 1. Why a citation needs a time

A live document citing a target that does not exist **is** an error. That is the ordinary case
and the checker should say so.

What makes it *not* an error is provenance. A record written in August that cites what was read
in August is correct even after the target moves, and no amount of inspecting the target settles
that — the information is missing from the document, not from the world.

The previous mechanism put currency in configuration instead: a `historical` path axis exempted
whole directories from checks about the tree's current state. That axis is the wrong one. It
cannot separate a live section from an honest historical record inside a single file, which is
the shape a changelog takes on its first day. Currency belongs on the citation.

**A dated citation is a declaration; a path glob is a suppression.** This project prefers the
first everywhere else, and the same argument applies here.

### What a stamp can and cannot settle

- **That a stamp is present is a catch.** It cannot be satisfied by accident.
- **That a stamp is *correct* is a catch only for targets under version control.** For a path in
  this tree, history can answer whether it existed at the stated moment.
- **For an external address, correctness rests on good faith.** Nothing here can verify that a
  page resolved on the date claimed.

The mechanism is therefore strongest where it is least needed and weakest where it matters most.
That asymmetry is real and is not hidden by the syntax.

Relevance is a separate axis and is not mechanizable. A target that still resolves can be stale,
superseded, or simply wrong. What a stamp buys is a clock: a citation old enough to deserve
re-reading can be surfaced for a person. That is a reminder, correctly, and is not a gate.

---

## 2. The form

```
[0TMQDKB-Ty]
 |______|_||
     |   | +-- type, two letters
     |   +---- separator
     +-------- timestamp, seven characters
```

Twelve characters, one bracket group. The stamp follows the citation it annotates:

```markdown
The registry contract is `docs/design.md` [0TMQDKB-Ty].
```

### 2.1 The timestamp

Thirty-five bits, big-endian, encoded as seven characters of five bits each:

| Field | Bits | Meaning |
|---|---|---|
| year | 10 | years since 2000, giving 2000 through 3023 |
| seconds | 25 | seconds since January 1, 00:00:00 UTC of that year |

**The year occupies the high bits, and that is load-bearing.** It is what makes a stamp sort
chronologically as a string, which was verified across a year boundary and over the full
representable range rather than reasoned about.

**Twenty-five bits is sufficient with room to spare.** A leap year holds 31,622,400 seconds
against a field capacity of 33,554,432 — 22.4 days of headroom, so leap seconds need no thought.

**Seven characters is an exact fit.** Seven times five is thirty-five, with no padding and no
waste. Six characters would give thirty bits, which buys only 2000 through 2031.

The alphabet is Crockford base32, which omits I, L, O and U so that no symbol can be confused
with 1 or 0. Stamps are rendered uppercase and **matched case-insensitively**.

### 2.2 The type

Two letters, rendered with the first capitalized and the second lowercase, and **matched
case-insensitively**. The case pattern is a reading aid: it marks the field boundary at a glance.
It carries no meaning, because if it did, any pipeline that lowercases identifiers would silently
rewrite the type rather than merely making it harder to read.

Case-insensitive matching leaves 676 codes, which is far more than this needs and lets each be a
mnemonic rather than an opaque index.

### 2.3 Why the separator is not redundant

The case shift alone does not mark the boundary, because the type's first letter is capitalized
like the stamp. The seam only becomes visible at the second letter, which is too late to read
comfortably. The hyphen earns its character.

---

## 3. Why these delimiters, and not the others

Four candidate marks were considered against the flavors that actually read these documents, and
against this project's own extractors. Three were rejected on evidence.

**Angle brackets are unusable.** In CommonMark a `<` followed by a tag name is literal HTML, and
a tag name is an ASCII letter followed by letters, digits or hyphens. Some stamps would parse as
HTML tags, and a sanitizer strips unknown tags — so the stamp would vanish from the rendered page
while remaining in the source. A provenance marker that a checker can see and a reader cannot is
exactly backwards.

**Braces are inert in CommonMark and GFM, but claimed elsewhere.** Pandoc attaches an adjacent
brace group to a code span as attributes; MyST reads a brace before a backtick span as a role.
They are also the placeholder syntax for Python string formatting, which is a hazard for any
document text passing through an assembler.

**The at sign is claimed by agent surfaces**, where it addresses files and other agents. These
documents are read there.

**Square brackets survive all of it**, and were chosen for a second reason: they are the
universal reference-marker convention. A reader who has never heard of this format still reads
the stamp as an annotation on the citation before it.

### 3.1 The one shape to avoid

`[text][label]` is CommonMark's full reference link. A two-group form would render literally only
while no matching definition exists anywhere in the document — a dependency on something being
absent, which is the class of fragility this whole design is meant to remove.

### 3.2 Why a hyphen and not a colon

Both are inert in markdown. The hyphen was chosen on behavior outside it. In YAML flow context a
colon followed by a space turns the token into a single-key mapping rather than a string, so the
colon form is correct only while nobody inserts a space. The hyphen has no equivalent failure,
and is additionally legal in filenames where a colon is not, and inert in URLs where a colon
means a scheme or a port.

### 3.3 The residual, stated plainly

A stamp immediately followed by an opening parenthesis is read as link text, and the parenthesized
text is extracted as a link target. A space prevents it.

**Do not rely on the space.** Whitespace is invisible, survives editing poorly, and a rule that
holds only while nobody deletes a character is not a rule. The extractor is taught the stamp's
shape instead, so that a stamp is never link text regardless of what follows. Precision belongs
to declared syntax, not to incidental formatting — which is this project's argument everywhere
else.

### 3.4 A collision that the delimiters already close

Crockford's alphabet contains all sixteen hexadecimal symbols, so roughly one stamp in 119 encodes
to seven characters that are entirely hex — measured over 200,000 samples, slightly worse than the
1-in-128 that uniform digits would predict, because the seconds field spans 94% of its range and
the resulting bias favors low symbols, which are exactly the hex half of the alphabet.

Undelimited, those stamps would be indistinguishable from short commit hashes. The brackets close
this without constraining the alphabet: the commit-hash pattern is anchored to backticks and
requires its whole content to be hexadecimal, and a bracketed stamp satisfies neither.

---

## 4. Reading a stamp

The token is opaque by construction. Seven characters buys compactness at the cost of legibility,
and the trade only pays at second precision — at day precision a plain date is three characters
longer and needs no tooling at all.

That cost is accepted rather than denied, and `kinemata stamp` decodes.

---

## 5. The reference key

A stamp answers *when*. It does not answer *what*, and a citation that spells its target inline
carries a fact that belongs in one declared place.

```
[0TMQDKB-Ru0169]
```

Three facts, three homes:

| field | answers | lives |
|---|---|---|
| the stamp | when this was verified | inline |
| the key | which source | inline |
| the entry for that key | where the source is | the bibliography, once |

The inline text carries only the two invariants. The volatile half — which repository, which
address, which path — is declared once and edited once when it moves.

**This closes the gap a commit hash leaves.** A hash is immutable *content* identity and says
nothing about *place*: a hash cited from another project is a valid coordinate in a tree the
checker was never pointed at. The key supplies the place the hash omits.

### 5.1 Shape

Two letters naming a type, then four digits, zero-padded to a fixed width.

**Fixed width is not cosmetic.** Variable width makes two spellings of one fact, which is the
re-derivation this project exists to catch.

**Four digits, because an existing sequence should migrate without being renumbered.** A live
corpus that crosses a three-digit ceiling forces a renumber, and a renumber breaks every
cross-reference already pointing into it — the exact churn this scheme exists to prevent. One
character is cheap against that.

The type is a namespace. Digits are unique **within a type**, so two types may carry the same
number without conflict, and the composite key is unique **within a project**. A project may keep
more than one bibliography file, but the key space is project-wide, so a duplicate is refused
across all of them rather than within each.

### 5.2 A key is local to the project that declares it

A key in this project's bibliography is *this* project's key for whatever it points at, in the
way that reference 12 in one paper is that paper's number for another's work rather than a number
both must agree on forever.

⚑ **This sentence used to say the entry "names the foreign identifier where there is one"**, which
quietly covered two different things with one word: another project's *name* for a source (RFC
7159, say) and the *repository* an artifact is in. Only the second is a field —
`repository`, required by the external codes in §5.4 and refused beside a local one. An outside
name for a source is what `target` and `note` are for.

A key is therefore only ever resolved against its own bibliography, and collision between
projects stops being a category of problem. Global uniqueness across trees would need either a
shared type vocabulary or a project prefix inside the token, and neither earns its cost.

### 5.3 Numbers are chosen, not minted

Any unused number is a valid number. The tool's job is refusal, not assignment: a duplicate key
is a finding, and a citation naming a key that does not exist is a finding. Both failures are
mechanically catchable, which is the property that matters.

Choosing rather than minting also keeps numbers sparse and meaningful, so an existing sequence
maps across as it stands instead of being renumbered to whatever came next.

### 5.4 Type codes

Type codes are the project's to define, over a reserved core. The core is reserved for two
distinct reasons, and conflating them produces a set that is either too small or too large.

**Codes the tool interprets must be reserved**, because behavior depends on them. If the checker
verifies that a given type's target really is an address, that code has to mean the same thing
everywhere.

**Common source types are reserved even where the tool never reads them**, because the value of a
shorthand is that it reads without explanation. That is the same reason square brackets were
chosen over every other mark. A project inventing its own private code for a book or a
specification throws away the only thing a shared notation offers, and standardizing the obvious
cases costs nothing.

Everything else belongs to the project.

**Every code is declared** — the reserved ones implicitly, a project's own explicitly — so a code
appearing in a citation that no declaration names is a typo the checker reports rather than a
silent pass.

**The reserved set is extensible**, because a closed built-in set with no extension point is a
defect this project has already shipped once: the document-suffix set was closed, and it left an
adopting project blind to the only two content files one of its repositories had while the scan
came back looking nearly green.

#### Interpreted codes

A conflicting project use of one of these is **refused at load**. Behavior depends on the code
meaning what it says, so reinterpreting it would make a check silently answer a different
question.

| code | means | what the tool does with it |
|---|---|---|
| `Wb` | web address | settles that it resolves |
| `Pa` | path in this tree | settles that it exists |
| `Cm` | commit in this repository | settles that the history knows it |
| `Px` | path in **another** repository | nothing can settle it here; see §5.8 |
| `Cx` | commit in **another** repository | nothing can settle it here; see §5.8 |

**The external codes are pairs, and the pairing is the design.** `Px` is `Pa` and `Cx` is `Cm`,
differing in locality and in nothing else. A single code meaning only *"not ours"* was proposed
first and rejected on what it loses: a code is one per entry, so it cannot say *external* and
*commit* at once, and the entry would stop telling a reader what sort of artifact the target is.

`Wb` has no pair. An address is off this machine by nature, so "in another repository" is not a
distinction it can draw — and note that *external* in this table means **another repository**,
while `[claims] external` means **reaching the network**. Two boundaries, deliberately not one
word: the codes carry `x`, the config key carries the network sense, and neither is read where the
other applies.

#### Standardized codes

The tool never reads these. They are reserved so that a citation carries meaning across projects
without a lookup, which is the whole return on a shared notation — the same argument that chose
square brackets over every other mark.

| code | means | | code | means |
|---|---|---|---|---|
| `Dc` | document | | `Rp` | repository |
| `Sp` | specification or standard | | `Bk` | book |
| `Ru` | ruling | | `Ar` | article or paper |
| `Is` | issue | | `Pr` | change request |

A conflicting project use of one of these is a **warning, not a refusal**. Refusing would enforce
a convention the tool cannot act on, and the only cost of divergence is legibility across
projects. That is the reminder-and-catch distinction applied to the vocabulary itself.

**Every reserved code points somewhere.** A code whose entry would *hold* its source rather than
reference one is a different mechanism wearing a type code, and does not belong in this table —
whatever a project may define locally.

**Additions to either table are not the tool's to make.** The reserved set is a shared convention,
and every code added to it is one some project may already be spending differently. It grows by
explicit decision, never by a maintainer noticing a gap.

### 5.5 Where the bibliography lives

A data file per project, declared from that project's configuration by a registry kind — the same
shape the word list already uses, and for the same reason its own header gives: a hand-maintained
table inside a checker went stale silently while the check reported clean.

Declaring it as a *registry* rather than loading it bespoke means the existing machinery applies
unchanged: the contract, the projection that renders it budgeted and loadable on demand, the
report of declared entries nothing cites, and the refusal that stops a bibliography which loaded
nothing from passing as clean.

**On demand matters.** A reader resolving one key does not need the whole bibliography, and a
bibliography kept in prose would sit inside the context ceiling permanently. Context overwhelm is
one of the three failures this project exists to address; its own mechanisms should not cause it.

### 5.6 A citation accompanies its target, until the target gets long

A key may stand beside a readable target or stand alone:

```markdown
The registry contract is `docs/design.md` [0TMQDKB-Pa0003].
The registry contract is [0TMQDKB-Pa0003].
```

**Accompany by default.** A document that cannot be read without resolving a key against a second
file has made every reader load the bibliography to understand a sentence — and context overwhelm
is the first of the three failures this project exists to address. A mechanism causing the failure
it was built to prevent is not defensible.

**The target may be spelled twice because the key is what makes the second spelling legitimate.**
An unaccompanied path is a bare mention; a path carrying a key is a declared citation, the way an
entry's `home` marks its canonical mention. The redundancy is also *checkable*: the bibliography
says where the key points, the sentence says where it points, and disagreement is a finding —
which is a positive assertion of the kind the registry mechanism otherwise cannot express.

**Let the key stand alone when the target is too long to read comfortably, or when there is no
readable target at all.** A book or an article has nothing to accompany. Measured on this
project's own working notes, distinct citation targets run to a median of 20 characters and a 90th
percentile of 50, with a maximum of 107 — a dated mailbox filename, which beside a token makes a
120-character line for one citation. The short case is the common one and the tail is real.

**The threshold is declared, not built in.** A project whose paths run longer sets its own.

### 5.7 Resolving a key

Two directions, and the second is what makes accompanying affordable.

**Forward — what a key points at**, which is how a reader gets the readable form of a citation
that stands alone.

**Reverse — every place a key is cited.** Without it, moving a source means finding every mention
by hand; with it, a move is one edit to the bibliography plus a generated worklist, with the gate
failing until the list is empty. That is this project's argument applied to its own citations:
silent rot becomes a task list.

A key that nothing cites needs no separate machinery — it is a declared entry nothing mentions,
which the existing report of unused entries already describes.

### 5.8 `Px` and `Cx` — evidence that lives in another repository

An entry whose code is `Px` or `Cx` names an artifact this repository does not contain, and says
which repository does:

```toml
[[entry]]
key = "Cx0001"
target = "42ece1296223babf896f00c514b2f0dc40d9e158"
repository = "doctorjei/kanibako-cli"
note = "the tripwire scoped to one module"
```

**The code and the field are required together, and each without the other is refused.** An
external code with no repository says the source is somewhere else without saying where, which is
a citation a reader cannot follow. A repository beside a local code says two contradictory things
about one target, and the code is the half a check acts on — so the entry would read as external
to a person and as this tree's to the tool.

**A citation this tree cannot settle, standing beside an external key, is not a finding.** It is a
citation of somebody else's artifact, checked by whoever owns that repository. The documentation
gate reports the count of them on every run and never fails on one, and the writer reports such a
source as *unsettled* rather than *gone* — every oracle here answers about the tree it was pointed
at, so calling it gone is a true sentence that invites a reader to delete real evidence.

**Why these codes exist at all.** A tool validated against other projects cites those projects, and
a project adopting a checker usually has a vendored dependency or a sibling repository it refers
to by path. Those citations are real, they are permanently unresolvable from here, and the two
alternatives are both worse than declaring them: left alone they are dead claims forever, so the
gate can never go green over text nobody should change; removed from the sentence so that nothing
is extracted, the evidence moves into a second file and out of the reasoning that depends on it,
against §5.6.

**Three properties keep this from becoming a suppression syntax**, and they are the reason it is
safe to have at all:

- **Resolution is asked first.** A target that exists here is this project's, whatever key sits
  beside it, so a declaration can never take a live claim out of the check.
- **Every occurrence on the line must be keyed, not any.** A sentence naming one path as another
  project's and then as this one's still contains a claim this tree can be wrong about.
- **A token the checker cannot locate stays checked.** The failure costs a false finding rather
  than a silent exemption, which is the direction every mechanism here errs in.

⚑ **This was a `foreign` field on a `Pa` or `Cm` entry until 2026-09-11**, and the field silently
re-read *"path in this tree"* as *"path in the named tree"*. Coherent, undeclared, and the exact
second-meaning-for-one-spelling this tool reports in other people's code. Two reserved codes were
minted instead — which is not the tool's to do, so they were approved one at a time — and the keys
were renumbered from 1 within their new types. Numbers are chosen rather than minted (§5.3), so
there was nothing to preserve across a retyping.

### 5.9 `confirmed` — the day a source was verified, and what it changes

An entry may carry the date it was last checked:

```toml
[[entry]]
key = "Wb0007"
target = "https://spec.commonmark.org/"
confirmed = "2026-09-11"
note = "the measurement this design rests on"
```

(The address above is a live one on purpose. `claims` reads fenced blocks — a dead link inside a
snippet a reader copies is still dead — so an invented example address in this document would be
a finding against the document that specifies the notation.)

**An entry with a date is a record; a citation without one is a pointer.** That is the whole of
it, and §6 is where the consequence lands: the staleness clock reaches pointers and leaves records
alone. The reasoning behind the clock — an address leaves the machine, so the date on it is worth
refreshing — is a fact about *going to read something*, not about *having read it*. A source the
project verified and wrote down does not become unverified because a week passed.

**Verified once, re-run on request.** `kinemata confirm` carries the network oracle and re-dates
only what it settles, so re-checking records is an act somebody chooses rather than a schedule.
This matters most where re-checking is not possible at all: a page that has since moved, a
reference kept because the decision rested on it. Those cannot be re-fetched and should not
therefore become permanent findings.

**Two refusals**, both for the same reason the whole mechanism exists:

- A value that is not a date. A source verified on an unreadable day is one nothing can say was
  verified.
- A date in the future. A record may say when a source was checked, never when it will be —
  provenance exists to separate *true when written* from *wrong when written*, and a date nobody
  could have checked at settles neither.

---

## 6. Provenance and the clock are separate axes

An earlier draft of this document argued that a commit hash needs no stamp, on the grounds that a
hash is self-dating. **That was wrong, and the correction is the general rule.**

A hash is immutable *content* identity, not a place and not a guarantee of existence. History is
rewritten in ordinary practice — rebase, amend, a dropped branch — so a hash can stop resolving,
and an abbreviation unique today becomes ambiguous as a repository grows. Without a stamp there
is no way to tell *true when written, history rewritten since* from *wrong when written*, and
telling those apart is the entire purpose of provenance.

So **every citation carries provenance, with no exemptions.** What varies is the clock:

| | provenance | staleness clock |
|---|---|---|
| what it answers | when was this true | when was this last confirmed |
| applies to | every citation | citations the tool cannot settle cheaply |

**The clock belongs to kinds that leave the machine.** A path or a commit is settled locally on
every run, so a clock would only restate what the run already knows. An address requires a network
request, which is why it is opt-in, and which is why a date on it is worth keeping.

**And within those, to pointers rather than records.** An address written inline and undeclared
says *go and read this*: it has to keep resolving, so a reminder to look again is the whole point.
A source entered in a bibliography with the day it was verified is the other thing — the sense
§5.2 means by *reference 12 in one paper* — and a journal reorganizing its site does not
invalidate the reference. **Declaring a source turns a pointer into a record**, and the clock
leaves records alone; `confirmed` on the entry is what says so. See §5.9.

Re-checking a record is therefore deliberate rather than scheduled. `kinemata confirm` carries the
same network oracle and re-dates what it settles, so a project re-runs its sources when it wants
to rather than every seventh day.

Archived material is left alone on both axes. A record cites what was true when written.

### 6.1 Which stamp dates which citation

Saying *"this path citation has no stamp"* requires knowing which stamp belongs to which
citation. That association was deliberately left unbuilt while it could be sidestepped — a
reference key lives *inside* a stamp, so a keyed citation already carries its own timestamp and
there is nothing to associate. A check for a *missing* stamp cannot sidestep it.

**The rule is a stated adjacency, not a guess.** A stamp dates the citation it immediately
follows, on the same line, with nothing or a single space between them. That is §5.6 read
literally — a citation accompanies its target — and it is the mirror of the rule the writer
already uses in the other direction, from a stamp back to the target beside it. The two are
asserted to agree on the same text rather than maintained in parallel.

```markdown
The registry contract is `docs/design.md` [0TMQDKB-Pa].
```

**What it cannot see, stated rather than discovered:**

- A stamp two spaces after its citation, or with punctuation between them, or on the following
  line, dates nothing. These read as near misses and are reported as undated.
- One stamp does not date two citations. Where a sentence names two targets and carries one
  stamp, the stamp dates the one it follows and the other is a finding.
- Where a line names one target more than once and the occurrences disagree about carrying a
  stamp, **nothing is reported**. The extractors answer with text and no position, so which
  occurrence the sentence asserts cannot be recovered, and the count of these is printed on every
  run. A false accusation of an undated citation teaches its reader that the check is noise,
  which switches the check off for the findings that were real; a miss costs one finding.
- A fenced block is an illustration, not a citation. A document specifying this notation writes
  whole examples of it.

The unit of a finding is a target cited on a line, not each occurrence of it — the extractors
disagree about repeats, and counting occurrences would make the size of the report depend on
which one produced it.

### 6.2 Declaring the policy

**The catch is off unless a project asks for it.** Armed on a tree that has never dated a
citation it reports every citation in the tree, and a gate that fires on everything on day one is
one somebody switches off — which is the failure the ratchet exists to prevent.

```toml
[citations]
provenance = true                    # every citation carries a stamp
stale_after = 7                      # days before the clock surfaces one; advisory
suffixes = [".py", ".md"]            # where the policy reaches; defaults to the claims scope
resources = "docs/resources.toml"    # documents dated in a list instead — §6.3
```

There is no list of exempt kinds, because §6 admits none.

**`suffixes` is a scope, and a scope is not an exemption.** A citation in a file the policy does
not reach is not an accepted finding — it is not a finding, because the project has said the
requirement does not apply there. That is the difference between this and a baseline record, and
it is why one is declared in the config a reviewer reads while the other is a list that has to be
driven down.

The reason it exists is that the two checks answer different questions about the same file. **A
dead path in a README is a defect wherever it appears**, so a project wants documentation claims
read everywhere. **A stamp beside that path is apparatus** — it records when a checker last
confirmed the reference — and in the first page a reader of the project sees, it is a token they
have to learn to skip. Without a scope of its own, the only way to keep stamps out of user-facing
prose was to drop those files from `[claims] suffixes` entirely, which throws away the more
valuable of the two checks.

It is refused when `provenance` is off, for the reason `stale_after` is: scoping a policy nobody
declared narrows nothing, while reading in the file as though a decision had been made.

**It is also the blunter of the two answers**, and §6.3 is the other. A scope buys the notation's
absence by giving up the coverage; a resource list keeps both. Both are kept, because a project
that wants a tree genuinely outside the policy's reach is making a legitimate declaration rather
than working around one.

**Adoption is the existing ratchet, not a second one.** An undated citation is recorded, split
and driven down exactly as a duplication finding is: record the population the project already
has, and the gate fails only on citations added after that. A second exemption list would
eventually disagree with the first about what a project accepted.

**The clock is refused without the catch.** It can only see citations that carry a date, so with
the stamp requirement off it would report on whichever citations happen to be dated and say
nothing about the rest — a short list that reads like a clean tree. Half a policy is refused
rather than run.

### 6.3 A document that cannot carry a stamp

Some documents are the project's face rather than its apparatus: a README, a design document, an
introduction an adopter reads to decide whether to adopt. A stamp in one of those is a token the
reader has to learn to skip, in the very prose written to be read straight through.

**So the document is declared in a list, and the list carries the date.**

```toml
# docs/resources.toml
[[resource]]
path = "README.md"
confirmed = "2026-09-11"
note = "the first page a reader sees"
```

Every citation in a declared document is dated by its entry. Nothing is exempted: a citation in a
document that is neither stamped nor listed is the finding it was before, and a *new* user-facing
document that starts citing things is one the catch asks about.

**The unit is the file.** Citation-level entries would copy every citation in the tree into a
registry and target-level every target — a second carrier of facts the documents already state,
which is the duplication this tool exists to report. The cost of the coarser unit is real and is
stated rather than discovered: a citation added after the last confirmation sits under a date that
predates it. What bounds it is that `claims` settles every citation in those documents on every
run, so the entry records a verification and is not what keeps the citations true.

**An entry with no date covers nothing.** Declaring a document says where its date will live, not
that anybody has checked it, and until a run confirms it its citations are undated exactly as they
were. This is the difference between a list and an allowlist, and it is the whole reason the
mechanism is safe: the date is not writable by anyone with a text editor, because the only thing
that writes it is a run that settled the document.

**Four refusals, and the last one is the one that earns the mechanism its keep:**

- A path no file answers to. A resource nothing can read covers no citation while reading in the
  list as though it did — and a rename is exactly when that happens.
- The same document declared twice. One document has one date; two entries let a run write one and
  leave the other reading as a record.
- A document the citation policy does not read. Its citations are not findings, so dating them
  buys nothing and the entry reads as coverage.
- **A document the claims check does not read.** Confirmation asks whether everything a document
  cites still holds, and `claims` is what answers. A document nothing extracts claims from would
  be dated by every run for having nothing to falsify it — a green entry certifying a document
  nobody checked.

**The clock reads the entry's date.** A listed document whose citations are all local paths ages
without consequence, because §6 clocks only the kinds that leave the machine. A listed document
that cites an address is where a file-level date starts paying: the entry is what the clock has to
read, and `kinemata confirm` is what moves it.

## 7. Who writes a stamp

**The checker writes what it verified.** A stamp advanced by hand is unverifiable — nothing
prevents the date moving without the check ever running, which is a reminder wearing a catch's
clothes. And a weekly clock cannot be served by hand at any real volume: this project's own
working notes carry citations in the hundreds.

This is the one place the tool writes into prose, so the boundary is drawn tightly:

- **The gate only ever reports.** A check that rewrites the tree it is judging can make itself
  pass, which is the failure this project exists to catch.
- **An explicit command writes**, and only when run deliberately.
- **It writes only what it confirmed in that run.** A stamp is a record of a check that happened,
  never an assertion that one should have.

**There are two things to write and they are read by different oracles.** A keyed citation is
dated where it stands, and its key names the one source to settle. A document declared under §6.3
is dated in the list, and what has to hold is *everything it cites* — which is the question the
documentation check answers, so the writer runs that rather than forming a second opinion about
the same tree. Nothing short of a settled yes dates a document: a falsified citation, one no
oracle could reach, one held open by a promise and one declared to live in another project's tree
are all citations the run did not confirm. The first is a defect and the rest are honest, and none
of them is a verification.

**A first date in a list has to be inserted**, which a stamp never does — a keyed citation already
carries a timestamp, so the edit is a fixed-width replacement and every other byte of the document
is the byte it was. Insertion is admitted in the list and refused in prose, and the distinction is
not squeamishness: the list is a file the tool maintains, and a document is somebody's writing.

## 8. What is not settled here

**The reserved type vocabulary.** The tiering is settled; the list grows only by explicit
decision, never because a maintainer noticed a gap.
