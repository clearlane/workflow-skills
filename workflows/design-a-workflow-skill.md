# Design a Dynamic Workflow Skill

Use this process to create or refactor multi-step skill without duplicating workflow control in prose.

## 1. Define Contract

Write down:

- Triggering requests.
- Required inputs and trust boundaries.
- Observable outputs.
- Safety invariants.
- Runtime capabilities available: scripts, workflow API, state store, delegation, approval, progress UI.

Stop if task is simple enough for one direct skill instruction. Do not create coordinator without resume, branching, concurrency, retry, safety, or repeated-use need.

## 2. Choose Coordinator Shape

Select smallest pattern from [workflow-patterns.md](../references/workflow-patterns.md):

- Route for independent paths.
- Pipeline for independent items.
- Ordered phases for staged transformations.
- Dependency graph for blocked work.
- Bounded loop for iterative improvement.
- Safety gate for destructive action.

Combine patterns only when task requires combination.

## 3. Encode Control Flow

Implement order, branching, concurrency, retries, and loop bounds in executable code.

Prefer:

1. Existing runtime workflow primitives.
2. Existing project language and stdlib.
3. Small coordinator script.

Avoid new dependency solely for orchestration syntax.

Make functions return explicit artifacts or state. Keep hidden mutable state out of model conversation.

## 4. Add Durable State

Persist enough state to resume:

- Current route or phase.
- Per-item or per-task status.
- Artifact identifiers.
- Retry counters.
- Terminal errors.

Make completed idempotent work skippable. Guard non-idempotent work against duplicate execution.

## 5. Set Failure and Concurrency Policies

Define:

- Retryable versus terminal errors.
- Maximum retries or loop iterations.
- Fail-fast, collect-failures, or threshold behavior.
- Runtime concurrency limit.
- Cancellation behavior.

Use one worker per independent item when runtime bounds concurrency. Batch only for concrete setup or service constraints.

## 6. Place Safety and Checks

Put validation at relevant boundary:

- Inputs before mutation.
- Artifact schema after generation.
- Existing test, lint, build, or validator before handoff when affected.
- Postconditions around irreversible operations when required for safety.

Put approval immediately before destructive action. Bind approval to exact proposal.

Do not add generic final verification phase when no deterministic check exists.

## 7. Write Skill Adapter

Keep `SKILL.md` small. Include:

- When workflow applies.
- Required inputs and runtime prerequisites.
- Invariants and safety boundaries.
- Coordinator entry command or API.
- Links to only references needed during execution.

Use `skill-development` or `skill-creator` for generic description, packaging, and resource guidance.

## 8. Exercise Resume Paths

Run representative checks:

- Fresh successful run.
- Interrupted run resumed from persisted state.
- One item failure in parallel pipeline.
- Retry bound reached.
- Changed destructive proposal requiring new approval.

Use runtime tests or small assert-based script. Test control flow, not prose formatting.
