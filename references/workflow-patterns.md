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

## Combining Patterns

Compose patterns in code, not copied prose. Common combinations:

- Route to distinct ordered workflows.
- Ordered discovery phase followed by parallel item pipeline.
- Pipeline where each item uses bounded feedback loop.
- Dependency graph with safety gate before mutation tasks.

Keep nesting shallow. If coordinator becomes difficult to inspect, split handlers or phases into named functions while preserving one state owner.

## State and Resume

Persist only durable facts:

- Selected route.
- Completed item or task IDs.
- Produced artifact paths or identifiers.
- Retry counts and terminal failures.
- Approved destructive proposal hash or equivalent exact scope.

Do not persist model chain-of-thought. Persist inputs, outputs, decisions, and observable state.

## Runtime Adapter Boundary

Keep runtime-specific details at coordinator edge:

- Progress UI or workflow dashboard calls.
- Agent/subagent creation API.
- Approval prompt API.
- Tool allowlist syntax.
- Cancellation and resume hooks.

Core workflow logic should remain understandable without one vendor's terminology.
