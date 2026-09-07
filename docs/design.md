# Design — The Registry Contract

**Status:** ratified · **Date:** 2026-09-02, revised 2026-09-05

A *registry* is the general form of what kanibako calls a keyspace: one declared place
holding information used broadly across a project's code, so that the information has a
single source of truth. Kanibako's registry holds settings keys. Another project's could
hold error codes, event types, feature flags, permissions, metrics names, or the
project's own capabilities. **The concept is general; the data model is the project's
choice.** This document defines what a data model must do to serve the role — and
nothing about what it must be.

---

## 1. The problems this serves

Stated by the user, in their words: agents get *overwhelmed with context*, *miss
issues*, and *duplicate code*.

Context overwhelm and duplication are the same problem seen twice. **An agent duplicates
what it cannot hold or find.** A registry attacks both ends: it is the single place to
look, and it is small enough to actually look at.

---

## 2. Two kinds of mechanism

**Carried by `structure.md` §1.** Every mechanism is either a *reminder*, which needs the
agent's cooperation and fails against a rogue one, or a *catch*, which runs against the
artifact and does not. The test is *could a rogue agent disable this?*

What the distinction demands of a registry specifically:

**Both consumers read the same source.** One registry, two outputs: a projection the
agent loads in-box, and a check that runs outside the box. They can never disagree,
because neither is maintained by hand. This is the §1 rule about one source applied to
the one mechanism defined here.

---

## 3. When to spend a mechanism at all

**Carried by `structure.md` §2** — the three factors (incentive, visibility, failure
loudness) and the worked examples.

What it settles for this document: duplication scores **yes / no / no** — skipping the
"does this exist already?" check saves work, a duplicate looks exactly like new code, and
nothing breaks when it lands. That is squarely mechanism territory. The three cases that
pass the test are exactly the user's three stated problems, and they are the scope of this
design.

---

## 4. The contract

A registry is anything that can answer one question. Everything else derives from it.

### 4.1 Required

```
entries() -> [Entry]
```

Returns every declared entry. An `Entry` requires exactly two fields:

| Field | Type | Meaning |
|---|---|---|
| `id` | string | the identifier as it appears in source |
| `clauses` | [ClauseID] | the normative statements governing this entry; may be empty |

Any further fields are the project's own and are passed through untouched. Kanibako's
entries carry `scope`, `type`, `default`, `since`, `migration`; a capability registry's
would carry something else entirely. **The structure never reads them.**

### 4.2 Derived, with overrides

These have default implementations built from `entries()`. A registry overrides one
only when the default is wrong for its data model.

| Operation | Default | Override when |
|---|---|---|
| `declared(id) -> bool` | membership in `entries()` | enumeration is too large to hold, and membership must be answered directly |
| `detect(text) -> [id]` | literal match of each `id` against the text | identifiers are constructed dynamically, aliased, or ambiguous as substrings |
| `resolve(id) -> [ClauseID]` | the entry's `clauses` field | linkage lives outside the entry |

One required method, three defaulted. That is the whole surface. A project with a YAML
manifest satisfies it in a few lines; a project with a type system or a database catalog
satisfies it with a real adapter, and neither is privileged.

### 4.3 Declared properties

```
closed: bool          # is an undeclared identifier an error?
budget: bytes         # ceiling on the projection's size
```

**`closed`** — kanibako's keyspace is closed: an undeclared key is not a key, and
reading or setting one is an error that names it. Not every registry can start that way;
a legacy codebase cannot close on day one. So `closed` is declared, and an open registry
routes undeclared identifiers to a **review list** rather than a failure. Closing is a
ratchet: record the baseline, fail on any increase, drive it down on a separate schedule
that does not block feature work.

The ratchet is built — `baseline.py`, `kinemata baseline`, read by `check`. Two
decisions the specification above left open, both settled by measurement rather than
argument:

- **What identifies a finding across commits** is entry, antipattern, path and matched
  text, with whitespace collapsed; never the line number, which every edit above the
  finding changes. Measured over 200 commits of real history, keying on the text costs
  one spurious report; keying on the line number would have reported most of the file.
