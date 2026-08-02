---
name: designing-workflow-skills
description: Design, refactor, package, or merge runtime-neutral workflow skills whose multi-step behavior spans executable coordination, validated skill settings, event-triggered guards, MCP or external-tool services, delegated workers, and explicit command entrypoints. Use when workflows need routing, phases, concurrency, dependencies, resume, bounded loops, configurable behavior, safety gates, progressive disclosure, validated adapters, or durable failure recovery, when bundling skills and components for host discovery and distribution, and when absorbing or consolidating one or many skills into one target without losing capabilities or copying host-specific syntax into core guidance.
---

# Designing Workflow Skills

Put workflow control in executable orchestration. Keep core instructions focused on activation, inputs, invariants, safety boundaries, coordinator entry, and direct links to needed resources.

## When to Use

Use this skill when creating or refactoring a reusable skill whose behavior needs one or more of:

- Branching, bounded concurrency, retries, dependencies, loops, checkpoints, or resume.
- Durable state or partial-failure recovery across multiple work items.
- Approval immediately before destructive or irreversible actions.
- Runtime-neutral setup and pre-flight checks, or adapters for events, external tools, delegated workers, commands, or layered settings.
- Progressive disclosure across core instructions, references, scripts, examples, and output assets.
- Packaging skills and components as a bundle a host discovers, loads, and distributes.
- Merging or consolidating several skills, or folding an upstream skill into an existing one, without losing capability coverage.

## When Not to Use

Do not use this skill for:

- A single direct task with no reusable workflow contract.
- Simple instructions whose order does not branch, retry, resume, or coordinate independent work.
- Generic skill copy-editing, one-time skill review, or host-specific syntax lookup without workflow design.
- Application orchestration that is not being packaged as an agent skill.

For borderline cases, start with direct instructions. Add executable coordination only after a concrete need for branching, resume, bounded retry, concurrency, safety gates, or repeated invocation appears.

## Core Architecture

Separate these concerns. Each row names the one owner of that concern and the resource holding its full contract.

| Need | Owner and shape | Contract |
|---|---|---|
| Define purpose, inputs, outputs, invariants, prerequisites | Skill contract | [structure.md](references/structure.md) |
| Choose one independent path | Route with a branch or dispatch table | [patterns.md](references/patterns.md) |
| Apply one operation to many independent items | `pipeline(items, worker)` | [patterns.md](references/patterns.md) |
| Run ordered stages once | Ordered `phase(name, operation)` calls | [patterns.md](references/patterns.md) |
| Execute dependency-aware work | Explicit graph/state variables plus runtime progress | [patterns.md](references/patterns.md) |
| Refine until a condition holds | Bounded `while` loop | [patterns.md](references/patterns.md) |
| Persist progress outside model context | State artifacts owned by coordinator | [patterns.md](references/patterns.md) |
| Perform irreversible work | Approval gate around the action | [patterns.md](references/patterns.md) |
| Guard or react at a lifecycle boundary | Thin event adapter | [events.md](references/events.md) |
| Call MCP or an external service | Typed external-tool adapter | [tools.md](references/tools.md) |
| Delegate one bounded independent task | Worker with explicit contract | [workers.md](references/workers.md) |
| Expose explicit reusable invocation | Thin command entrypoint adapter | [commands.md](references/commands.md) |
| Make skill behavior configurable | Validated settings adapter | [settings.md](references/settings.md) |
| Provision prerequisites or prove readiness | Separate setup entrypoint and pre-flight report | [setup.md](workflows/setup.md) |
| Install an agent skill | Discover, install, verify in same scope | [install.md](references/install.md) |
| Package components for host discovery and distribution | Bundle manifest, conventional component locations, portable bundle-root references | [packaging.md](references/packaging.md) |
| Route logic, knowledge, samples, and output material | Bundled resources | [structure.md](references/structure.md) |
| Name a new or renamed resource | One word, else family-first hierarchy | [naming.md](references/naming.md) |
| Merge many skills into one target | Evidence-bound absorption run with snapshot rollback | [workflow](workflows/absorb.md), [rules](references/absorb.md) |

The coordinator is the workflow source of truth. Prose may explain why a transition exists, but must not duplicate executable control flow. Each adapter owns its host syntax; core guidance stays runtime-neutral.

## Runtime-Neutral Rules

These rules hold across every concern above. Each adapter's own contract lives in its reference.

- Treat `pipeline()` and `phase()` as conceptual APIs. Use the host's native workflow runtime when available; otherwise use a small script in an already-used project language.
- Do not add a dependency only to obtain workflow syntax. Arrays, functions, state files, and bounded loops are enough.
- Persist durable state after meaningful units of work. Resume from artifacts, not conversational memory.
- Make idempotent steps safe to rerun. Mark non-idempotent steps and guard them with persisted completion state.
- Treat every external input as untrusted: command arguments, paths, event payloads, settings content, and tool responses. Validate before use, and never splice raw values into shell text.
- Grant least privilege at every boundary, and keep secrets in a secret store rather than settings, logs, or workflow artifacts.
- Keep host discovery, metadata, context loading, invocation, and interaction syntax in runtime adapters. Never copy runtime-specific syntax into core workflow guidance.
- Do not restate a contract that the table above assigns to another resource.

## Validation Placement

Do not append a generic "verification phase" to every workflow. Put checks where failure becomes actionable:

- Validate inputs before mutation.
- Run schema or contract checks after producing the relevant artifact.
- Run repository-native checks such as `make check`, tests, linters, or validators before handoff when the task changes validated surfaces.
- Use postconditions around irreversible actions when needed for safety or data-loss prevention.

Prefer existing deterministic checks. Do not restate their logic as prompt instructions.

## Safety Gates

Keep analysis and destructive execution separate:

1. Compute exact proposed action and impact.
2. Persist proposal when resume matters.
3. Ask for explicit approval with concrete scope.
4. Execute only approved action.
5. Record result or failure before continuing.

Approval is a runtime event, not prose such as "continue only if approved."

Approval protects irreversible actions. When mutation is confined to a snapshotted scope, an equivalent gate is reversibility: bind the exact plan, snapshot the scope before mutation, reject evidence that no longer matches the bound plan, and restore the snapshot automatically on unsafe or exhausted execution. Use this shape only when the snapshot provably restores the pre-mutation state.

## Fallback Without a Workflow Runtime

When host lacks dynamic workflows:

1. Write minimal coordinator script using project stdlib.
2. Store state in a small JSON or existing project state format.
3. Expose one thin entry command with explicit validated inputs.
4. Keep `SKILL.md` as adapter telling agent when and how to invoke script.

Use prose-only sequencing only for short, low-risk workflows that do not need resume, concurrency, retry, or partial-failure handling.

## Absorbing Skills

Merge skills semantically, never by concatenation. Keep sources read-only, store run progress in a durable directory outside every skill, and give every capability and runtime dependency an explicit disposition so nothing is dropped silently. Organize the result by canonical job shape rather than by absorbed-source name.

Every absorption also tests this skill's own coordinator against unfamiliar material. Record the resulting verdict, and prefer fixing an observed coordinator defect during the run that exposed it.

## Design Workflow

Follow [design.md](workflows/design.md) when creating or refactoring a workflow skill. Its coordinator derives the phase list from the contract you record, so a skill only walks the phases its capabilities require.

When reviewing upstream sources or refreshing absorbed guidance, use [UPSTREAM.md](UPSTREAM.md) as baseline and changelog registry.
