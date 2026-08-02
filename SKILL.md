---
name: designing-workflow-skills
description: Design or refactor runtime-neutral workflow skills whose multi-step behavior spans executable coordination, validated skill settings, event-triggered guards, MCP or external-tool services, delegated workers, and explicit command entrypoints. Use when workflows need routing, phases, concurrency, dependencies, resume, bounded loops, configurable behavior, safety gates, progressive disclosure, validated adapters, or durable failure recovery without copying host-specific syntax into core guidance.
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

## When Not to Use

Do not use this skill for:

- A single direct task with no reusable workflow contract.
- Simple instructions whose order does not branch, retry, resume, or coordinate independent work.
- Generic skill copy-editing, one-time skill review, or host-specific syntax lookup without workflow design.
- Application orchestration that is not being packaged as an agent skill.

For borderline cases, start with direct instructions. Add executable coordination only after a concrete need for branching, resume, bounded retry, concurrency, safety gates, or repeated invocation appears.

## Core Architecture

Separate ten concerns:

1. **Skill contract** — Define purpose, inputs, outputs, invariants, and runtime prerequisites.
2. **Coordinator** — Execute ordering, branching, concurrency, retries, loops, and resume logic.
3. **State artifacts** — Persist progress and outputs outside model context.
4. **Event adapters** — Guard or react at lifecycle boundaries without owning workflow state.
5. **External-tool adapters** — Connect MCP or service tools through typed, least-privilege contracts.
6. **Delegated workers** — Own one bounded task with explicit inputs, capabilities, output, and failure contract.
7. **Entrypoint adapters** — Parse and validate explicit invocation, then call coordinator without owning workflow logic.
8. **Settings adapters** — Resolve validated user and project preferences without storing mutable workflow progress.
9. **Bundled resources** — Route deterministic logic, detailed knowledge, runnable examples, and output materials by use.
10. **Setup and pre-flight** — Provision explicit prerequisites separately from side-effect-free readiness checks.
11. **Checks** — Run existing validators, tests, schemas, or build targets at relevant boundaries.

The coordinator is the workflow source of truth. Prose may explain why a transition exists, but must not duplicate executable control flow.

## Runtime-Neutral Rules

- Treat `pipeline()` and `phase()` as conceptual APIs. Use the host's native workflow runtime when available; otherwise use a small script in an already-used project language.
- Do not add a dependency only to obtain workflow syntax. Arrays, functions, state files, and bounded loops are enough.
- Persist durable state after meaningful units of work. Resume from artifacts, not conversational memory.
- Make idempotent steps safe to rerun. Mark non-idempotent steps and guard them with persisted completion state.
- Keep destructive actions behind explicit user approval immediately before execution.
- Use host-native planning, delegation, approval, and progress primitives. Do not hardcode one vendor's tool names in reusable guidance.
- Declare tools only when the target runtime supports a tool allowlist and the workflow actually needs those capabilities.
- Keep global phases, retries, progress, approvals, and durable state in coordinator. Give each worker one bounded responsibility and structured return contract.
- Keep event handlers thin, independent, bounded by timeout, and safe under concurrent execution.
- Validate external-tool schemas, authentication, permissions, and side effects before coordinator invocation.
- Treat command arguments, paths, and referenced resources as untrusted inputs. Parse and validate them before coordinator invocation.
- Keep user settings separate from mutable workflow state. Resolve typed defaults, user settings, project settings, and invocation overrides into one immutable effective configuration with provenance.
- Keep secrets out of ordinary settings files. Treat settings content and configured paths as untrusted input.
- Keep setup explicit and idempotent. Run route-specific pre-flight before creating run state or dispatching work, then revalidate volatile safety conditions at the action boundary.
- Keep skill, settings, event, external-tool, worker, and command discovery, metadata, context loading, invocation, and interaction syntax in runtime adapters. Never copy runtime-specific syntax into core workflow guidance.

## Pattern Selection

