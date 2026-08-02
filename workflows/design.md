# Design a Workflow Skill

Create or refactor a multi-step skill without holding workflow control in prose. The coordinator at `scripts/design.py` derives the phase list from the contract you record, so a skill with no settings never walks a settings phase.

When the work merges existing skills rather than designing new behavior, follow [absorb.md](absorb.md) first, then run this workflow for whatever the merged contract still lacks.

## Define the Contract

Before starting a run, write down:

- Triggering requests, required inputs, trust boundaries, and observable outputs.
- Safety invariants and irreversible actions.
- Runtime capabilities available: scripts, workflow API, state store, delegation, approval, progress UI.
- Deployment shape and host discovery requirements.

Then decide which capabilities the skill actually needs. Each one selects its phase and nothing else:

| Capability | Select when | Contract |
|---|---|---|
| `coordinator` | Order, branching, concurrency, retries, or loops need executable control | [patterns.md](../references/patterns.md) |
| `state` | Work must resume after interruption or partial failure | [patterns.md](../references/patterns.md) |
| `settings` | Users need stable preferences across runs | [settings.md](../references/settings.md) |
| `setup` | Prerequisites need provisioning or readiness proof | [setup.md](setup.md) |
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

`checks` places validation where failure becomes actionable rather than as a trailing verification phase, and puts approval immediately before irreversible actions. Prefer an existing deterministic check over restating its logic.

`review` closes the run with the questions below.

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

## Review Questions

Each question tests one owner boundary; the owning reference holds the rule itself.

- Does executable code own ordering, branching, and bounded retries, with interrupted work resumable from durable state?
- Is concurrency set by runtime configuration rather than a fixed prose batch size?
- Are destructive actions gated immediately before execution, or confined to a provably restorable snapshot?
- Do checks call existing validators instead of restating their logic?
- Does each adapter — event, external-tool, worker, command, settings — own exactly its own boundary while the coordinator retains global state?
- Are runtime-specific names and syntax confined to adapters?
- Is every external input validated before use, without raw shell interpolation?
- Is setup explicit, idempotent, and separate from activation, with route-specific pre-flight before mutable state?
- Are volatile permissions, target identity, locks, and destructive scope revalidated at point of use?
- Does each rule have exactly one canonical home, with no duplicated prose or unused scaffolding?
- Do new or renamed resources follow the filename convention?

After real use, fix missed activation, ambiguous routes, repeated manual logic, unused resources, and broken assumptions with the smallest targeted change.
