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
both must agree on forever. The entry names the foreign identifier where there is one.

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
| `Cm` | commit | settles that the history knows it |

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

Archived material is left alone on both axes. A record cites what was true when written.

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

## 8. What is not settled here

**The reserved type vocabulary.** The tiering is settled; the list grows only by explicit
decision, never because a maintainer noticed a gap.
