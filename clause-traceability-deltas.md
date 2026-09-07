# Clause Traceability Brief — two design deltas

**Written against v3** (`brief-new.md`, which resolves G1–G4 and both minors).

**These are not defects.** They are two places where the design meets work done from a
different angle, and where the brief would gain from a change it has no way to see from
inside. Each states what it costs the brief — in both cases, less than it looks.

---

## Delta 1 — `STANCE`, a fifth classification class

### The gap

§2's four classes are NORM, RATIONALE, HISTORY, GUIDANCE. **None of them has a home for text
that binds disposition rather than action.**

The failure is specific and was reached by falling into it. §2's test for RATIONALE —

> Rationale vs history test: **would this text change an agent's action today?**

— misfires on disposition-bearing text, because such text does not determine any single
action. It shifts behavior across the cases **no rule covers**. Under an actionability test it
scores zero and reads as filler.

Run through §2's grid, it lands in **GUIDANCE**: "non-binding; explicitly unspecified or
advisory." That is the wrong label, and it is actively dangerous in combination with §10, whose
first non-goal is lossy compression — a class marked non-binding is the first thing a
token-budget pass deletes.

**Disclosure: I nearly cut exactly such a passage, on exactly that reasoning.** The near-miss is
the evidence for the class, not an argument for it.

### The proposed row, in the form of §2's table

| Class | Test | ID? | Coverage required? |
|---|---|---|---|
| **STANCE** | binding on **disposition**, not action; governs where law is silent. Discriminator: *would an agent that ignored this still satisfy every rule, and still be doing the wrong thing?* | yes, `Tags: stance` | **no — deliberately not gate-able** |

### Why it carries an ID with no gate

**The identifier is the protection.** Naming makes the text addressable, makes its deletion
visible in a diff, and lets an editor cite it in an `escalate:spec-insufficient` record. Being
unenforceable is the definition of the class, not a defect in it — which is why it must not be
resolved by forcing a gate onto it.

### Two guards, because an unenforceable class invites abuse

An unenforceable class is an escape hatch from writing a real gate unless it is fenced:

1. **`STANCE` lives only in a tier the agent cannot edit.** Agents may cite it; they may never
   author or amend it. The file permission is the mechanism — a non-mechanical category,
   mechanically protected. The guard on an unenforceable class must itself be enforceable, or
   it is not a guard.
2. **`STANCE` may not be invoked to relax a NORM.** It resolves silence, not conflict.

Guard 2 has the same directional shape as a rule already in this design space — *may constrain
further, never relax*. That shape has now turned up twice independently, which suggests it is a
primitive worth naming once rather than restating per rule.

### The measurement that settles the obvious objection

The objection is that unenforceable text is bulk to be trimmed. Measured on a real instruction
corpus: the entire body of disposition-bearing text was **344 B — 2.6% of a ~13.2 KB session
load**. Deleting all of it saves roughly **ninety tokens**. The path tables in the same corpus
were six times its size.

**Being wrong about foundational text costs far more than the bytes ever return.** When a
passage is disposition-shaped and small, keep it.

### What this costs the brief

- One row in §2's class table, and `stance` added to the tag vocabulary in §2.2.
- One clause in §2.2 acceptance: every STANCE statement carries an ID and `Tags: stance`.
- One exemption in §10: lossy-compression pressure does not apply to STANCE.
- **One real mechanical addition.** §2.2 (b) sends the non-NORM set to human review "filtered
  by modal verbs (must, shall, never, only, always, required)." **Stance text rarely carries a
  modal** — "assume charity, not malice" has none — so a STANCE statement misfiled as GUIDANCE
  is invisible to the one filter designed to catch misfiling. The non-NORM review needs a
  second pass over the unfiltered GUIDANCE set, or the class arrives with its own blind spot.

---

## Delta 2 — re-base §4 onto the registry role, with the keyspace as one instance

### The claim

