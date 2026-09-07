# Clause Traceability & Gate Coverage — Implementation Brief

**Target:** kanibako-cli · **Status:** design, not ratified
**Companion:** `clause-traceability-rationale.md`

This file is normative. Rationale lives in the companion, addressed as `[W-n]`.
**Read a rationale entry only when you disagree with a rule, or need to decide a case
this brief does not cover. Do not read the companion end-to-end.**

Identifier namespaces, so they are never confused:

| Form | Meaning |
|---|---|
| `[W-n]` | rationale entry in the companion file |
| `R-n` | a ruling recorded in the keyspace manifest (existing numbering, unchanged) |
| `D-*`, `M-*` | manifest decision / migration IDs (existing) |
| `spec~…~n` | a clause ID with revision `n` |

---

## 0. Before writing code

**The first work item is a spike, not classification.** Phases 1–2 rest on OFT's
Markdown import supporting the item shape used here (ID with revision, `Needs:`,
`Covers:`, `Tags:`). Until that is confirmed against a real run, nothing below §2 is
known to be buildable. Phase 0's *content* can proceed in parallel, since it needs no
tooling; its *serialization format* waits on the spike.

1. Read the OFT user guide
   (`https://github.com/itsallcode/openfasttrace/blob/develop/doc/user_guide.md`).
   All OFT **syntax** in this brief is indicative and unverified; the guide is
   authority. Correct the syntax in this brief where they disagree.
2. Confirm the current OFT release and its Java requirement.
3. Run OFT against a three-item fixture (one `spec`, one `impl`, one `utest`) that
   exercises revision mismatch and `Tags:`. Record the exact syntax that worked.
   In the same spike, record: **(a)** which machine-readable export OFT offers for
   the trace (the §3 index generator consumes it — if none is suitable, the generator
   parses the plain report, and that is a finding to report); **(b)** whether OFT has
   any support for renaming an item ID. §2.2 assumes neither answer; it is written to
   work without both. **(c)** Whether OFT's Markdown importer recognises an item whose
   header and body sit **inside a fenced code block**, and whether a `#`-prefixed line
   inside a fence is taken as a heading. About a third of the keyspace spec's lines,
   including most key definitions, are inside fences. If items in fences are not
   importable, that is a §0.4 stop-and-report: the spec would need restructuring before
   Phase 1, and that is a director decision.
4. If a **rule** in this brief (as opposed to its syntax) conflicts with how OFT
   actually works, **stop and report**. Do not reimplement OFT behind a
   compatible-looking surface. `[W-5]`

---

## 1. Architecture

```
  settings-keyspace-1.8.0.md ──┐
  system-design-1.8.0.md ──────┤ spec~ items (clause IDs)
  keyspace-manifest.yaml ──────┤ key~ items, each Covers: its clauses
  src/**.py   (impl-> tags) ───┤
  tests/**.py (utest-> tags) ──┘
                               │
                          [ OFT trace ]   ← host / CI only (Java 17+)
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
      trace-report.html   clause-index.json   exit code
       (human review)      (box-consumable)   (CI gate)
```

OFT runs host-side or in CI only. Boxes never invoke it; they consume
`clause-index.json`, delivered read-only. `[W-5]`

The diagram shows the target state. Phase 0 scopes to the keyspace spec only;
`system-design-1.8.0.md` enters when open decision §12.4 resolves.

### 1.1 Artifact types

| Type | Lives in | Meaning |
|---|---|---|
| `spec` | the two Markdown specs | a normative clause |
| `key` | manifest projection | a declared keyspace key — **provisional; open decision §12.2**. The preferred outcome is that `key` is *not* an OFT type and the manifest's `clauses:` field plus the generated index carry the linkage. The diagram shows the OFT-type variant only because it is the one that needs drawing. |
| `impl` | `src/**` | code implementing a clause |
| `utest` / `itest` | `tests/**` | a gate enforcing a clause |

A `spec` item needs `impl` and at least one of `utest`/`itest`. Keys map to the `spec`
clauses that govern them, via manifest `clauses:`; that mapping is the inverse index
regardless of how §12.2 resolves.

**Tagging obligation.** Code that implements a briefed clause carries an `impl` tag for
it, written by the writer in the same change. Untagged code is invisible to every
mechanism in this brief — the ratchet, `for-diff`, and `drift` all see only tags. A
briefed clause implemented without a tag is a `return` (§6.4).

### 1.2 Clause granularity and revision

