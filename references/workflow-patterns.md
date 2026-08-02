# Dynamic Workflow Patterns

Use these patterns as coordinator shapes. Examples are pseudocode; map them to runtime-native APIs or a small script in an existing project language.

## 1. Routing

Use when one request selects one independent workflow.

```text
route = classify(input)
handlers[route](input)
```

Keep routing data separate from handler implementation. Reject unknown routes or choose an explicit safe fallback. Do not ask model to read a workflow file and "follow it exactly"; dispatch executable handler instead.

Persist route when later resume must continue same path.

## 2. Parallel Item Pipeline

Use when same operation applies independently to many items.

```text
results = pipeline(items, processItem, concurrency = runtimeLimit)
```

Track status per item: pending, running, completed, or failed. Persist result after each item. Retry only failed retryable items.

Prefer one worker per item when runtime bounds concurrency. Batch only for shared setup, bulk APIs, rate limits, or runtimes without concurrency controls.

Failure policy options:

- **Fail fast** — stop when any item failure invalidates whole result.
- **Collect failures** — continue independent items, then return completed and failed sets.
- **Threshold** — stop after failure rate or count exceeds explicit limit.

## 3. Ordered Phases

Use when stages run once in fixed order and each stage consumes prior output.

```text
context = phase("discover", discover, input)
context = phase("plan", plan, context)
context = phase("apply", apply, context)
```

Let script order define sequence. Each phase returns an artifact or state value consumed by next phase. Persist only outputs needed for resume or audit.

Do not duplicate sequence as mandatory prose entry/exit criteria. Document a phase contract only when inputs, outputs, or invariants are not obvious from code.

## 4. Dependency Graph

Use when tasks have non-linear dependencies.

```text
state = {
  inventory: pending,
  analysis: blockedBy(inventory),
  patch: blockedBy(analysis),
  report: blockedBy(analysis, patch)
}
runReadyTasks(state)
```

Represent dependencies in data or code. Let runtime progress view report state when available. Persist completed task IDs and artifacts so restart does not rebuild graph from chat history.

Detect cycles before execution. Run independent ready tasks concurrently.

## 5. Bounded Feedback Loop

Use when result improves iteratively until measurable condition holds.

```text
attempt = 0
while not done(result) and attempt < maxAttempts:
    result = improve(result)
    attempt += 1
```

Every loop needs:

- Measurable termination condition.
- Hard iteration or time bound.
- Persisted best-known result when work is expensive.
- Failure result when bound expires.

Never use "repeat until good" without objective condition and bound.

## 6. Safety Gate

Use around destructive, irreversible, costly, or externally visible actions.

```text
proposal = calculateAction(input)
approval = requestApproval(proposal)
if approval.matches(proposal):
    result = execute(proposal)
    record(result)
```

Approval must include exact scope. Recompute or request approval again when proposal changes. Never infer approval from earlier discussion.

## 7. Command Entrypoint Adapter

Use when workflow needs explicit, reusable invocation through host command surface.

```text
request = parseInvocation(rawInput)
validated = validate(request)
context = loadRequiredContext(validated)
result = coordinator(validated, context)
render(result)
```

Adapter owns:

- Discovery metadata and concise invocation help.
- Argument parsing, defaults, normalization, and validation.
- Required resource and prerequisite checks.
- Host-native context acquisition and interaction.
- Coordinator invocation and status rendering.

Coordinator owns:

- Routing, phase order, concurrency, retries, loops, checkpoints, resume, and rollback.
- Durable workflow state and artifact production.
- Exact approval gates and side-effect execution.

Do not encode workflow transitions in command prose. Do not splice raw arguments into shell commands or paths. Pass validated values through explicit coordinator parameters.

See [command-entrypoints.md](command-entrypoints.md) for adapter contract and focused checks.

## 8. Delegated Worker Adapter

Use when coordinator assigns one bounded task through host delegation runtime.

```text
contract = defineWorker(task, ownedScope, capabilities, outputSchema)
context = loadApplicableContext(contract)
result = delegate(contract, context)
record(result)
```

Worker owns assigned task only. Coordinator owns selection, dependencies, concurrency, retries, durable state, approvals, rollback, and result aggregation.

