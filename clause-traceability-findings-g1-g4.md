# Clause Traceability Brief — four findings on v2

**Reviewed:** `clause-traceability-brief(2).md` (19:47 revision; strictly later than the 19:25
file and additive over it, so treated as current) against `settings-keyspace-1.8.0.md`.

**Scope of this document:** four findings, G1–G4, plus a minor pair. The two design deltas
discussed separately — `STANCE` as a fifth classification class, and §4 re-based onto a general
registry role — are **not** in this document.

**All six v1 findings are resolved in v2.** F1 (Phase 0 scope), F2 (where classes live), F3
(hash normalization pinned), F4 (`key` marked provisional), F5 (sample floor), F6 (rename
without OFT support). Two fixes the author added unprompted — the §0 spike ahead of everything,
and §6.5 removing ledger writes from the read-only editor — are both correct; the second closes
a hole in v1 that asked a read-only role to write a file.

Every measurement below states its method so it can be re-run and disagreed with. Where a
number here differs from one I reported earlier, the number here is the measured one.

---

## G3 — RATIONALE text welds into the preceding clause's body hash

**Fix this first.** It is an interaction between two v2 fixes, so the others sit on top of it.

**Where.** §1.2 defines the hashed body as:

> the clause body (everything after the OFT item header **up to the next item or heading**)

§2.2 then places RATIONALE and HISTORY outside the item system:

> RATIONALE and HISTORY are not OFT items and carry no ID. They get a lightweight inline
> marker … e.g. an HTML comment **immediately preceding the paragraph**

**The defect.** A RATIONALE paragraph that follows a NORM item — the natural placement, since
it explains that clause — is neither an item nor a heading. It therefore falls **inside** the
preceding clause's body window and is hashed as part of it.

**Consequences, in order of severity:**

1. Editing rationale changes a NORM clause's body hash. §1.2 says "CI fails when a clause body
   changes without a revision bump," so the edit fails CI until the clause revision is bumped.
2. Bumping the revision triggers §5: "A change that alters a NORM clause splits into two
   separately merged changes." A typo fix in an explanation now costs two merges and a
   re-confirmation of the clause's gates.
3. §5 requires `kanibako spec stale` to be non-empty between those merges. So a rationale edit
   manufactures a stale coverage signal for a clause whose normative text did not change.
4. The body hash silently means "clause text **plus** any trailing rationale." §1.2's stated
   intent — "Re-wrapping a paragraph is free; changing any character is a bump" — is about the
   clause. It now binds text the classification model deliberately excluded from clause-hood.

**This is self-inflicted by the v2 improvements**, which is why it is worth naming rather than
patching quietly: v1 had no body hash to weld into, and no inline markers to weld.

**Fix options**, cheapest first:

- **Terminate the body window at a marker.** Define the body as ending at the next item,
  heading, **or classification marker**. The markers are already required to be "greppable, one
  per statement, and unambiguous to a deterministic parser" (§2.2), so the parser that finds
  them exists by Phase 1 regardless. One clause added to §1.2.
- **Require rationale to precede the item it explains.** Cheap to state, expensive to enforce,
  and it fights how people write.
- **Make RATIONALE/HISTORY items with no coverage requirement.** Clean model, but it reopens F2
  and contradicts §2.2's "no ID" rule.

The first is the only one that does not disturb a settled decision.

---

## G1 — the clause-count estimate is low, and now sizes the wrong thing

**Where.** §1.2: "One `spec` item per **independently testable normative statement**, not per
section. **Expect 15–40 in `§2a` alone.**"

**Measured.** §2a of `settings-keyspace-1.8.0.md` is lines 559–849, **291 lines**.

| Reading of "independently testable normative statement" | Count in §2a |
|---|---|
| Strict — statements carrying an explicit modal (`MUST`, `SHALL`, `NEVER`, `ONLY`, `ALWAYS`, `REQUIRED`, `CANNOT`) | **58** |
| Broad — every statement-like unit: sentences, list and arrow items, table rows, and key-definition rows inside fenced blocks | **307** |