One `spec` item per **independently testable normative statement**, not per section.
ID form: `spec~keyspace-containment-collision~1`. `[W-6]`

**Sizing.** Counting rule: split the document into statement-like units (one per
sentence over ~25 characters, list or arrow item, table row, key-definition row, and
fenced-block comment line); the strict NORM candidate set is the units carrying an
explicit modal (must, shall, never, only, always, required). On
`settings-keyspace-1.8.0.md` that gives roughly **1,500 units and ~290 strict
candidates**, and the brief's own definition is broader than the modal filter — a key
row with no modal is still independently testable. Plan Phase 0 for **300–500 NORM
clauses in the keyspace spec**, plus `system-design-1.8.0.md` (§2). Review load, not
classification, is the binding constraint of the phase.

**Bump the revision on any change to the statement text**, not only on changes to its
meaning. `clause-index.json` records a body hash per clause; CI fails when a clause
body changes without a revision bump. A typo fix pays the bump and a re-confirmation of
its gates. That cost is small; an unbumped meaning change silently disables §5. `[W-11]`

**The body window is pinned too:** the clause body runs from the end of the OFT item
header to the first of — the next item header, the next Markdown heading, or the next
**classification marker** (§2.2). A RATIONALE or HISTORY paragraph following a clause is
therefore outside the clause's hash; editing an explanation never bumps the clause it
explains. The window parser is **fence-aware**: a `#`-prefixed line inside a fenced code
block is not a heading, and a fence boundary does not end a body. `[W-11]`

**Normalization is whitespace-only, and pinned:** the body, as delimited above, is
Unicode-NFC-normalized, every run of whitespace including newlines is collapsed to one
space, leading and trailing whitespace is trimmed, and the result is hashed with
SHA-256. Nothing else is stripped — not Markdown emphasis, not backticks, not
punctuation. Re-wrapping a paragraph is free; changing any character is a bump. The
check is meant to be dumb. `[W-11]`

---

## 2. Phase 0 — Classification

**Scope: the whole of `settings-keyspace-1.8.0.md` and the whole of
`system-design-1.8.0.md`, every section of each.** Not a subset of sections. The
keyspace spec transfers authority to `system-design` in fourteen places ("moved to",
"MIGRATED WHOLE", "THAT FILE is now their only carrier"), several of them class-A
containment material; a design that excludes the carrier of that text has coverage
reading green on pointers. A document that has not completed Phase 0 is not imported
into OFT and is exempt from the unclassified-statement check below — this now applies
only to documents added later. Order: keyspace `§0`, `§2a`, `§2c` first as the
checkpoint for reviewing the classifier's output; then the rest of the keyspace spec;
then `system-design`. `[W-19]`

**Pointers are not NORMs.** A statement whose normative content is that the rule lives
elsewhere ("the copier rules are in `system-design` §N") is classified GUIDANCE with
`Tags: guidance, pointer`, and the target statement is the NORM. A gate that asserts the
pointer covers nothing; the coverage requirement attaches to the target. `[W-19]`

Classify every statement in the document into exactly one class:

| Class | Test | ID? | Coverage required? |
|---|---|---|---|
| **NORM** | asserts something that must hold; violation is a defect | yes | yes |
| **RATIONALE** | explains why a NORM exists; would change an agent's action today | no | no |
| **HISTORY** | records what something used to be | no, but carries `expires:` (version or date) | no |
| **GUIDANCE** | non-binding; explicitly unspecified or advisory | yes, `Tags: guidance` | no `[W-7]` |

Rationale vs history test: **would this text change an agent's action today?**

**Classification is a standing obligation, not a one-time pass.** Every statement added
to a spec is classified in the same change. From Phase 1 onward, CI fails on an
unclassified statement. Without this the metric in §2.2 is dead the day Phase 0 ends.
`[W-9]`

### 2.1 Evidence class

Assign every NORM clause a class in the same pass:

| Class | Applies to | Required evidence |
|---|---|---|
| **A** | credentials, containment/isolation boundaries, anything deleting user data, public CLI/API contract | gate + adversarial editor pass + mandatory director review |
| **B** | resolution/cascade semantics, binding emission, seed and copy behaviour | gate + adversarial editor pass |
| **C** | everything else | gate |

Class A should be a few percent of clauses. Over-assignment is the failure mode. `[W-8]`

### 2.2 Rules

