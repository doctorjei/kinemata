# Structure

**How to build scaffolding for an agent-run project that actually holds.**

`kinemata` ships a handful of mechanisms — the registry layer specified in `docs/design.md`,
plus the checks over undeclared text and documentation claims described in `README.md`. This
document is the other half: the method that produced them, stated generally enough to apply to
mechanisms this project does not ship, and to ones it built, measured, and threw away.

Every principle below was forced by a specific failure, and each one names the failure that
forced it. That is the point of the format, not decoration. A principle with no incident
behind it is someone's taste, and taste is how scaffolding grows into bureaucracy.

---

## 1. Every mechanism is a reminder or a catch

These are different designs and must not be conflated.

|  | **Reminder** | **Catch** |
|---|---|---|
| When | before and during the work | after, on the artifact |
| Form | information surfaced at the moment of decision | a check run against the result |
| Needs the agent's cooperation | yes — it can be ignored | **no** |
| Fails against a rogue agent | yes | no |
| Fails as a prompt | no | yes — by the time it fires, the work is done |

> **The test, for any mechanism:** *could a rogue agent disable this?*
> If yes, it is a reminder. File it as one, and do not count it for the rogue case.

Four consequences, each of which has bitten:

**A mechanism whose kind you have not named is a reminder.** That is the default, because
cooperation is the default assumption. Naming it costs one line and prevents counting a
prompt as a guarantee.

**A catch must run where the agent cannot reach it.** This makes the sandbox/host boundary
the trust boundary. A CI workflow file that lives in the repository is editable by the agent
it constrains; branch protection with the job as a *required status check* is what promotes
it from reminder to catch. Shipping the workflow and calling it a catch is the most common
version of this error.

**A catch scoped to one module is not a catch.** In the incident this project was validated
against, the cleanup commit shipped its own tripwire — scoped to the module being fixed. It
missed eight sites in six other modules. A check that only looks where you already looked
confirms the fix you already made.

**The reminder and the catch should read one source.** `kinemata review` and `kinemata check`
run identical analysis and differ only in exit code and where they run — one scan, two
consequences. Two mechanisms that
can disagree eventually will, and the disagreement always surfaces at the worst moment.

---

## 2. Spend mechanism only where a written norm fails

Mechanism costs code, CI time, and rigidity. Spending it where a sentence already works is
waste, and a structure that over-mechanizes becomes brittle — which is its own way of going
astray. Three factors decide:

1. **Incentive** — does an agent gain anything by violating? (less work, a faster path)
2. **Visibility** — is the violation apparent in the artifact, or does it hide?
3. **Failure** — does it fail loudly, or silently?

> **Trust a written norm where compliance is cheap, violation is visible, and nothing is
> gained by defecting. Spend mechanism where violation is cheap, invisible, or rewarded.**

| Case | Incentive | Visible | Fails loudly | Verdict |
|---|---|---|---|---|
| Agents being antagonistic toward each other | none | yes | yes | written norm |
| Skipping "does this exist already?" | **yes** | **no** | **no** | **mechanism** |
| Landing code without a coverage tag | **yes** | **no** | **no** | **mechanism** |
| Editing local directives to relax a system rule | **yes** | **no** | **no** | **mechanism** |

The first row is not hypothetical. Adversarial spirals between agents are a real observed
failure mode of multi-agent systems — and still the wrong place to spend mechanism, because
an agent gains nothing by it, it is plainly visible in the transcript, and it fails loudly.
A stated norm handles it. The remaining three rows are exactly the failures this project
exists for, which is why they get machinery and that one does not.

---

## 3. Refuse, don't no-op

**A check that quietly stops checking is worse than no check**, because it also spends the
credibility of a passing result. Everything downstream now believes something false.

In practice this means a mechanism reports rather than skips:

- A misconfigured registry raises. It does not fall back to a default and continue.
- A registry that cannot recognize its own identifiers cannot be `closed` — it raises rather
  than returning an empty list, because an empty list of violations reads exactly like
  compliance.
- **A registry that loads cleanly but yields no entries raises.** Every part of the
  declaration can be individually valid — the module exists, it parses, the kind is known —
  and the registry still holds nothing the adapter recognizes. This project shipped exactly
  that against its own source for six commits: `python-constants` pointed at three modules
  that contain no module-level string constants, so the projection was empty and the gate
  exited 0 the entire time. The wrong adapter reads precisely like a clean tree.
- Suppression is reported, never silent. When the scan drops an antipattern that matches more
  sites than the threshold allows, it says so.

Note what the exception in each case is not: a warning. A warning on a green run is read as
green. The escape hatch for the empty-registry rule is `allow_empty = true`, declared per
registry in the config, because an exemption someone chose and can see is a different object
from one the tool took quietly.

The corollary is uncomfortable: **you cannot tell that a check still checks by reading it.**
The only way to know is to break something on purpose and confirm the check notices.

