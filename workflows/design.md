# Design a Workflow Skill

Create or refactor a multi-step skill without holding workflow control in prose. The coordinator at `scripts/design.py` derives the phase list from the contract you record, so a skill with no settings never walks a settings phase.

## When to Use

Use this workflow when what a skill should do is what is being decided: a new skill, or an existing one whose contract no longer matches its behavior.

Every sibling workflow starts from material this one does not have yet, so the dividing question is what already exists. Merging several skills into one is [absorb.md](absorb.md), and this workflow then covers whatever the merged contract still lacks. Auditing a skill whose quality is unknown is [review.md](review.md), and closing the findings it produced is [remediate.md](remediate.md). Moving files without changing behavior is [restructure.md](restructure.md).

Do not use this workflow to audit a skill you are not changing, or for a single direct task with no reusable workflow contract.

## Define the Contract

Before starting a run, write down:

- Triggering requests, required inputs, trust boundaries, and observable outputs.
- Safety invariants and irreversible actions.
- Runtime capabilities available: scripts, workflow API, state store, delegation, approval, progress UI.
- Deployment shape and host discovery requirements.

The contract records what has been decided, so anything still open is work this phase owes. Enumerate what is underspecified per capability, present it grouped by what it affects, and resolve it before the run advances. Agreement is not resolution: an answer of "whatever you think is best" leaves the question open, so answer it with concrete recommendations and their consequences, and treat it as unresolved until one is chosen.

Then decide which capabilities the skill actually needs. Each one selects its phase and nothing else:

| Capability | Select when | Contract |
|---|---|---|
| `coordinator` | Order, branching, concurrency, retries, or loops need executable control | [patterns.md](../references/patterns.md) |
| `state` | Work must resume after interruption or partial failure | [state and resume](../references/patterns.md#state-and-resume) |
| `settings` | Users need stable preferences across runs | [settings.md](../references/settings.md) |
| `setup` | Prerequisites need provisioning or readiness proof | [setup.md](../references/setup.md) |
| `install` | The workflow installs agent skills | [install.md](../references/install.md) |
| `events` | Behavior must occur at a host lifecycle boundary | [events.md](../references/events.md) |
| `tools` | The workflow calls MCP servers or external services | [tools.md](../references/tools.md) |
| `workers` | Bounded independent tasks are delegated | [workers.md](../references/workers.md) |
| `commands` | Users need explicit reusable invocation | [commands.md](../references/commands.md) |
| `packaging` | The skill ships inside a bundle a host must discover and distribute | [packaging.md](../references/packaging.md) |

Stop here if the task is simple enough for one direct instruction. Do not create a coordinator without a resume, branching, concurrency, retry, safety, or repeated-use need.

## Start a Run

```bash
python3 scripts/design.py init \
  --name <skill-name> \
  --skill <skill-path> \
  --run-dir <run-directory> \
  --capability coordinator \
  --capability state
```

Omit `--capability` entirely for a skill that needs none. The run directory must be empty and must not sit inside the skill being designed.

When the deliverable ships as a bundle rather than one skill, the selection covers component kinds too: ask what each kind is for, present kind, count, and purpose as one table, and get it approved before the first file exists. A skeleton is cheap to change and a built-out bundle is not, which is what makes this the checkpoint. [packaging.md](../references/packaging.md) owns what the scaffold contains.

Inspect the current phase, its owning resource, and the next action at any time:

```bash
python3 scripts/design.py status --run-dir <run-directory>
```

## Work Each Phase

`status` names one phase and the resource that holds its contract. Read that resource, design that concern, then record the decision:

```bash
python3 scripts/design.py complete-phase \
  --run-dir <run-directory> \
  --phase <phase> \
  --note "<decision and rationale>"
```

Phases complete in order. The coordinator rejects an out-of-order or empty-note completion, and every decision persists under `decisions/` so an interrupted run resumes from artifacts rather than memory.

When a capability surfaces late, extend the plan without losing completed work:

```bash
python3 scripts/design.py add-capability \
  --run-dir <run-directory> \
  --capability events
```

## Phases the Coordinator Always Runs

`contract` opens every run: record purpose, inputs, outputs, invariants, and prerequisites against [structure.md](../references/structure.md).

`resources` plans the files themselves. Route repeated deterministic logic to scripts, detailed schemas and decision tables to references, runnable samples to examples, and output-only material to assets. Keep one canonical home per rule and create no unused placeholder. Name each planned file before creating it using [naming.md](../references/naming.md).

`checks` places validation where failure becomes actionable rather than as a trailing verification phase, and puts approval immediately before irreversible actions, following [checks.md](../references/checks.md).

`review` closes the run against the owner-boundary questions in [closure.md](../references/closure.md). Completing it refuses while the skill carries a format error a host would reject it for, and names the fix for each. Those are the boundary questions a parser can settle, so the run hears about them rather than a later reviewer.

## Exercise the Result

Run the focused checks owned by each resource the contract selected. Then exercise the coordinator behavior no single adapter owns:

- Fresh successful run, and an interrupted run resumed from persisted state alone.
- One item failure inside a parallel pipeline, with sibling items unaffected.
- Retry bound reached, returning a terminal result rather than looping.
- Changed destructive proposal requiring fresh approval.
- Coordinator failure rendered with durable artifacts and resume information.
- One run proving preferences stay immutable while coordinator state changes.
- A representative real task proving the references and scripts improve the outcome.

Use runtime tests or a small assert-based script. Test control flow, not prose formatting. In this repository, run `python3 scripts/check.py`.

Its document-structure checks parse markdown and YAML through `scripts/document.py` rather than matching text, so fenced blocks and inline code never register as links. Install the parsers once with `pip install -r requirements.txt`. Ask a structural question directly while drafting:

```bash
python3 scripts/document.py links .
python3 scripts/document.py outline SKILL.md
```