- Freeze all IDs at end of phase. A later rename is a single merge that touches spec,
  `src/`, `tests/`, and manifest together, plus an alias marker on the renamed item in
  the spec (`<!-- alias: spec~old-id~3 -->`, same marker family as §2.2's class markers,
  spec-authored, index-read) which the generator surfaces as `aliases:` on the clause. A
  conformance check asserts no reference to the old ID survives outside `briefs/` and
  `decisions.jsonl`, which are immutable and resolve through the alias. If the §0 spike
  finds OFT has native rename support, use that for the spec side and keep the rest.
- Record NORM share by volume. Track as a trend, not a threshold. `[W-9]`
- Delegatable to an agent with a strict output format. Agent output is not
  deterministic: run **two independent classifications and review the diff**.
- Human review covers **(a) every class A assignment** and **(b) the non-NORM set
  filtered by modal verbs** (must, shall, never, only, always, required). The NORM set
  cannot show what is missing from it; the misfiled NORM is in the other pile. `[W-1]`

**What "deterministic" means here.** The classifier is an agent and is not
deterministic. The *artifact* is: the classification is run, reviewed, frozen, and
never regenerated. Re-runs exist only during Phase 0 as a review instrument (the diff
of two passes). After freeze, a new statement is classified by hand or by agent when
it is written, never by re-classifying the document.

**Where the classes live — in the spec, nowhere else.** The spec Markdown is the sole
author of every clause's class and evidence class; the index only reads it.

- NORM and GUIDANCE are OFT items. Class and evidence class are OFT `Tags:`
  (`Tags: norm, class-b`; `Tags: guidance`). OFT imports them; the index generator
  (§3) reads them from OFT's export.
- RATIONALE and HISTORY are not OFT items and carry no ID. They get a lightweight
  inline marker the generator parses directly from the Markdown — e.g. an HTML
  comment immediately preceding the paragraph, `<!-- rationale -->` or
  `<!-- history expires:1.9.0 -->`. The exact spelling is the Phase 0 agent's to
  choose, subject to: greppable, one per statement, and unambiguous to a
  deterministic parser. Record the choice in this brief.
- The unclassified-statement check (§2) is that parser, defined over **statements**,
  not paragraphs. The statement taxonomy is enumerated: paragraph, list or arrow item,
  table row, key-definition row, and **comment line inside a fenced code block**. The
  parser is fence-aware (§1.2). Any statement in a Phase-0-complete document that is
  neither inside an OFT item nor preceded by a marker fails CI. A paragraph-scoped
  check would miss roughly 44% of the keyspace spec's modal-carrying lines, most of
  them the key definitions §4 has to resolve against.

The two classification passes each emit a worksheet (`phase0/pass-a.tsv`,
`phase0/pass-b.tsv`: section, statement, class, evidence class). The worksheets exist to
be diffed and reviewed; once the tags and markers are written into the spec and
reviewed, both are deleted. **No `clause-manifest.json`.** After Phase 0 there are
exactly two carriers of clause metadata: the spec (authoritative) and the index
(generated).

**Acceptance, per document in scope:** every NORM statement carries an ID. No statement
carries two. Every RATIONALE and HISTORY statement carries its marker; every HISTORY
marker carries `expires:`. Every NORM clause carries an evidence-class tag. Every
authority-transferring pointer is tagged `pointer` and its target carries an ID. The
unclassified-statement parser, over the taxonomy above, returns empty. Class A share
recorded.

---

## 3. Phase 1 — OFT baseline

1. Wire OFT into CI. Import every spec Markdown file that has completed Phase 0
   (initially: the keyspace spec only); import coverage tags from `src/**` and
   `tests/**`.
2. Tag existing conformance tests with clauses they already assert. **Write no new
   tests in this phase.**
3. Emit `trace-report.html` from OFT directly.
4. **Deliver `kanibako spec build-index`** (host-side; needs Java only because it
   invokes OFT). It is a named deliverable of this phase, not a by-product: OFT knows
   nothing of evidence classes, body hashes, RATIONALE markers, or aliases. Inputs:
   OFT's machine-readable export (format per the §0 spike) and the spec Markdown.
   Output: `clause-index.json`, carrying per clause — class, evidence class, revision,
   body hash (§1.2), aliases, covering items with link status, and for RATIONALE/HISTORY
   statements their marker and `expires:`. CI runs it and commits or publishes the
   result; nothing edits the index by hand.
5. **Do not fail the build.** Record the baseline uncovered count in `devnotes.md`.
   Expect it to be higher than feels reasonable. `[W-10]`

Then enable the ratchet: CI fails on any **increase** in uncovered clauses. New NORM
clauses ship with a gate or do not ship. Backlog reduction is separately scheduled and
must not block feature work.