| Need | Coordinator shape |
|---|---|
| Choose one independent path | Route with a branch or dispatch table |
| Apply one operation to many independent items | `pipeline(items, worker)` |
| Delegate one bounded independent task | Worker adapter with explicit contract |
| Guard or react at lifecycle boundary | Thin event-hook adapter |
| Call MCP or external service | Typed external-tool adapter |
| Run ordered stages once | Ordered `phase(name, operation)` calls |
| Execute dependency-aware work | Explicit graph/state variables plus runtime progress |
| Refine until a condition holds | Bounded `while` loop |
| Perform irreversible work | Approval gate around the action |
| Expose explicit reusable invocation | Thin command entrypoint adapter |
| Make skill behavior configurable | Validated skill-settings adapter |
| Provision prerequisites or prove readiness | Separate setup entrypoint and pre-flight report |

Read [patterns.md](references/patterns.md) for concrete structures and failure policies.

Follow [setup.md](workflows/setup.md) when workflow needs environment provisioning, capability checks, credentials, service health, resource checks, or resume compatibility before execution.

Read [structure.md](references/structure.md) for activation, progressive disclosure, resources, deployment shapes, and skill checks.

Read [events.md](references/events.md) when workflow reacts to host lifecycle or action boundaries.

Read [tools.md](references/tools.md) when workflow uses MCP servers or other external services.

Read [workers.md](references/workers.md) when workflow delegates bounded work.

Read [commands.md](references/commands.md) when workflow needs an explicit command surface.

Read [settings.md](references/settings.md) when skill behavior needs user-local, project-local, or invocation-level preferences.

## Skill Structure

Start from concrete use cases. Keep only activation-adjacent rules and coordinator entry in core instructions. Route repeated deterministic work to scripts, detailed knowledge to references, runnable samples to examples, and output-only material to assets.

Create only directories and metadata required by current host or repository. Use repository-native initialization, validation, discovery, and packaging when available. Test both activation and actual utility, then refine from observed failures.

## Event Hooks

Add event adapter only when action must occur at host boundary rather than normal coordinator step. Use deterministic handler for enforceable validation, transformation, logging, or fast external checks. Use model-evaluated handler only for bounded semantic judgment with safe fallback.

Normalize host result into explicit `continue`, `deny`, `ask`, `modify`, `message`, or `fail` outcome. Handler must validate event payload, stay within owned scope, avoid ordering assumptions, and persist cross-event facts under stable workflow identity.

## External Tools

Treat MCP and service tools as untrusted external capabilities. Adapter defines transport, configuration, authentication, discovered schemas, permissions, timeouts, rate limits, and result normalization. Coordinator owns call order, batching, retries, idempotency, partial success, approval, and resume.

Keep secrets outside committed configuration and logs. Use least-privilege credentials and tool scopes. Verify exact transport and host syntax against current runtime or protocol documentation.

## Delegated Workers

Delegate only when work is bounded, independently checkable, and expressible through explicit inputs and outputs. Handle small synchronous work directly. Use command entrypoint when user needs explicit reusable invocation.

Worker contract must define:

- Stable purpose and selection conditions, including when not to use it.
- Inputs, owned scope, applicable project context, and required capabilities.
- Output artifact or schema coordinator can consume.
- Retryable, partial, blocked, and terminal outcomes.

Use least privilege. Keep host-default execution settings unless concrete capability, latency, cost, or isolation need requires override. Worker may use local steps, but must not own global workflow state or duplicate coordinator transitions.

## Command Entrypoints

Add command entrypoint only when users need repeatable explicit invocation, documented arguments, discoverability, or manual control over side effects.

Keep adapter thin:

1. Parse declared inputs.
2. Validate values, paths, resources, and prerequisites.
3. Gather only context coordinator needs.
4. Invoke one coordinator entry function or command.
5. Render status, artifacts, and actionable failures.

Do not put phases, retries, loops, checkpoints, rollback, or approval state in command prose. Do not splice raw arguments into shell text. Coordinator remains workflow source of truth.

## Skill Settings

Use settings only for user-controlled preferences such as modes, limits, feature flags, and optional context. Keep progress, retries, approvals, artifacts, and completion markers in coordinator state.

