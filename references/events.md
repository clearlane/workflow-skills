# Runtime-Neutral Event Hooks

Use event hooks as thin adapters around observable workflow boundaries.

## When to Add Hook

Add hook when behavior must occur at host boundary regardless of normal workflow route:

- Guard proposed action before side effect.
- React to completed action result.
- Supply context when session or request begins.
- Preserve durable facts before context reduction or shutdown.
- Enforce handoff contract when main flow or worker finishes.
- Emit bounded audit, notification, or external signal.

Keep ordinary ordered work in coordinator. Do not use hook as hidden phase system.

## Boundary Classes

| Boundary | Typical use |
|---|---|
| Before action | Validate, deny, ask, or normalize proposed input |
| After action | Inspect result, run focused check, record artifact, emit feedback |
| User input | Add applicable context or reject invalid request at trust boundary |
| Worker or workflow completion | Check declared artifacts and terminal status |
| Session start or end | Initialize or clean durable runtime state |
| Before context reduction | Persist critical observable facts |
| Runtime notification | Log or forward bounded signal |

Adapter maps host event names to these classes.

## Execution Mode

- **Deterministic handler**: Use for schemas, path rules, permissions, exact policy, file operations, fast checks, and external commands.
- **Model-evaluated handler**: Use only for bounded semantic judgment where deterministic rule is unavailable.
- **Layered handler**: Run deterministic prefilter first; ask model only about remaining ambiguity.

Never let model judgment replace exact approval, credential policy, path containment, or data-loss prevention. Define safe fallback for timeout or malformed result.

## Handler Contract

Define:

- Boundary class and selection matcher.
- Typed input schema and untrusted fields.
- Owned scope and allowed side effects.
- Execution mode, timeout, and cancellation behavior.
- Normalized outcome: `continue`, `deny`, `ask`, `modify`, `message`, or `fail`.
- Structured modification schema when handler may change input.
- Error channel, retry policy, and observability fields.

Host adapter owns registration shape, event names, match syntax, transport envelope, exit protocol, and result serialization.

## Payload Envelope

Telling a handler to treat its input as untrusted is incomplete without saying
what it validates against. When the host imposes no event shape, default to the
CloudEvents 1.0 specification rather than inventing an envelope per skill.

It supplies the three things this guidance already assumes but never named. A
required identifier and source give the deduplication key that idempotent
redelivery needs, so a handler can recognize a repeat instead of re-running its
effect. A reverse-DNS type gives a stable taxonomy, so matchers select on a
declared identity rather than a string that drifts. A declared content type
tells the handler which parser to use before it reads any untrusted field.

A host-native event shape wins where one exists. Map it to the envelope at the
adapter, the same boundary that already owns registration and transport, and
keep the mapping out of core guidance.


## Coordinator Ownership

Hook may validate, normalize, signal, or record boundary fact. Coordinator still owns:

- Route and phase order.
- Retry, rollback, resume, and aggregate progress.
- Approval state and destructive execution.
- Cross-item dependencies and cancellation.

If hook needs multi-step recovery, invoke coordinator entrypoint with structured parameters instead of embedding workflow in handler.

## Safety and Input Handling

- Treat event payload, paths, commands, outputs, and user content as untrusted.
- Validate required fields and types before use.
- Resolve paths against allowed roots and account for symlinks.
- Pass arguments as structured values; never concatenate raw shell text.
- Redact secrets from messages, logs, caches, and external telemetry.
- Bound external calls by timeout and explicit failure policy.
- Preserve exact proposed mutation for approval when handler guards side effect.
- Fail closed only for explicitly critical invariant; otherwise return actionable failure without corrupting workflow state.

## State, Concurrency, and Activation

Assume matching handlers may run concurrently and in unspecified order.

- Keep handlers independent unless coordinator provides explicit dependency.
- Use stable workflow, session, item, or action identifiers; never shell process ID alone.
- Write state atomically and define ownership or locking for shared artifacts.
- Make retries idempotent or guard non-idempotent effects.
- Key caches by input digest, policy version, scope, and environment; set bounded freshness.
- Read conditional activation from validated project or runtime configuration with safe default.

Registration changes may require host reload. Runtime configuration read by existing handler should take effect according to adapter contract.

## Latency and External Systems

Keep hot-path handlers short. Minimize I/O, cache expensive deterministic checks safely, and run independent work concurrently only when resources and side effects do not conflict.

For scanners, metrics, databases, or notifications:

- Validate destination and authentication.
- Escape or parameterize payloads.
- Define redaction, timeout, retry, idempotency, and rate-limit behavior.
- Decide whether failure blocks action, records warning, or queues later work.

## Lifecycle and Debugging

Adapter documents registration load, reload, startup validation, active-handler inspection, logs, and direct local execution. Core guidance makes no universal hot-reload claim.

Persist only observable input, normalized outcome, duration, artifact identifiers, and errors. Do not persist hidden reasoning.

## Checks

- Registration passes current host schema validator.
- Selection matches intended positive and negative boundaries.
- Missing, malformed, traversal-like, and secret-bearing inputs fail safely.
- Deterministic handlers return valid normalized outcomes within timeout.
- Model-evaluated handlers have bounded criteria and safe fallback.
- Concurrent handlers do not race on shared state or external effects.
- Cross-boundary state survives retry and cleanup under stable identity.
- Destructive action requires exact approval and remains unexecuted on denial.
- External integration redacts secrets and handles timeout or rate limit.
- Coordinator retains global workflow ownership.
