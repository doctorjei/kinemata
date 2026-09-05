# Design — The Registry Contract

**Status:** draft, not ratified · **Date:** 2026-09-02

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

The user's reason for wanting mechanisms at all, in their words: to **remind** agents
about issues when they forget, and to **catch** a rogue agent. Those are different
designs and must not be conflated.

| | **Reminder** | **Catch** |
|---|---|---|
| When | before and during the work | after the work |
| Form | information surfaced at the moment of decision | a check run against the artifact |
| Needs the agent's cooperation? | yes — it can be ignored | **no** |
| Fails against a rogue agent | yes | no |
| Fails as a prompt | no | yes — by the time it fires the work is done |

**A catch only catches if it runs where the agent cannot reach it.** Anything an agent
can edit, skip, or disable is a reminder wearing a catch's clothes.

> **The test, for any mechanism proposed anywhere in this project:**
> *Could a rogue agent disable this?* If yes, it is a reminder. File it as one, and do
> not count it for the rogue case.

This makes the box/host boundary the trust boundary. Three existing mechanisms already
respect it — the trace runs host-side with the index delivered read-only, the harness
rather than the editor appends the decision ledger, and the CI gates are exit codes.

**Both consumers read the same source.** One registry, two outputs: a projection the
agent loads in-box, and a check that runs outside the box. They can never disagree,
because neither is maintained by hand.

---

## 3. When to spend a mechanism at all

Mechanism has costs — code, CI time, rigidity — and spending it where a sentence already
works is waste. A structure that over-mechanizes becomes heavy and brittle, which is its
own way of going astray.

Three factors decide:

1. **Incentive** — does an agent gain anything by violating? (less work, faster path)
2. **Visibility** — is the violation apparent in the artifact, or does it hide?
3. **Failure** — does it fail loudly, or silently?

> **Trust a written norm where compliance is cheap, violation is visible, and nothing is
> gained by defecting. Spend mechanism where violation is cheap, invisible, or rewarded.**

Worked examples:

| Case | Incentive | Visible | Fails loudly | Verdict |
|---|---|---|---|---|
| Antagonism toward another agent | none | yes | yes | written norm suffices |
| Skipping the "does this exist already?" check | **yes** | **no** | **no** | **mechanism** |
| Landing code without a coverage tag | **yes** | **no** | **no** | **mechanism** |
| Editing local directives to relax a system rule | **yes** | **no** | **no** | **mechanism** |

The three that need mechanism are exactly the user's three stated problems. That is the
scope of this design.

---

## 4. The contract

A registry is anything that can answer one question. Everything else derives from it.

### 4.1 Required

```
enumerate() -> [Entry]
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

These have default implementations built from `enumerate()`. A registry overrides one
only when the default is wrong for its data model.

| Operation | Default | Override when |
|---|---|---|
| `declared(id) -> bool` | membership in `enumerate()` | enumeration is too large to hold, and membership must be answered directly |
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
  contract is behavioural.
- **That entries be settings.** The role is "information used broadly across the code."
  Settings are one instance.
- **One registry per project.** The common case is one; a project may have more. The
  contract does not preclude it and no collection machinery is built for it.
- **A clause for every entry.** `clauses` may be empty. Traceability is a separate
  concern that a registry *supports* rather than requires.

---

## 7. Open

1. **Where does the capability registry's data come from initially?** Hand-declared is
   honest but front-loads cost on an existing codebase. Bootstrapping from the module
   surface is cheaper and lower quality. Probably: seed open, ratchet toward closed.
2. **Granularity of a capability.** Module, class, function, or "mechanism" as a human
   judgment. Too fine and the projection blows its budget; too coarse and it stops
   preventing duplicates. Needs a real corpus to calibrate against.
3. **Does `detect` need language awareness** to avoid matching identifiers inside
   comments and strings, or is the false-positive rate tolerable? Measure before
   building.
4. **Interaction with the clause-traceability brief.** That brief assumes one keyspace
   manifest. If this contract is right, its §4 should be re-based onto the registry role
   and its §6.1 signals 2 and 3 should read `detect()` rather than a key set. To relay.