Settings adapter owns schema, defaults, locations, precedence, parsing, migration, reload semantics, and provenance. Use host-native structured configuration or a real parser and serializer already available in project. Commands, event handlers, workers, and coordinator consume validated effective settings rather than reparsing files independently.

When settings are writable, validate proposed values before same-directory atomic replacement and protect against concurrent updates. Use secret store or protected environment for credentials. See [settings.md](references/settings.md).

## Concurrency and Delegation

Default to one worker per independent item when the runtime provides bounded concurrency and resumable progress. This preserves item-level status and avoids losing an entire batch on failure.

Batch only when one of these is true:

- Setup cost dominates item work.
- An external API imposes bulk or rate-limit constraints.
- Items require shared context to produce a correct result.
- The runtime has no concurrency control and the coordinator must impose one.

Set concurrency in runtime configuration. Never encode a universal batch size such as 10–20 items.

## Setup and Pre-flight

Separate environment mutation from readiness observation. Setup must be an explicit, idempotent entrypoint that plans and records installations, initialization, registration, or migration. Never run setup merely because the skill activated.

For agent-skill installation, use `npx skills`: discover with `add <source> --list`, install exact skill and agent selections, make project/global and copy/link choices explicit, and verify in the same scope. Use `--agent '*'` when installation must cover every agent supported by the current CLI. Never hardcode agent directories or claim this installs arbitrary system prerequisites.

Before creating mutable run state or dispatching work, derive route-specific requirements and produce a structured pre-flight report. Check only prerequisites needed by the selected invocation. Classify findings as blocking, approval-requiring, or warnings, and include concrete remediation without exposing secrets.

Cache expensive observations only with environment, input, settings, capability-version, and expiry keys. Re-run pre-flight after setup. Revalidate volatile credentials, permissions, locks, target identity, and destructive scope immediately before use; pre-flight never replaces an action-local safety gate. See [setup.md](workflows/setup.md).

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
3. Expose one thin entry command with explicit validated inputs.
4. Keep `SKILL.md` as adapter telling agent when and how to invoke script.

Use prose-only sequencing only for short, low-risk workflows that do not need resume, concurrency, retry, or partial-failure handling.

## Design Workflow

Follow [design.md](workflows/design.md) when creating or refactoring a workflow skill.

When reviewing upstream sources or refreshing absorbed guidance, use [UPSTREAM.md](UPSTREAM.md) as baseline and changelog registry.

## Review Questions

- Does executable code own ordering and branching?
- Can interrupted work resume from durable state?
- Are retries bounded and safe?
- Is concurrency controlled by runtime rather than arbitrary prose batching?
- Are destructive actions gated immediately before execution?
- Do checks call existing validators instead of duplicating them?
- Are runtime-specific tool names isolated to runtime adapters?
- Does core skill route detailed knowledge and repeated logic without duplication?
- Are event handlers thin, independent, timeout-bounded, and safe under concurrent execution?
- Does external-tool adapter validate schemas, authentication, permissions, and partial failures?
- Does each delegated worker own one bounded task with structured input, output, and failure status?
- Does coordinator retain global phases, retries, progress, approvals, and durable state?
- Does command entrypoint only validate invocation and call coordinator?
- Are settings typed, validated, precedence-defined, and separate from mutable workflow state?
- Does one adapter own settings discovery, parsing, migration, reload, and provenance?
- Are arguments and paths validated before use without raw shell interpolation?
- Is setup explicit, idempotent, version-aware, and separate from normal activation?
- Does skill installation use `npx skills`, explicit source/skill/agent/scope/mode, discovery before mutation, and same-scope verification without hardcoded agent paths?
- Does route-specific pre-flight run before mutable state or work dispatch and return actionable blockers?
- Are volatile permissions, target identity, locks, and destructive scope revalidated at point of use?
- Could exact command syntax be deleted in favor of host documentation?
- Could unused scaffolding, duplicated prose, or host syntax be deleted?