A settings keyspace is **one instance of a general shape**: a single declared place holding
information used broadly across a project's code, existing so that information has one source
of truth. The same shape recurs as config schemas, feature-flag registries, error-code
catalogs, event and message-type registries, metrics keys, i18n string catalogs, and permission
namespaces. Each is a closed namespace of identifiers that appear as literals throughout the
code and carry per-identifier metadata.

**Kanibako-specific is the instance** — `keyspace-manifest.yaml`, `box.enable_vault`, the scope
cascade — **not the concept.**

### Why this is worth saying to a brief that is working

Not for elegance. Two concrete consequences:

**1. §6.1 signals 2 and 3 stop being manifest-shaped.** They currently read:

> 2. **Key literals in changed lines** — match the manifest key set against added and removed
>    text, resolve through `clauses:`. Strong.
> 3. **Touched manifest rows** — their `clauses:` directly. Strong.

Re-based, both are one operation on the role: *recognize a declared identifier in a line of
source, and resolve it to its governing clauses.* Identical behavior for a keyspace, and it
keeps working when the project's declared place is a schema, an enum, or a table catalog. This
also makes explicit why signals 2 and 3 are stronger than signal 1: an identifier literal is an
exact fact, where hunk proximity is an inference about locality.

**2. §12.2 becomes decidable on its own merits.** If the storage model is substitutable across
projects, then whether `key~` is an OFT artifact type turns on whether every candidate model
can be expressed as OFT items at all — a keyspace can; a type system or a table catalog may
not. That is a better ground for the decision than the one currently available.

### The minimum contract

What a project's data model must be able to do to fill the role:

| | Operation | Feeds |
|---|---|---|
| a | enumerate its identifiers | the projection (§4.2) |
| b | resolve an identifier to its governing clause IDs | `spec key`, `for-diff` |
| c | recognize an identifier literal in a line of source | `for-diff` signals 2 and 3 |
| d | answer whether a given identifier is **declared** | the closed-world check |

**(d) is what makes the model a mechanism rather than a convention** — it is the operation that
raises rather than advises. (a)–(c) inform; (d) refuses.

### One caution, learned the expensive way

**The storage model is substitutable across projects, not plural within one.** A project might
mix two models, but that is not the assumption. The design consequence is narrow: do not
hardcode a singleton in a way that *forbids* mixing, and do not build machinery for N registries
inside one project. **"Don't preclude," not "build for N."** The second reading costs real
complexity for a case that does not occur.

### Evidence that the role is real and not an abstraction imposed after the fact

§4.2's acceptance criterion in the brief reads:

> `kanibako spec keys` under 16 KB total and under 160 bytes per key line (**a byte budget, not
> a token count — tokenizers differ, bytes do not**)

An independent implementation of exactly this role — built from a different corpus, for a
different purpose — arrived at the same 16 KB default and states the reason in nearly the same
words. **Two designs converging on one sentence is evidence the shape is real**, rather than a
generalization applied from outside. That implementation exists and is readable if useful
(`doctorjei/kinemata`); it is offered as an existence proof, not as a dependency — §10's
position on taking dependencies is right and this does not ask to change it.

Its own experience is worth one warning, though: the same measurement showed that deriving a
projection from a project's *code surface* rather than its declared place produced 35.8 KB
against that 16 KB budget. The declared place is what makes the projection loadable. §4.1 is
already right about this; the point is that the budget in §4.2 is load-bearing, not decorative.

### What this costs the brief

Mostly wording, and §4 keeps all of its content:

- A short §4.0 naming the role and the four operations, with the manifest declared as kanibako's
  implementation of it.
- §6.1 signals 2 and 3 restated in terms of (c) and (b).
- One line in §12.2 recording the new ground for the decision.

---

## What this document does not do

It does not revisit G1–G4; v3 resolves them. It does not propose replacing any part of the
design, and it takes no position on the §0 spike, which remains the item that most determines
whether the rest is buildable.