*Method:* split the section into units — one per list item, arrow item, table row, key row, or
sentence over 25 characters — then filter by the modal set above. The modal filter is the
brief's own instrument: §2.2 requires human review of "the non-NORM set **filtered by modal
verbs** (must, shall, never, only, always, required)."

**So the strict count already exceeds the brief's upper bound by 45%, and the brief's own
definition is broader than the strict count.** A key-definition row such as
`<scope>.bindings.rw | CONCRETE | dict[box_dest → (host_src[, opts])] … TERMINAL key, DEST-KEYED`
is independently testable and carries no modal at all.

**Document-wide**, which is what v2 actually scopes: **1,504** statement-like units, **287**
carrying an explicit modal. Phase 0's scope in v2 is "the whole of `settings-keyspace-1.8.0.md`,
every section" — not §2a — so the figure that sizes the phase is the document one, and §1.2
still quotes a fragment.

**Why it matters.** Everything downstream is sized off this number: two independent
classification passes to be diffed (§2.2), human review of every class A plus the whole non-NORM
set filtered by modal verb (§2.2), and the Phase 1 baseline uncovered count that the ratchet
freezes (§3). At 15–40 those are an afternoon. At 287+ with two passes and a full non-NORM
review, Phase 0 is the largest item in the plan and the review load is the binding constraint,
not the classification.

**Fix.** Replace the §2a estimate with a document-level range and state the counting rule that
produced it. If a per-section figure is still wanted, give §2a's own: 58 strict, more under the
brief's definition.

---

## G2 — the unclassified-statement check is defined over "paragraphs"

**Where.** §2.2: "The unclassified-statement check (§2) is that parser: **any paragraph** in a
Phase-0-complete document that is neither inside an OFT item nor preceded by a marker fails CI."
§2.2 acceptance: "The unclassified-statement parser returns empty on the document."

**Measured**, across the whole keyspace spec — lines carrying an explicit modal, by the
structure they sit in:

| Context | Modal-carrying lines | Share |
|---|---|---|
| Paragraph | 132 | 56% |
| Fenced block | 73 | 31% |
| List / arrow item | 24 | 10% |
| Table row | 8 | 3% |
| **Total** | **237** | |

*Method:* fence-tracking line classifier; "paragraph" means any non-blank line outside a fence
that is not a list item or table row, so continuation lines inflate that row. The 56% is
therefore an **over**-estimate of what a paragraph-scoped check would reach.

**The defect.** A check scoped to paragraphs is blind to **44%** of the document's
modal-carrying content — and 35% of the document's lines are inside fenced blocks. This
matters more than the ratio suggests, because the fenced blocks are where the key definitions
live, and those are the statements the manifest linkage in §4 has to resolve against.

**A concrete sample** from §2a, inside a fenced block:

> `**SEED DESTINATIONS ARE ENUMERATED, NEVER A WHOLE-DIRECTORY COPY — AND THIS HOLDS AT EVERY
> LEVEL.** The enumeration IS an allowlist, so it is a correctness property, not a style
> choice.`

That is a class-A-shaped containment statement — it governs what a copier may write — sitting
inside a fence, prefixed with `#`, invisible to a paragraph-scoped parser.

**A second-order problem, found by hitting it.** Writing the measurement above, my first parser
mistook `#`-prefixed comment lines *inside* fenced blocks for Markdown headings, and silently
mis-sectioned the document. §1.2's body window is defined as running "up to the next item or
**heading**." A parser that does not track fences will terminate clause bodies at those lines.
So the same ambiguity that breaks the unclassified check also breaks the body hash. **Whatever
parses this document has to be fence-aware, and the brief should say so.**

**Fix.** Define the check over **statements** with an enumerated block taxonomy — paragraph,
list item, table row, and fenced-block comment line — and state that the parser is fence-aware.
Then re-state §2.2 acceptance against that taxonomy, since "returns empty on the document" is
only meaningful once the unit is defined.