- **Multiplicity is recorded**, so a record covering three identical sites does not
  exempt a fourth. A baseline that cannot count is a baseline that absorbs.

The honest limit, stated because the alternative is implying reach this does not have:
an agent can re-record the baseline and silence a real finding. That act is a committed
file change, which puts it in exactly the category §5's **Catch B** describes — a new
declaration, visible in the diff, routed to review. The mechanism makes the exemption
list *visible and countable*; it does not make it unreachable.

**`budget`** — the projection must stay loadable or it stops being a reminder. A byte
budget, not a token count: tokenizers differ, bytes do not. **The budget is itself a
catch** — CI fails when the projection exceeds it. This is the one mechanism in this
document that acts directly on context overwhelm, and it works by making the registry's
growth visible at the moment it becomes a problem rather than after.

---

## 5. First application — duplication

The failure the user calls costliest, and the one with the thinnest defense today. The
whole of the current guard is a sentence in the writer's role definition: *"Check for an
existing mechanism before writing a new one."* That is a reminder, it is ignorable, and
by §3 it is squarely in mechanism territory — skipping the check saves work, a
duplicate looks exactly like new code, and nothing breaks when it lands.

A **capability registry** declares what the project can already do. Entries are
mechanisms, not settings.

| | Mechanism |
|---|---|
| **Reminder** | the projection, budgeted small enough that an agent cannot plausibly claim not to have seen it |
| **Catch A** | new code introducing an *undeclared* capability — CI failure when `closed`, review list when open |
| **Catch B** | a new *declaration* is visible in the diff, and routes to review |

### What this does and does not do

**It does not detect that two things do the same job.** That is semantic, not syntactic,
and claiming otherwise would be the kind of overreach this project exists to prevent.

What it does is force the agent to a fork: **reuse an existing entry, or declare a new
one.** Both branches are safe. Reuse is the outcome we want. Declaring is a visible act
in a diff, which is where a human or an editor asks the only question that matters —
*did this need to exist?* Catch B is a routing mechanism, not an automated judgment, and
should not be described as more.

The forgetful agent is handled by the reminder. The rogue agent is handled by the fact
that both branches leave a trace, and skipping both fails CI.

---

## 6. What this deliberately does not require

- **Any particular storage** — YAML, a database, code annotations, a type system. The
  contract is behavioral.
- **That entries be settings.** The role is "information used broadly across the code."
  Settings are one instance.
- **One registry per project.** The common case is one; a project may have more. The
  contract does not preclude it and no collection machinery is built for it.
- **A clause for every entry.** `clauses` may be empty. Traceability is a separate
  concern that a registry *supports* rather than requires.

---

## 7. Questions this document opened

Three were closed by measurement rather than argument, during corpus analysis. They are
kept rather than deleted, because the measurement is the answer's whole warrant.

1. **Where does a capability registry's data come from initially?** **Closed: hand-declared,
   seeded open, ratcheted toward closed.** Bootstrapping from the module surface was
   rejected — projecting a codebase's public functions came to 35.8 KB against a 16 KB
   budget, so a registry derived that way cannot be loaded at all.
2. **Granularity of a capability.** **Closed: the question was on the wrong axis.** Module,
   class and function are *code* units; the duplication in a ~45-commit hand-read sample is
   in *values* and in the routes that touch declared slots. Four categories fell out of the
   corpus and held on a second codebase with no manifest at all — so the failure is
   source-of-truth-relative, not keyspace-relative.
3. **Does `detect` need language awareness?** **Closed: yes, and the false-positive rate is
   not tolerable.** Naive matching produced 1,537 hits on a 65k-line codebase, 1,054 of them
   from three constants whose values are ordinary domain words. Two filters, both forced by
   that measurement, bring it to 43. See `prose.py` and `report.py`.

Still open:

4. **Interaction with the clause-traceability brief.** That brief assumes one keyspace
   manifest. If this contract is right, its §4 should be re-based onto the registry role
   and its §6.1 signals 2 and 3 should read `detect()` rather than a key set. To relay.
