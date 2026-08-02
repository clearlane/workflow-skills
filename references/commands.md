# Runtime-Neutral Command Entrypoints

Use command as thin adapter around executable workflow coordinator. Host owns exact registration, metadata, invocation, context, and interaction syntax.

## When to Add Command

Add explicit command entrypoint when workflow needs at least one:

- Repeatable manual invocation.
- Discoverable name and concise help.
- Declared arguments or options.
- Manual-only control over costly, destructive, or externally visible action.
- Stable bridge from host command surface to coordinator.

Do not add command when ordinary skill activation already supplies all required inputs and no explicit invocation contract exists.

## Adapter Contract

Command adapter performs one bounded job:

```text
input = parse(rawInvocation)
validated = validate(input)
context = acquire(validated)
result = runCoordinator(validated, context)
render(result)
```

Define:

- **Purpose**: One workflow invocation, not general prompt collection.
- **Inputs**: Required, optional, defaulted, mutually exclusive, and repeatable values.
- **Outputs**: Status, artifact paths, identifiers, and next action.
- **Prerequisites**: Runtime capabilities, files, credentials, services, and executables.
- **Side effects**: Read, write, network, destructive, costly, and externally visible operations.
- **Invocation policy**: Automatic activation allowed or explicit user invocation required.

Write adapter body as instructions to agent or executable bridge, not marketing text describing future behavior.

## Input Boundary

Treat raw invocation as untrusted.

- Reject missing required values.
- Reject unknown options unless passthrough is explicit and safe.
- Normalize only documented aliases and defaults.
- Validate enums, identifiers, numeric ranges, and mutually exclusive options.
- Resolve paths, reject traversal outside allowed roots, and check expected file type.
- Keep secrets out of logs, state, and rendered status.
- Pass values as structured parameters. Never concatenate raw input into shell text.

Use command arguments for values user already knows. Ask questions only for unresolved choices, conditional details, or exact approval.

## Context and Runtime Capabilities

Acquire minimum context coordinator needs:

- Referenced files or selected resources.
- Repository state and configuration.
- Existing durable workflow state.
- Host capabilities available for progress, delegation, approval, and cancellation.

Keep exact context-loading syntax and resource-root lookup in runtime adapter. Core workflow accepts values and artifacts, not host interpolation expressions.

Declare tool allowlist only when host supports it. Grant least capability needed by adapter; coordinator and workers should receive their own bounded capabilities.

Let host own command discovery and namespacing. Choose collision-resistant name, concise description, and accurate argument help without encoding one directory convention or metadata schema in reusable guidance.

## Interaction and Approval

Do not turn command into questionnaire.

- Accept known values as arguments.
- Ask one decision at point it becomes necessary.
- Offer choices only when they are mutually exclusive and meaningful.
- Show detected defaults before using them when consequence matters.
- Keep destructive or external actions behind coordinator approval gate bound to exact proposal.
- Require explicit invocation when command itself exposes sensitive side effects.

Command may request input, but coordinator state records resulting durable decision when resume matters.

## Failure Behavior

Translate failures without taking control from coordinator:

- Invalid invocation: show rejected value and expected contract.
- Missing prerequisite: name missing capability and corrective action.
- Context failure: identify unreadable or invalid resource without leaking secrets.
- Coordinator failure: show phase or item status, persisted artifacts, and resume command.
- Approval mismatch: stop and request approval for changed proposal.
- Unsupported host capability: fail clearly or choose documented safe fallback.

Do not invent retry, rollback, or resume behavior in adapter. Render coordinator result.

## Focused Checks

Test adapter boundary, not prose formatting:

- Command is discoverable with correct description and argument help.
- Missing, malformed, unknown, and conflicting inputs fail before coordinator runs.
- Defaults and aliases normalize predictably.
- Spaces, quotes, metacharacters, and traversal-like paths remain data, not executable text.
- Missing files, permissions, credentials, and runtime capabilities produce actionable errors.
- Coordinator receives exact validated parameters and returns status unchanged.
- Nonzero coordinator result preserves artifacts and resume information.
- Sensitive side effects require explicit invocation and exact approval.

Use host-specific syntax tests in runtime adapter package. Keep core workflow tests runtime-neutral.
