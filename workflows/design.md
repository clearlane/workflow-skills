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
- Whether prerequisites require explicit setup and which readiness conditions need pre-flight checks.
- Whether users need stable skill settings, which scopes exist, and whether any values are secrets.

Stop if task is simple enough for one direct skill instruction. Do not create coordinator without resume, branching, concurrency, retry, safety, or repeated-use need.

When the work merges existing skills rather than designing new behavior, follow [absorb.md](absorb.md) instead of restarting the contract from scratch. Absorb first, then continue this process for whatever the merged contract still lacks.

## 2. Choose Coordinator Shape

Select smallest pattern from [patterns.md](../references/patterns.md):

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

Keep one canonical home per rule. Create no unused directory or placeholder. See [structure.md](../references/structure.md).

Name each planned file before creating it. Prefer one word where clear; otherwise use a stable family-first hierarchy such as `command-create` and `command-review`. Read [naming.md](../references/naming.md) and include the filename check in the repository's normal validation path when possible.

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

## 7. Design Setup and Pre-flight

When prerequisites exist:

1. Derive requirements from validated invocation, selected route, effective settings, and target environment.
2. Keep setup as an explicit, idempotent, version-aware entrypoint; preview and approve privileged or material changes. For agent-skill installation, use `npx skills` with discovery, explicit source/skill/agent/scope/mode, and same-scope verification rather than host paths.
3. Make pre-flight side-effect-free and return structured ready, blocked, approval-required, and warning results with remediation.
4. Run pre-flight before creating mutable run state or dispatching workers. Re-run it after setup from fresh observations.
5. Cache expensive observations only with environment identity, relevant digests, capability version, and bounded expiry.
6. Revalidate volatile credentials, permissions, locks, target identity, and destructive scope immediately before use.

See [setup.md](setup.md).

## 8. Place Safety and Checks

Put validation at relevant boundary:

- Inputs before mutation.
- Artifact schema after generation.
- Existing test, lint, build, or validator before handoff when affected.
- Postconditions around irreversible operations when required for safety.

Put approval immediately before destructive action. Bind approval to exact proposal.

Do not add generic final verification phase when no deterministic check exists.

## 9. Design Skill Settings

When behavior is configurable:

1. Define schema, types, defaults, allowed values, version, and disable behavior.
2. Separate preferences from mutable coordinator state and secrets.
3. Define user, project, and invocation scopes with deterministic precedence and provenance.
4. Let host adapter own location, format, discovery, parsing, migration, caching, and reload semantics.
5. Pass one immutable effective snapshot to coordinator and bounded adapters.
6. Use validated serialization, same-directory atomic replacement, and concurrency protection for updates.

See [settings.md](../references/settings.md).

## 10. Design Event Hooks

For each required boundary:

1. Select deterministic, model-evaluated, or layered execution.
2. Define matcher, input schema, owned scope, timeout, and normalized outcome.
3. Keep workflow transitions in coordinator.
4. Define stable state identity, concurrency, idempotency, and safe fallback.
5. Validate registration and representative event payloads.

See [events.md](../references/events.md).

## 11. Design External Tools

For each MCP or service adapter:

1. Define required capabilities, schemas, transport needs, and lifecycle.
2. Validate portable configuration, authentication, tenant, and least privilege.
3. Put call order, retries, partial success, approval, and resume in coordinator.
4. Normalize results and redact secrets.
5. Test connectivity, discovery, success, auth, timeout, rate-limit, and recovery paths.

See [tools.md](../references/tools.md).

## 12. Design Delegated Workers

For each delegated task, define:

1. Stable purpose and positive or negative selection conditions.
2. Structured inputs, exact ownership, and applicable project context.
3. Least-privilege capabilities and any justified execution override.
4. Output artifact or schema coordinator consumes.
5. Partial, retryable, blocked, terminal, and cancellation results.

Keep global phases, dependencies, retries, progress, approvals, rollback, and durable state in coordinator. See [workers.md](../references/workers.md).

## 13. Design Command Entrypoint

When explicit command surface is needed, implement thin runtime adapter:

1. Declare purpose, arguments, prerequisites, and invocation policy.
2. Parse and validate raw inputs before use.
3. Gather minimum required context through host-native APIs.
4. Call one coordinator entrypoint with structured values.
5. Render status, artifacts, failures, and resume information.

Keep exact registration, metadata, context, and interaction syntax outside core workflow guidance. Never splice raw arguments into shell text. See [commands.md](../references/commands.md).

## 14. Write Skill Adapter

Keep `SKILL.md` small. Include:

- When workflow applies.
- Required inputs and runtime prerequisites.
- Invariants and safety boundaries.
- Coordinator entry command or API.
- Links to only references needed during execution.
- Host metadata and deployment adapter requirements.

Keep activation metadata specific and core instructions lean. Use repository-native initializer, validator, discovery, and packaging when available.

## 15. Exercise Setup, Pre-flight, Activation, Adapters, Settings, and Resume

Run representative checks:

- Already-ready environment where setup is a no-op and pre-flight succeeds.
- Missing provisionable and non-provisionable prerequisites with exact remediation.
- Setup followed by fresh pre-flight rather than assumed readiness.
- Stale pre-flight cache and volatile condition changed before action.
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
- Invalid filename characters or separators, plus manual review that multiword names are necessary and family-first.

Use runtime tests or small assert-based script. Test control flow, not prose formatting.

After real use, fix missed activation, ambiguous routes, repeated manual logic, unused resources, and broken assumptions with smallest targeted change.