**Definition of uncovered, for the ratchet:** a clause with **no coverage link at all**.
A clause whose only coverage points at a superseded revision is **stale**, not
uncovered. OFT reports these as distinct link statuses; keep them distinct. Stale is
owned by §5 and never counted by the ratchet — otherwise the amendment commit §5
requires cannot pass CI. `[W-10]`

**Acceptance:** report renders; uncovered list is plausible on inspection; baseline
recorded; `kanibako spec uncovered` and `kanibako spec stale` return disjoint sets.

---

## 4. Phase 2 — Manifest linkage and projection

### 4.1 Structured provenance

```yaml
box.enable_vault:
  scope: box
  type: bool
  set: cli+file
  default: true
  clauses: [spec~box-vault-enable~1, spec~scope-containment~2]
  since: 2026-07-14
  rulings: [R-11, D-M6]          # manifest rulings, not rationale entries
  superseded: ["box.vault (2026-06-30)"]
  migration: {id: M-9, from: box.vault, since: "1.7.0", drop_after: "1.9.0"}
```

- `note:` survives with a hard length cap enforced by the conformance suite.
- Trailing-comment history moves into `rulings` / `superseded` / `migration`.
- Retired names move to `not_keys`, which already enforces them. **Delete** the prose
  note rather than rephrasing it. `[W-3]`

### 4.2 Commands

| Command | Output |
|---|---|
| `kanibako spec keys` | all keys, no commentary. The director's loadable projection. |
| `kanibako spec key <name>` | one row plus full text of its governing clauses |
| `kanibako spec clause <id>` | clause text, covering gates, covered keys |
| `kanibako spec uncovered` | NORM clauses with no coverage link |
| `kanibako spec stale` | gates referencing a superseded clause revision |

All five read `clause-index.json`; none of these five requires Java, and all work
in-box. (`build-index`, §3, is the one `spec` subcommand that does need Java, and it
runs host-side only.)

**Acceptance:** `kanibako spec keys` under 16 KB total and under 160 bytes per key
line (a byte budget, not a token count — tokenizers differ, bytes do not). `kanibako
spec key` under 200ms wall-clock **including interpreter startup**, which is a
lazy-import constraint: the `spec` command group imports nothing that transitively
imports the YAML manifest loader, and reads only `clause-index.json`. A conformance
test asserts every manifest key resolves to ≥1 clause ID.

---

## 5. Phase 2.5 — Amendment ordering (gate, not a feature)

A change that alters a NORM clause **splits into two separately merged changes**
(two PRs, or two commits landing on `main` independently — squash-merge collapses
commits inside one PR, so the unit is the merge):

1. **Amendment** — clause text edited, revision incremented, ratified. Lands alone.
2. **Implementation** — writer works against the new revision; gates updated and
   re-confirmed.

Between them, `kanibako spec stale` **must be non-empty**. An empty stale set at an
amendment merge means either nothing covered the clause (a Phase 1 gap, now visible)
or the revision was not bumped (a defect — which the body-hash check in §1.2 catches
mechanically). `[W-11]`

**Acceptance:** a conformance check, run on the **merge diff into `main`**, rejects any
change that both alters a clause revision and modifies files carrying coverage tags for
that clause. The amendment merge passes the ratchet because stale is not uncovered
(§3).

---

## 6. Phase 3 — Briefs, diff resolution, editor loop

### 6.1 `kanibako spec for-diff [--base REF]`

Resolve a diff to a clause set by union of three signals, reporting which signal
produced each result:

1. **Coverage tags in touched files.** Two strengths: a tag **within a touched hunk
   (±15 lines) is strong**; any other tag in a touched file is **weak**. Report both;
   only strong signals feed the escalation trigger (§6.3). `[W-18]`
2. **Key literals in changed lines** — match the manifest key set against added and
   removed text, resolve through `clauses:`. Strong.
3. **Touched manifest rows** — their `clauses:` directly. Strong.

Also report the highest evidence class among resolved clauses (strong and weak: a weak
class-A hit still routes to director review, because the cost of missing it is the
reason class A exists).

### 6.2 Briefs become files

Currently ephemeral. This is the blocking change of the phase. `[W-12]`

Write `canon/workbook/briefs/<task-id>.md`, checked in:

