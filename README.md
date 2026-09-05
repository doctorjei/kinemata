# kinemata

Keeping agent-run software projects from going astray.

Agents on a codebase fail in recognisable ways: they get **overwhelmed with
context**, they **miss issues**, and they **duplicate code that already exists**.
This is scaffolding against those failures — declare a fact in one place, then
give agents a way to find it and a way to be caught re-deriving it.

**Status: early.** The registry layer described below is built, tested, and
validated against real duplication incidents from real project history. The
wider structure it belongs to is designed but not built.

---

## The distinction everything hangs on

Every mechanism here is either a **reminder** or a **catch**, and they are not
interchangeable.

|  | Reminder | Catch |
|---|---|---|
| When | before and during the work | after, on the artifact |
| Needs the agent's cooperation | yes — it can be ignored | **no** |
| Fails against a rogue agent | yes | no |
| Fails as a prompt | no | yes — the work is already done |

> **The test, for any mechanism:** *could a rogue agent disable this?*
> If yes, it is a reminder. File it as one, and do not count it for the rogue case.

That makes the box/host boundary the trust boundary. `review` and `check` below
run identical analysis and differ only in exit code and where they run — the
difference is deliberate, because two mechanisms that could disagree eventually
will.

## When *not* to build a mechanism

Mechanism costs code, CI time, and rigidity. Spending it where a written norm
already works is waste, and a structure that over-mechanises becomes brittle —
its own way of going astray.

Three factors decide:

1. **Incentive** — does an agent gain anything by violating? (less work, faster)
2. **Visibility** — is the violation apparent in the artifact, or does it hide?
3. **Failure** — loud, or silent?

> Trust a written norm where compliance is cheap, violation is visible, and
> nothing is gained by defecting. Spend mechanism where violation is cheap,
> invisible, or rewarded.

Agents being unpleasant to each other fails all three tests for needing
mechanism — a sentence handles it. Landing code without a coverage tag passes
all three. Only the second gets machinery.

---

## Registries

A **registry** is one declared place holding information used broadly across a
project's code, so that information has a single source of truth. What it
*holds* is the project's choice — settings keys, error codes, event types,
canonical helpers. This defines only what a data model must **do** to serve the
role.

One required method:

```python
entries() -> [Entry]     # Entry needs only: id, clauses
```

`declared()`, `resolve()` and `detect()` have defaults derived from it, which a
registry overrides only when the default is wrong for its data model.

Each entry may declare **antipatterns** — the spelling that means somebody
re-derived it instead of routing through it:

| Canonical thing | Spelling that means it was bypassed |
|---|---|
| `WORKSET_META_FILE = "workset.yaml"` | the literal `"workset.yaml"` |
| `run_or_die(...)` | an inlined `check=True` |
| `read_mode(dir, "vm")` | a hardcoded `mode = "vm"` |

**It does not detect that two pieces of code do the same job.** That is
semantic, and a mechanism claiming it would be lying about its reach. What it
does is force a fork: reuse the entry, or *declare* a new one. Reuse is the
outcome you want; declaring is visible in a diff, which is where a reviewer asks
the only question that matters — did this need to exist?

## Usage

```bash
pip install -e ".[dev]"
```

Declare your registries in `kinemata.toml`:

```toml
[project]
root = "."
exclude = ["tests/"]

# Values: antipatterns are derived from the constants themselves.
[[registry]]
name = "constants"
kind = "python-constants"
modules = ["src/pkg/constants.py"]

# Code: canonical helpers, declared by hand.
[[registry]]
name = "helpers"
kind = "code-patterns"

  [[registry.entry]]
  id = "run_or_die"
  antipatterns = ['check\s*=\s*True']
  home = ["pkg/_run.py"]
```

Then:

```bash
kinemata ids       # the projection: what already exists. Budgeted, loadable.
kinemata review    # advisory. Always exits 0. Run in-box, during the work.
kinemata check     # the gate. Exits 1 on a strong finding. Run in CI.
```

See `examples/ci-github-actions.yml` — including why a workflow file alone is
still a reminder, and what promotes it to a catch.

## Precision

Naive matching is unusable. On a 65k-line codebase, deriving antipatterns from
constants produces **1,537** matches; three constants whose values are ordinary
domain words account for 1,054 of them. Two filters, both forced by measurement:

- **Strong vs weak.** A whole string literal equal to the value is *strong*; the
  value inside a longer literal is *weak* and often a different namespace that
  merely shares characters. **Only strong findings gate.** 1,537 → 314.
- **Frequency suppression.** An antipattern matching more sites than
  `max_sites` (default 20) is a domain word, not a duplication signal. 314 → 43.
  **Reported, never silent** — a check that quietly stops checking is worse than
  no check.

## What it was validated against

Not synthetic fixtures. Labelled incidents from real project history, where a
commit message names the sites a human found by hand:

- **9/9 recall** reconstructing the tree before a documented cleanup commit.
- **3 real bypasses that the manual fix missed**, one still on `main`.
- On a second, unrelated codebase it initially found **nothing** — correctly
  diagnosing a missing adapter rather than a broken mechanism. With
  `code-patterns` it finds 6 live bypasses there.

And a failure worth publishing: `unused()` **failed** its validation, 0/3
against an incident recording three declared keys with "no reader at all". It
detects *mention*, not *use* — and every declared entry is mentioned somewhere,
because that is what declaring is. It is labelled known-weak in its own
docstring and requires excluding a project's declaring machinery to mean
anything.

## Known gaps

- Everything here detects **re-derivation of something already declared**.
  Nothing detects **two new things duplicating each other, neither declared** —
  probably the more common case in greenfield work.
- A CI workflow lives in the repo, so an agent can edit it. Branch protection
  with the job as a *required status check* is what makes it a catch.
- Validated on two codebases by one author. The categories held across both;
  they have not been tested against an unrelated project.

## Design

`docs/design.md` — the registry contract, the reminder/catch split, and the
reasoning behind both.

## License

GPL-3.0-only. See `LICENSE.md`.

Contributions involving generative AI tools: see `AIPOLICY.md`.
