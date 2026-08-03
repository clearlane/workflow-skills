# Runtime-Neutral Delegated Workers

Use delegated workers for bounded autonomous tasks inside coordinator-owned workflow.

## Selection

| Need | Use |
|---|---|
| Small synchronous task needing current context | Handle directly |
| Independent task with explicit input and checkable output | Delegated worker |
| Same operation across independent items | Coordinator pipeline with one worker per item |
| Explicit reusable user invocation | Command entrypoint adapter |
| Ordering, retries, resume, approval, or shared progress | Coordinator |

Do not delegate only to make prompt longer, create persona, or hide unclear ownership.

## Ownership Boundary

Coordinator owns:

- Route, phase order, dependencies, concurrency, retry bounds, and cancellation.
- Durable state, checkpoints, approvals, rollback, and aggregate progress.
- Input partitioning, worker selection, result collection, and final handoff.

Worker owns:

- One bounded task over assigned scope.
- Local reasoning and tool use permitted by contract.
- Structured artifact, evidence, status, and failure details.

Worker may perform local steps. It must not create second global workflow, infer approval, mutate outside owned scope, or retain progress only in conversation.

## Worker Contract

Define minimum sufficient fields:

- **Identity**: Stable collision-resistant name and narrow purpose.
- **Selection**: Positive, implicit, proactive, and negative conditions.
- **Inputs**: Structured values, paths, artifacts, assumptions, and trust boundaries.
- **Ownership**: Exact files, items, decisions, or domain slice worker controls.
- **Context**: Applicable project instructions and local conventions.
- **Capabilities**: Required read, write, execution, network, or external-effect access.
- **Method constraints**: Required criteria and forbidden behavior, not copied coordinator phases.
- **Output**: Artifact or schema, evidence, status, and next action.
- **Failure policy**: Retryable, partial, blocked, terminal, and cancellation behavior.

Prefer contract over persona. Add domain role only when it changes decisions or quality criteria.

## Writing a Contract From a Description

A worker is usually asked for in one line. Turning that into a contract is itself a bounded task:

- Extract the intent including what the description implies but does not say, then narrow it. A worker for "review the API" that reviews one route's contract is bounded; one that reviews the API is not. Narrowing is the default and does not need to be asked about, because a scope stated back concretely is easier to widen than an unbounded one is to finish.
- Write selection conditions as situations that trigger the worker, not as keywords. A condition someone can match against a real request is testable; a keyword list is not.
- Structure the instructions as responsibilities, method, quality criteria, and output, so the worker's obligations are separable from the coordinator's ordering.
- Choose the smallest capability set the task needs, and inherit the caller's execution tier rather than pinning one. A pinned tier is a portability claim about a host the worker may never run on.
- Read the project's own agent instructions and carry the local conventions into the contract, so a generated worker matches the repository it lands in.

## Edge Cases

Every contract enumerates what breaks its normal path and states the response. At minimum: ambiguous input, a collision with something that already exists, a subject too large or too small for the method, and a missing prerequisite.

Two responses generalize and belong in every contract that can hit them:

- A warning does not become a failure. An unknown field or an empty directory is reported and the run continues; treating it as fatal makes the worker unusable on real input.
- An unreadable item is reported and skipped, not fatal to the batch. One bad file must not lose the evidence from the other forty.

## Task Shapes

- **Analysis**: Gather scoped evidence, identify patterns or gaps, rank findings, return actionable locations.
- **Generation**: Inspect local conventions, create bounded artifacts, report changed paths and unresolved constraints.
- **Validation**: Apply explicit criteria, return evidence-backed violations and deterministic pass or fail status.

Keep orchestration outside worker. If task needs shared phase state or coordinates other workers, move that logic into coordinator.

## Activation Scenarios

Test selection with scenarios instead of relying on keyword lists:

- Explicit request matching worker purpose.
- Implicit request where task shape clearly matches.
- Proactive use after prerequisite artifact exists.
- Negative case handled directly.
- Overlap case where another worker is better match.
- Boundary case lacking required input or safe ownership.

Runtime may encode scenarios in metadata, tests, examples, or router fixtures. Core contract does not require one syntax.

## Capabilities and Execution Settings

Grant least privilege by effect:

- Read project files or structured context.
- Write only owned files or artifacts.
- Execute only required local checks or commands.
- Use network only when task requires external data.
- Require coordinator gate for destructive, costly, or externally visible effects.

Use host-default execution settings. Override only for concrete capability, latency, cost, isolation, or context need. Record override reason in runtime adapter.

## Runtime Adapter Boundary

Adapter owns:

- Discovery path, metadata fields, namespace, and invocation API.
- Mapping capability classes to host permissions or tools.
- Project-context loading and structured input serialization.
- Execution setting selection, cancellation, timeout, and result transport.
- Host-native metadata validation.

Core worker contract must remain understandable without adapter syntax.

## Results and Failures

Return structured result with:

- Worker and item identifier.
- `completed`, `partial`, `blocked`, `retryable`, `failed`, or `cancelled` status.
- Produced artifact paths or identifiers.
- Evidence and checks run.
- Error category and safe retry guidance.
- Unresolved questions or next action.

Coordinator records result before retrying, rescheduling, rolling back, or continuing.

## Handoff

A generated component goes to the validator that owns its contract before it reaches the user, and the validator is chosen by what was generated rather than by what is convenient. Generation that reports success without that step is reporting that files exist.

The handoff then names, per component: what was created, the situations that will select it, where it lives, how to exercise it, and the exact next validation to run. A summary that stops at the file list leaves the user to discover activation by accident.

## Checks

- Selection scenarios cover positive, negative, overlap, and missing-input cases.
- Worker cannot mutate outside declared ownership.
- Capability set matches actual side effects.
- Host metadata passes current host validator.
- Typical and edge-case tasks produce declared output schema.
- Partial and terminal failures preserve evidence and actionable next step.
- Coordinator receives exact result and retains global state ownership.
- Runtime-specific names and syntax remain confined to adapter package.