```yaml
---
task: T-441
clauses: [spec~box-vault-enable~1, spec~scope-containment~2]
predicted_class: B          # advisory; the binding class comes from the derived set (§6.6)
scope: ["src/kanibako/box/**"]
keys: [box.enable_vault]
issued: 2026-09-02
supersedes: null            # or the filename of the brief this replaces
---
```

- Clause IDs only. **Never paraphrased constraints.**
- Immutable once issued. A brief needing change is superseded by a new file
  referencing it. The ledger (§6.5) names the brief file, not just the task, so
  `derived \ briefed` is always computed against the brief in force at that diff.

### 6.3 Editor procedure

Ordering is normative: `[W-13]`

1. Run `for-diff`; form a judgment from the diff plus that clause set.
2. **Then** read the writer's rationale, as a second pass, for intent mismatch.

Report `derived_strong \ briefed`. Non-empty is the escalation trigger. Weak-signal
clauses outside the brief are listed in the record but do not trigger by themselves.
`[W-18]`

### 6.4 Verdicts

| Verdict | Meaning | Routes to |
|---|---|---|
| `accept` | conforms to brief and derived clause set | director |
| `return` | implementation defect, including a briefed clause without an `impl` tag | writer |
| `escalate:brief-insufficient` | spec covers it; extraction missed it | director |
| `escalate:spec-insufficient` | clause ambiguous, or two clauses conflict | director → spec defect list |

The two escalation classes must stay distinguishable in the record. `[W-14]`

**Escalation friction is bounded by mechanism, not by exhortation:**

- When `derived_strong \ briefed` is non-empty, `for-diff` **emits the
  `escalate:brief-insufficient` record pre-filled with that set.** The set is the
  argument. The editor confirms or annotates; it composes nothing.
- `escalate:spec-insufficient` is a two-field template: the clause ID(s), and one line
  naming the ambiguity or conflict. Nothing else is required.

### 6.5 Decision ledger

The editor is read-only by construction and **does not write the ledger**. The
editor's final output is the record below as structured data; the kanibako harness,
host-side, appends it to `decisions.jsonl` and commits. No agent role holds write
access to the ledger — the writer cannot alter it either. `[W-12]`

One record per editor decision:

```json
{"task":"T-441","brief":"briefs/T-441.md","verdict":"accept",
 "briefed":["spec~..."],"derived_strong":["spec~...","spec~..."],
 "derived_weak":["spec~..."],"evidence_class":"B","diff_sha":"...","ts":"..."}
```

### 6.6 Required evidence

| Class | Editor must have |
|---|---|
| C | gate passing; derived clause set checked |
| B | above, plus a recorded adversarial pass — an attempt to find a violation, not a confirmation read |
| A | above, plus `accept` routes to mandatory director review rather than closing |

**Class comes from the derived set (strong and weak), never from the brief's
`predicted_class`.**

**Acceptance:** `derived \ briefed` computable from the ledger for any past task,
against the brief file the record names.

---

## 7. Phase 4 — Expiry and drift

- `kanibako spec expired` — migration entries past `drop_after`, and HISTORY statements
  past `expires:`, against the current version/date. Fails the conformance suite.
  This is the mechanism by which §10's "HISTORY volume must fall" is true rather than
  hoped for. `[W-3]`
- `kanibako spec dead --since 90d` — NORM clauses absent from any brief or `for-diff`
  result in the window. Detects **disuse**.
- `kanibako spec drift --commits 20` — clauses whose tagged hunks (±15 lines, same
  window as §6.1, **not** whole files) churned while the clause text did not. Detects
  **drift**; rank it above `dead`. `[W-15]`

`dead` and `drift` emit review lists. Neither auto-deletes.

---

## 8. Phase 5 — Sampling

Director reviews a fraction of **accepted** work against the spec directly, never
against the brief. `[W-16]`

- Weight by evidence class. Class A is already 100% by §6.6; sample B and C, B higher,
  with a nonzero floor on C.
- Sample size per month: `max(25% of accepts, min(8, accepts))`. Start at the 25%
  end. The count floor is what matters at low volume: 10% of twenty accepts is two
  samples, which measures nothing. In a month with fewer than eight accepts, review all
  of them.
- Log a miss class on every escape: `brief-omitted`, `editor-missed`, `spec-ambiguous`,
  `nothing-covered`.
- **Every escape terminates in a gate, not just a correction.**
- Steady-state rate floats: clean samples lower it, a caught escape raises it. The
  absolute floor does not float.

---

## 9. Ordering

