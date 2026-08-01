---
name: designing-workflow-skills
description: Design or refactor agent skills that need routing, ordered phases, parallel item processing, dependency tracking, resumable state, bounded feedback loops, or safety gates. Use when multi-step logic should move from prose into executable orchestration, when choosing pipeline/phase/graph/loop patterns, or when reviewing workflow reliability across Codex, Claude Code, and other agent runtimes.
---

# Designing Workflow Skills

Put workflow control in executable orchestration. Keep `SKILL.md` focused on activation, inputs, invariants, safety boundaries, and links to runtime code.

Use `skill-development` or `skill-creator` for generic skill packaging, descriptions, progressive disclosure, and resource layout. Use this skill only for multi-step execution design.

## Core Architecture

Separate four concerns:

1. **Skill contract** — Define purpose, inputs, outputs, invariants, and runtime prerequisites.
2. **Coordinator** — Execute ordering, branching, concurrency, retries, loops, and resume logic.
3. **State artifacts** — Persist progress and outputs outside model context.
4. **Checks** — Run existing validators, tests, schemas, or build targets at relevant boundaries.

The coordinator is the workflow source of truth. Prose may explain why a transition exists, but must not duplicate executable control flow.

## Runtime-Neutral Rules

- Treat `pipeline()` and `phase()` as conceptual APIs. Use the host's native workflow runtime when available; otherwise use a small script in an already-used project language.
- Do not add a dependency only to obtain workflow syntax. Arrays, functions, state files, and bounded loops are enough.
- Persist durable state after meaningful units of work. Resume from artifacts, not conversational memory.
- Make idempotent steps safe to rerun. Mark non-idempotent steps and guard them with persisted completion state.
- Keep destructive actions behind explicit user approval immediately before execution.
- Use host-native planning, delegation, approval, and progress primitives. Do not hardcode one vendor's tool names in reusable guidance.
- Declare tools only when the target runtime supports a tool allowlist and the workflow actually needs those capabilities.

## Pattern Selection

| Need | Coordinator shape |
|---|---|
| Choose one independent path | Route with a branch or dispatch table |
| Apply one operation to many independent items | `pipeline(items, worker)` |
| Run ordered stages once | Ordered `phase(name, operation)` calls |
| Execute dependency-aware work | Explicit graph/state variables plus runtime progress |
| Refine until a condition holds | Bounded `while` loop |
| Perform irreversible work | Approval gate around the action |

Read [workflow-patterns.md](references/workflow-patterns.md) for concrete structures and failure policies.

## Concurrency and Delegation

Default to one worker per independent item when the runtime provides bounded concurrency and resumable progress. This preserves item-level status and avoids losing an entire batch on failure.

Batch only when one of these is true:

- Setup cost dominates item work.
- An external API imposes bulk or rate-limit constraints.
- Items require shared context to produce a correct result.
- The runtime has no concurrency control and the coordinator must impose one.

Set concurrency in runtime configuration. Never encode a universal batch size such as 10–20 items.

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

## Fallback Without a Workflow Runtime

When host lacks dynamic workflows:

1. Write minimal coordinator script using project stdlib.
2. Store state in a small JSON or existing project state format.
3. Expose one entry command with explicit inputs.
4. Keep `SKILL.md` as adapter telling agent when and how to invoke script.

Use prose-only sequencing only for short, low-risk workflows that do not need resume, concurrency, retry, or partial-failure handling.

## Design Workflow

Follow [design-a-workflow-skill.md](workflows/design-a-workflow-skill.md) when creating or refactoring a workflow skill.

## Review Questions

- Does executable code own ordering and branching?
- Can interrupted work resume from durable state?
- Are retries bounded and safe?
- Is concurrency controlled by runtime rather than arbitrary prose batching?
- Are destructive actions gated immediately before execution?
- Do checks call existing validators instead of duplicating them?
- Are runtime-specific tool names isolated to runtime adapters?
- Could generic skill guidance be deleted in favor of `skill-development` or `skill-creator`?