---

## G4 — deferring `system-design-1.8.0.md` is not neutral

**Where.** §12.4 defers the question of whether `system-design-1.8.0.md` needs classification at
all. §2 makes the deferral total: "a document that has not completed Phase 0 is not imported
into OFT and is exempt from the unclassified-statement check"; §12.4 adds "it is outside every
mechanism here — no IDs, no import, no ratchet."

**Measured** in `settings-keyspace-1.8.0.md`: **29** references to `system-design-1.8.0.md`, of
which **14** transfer authority rather than merely cross-referencing — phrased "moved to",
"MIGRATED WHOLE", or "THAT FILE is now their only carrier". Examples: the seed whitelists and
the copier's traversal/symlink enforcement rules (line 829); seed and template copy ordering
(845); `<VAR>` delivery at launch (746); leaf sanitisation and the length-bounded socket name
(922); detection and import, migrated whole (1553).

*Method:* line-level match on `system-design`, then a second match for authority-transfer
phrasing. Both counts are re-runnable and I would expect a reader to check the 14.

**The defect.** In 14 places the normative substance of a keyspace clause has been moved into a
document that Phase 0 excludes. The pointing clause gets an ID, a class, an evidence class, a
body hash, and a coverage requirement. The text it points at gets none of them. Specifically:

- **Coverage reads green for clauses whose content is elsewhere.** A clause saying "the rules
  live in `system-design`" is trivially satisfiable by a gate that asserts the pointer, not the
  rule.
- **§5 cannot see amendments to the migrated text.** The body hash covers the pointer. The
  rules can change freely with no revision bump, no stale signal, and no two-merge split — the
  exact bypass §5 exists to prevent.
- **Several of the migrated topics are class A by §2.1's own test** — containment boundaries and
  what a copier may write to disk. Deferring them defers the highest-evidence material.

**Fix options:**

- **Classify `system-design-1.8.0.md` in Phase 0** alongside the keyspace spec. Largest cost,
  and it makes §12.4 moot.
- **Treat an authority-transferring pointer as a defect** and require the clause to carry its
  own normative text, with the other document holding elaboration only. Consistent with §10's
  "delete the prose note rather than rephrasing it" and with the design's one repeated idea:
  declare once, generate views, never hand-maintain a second copy.
- **Accept the gap explicitly** — enumerate the 14, record them as known-uncovered, and exclude
  them from the Phase 1 baseline so the ratchet does not certify them as covered. Cheapest, and
  honest, but it leaves class A material outside every mechanism.

The middle option is the one that matches the rest of the design.

---

## Minor

- **§4.2 says "None require Java."** The table it closes lists `kanibako spec keys`, `key`,
  `clause`, `uncovered`, `stale` — all index readers, so the claim holds for that table. But §3
  step 4 delivers `kanibako spec build-index` and states it "needs Java only because it invokes
  OFT". The two sit close enough that "None require Java" reads as covering the whole `spec`
  command group. Scope the sentence to the table.
- **`aliases:` has no specified author.** §2.2 requires an `aliases:` entry "on the clause in the
  index mapping old ID → new", and §3 lists aliases among the index's per-clause fields. But
  §2.2 also establishes that the spec is "the sole author of every clause's class and evidence
  class; the index only reads it," and §3 says "nothing edits the index by hand." So the alias
  has no declared source: it cannot be hand-written into a generated file, and no spec-side
  syntax for it is given. Name where an alias is written.

---

## Method note

Counts came from line-level classifiers over the two documents, not from reading end to end.
Each is stated with its heuristic above so it can be re-run and contested. The two places where
this document corrects an earlier report of mine:

- **G2** was previously stated as "the densest normative content is in fenced blocks and list
  items." Measured, paragraphs still hold the plurality at 56%. The finding survives — a
  paragraph-scoped check misses 44% — but the original wording overstated it.
- **G4** was previously reported as 28 cross-references. The measured figure is 29, of which 14
  transfer authority; the 14 is the number that carries the argument.