| Phase | Delivers alone | Blocks |
|---|---|---|
| 0 Classification + evidence class | addressable clause IDs | everything |
| 1 OFT baseline | uncovered count, ratchet | 2 |
| 2 Manifest + projection | director view, inverse index | 2.5 |
| 2.5 Amendment ordering | working stale signal | 3 |
| 3 Briefs + for-diff + editor | independent review clause set | 4, 5 |
| 4 Expiry + drift | automatic decay | — |
| 5 Sampling | false-accept measurement | — |

Two hard constraints: **2.5 precedes any Phase 3 work**, and **durable briefs land at
the start of Phase 3, not the end.** `[W-17]`

Under schedule pressure, cut 4 before 5. Never start 3 before 2 is stable.

---

## 10. Non-goals

- **Lossy compression of the spec** — deleting rationale to hit a token target. **Not a
  licence to grow:** every added line must be NORM or action-changing RATIONALE, and
  HISTORY volume must fall over time (enforced by `expires:`, §7). A statement needing
  more than ~50 words is usually several clauses; split it. `[W-1]`
- **Generating code from the manifest.** Ruled against 2026-08-15; stands on the
  commentary-preservation leg. The ruling text should be amended to drop the hot-path
  leg. Reader views and trace artifacts are in scope and are not the same thing.
  `[W-2]`
- **A per-file changelog.** Ruled against; stands. `[W-3]`
- **Replacing the existing conformance suite.** This layer sits above it.
- **Adopting an SDD framework as a dependency** (OpenSpec, Spec Kit, BMAD-METHOD,
  agent-spec). Ideas borrowed and attributed; no dependency taken. **Do not propose
  replacing this design with one of them.** `[W-4]`

---

## 11. Risks

| Risk | Mitigation |
|---|---|
| NORM misclassified as RATIONALE, silently dropping a coverage requirement | review the **non-NORM** set by modal verb; two independent classifications diffed |
| `for-diff` under-reports, giving false confidence | per-signal provenance; empty strong set on a nontrivial diff is suspicious; §8 measures the real rate |
| `for-diff` **over-reports**, so `derived \ briefed` is non-empty on every diff and escalation becomes noise the editor learns to ignore | hunk-proximity weighting; only strong signals trigger; track escalation rate — a rising rate with a flat miss rate in §8 means weighting is too loose |
| Clause meaning changed without a revision bump, bypassing §5 | body hash in `clause-index.json`; CI fails on body change without bump |
| Implementation lands without `impl` tags, invisible to every mechanism | tagging obligation (§1.1); missing tag is a `return` |
| Coverage tags rot as code moves | OFT revision-mismatch warnings; tags reviewed as part of the diff |
| Clause IDs churn | freeze at end of Phase 0; renames are one atomic merge plus an index alias (§2.2) |
| Agent trace summaries treated as ground truth | the trace is tool output; an agent summary of it is a starting point only |
| Projection drifts from manifest | generated, never hand-maintained; freshness asserted in CI |
| Class A over-assigned, restoring blanket review | human review of every A; track A share of clauses and of accepts |
| Briefs edited to match what was built | immutable once issued; supersession only; ledger names the brief file |
| Amendment and implementation land together | §5 conformance check on the merge diff; empty stale set at amendment is itself a finding |
| Ratchet and amendment gate fight each other | stale counted separately from uncovered (§3) |
| Rationale text welds into a clause's body hash, so explanation edits force bumps and manufacture stale signals | body window ends at a classification marker (§1.2) |
| OFT cannot import items inside fenced blocks, leaving a third of the spec un-addressable | §0 spike item 3(c); stop-and-report if so |
| A second spec document enters half-classified and breaks the unclassified check for everything | per-document Phase 0 gate: a document is imported only once it passes §2 acceptance in full |

---

## 12. Open decisions

1. **StrictDoc alongside OFT?** Overlaps substantially. Defer until Phase 3 ships.
2. **Does `key~` need to be an OFT artifact type**, or is manifest `clauses:` plus a
   generated trace artifact enough? Prefer the latter; validate in Phase 2.
3. **Where the editor runs.** Suggest in-box advisory, host-side authoritative.
4. ~~Does `system-design-1.8.0.md` need classification at all?~~ **Resolved: yes**, in
   Phase 0, after the keyspace spec (§2). Fourteen keyspace clauses transfer authority
   to it, so excluding it left class-A material outside every mechanism.
5. **Hunk window for strong signals.** ±15 lines is a starting guess. Tune against the
   §8 miss classes: `brief-omitted` escapes whose clause was a weak signal mean the
   window is too tight.
