# Setup and Pre-flight Workflows

Use setup and pre-flight as separate executable concerns. Setup changes the environment; pre-flight proves that a specific workflow invocation is ready to run.

## Selection

Add setup only when the skill has prerequisites that can be installed, initialized, registered, or migrated. Add pre-flight when missing capabilities, credentials, configuration, permissions, services, disk space, repository state, or destructive scope would otherwise fail after work begins.

Skip a dedicated pre-flight when the coordinator has one cheap, local, side-effect-free operation whose normal input validation already gives an actionable failure.

## Contracts

### Setup

Setup accepts a target scope and desired version or configuration. It returns:

- `ready`: requirements already satisfied or successfully provisioned.
- `changed`: exact resources created, upgraded, registered, or repaired.
- `blocked`: requirements the workflow cannot provision automatically.
- `warnings`: non-blocking compatibility or policy concerns.
- `rollback`: how to reverse setup changes when reversal is supported.

Setup must be explicit, idempotent, version-aware, and safe to rerun. Never install packages, alter credentials, migrate state, or modify host registration merely because a skill activated. Preview material changes and request approval when they are costly, privileged, destructive, or externally visible.

### Pre-flight

Pre-flight accepts the validated invocation, effective settings, target environment, and required capability profile. It returns a machine-consumable readiness report:

```text
{
  status: ready | blocked | approval_required,
  checks: [{id, status, observed, required, remediation}],
  invocationDigest,
  settingsDigest,
  environmentIdentity,
  expiresAt
}
```

Use stable check IDs and normalized statuses. Redact secrets; report presence, source, scope, tenant, or expiry rather than values.

## Coordinator Shape

```text
request = validateInvocation(rawInput)
settings = resolveSettings(request)
requirements = deriveRequirements(request, settings)
report = preflight(request, settings, requirements)

if report.status == blocked:
    return renderRemediation(report)
if report.status == approval_required:
    approval = requestApproval(report.proposal)
    requireMatchingApproval(approval, report.proposal)

run = startOrResume(request, settings, report)
return coordinator(run)
```

Do not create mutable run state, acquire long-lived locks, dispatch workers, or perform domain mutations before a blocking pre-flight succeeds. A short-lived readiness report is not workflow progress state.

If setup is required:

```text
report = preflight(...)
if report.hasProvisionableBlocks:
    plan = planSetup(report)
    approval = requestApproval(plan) when plan.requiresApproval
    setupResult = applySetup(plan, approval)
    report = preflight(...)  // fresh observation, never assume setup worked
require(report.status == ready)
```

Keep setup and normal execution as separate coordinator entrypoints or explicit modes. Never hide setup as a retry side effect.

## Check Classes

Derive checks from the selected route instead of running every possible integration check:

1. **Invocation** — required inputs, path containment, target identity, incompatible flags.
2. **Runtime** — executable and runtime versions, host features, coordinator/state support.
3. **Project** — repository root, expected files, clean/dirty policy, current branch, native commands.
4. **Configuration** — schema version, effective values, provenance, unsafe paths, migration need.
5. **Credentials and permissions** — secret presence, expiry, tenant/account identity, least privilege.
6. **External dependencies** — service health, capability/schema discovery, rate-limit headroom.
7. **Resources** — writable locations, disk/memory quota, concurrency slots, required ports or locks.
8. **Safety** — exact mutation scope, backup or rollback prerequisite, approval requirement.
9. **Resume compatibility** — existing state identity, coordinator/schema version, input and settings digests.

Classify each result as blocking, approval-requiring, or warning. A warning must not be a disguised requirement.

## Freshness and Revalidation

Cache only expensive, side-effect-free observations. Key cached reports by environment identity, route, relevant input digest, settings digest, and capability/schema version. Give them a bounded expiry.

Revalidate immediately before an irreversible action when readiness can change between pre-flight and use, including credentials, permissions, target identity, lock ownership, destructive proposal, and external service capability. Pre-flight does not replace an action-local safety gate.

## Concurrency and Failure

Run independent read-only checks concurrently when the runtime bounds concurrency. Serialize checks that contend for the same service, token, lock, or rate limit.

- Bound every network check with timeout and cancellation.
- Retry only transient observations and cap retries.
- Distinguish unavailable from unauthorized, incompatible, and malformed.
- Return all independent blockers when doing so is cheap; fail fast when continuing is unsafe or expensive.
- Give each blocker one concrete remediation and a command or adapter entrypoint only when verified for the current host.

## Setup Safety

- Prefer repository-native or host-native installers and initializers.
- Pin or constrain versions according to project policy; verify installed version after setup.
- Use atomic writes and backups for configuration migration.
- Keep credentials in a secret store or protected environment, never setup logs or ordinary settings.
- Do not broaden permissions to make a check pass.
- Record setup changes separately from workflow run state.
- Re-run pre-flight from fresh observations after setup or repair.

## Focused Checks

Exercise:

- Already-ready environment: setup is a no-op and pre-flight is ready.
- Missing provisionable prerequisite: setup plan is exact, approved if needed, and idempotent.
- Missing non-provisionable prerequisite: blocker names owner and remediation.
- Wrong runtime or schema version: incompatible rather than generic failure.
- Missing, expired, wrong-tenant, and under-scoped credentials without secret disclosure.
- Service timeout, rate limit, and capability mismatch.
- Dirty repository or unsafe target path according to declared policy.
- Stale cached report and environment change after pre-flight.
- Resume state created by incompatible inputs, settings, or coordinator version.
- Setup reports success but fresh pre-flight still fails.
- Destructive proposal changes after pre-flight and requires new approval.
