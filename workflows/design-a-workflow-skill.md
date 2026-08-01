# Design a Dynamic Workflow Skill

Use this process to create or refactor multi-step skill without duplicating workflow control in prose.

## 1. Define Contract

Write down:

- Triggering requests.
- Required inputs and trust boundaries.
- Observable outputs.
- Safety invariants.
- Runtime capabilities available: scripts, workflow API, state store, delegation, approval, progress UI.
- Deployment shape and host discovery requirements.
- Event boundaries requiring independent guard or reaction.
- MCP servers or external services, schemas, authentication, and side effects.
- Whether any task is bounded and independent enough for delegated worker.
- Whether workflow needs explicit command entrypoint, declared arguments, or manual-only invocation.
- Whether users need stable skill settings, which scopes exist, and whether any values are secrets.

Stop if task is simple enough for one direct skill instruction. Do not create coordinator without resume, branching, concurrency, retry, safety, or repeated-use need.

## 2. Choose Coordinator Shape

Select smallest pattern from [workflow-patterns.md](../references/workflow-patterns.md):

- Route for independent paths.
- Pipeline for independent items.
- Delegated worker adapter for one bounded independent task.
- Event hook adapter for host lifecycle boundary.
- External-tool adapter for MCP or service capability.
- Ordered phases for staged transformations.
- Dependency graph for blocked work.
- Bounded loop for iterative improvement.
- Safety gate for destructive action.
- Thin command entrypoint adapter for explicit invocation.

Combine patterns only when task requires combination.

## 3. Plan Reusable Resources

For each use case, identify:

- Repeated deterministic logic for scripts.
- Detailed schemas, policies, or decision tables for references.
- Runnable or copyable samples for examples when repository uses them.
- Output-only templates or media for assets.

Keep one canonical home per rule. Create no unused directory or placeholder. See [skill-structure.md](../references/skill-structure.md).

## 4. Encode Control Flow

Implement order, branching, concurrency, retries, and loop bounds in executable code.

Prefer:

1. Existing runtime workflow primitives.
2. Existing project language and stdlib.
3. Small coordinator script.

Avoid new dependency solely for orchestration syntax.

Make functions return explicit artifacts or state. Keep hidden mutable state out of model conversation.

## 5. Add Durable State

Persist enough state to resume:

- Current route or phase.
- Per-item or per-task status.
- Artifact identifiers.
- Retry counters.
- Terminal errors.

Make completed idempotent work skippable. Guard non-idempotent work against duplicate execution.

## 6. Set Failure and Concurrency Policies

Define:

- Retryable versus terminal errors.
- Maximum retries or loop iterations.
- Fail-fast, collect-failures, or threshold behavior.
- Runtime concurrency limit.
- Cancellation behavior.

Use one worker per independent item when runtime bounds concurrency. Batch only for concrete setup or service constraints.

## 7. Place Safety and Checks

Put validation at relevant boundary:

- Inputs before mutation.
- Artifact schema after generation.
- Existing test, lint, build, or validator before handoff when affected.
- Postconditions around irreversible operations when required for safety.

Put approval immediately before destructive action. Bind approval to exact proposal.

Do not add generic final verification phase when no deterministic check exists.

## 8. Design Skill Settings

When behavior is configurable:

1. Define schema, types, defaults, allowed values, version, and disable behavior.
2. Separate preferences from mutable coordinator state and secrets.
3. Define user, project, and invocation scopes with deterministic precedence and provenance.
4. Let host adapter own location, format, discovery, parsing, migration, caching, and reload semantics.
5. Pass one immutable effective snapshot to coordinator and bounded adapters.
6. Use validated serialization, same-directory atomic replacement, and concurrency protection for updates.

See [skill-settings.md](../references/skill-settings.md).

## 9. Design Event Hooks

For each required boundary:

1. Select deterministic, model-evaluated, or layered execution.
2. Define matcher, input schema, owned scope, timeout, and normalized outcome.
3. Keep workflow transitions in coordinator.
4. Define stable state identity, concurrency, idempotency, and safe fallback.
5. Validate registration and representative event payloads.

See [event-hooks.md](../references/event-hooks.md).

## 10. Design External Tools

For each MCP or service adapter:

1. Define required capabilities, schemas, transport needs, and lifecycle.
2. Validate portable configuration, authentication, tenant, and least privilege.
3. Put call order, retries, partial success, approval, and resume in coordinator.
4. Normalize results and redact secrets.
5. Test connectivity, discovery, success, auth, timeout, rate-limit, and recovery paths.

See [external-tools.md](../references/external-tools.md).

## 11. Design Delegated Workers

For each delegated task, define:

1. Stable purpose and positive or negative selection conditions.
2. Structured inputs, exact ownership, and applicable project context.
3. Least-privilege capabilities and any justified execution override.
4. Output artifact or schema coordinator consumes.
5. Partial, retryable, blocked, terminal, and cancellation results.

Keep global phases, dependencies, retries, progress, approvals, rollback, and durable state in coordinator. See [delegated-workers.md](../references/delegated-workers.md).

## 12. Design Command Entrypoint

When explicit command surface is needed, implement thin runtime adapter:

1. Declare purpose, arguments, prerequisites, and invocation policy.
2. Parse and validate raw inputs before use.
3. Gather minimum required context through host-native APIs.
4. Call one coordinator entrypoint with structured values.
5. Render status, artifacts, failures, and resume information.

Keep exact registration, metadata, context, and interaction syntax outside core workflow guidance. Never splice raw arguments into shell text. See [command-entrypoints.md](../references/command-entrypoints.md).

## 13. Write Skill Adapter

Keep `SKILL.md` small. Include:

- When workflow applies.
- Required inputs and runtime prerequisites.
- Invariants and safety boundaries.
- Coordinator entry command or API.
- Links to only references needed during execution.
- Host metadata and deployment adapter requirements.

Keep activation metadata specific and core instructions lean. Use repository-native initializer, validator, discovery, and packaging when available.

## 14. Exercise Activation, Adapters, Settings, and Resume

Run representative checks:

- Fresh successful run.
- Interrupted run resumed from persisted state.
- One item failure in parallel pipeline.
- Positive, negative, overlap, and missing-input skill activation scenarios.
- Event handler malformed input, timeout, concurrency, and safe fallback.
- External-tool missing authentication, schema mismatch, rate limit, partial success, and resume.
- Positive, negative, overlap, and missing-input worker selection scenarios.
- Worker attempt to mutate outside owned scope.
- Partial or terminal worker result preserved by coordinator.
- Retry bound reached.
- Changed destructive proposal requiring new approval.
- Missing, malformed, conflicting, and traversal-like command inputs.
- Missing settings, precedence conflicts, malformed types, unknown schema version, unsafe paths, concurrent update, failed migration, and settings rollback.
- One run proving preferences remain immutable while coordinator state changes.
- Coordinator failure rendered with durable artifacts and resume information.
- Sensitive entrypoint requiring explicit invocation and exact approval.
- Representative real task proving references and scripts improve outcome.

Use runtime tests or small assert-based script. Test control flow, not prose formatting.

After real use, fix missed activation, ambiguous routes, repeated manual logic, unused resources, and broken assumptions with smallest targeted change.