This project's documentation checker demonstrated both halves within an hour of being
written. It first over-reported — 23 findings, none of them real, because prose that
*discusses* a path was read as asserting one. The fix for that introduced the opposite
failure: the negation heuristic skipped the entire line containing a negation word, so a
line that also made a genuine claim went unchecked. It reported clean while checking less
than it claimed. That was found by injecting five known faults and watching them fail to
fire — not by rereading the code, which had already been reread.

---

## 4. Classify before you test

When a mechanism judges *text* — a rule, a directive, a piece of documentation — the value
test you apply depends on what class the text is. Applying the wrong test to foundational
text is how three near-misses happened in a single working session.

The specific error: running an actionability test ("would this change an agent's action
today?") on text that is binding on *disposition* rather than action. Such text does not
determine any single action; it shifts behavior across the cases no rule covers. Under an
actionability test it scores zero and looks like filler. It is not filler — it is the only
thing operating where the rules run out.

> **Corrected procedure — test the class before you test the value.**
>
> 1. **Classify first.** Ask the discriminator: *would an agent that ignored this still
>    satisfy every rule, and still be doing the wrong thing?* If yes, the text is binding
>    on disposition, and the actionability test does not apply to it.
> 2. **Weigh the asymmetry.** In the case that prompted this, the entire body of
>    disposition-bearing text was 344 bytes — 2.6% of the session's context load. Cutting it
>    saved roughly ninety tokens. Being wrong about foundational text costs far more than
>    the bytes ever return. **When a passage is disposition-shaped and small, keep it.**
> 3. **Foundational is not the same as actionable.** Values govern the unanticipated case,
>    which is precisely where no rule exists to be followed. A structure built only from
>    rules is brittle exactly where it can least afford to be.

---

## 5. Classes of normative text

Classification only works against a fixed set of classes. A four-class model — normative
statements, rationale, history, and non-binding guidance — comes from a document
classification brief by another author and is not ours to reproduce here. What follows is
this project's addition to it, and the reason the addition was necessary.

**`STANCE`** — binding on **disposition**, not action; governs where the law is silent.

| | |
|---|---|
| Discriminator | *Would an agent that ignored this still satisfy every rule, and still be doing the wrong thing?* |
| Carries an identifier | yes |
| Gate-able | **no — deliberately not** |

The four-class model has no home for text of this kind. Run through it, disposition-bearing
text lands in non-binding guidance, which marks it compressible — and compressing it is
exactly the error of §4.

`STANCE` carries an identifier despite having no gate. **The identifier is the protection:**
naming makes the text addressable, makes its deletion visible in a diff, and lets a reviewer
cite it in an escalation. Being unenforceable is the definition of the class, not a defect
in it.

An unenforceable class invites abuse as an escape hatch from writing a real gate, so it
needs two guards:

1. **`STANCE` lives only in a tier the agent cannot edit.** Agents may cite it; they may
   never author or amend it. The file permission is the mechanism — a non-mechanical
   category, mechanically protected. Note that this guard is itself a *catch* by §1, and
   that is not an accident: the guard on an unenforceable class must be enforceable, or
   there is no guard.
2. **`STANCE` may not be invoked to relax a normative rule.** It resolves silence, not
   conflict.

---

## 6. Validate against labeled history, and publish the failures

**Fixtures test what you already thought of.** A mechanism built and tested against its own
author's fixtures measures the author's imagination, which is the thing in question.

The alternative is cheap and most projects already have it: **labeled history.** Find commits
whose messages name the sites a human found by hand — cleanup commits, "remove duplicate X"
commits, incident fixes. Reconstruct the tree as it stood *before* the fix. The human's list
is the answer key, so recall is measurable rather than asserted.

What that produced here, published in full because the mixed result is the honest one:

| Result | Reading |
|---|---|
| **9/9 recall** on a documented cleanup commit | the mechanism finds what a careful human found |
| **3 further bypasses the manual fix missed**, one still live | it finds what a careful human missed |
| **1,537 → 314 → 43** matches, after two filters | naive matching is unusable; both filters were forced by measurement, not taste |
| A second codebase initially yielded **nothing** | a missing adapter, correctly distinguished from a broken mechanism |
| `unused()` **failed 0/3** | it detects *mention*, not *use* — kept, labeled weak in its own docstring |

The last row is the one that matters most. A mechanism that fails validation and is quietly
kept anyway poisons every result the suite produces afterward. Publishing the failure is what
lets a reader calibrate the rest.

Two habits follow from the same discipline:

**Finish the sample.** Numbers taken from the part of a list you read first inherit whatever
made you read there. Classifying 13 of 47 consolidation commits put the reachable share of a
gap at ~62%; classifying the remaining 34 put it at 31%. The build order those numbers informed
survived, but the coverage claim did not, and it would have stayed wrong indefinitely — nothing
about the partial number looks partial once it is written down.

**Measure before cutting.** In a context-budget review, 46% of the target document turned out
to be HTML comments that the loader strips — the apparent 28 KB was really 13 KB. Most of the
apparent bloat was never loaded at all. Separately, projecting a codebase's public functions
came to 35.8 KB against a 16 KB budget, which settled an open design question by arithmetic
rather than argument.

**Usage count is not a proxy for value.** A term with zero in-corpus references can be
load-bearing, because its consumer is the conversation rather than the document. Every disuse
detector inherits this blind spot. That is why `unused()` emits a review list and never a cut
list, and why any detector of the same shape should do the same.

---

## 7. A shape that recurs

Two rules arrived at independently turned out to have the same form:

- Local rules may **constrain further** than system rules, never relax them.
- `STANCE` may **constrain** where the law is silent, never relax a normative rule.

Both are directional: a subordinate layer may add obligation and may not subtract it. The
shape has now appeared twice from unrelated starting points, which suggests it is a primitive
of this kind of structure rather than a coincidence of two rules. It is recorded here as an
observation, not yet as a mechanism — there is no check for it, and inventing one before a
third instance appears would violate §2.

---

## 8. The registry layer, read against these principles

What this project ships, read back against its own rules:

| Principle | How the registry layer answers it |
|---|---|
| §1 reminder or catch | `ids`, `review` and `undeclared` are reminders; `check` and `claims` are catches, and only in CI with branch protection |
| §1 one source | `review` and `check` run identical analysis; only the exit code differs |
| §2 spend test | duplication scores yes/no/no — cheap to commit, invisible in a diff, silent on landing |
| §3 refuse | bad configuration raises; an empty registry raises; a registry that cannot detect its identifiers refuses to be `closed`; suppression is reported |
| §3 break it on purpose | the self-check's five entries were each verified by injecting the bypass and watching the gate fail |
| §6 validation | labeled history from real repositories, with the components that failed labeled as failing |
| §4 classify first | `undeclared` reports; `check` and `claims` gate. A missing file is a fact; text repeating with no declared home is a judgment |

And where it does not reach, stated plainly because §6 requires it.

The gap was that everything above needs the thing to be **declared first**. Measuring it
against 196 consolidation commits turned that single gap into three, with very different
reach:

| Shape | Instances | Reachable |
|---|---|---|
| A value or message spelled in several places, declared nowhere | 5 | **4** — shipped as `undeclared` |
| Two copies of a code block, drifted apart | 4 | 0 — on measurement, see below |
| Two implementations of one rule that share no text | 4 | 0 — out of reach by nature |

Thirteen instances in 37 attributable commits, from a sample of 47 drawn from 196. **Four of
the thirteen are reachable today.**

That table sorts by how the duplicates *resemble* each other, which is not the only thing
deciding reach. One instance in the sample is a value spelled twice — the first row, the class
the shipped mechanism was built for — and is still out of reach, because both carriers live in
a config file another tool writes. Nothing here reads outside the source tree. It is one case,
not a distribution, and the narrow claim is all it supports: **resemblance decides whether a
mechanism could see it, locus decides whether it gets to look.**

That fraction is worth stating because an earlier version of it was wrong in this document's
own favor. The first 13 commits classified gave 8 gap instances and about 5 reachable — 62%.
But those 13 were the ones whose subjects looked most promising, read first, and finishing the
sample cut the reachable share to **31%**. Nothing changed except that the unexamined
two-thirds got examined.

> **A proportion taken from the interesting end of a list is not a measurement.** The bias runs
> toward whatever made you start reading there, which is usually the thing you hoped to find.

The third is the one that recurs most in that corpus: two modules enforcing the same refusal
in different words, two code paths answering "what is effective" differently. Nothing
syntactic can see it, and a mechanism claiming to would be the overreach §1 exists to prevent.
By this document's own test it is a **reminder** problem — an agent that can find what exists
does not write it twice — and the honest answer is to say so rather than ship a detector that
appears to cover it.

Worth recording how the first was reached: the mechanism for it scored **0/4** on its first
validation, because it compared text for equality while the incident's sites were *composed*
— `Path("/etc/pkg/config.yaml")` against `Path("/etc/pkg") / NAME`. Equality was the wrong
relation, and only a labeled incident could have said so. Fixtures would have agreed with the
author.

The second row was expected to be reachable and **was not**, which is worth more than the row
that worked. A clone detector over normalized syntax trees found the labeled incident **0
times** at a precision usable as a list (187 findings on a 65k-line tree); the windows small
enough to appear to find it produced 647 to 2,673 findings, and those apparent hits turned
out to be artifacts of unreliable line attribution. The reason is structural:

> **A clone detector is sharpest on copies that have not yet diverged — exactly the copies
> that have not yet hurt anyone.** The incident's three copies were worth finding *because*
> one of them had lost a path split the others kept. That drift is what made them the same
> idea in different shapes, and it is what removed the signal.

So the mechanism was built, measured, and **not shipped**. §6 asks for failures to be
published; this is one, and the alternative it lost to covers more for a fraction of the cost.

---

## See also

- `README.md` — what the tool does and how to run it.
- `docs/design.md` — the registry contract in full.