Use host-default execution settings unless task has concrete capability, latency, cost, isolation, or context requirement. Validate host metadata in adapter and worker behavior through positive, negative, overlap, and failure scenarios.

See [delegated-workers.md](delegated-workers.md) for contract and focused checks.

## 9. Event Hook Adapter

Use when workflow must guard or react at host lifecycle boundary.

```text
event = parseHostEvent(rawEvent)
validated = validateEvent(event)
outcome = handler(validated)
return normalize(outcome)
```

Handler owns one boundary decision or reaction. Coordinator owns global ordering, state, retry, approval, rollback, and resume. Assume matching handlers may run independently and concurrently.

See [event-hooks.md](event-hooks.md) for boundary classes, safety, state, and checks.

## 10. External Tool Adapter

Use when coordinator calls MCP server or external service.

```text
capability = discoverRequiredCapability(adapter)
request = validateRequest(input, capability.schema)
result = adapter.call(capability, request)
record(normalize(result))
```

Adapter owns protocol, authentication, connection, schema discovery, permission mapping, and result normalization. Coordinator owns call graph, batching, retry, partial success, approval, and durable progress.

See [external-tools.md](external-tools.md) for integration contract and focused checks.

## 11. Skill Settings Adapter

Use when workflow behavior needs stable user or project preferences.

```text
documents = discoverAndValidateSettings()
effective, provenance = resolveSettings(defaults, documents, invocation)
result = coordinator(input, freeze(effective))
recordSettingsDigest(result.run, effective)
```

Settings adapter owns schema, locations, parsing, migration, precedence, reload, and provenance. Coordinator owns mutable progress, retries, approvals, artifacts, and resume. Do not store both in same contract.

Commands, event handlers, workers, and external-tool adapters consume same validated effective snapshot. Secrets arrive through separate protected boundary. See [skill-settings.md](skill-settings.md) for full contract and checks.

## 12. Setup and Pre-flight

Use setup to provision or migrate prerequisites and pre-flight to observe readiness for one validated invocation.

```text
request = validateInvocation(rawInput)
settings = resolveSettings(request)
requirements = deriveRequirements(request, settings)
report = preflight(request, settings, requirements)
requireReady(report)
result = coordinator(request, settings, report)
```

Keep setup explicit, idempotent, version-aware, and separate from normal activation. Run route-specific pre-flight before mutable run state or worker dispatch. Re-run pre-flight after setup, and revalidate volatile conditions at point of use.

See [setup-preflight.md](../workflows/setup-preflight.md) for contracts, check classes, remediation, freshness, and focused checks.

## Combining Patterns

Compose patterns in code, not copied prose. Common combinations:

- Route to distinct ordered workflows.
- Ordered discovery phase followed by parallel item pipeline.
- Pipeline where each item uses bounded feedback loop.
- Dependency graph with safety gate before mutation tasks.
- Thin command entrypoint invoking any coordinator shape.
- Pipeline delegating one bounded worker per independent item.
- Event hook guarding safety gate or invoking coordinator entrypoint.
- Pipeline or dependency graph issuing typed external-tool calls.
- Command entrypoint applying validated invocation overrides before coordinator start.
- Explicit setup entrypoint followed by fresh route-specific pre-flight.

Keep nesting shallow. If coordinator becomes difficult to inspect, split handlers or phases into named functions while preserving one state owner.

## State and Resume

Persist only durable facts:

- Selected route.
- Completed item or task IDs.
- Produced artifact paths or identifiers.
- Retry counts and terminal failures.
- Approved destructive proposal hash or equivalent exact scope.

Do not persist model chain-of-thought. Persist inputs, outputs, decisions, and observable state.

Record effective settings digest and provenance when configuration affects reproducibility. Keep settings document outside mutable workflow-state schema.

## Runtime Adapter Boundary

Keep runtime-specific details at coordinator edge:

- Progress UI or workflow dashboard calls.
- Agent/subagent creation API.
- Approval prompt API.
- Tool allowlist syntax.
- Cancellation and resume hooks.
- Settings locations, formats, precedence, reload, and migration semantics.

Core workflow logic should remain understandable without one vendor's terminology.
