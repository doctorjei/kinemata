# Clause Traceability Brief — findings on v3

**Reviewed:** the v3 revision, against `settings-keyspace-1.8.0.md` and
`system-design-1.8.0.md`.

**G1–G4 and both minors are resolved.** The fixes are the right ones and in two cases
better than what was proposed:

| Finding | Resolution in v3 |
|---|---|
| G3 — rationale welds into the body hash | §1.2 pins the body window to "the next item header, the next Markdown heading, or the next **classification marker**", and states outright that a following RATIONALE paragraph is outside the hash. Risk row added. |
| G2 — check defined over paragraphs | §2.2 redefines it over **statements** with an enumerated taxonomy, and requires a fence-aware parser. |
| G1 — clause estimate an order of magnitude low | §1.2 gains a *Sizing* paragraph with the counting rule, and plans Phase 0 for 300–500 NORM clauses. Names review load as the binding constraint. |
| G4 — deferring `system-design` is not neutral | §2 scope covers both documents; the "**Pointers are not NORMs**" rule attaches coverage to the target rather than the pointer; §12.4 resolved. |
| Minor — "None require Java" | §4.2 scopes the claim to the five index readers and names `build-index` as the exception. |
| Minor — `aliases:` had no author | A spec-side `<!-- alias: … -->` marker, in the same family as the class markers. |

**The best change is one nobody asked for.** §0 spike item **3(c)** — whether OFT's
Markdown importer recognises an item inside a fenced code block, and whether a
`#`-prefixed line inside a fence reads as a heading. That is now the highest-stakes
item in the document: about a third of the keyspace spec's lines are inside fences,
including most key definitions. If the answer is no, Phase 1 is blocked on restructuring
the spec, and everything downstream moves. Running that spike first is right.

Three new problems, all introduced by the fixes.

---

## V1 — §1 contradicts §2 and its own resolved decision

**Where.** §1, closing the Architecture section:

> The diagram shows the target state. **Phase 0 scopes to the keyspace spec only;
> `system-design-1.8.0.md` enters when open decision §12.4 resolves.**

**Why it is now wrong.** §12.4 *is* resolved — struck through in §12, answered "yes" —
and §2 scopes Phase 0 to both documents whole. §1 still describes the superseded plan.

**Why it matters more than a stale sentence usually would.** §1 is the orientation
section; a reader who stops there gets the pre-fix scope, which is exactly the scope G4
showed leaves class-A material outside every mechanism. The document now states its
scope in two places and they disagree.

**Fix.** Replace with the resolved position: Phase 0 covers both documents, keyspace
first, `system-design` after. One sentence.

---

## V2 — the ratchet trips precisely when a document is admitted correctly

**Where, in tension.** §3 step 1:

> Import every spec Markdown file that has completed Phase 0 **(initially: the keyspace
> spec only)**

§3, after the baseline:

> Then enable the ratchet: CI fails on any **increase** in uncovered clauses.

§2 now requires `system-design` to be classified in full, after the keyspace spec.

**The defect.** The baseline is recorded over the keyspace spec alone. When
`system-design` completes Phase 0 and is imported, it arrives with a block of newly
identified NORM clauses, most of them with no coverage links yet — Phase 1 explicitly
writes no new tests. Uncovered goes up, and **CI fails on the merge that did the work
correctly.**

The existing risk row — "A second spec document enters half-classified … per-document
Phase 0 gate: a document is imported only once it passes §2 acceptance in full" —
addresses the *unclassified check*, not the ratchet's *count*. Passing the gate in full
is what causes the increase.

The rational response to a gate that fires on correct work is to switch it off, or to
re-baseline in the same commit, which silently absorbs whatever else arrived.

**Measured, so the size is known rather than feared.** Under the same counting rule §1.2
now adopts, `system-design-1.8.0.md` is **430 lines, 364 statement-like units, 71 strict
NORM candidates**, only 5% of lines inside fences — a much flatter document than the
keyspace spec. So the admission event adds on the order of 71–150 clauses at once, nearly
all uncovered on arrival.

**Fix options:**

- **Baseline per document.** The ratchet compares each document against its own recorded
  baseline; admitting a document records its baseline in the same merge, and that record
  is the visible artifact. Cleanest, and it matches how the per-document Phase 0 gate
  already works.
- **Admission re-baselines, deliberately.** A single named operation whose diff shows the
  new count. Requires the review discipline to look at it.
- **Ratchet on covered share rather than absolute count.** Rejected here for the reason
  §3 already gives about counts — a ratio moves for reasons unrelated to the work.

---

## V3 — the sizing has a hole where `system-design` should be

**Where.** §1.2, *Sizing*:

> Plan Phase 0 for **300–500 NORM clauses in the keyspace spec**, plus
> `system-design-1.8.0.md` (§2).

**The defect.** "Plus" carries no number, and §2 now makes that document mandatory. The
figure that sizes the phase is therefore incomplete in the one paragraph written to size
it — and the whole point of the G1 fix was that the phase had been sized against a
fragment.

**Measured**, applying §1.2's own counting rule to both documents:

| Document | Lines | In fences | Statement-like units | Strict NORM candidates |
|---|---|---|---|---|
| `settings-keyspace-1.8.0.md` | 1,556 | 35% | 1,504 | 287 |
| `system-design-1.8.0.md` | 430 | 5% | 364 | 71 |

**Fix.** State the second document's range explicitly. Note also that the two documents
have very different shapes: at 5% fenced, `system-design` is ordinary prose, so the
fence-aware parser and the fenced-block statement type matter far less there. The
classification effort per line will not be the same, and the plan should not assume it
is.

---

## Minor

**§1.2's counting rule reads as a clause-identity rule.** It sits immediately after "One
`spec` item per **independently testable normative statement**", and gives a mechanical
procedure — split into units, filter by modal. A Phase 0 agent could reasonably implement
clause splitting from it and emit one clause per table row.

It is a **sizing estimator**, not a definition of clause identity. The paragraph says as
much implicitly ("the brief's own definition is broader than the modal filter"), but one
explicit sentence would prevent the misreading: *this rule estimates the population; it
does not decide clause boundaries.*

---

## Method note

Counts came from line-level classifiers over the two specs, using §1.2's stated rule so
the numbers are comparable to the ones already in the brief. They are proxies — a
statement can span lines, and a line can hold several — and are stated as ranges for that
reason. Every figure here is re-runnable and worth contesting.
