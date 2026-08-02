# Setup and Pre-flight

Use setup and pre-flight as separate executable concerns. Setup changes the environment; pre-flight proves that a specific workflow invocation is ready to run.

For installing agent skills, use the open `skills` CLI through `npx`. Do not invent host-specific skill directories, copy files manually, or assume one agent. `npx skills` owns source resolution, skill discovery, supported-agent paths, scope, lock metadata, and installation mode.

## Inputs

Collect or derive these before constructing an install command:

- `source`: GitHub shorthand, Git/GitLab URL, direct repository subpath, or local path accepted by `npx skills`.
- `skills`: exact discovered skill names, or all skills only when explicitly requested.
- `agents`: explicit supported agent IDs, or `*` when installation should cover every supported agent detected by the CLI.
- `scope`: `project` or `global`; never infer global merely because project detection failed.
- `mode`: `copy` for portable, independent installation or the CLI default link mode for active local development.
- `cliVersion`: a project-pinned version when policy provides one; otherwise the version resolved by `npx`.

Treat source, skill names, agent IDs, scope, and mode as data passed as separate process arguments. Never concatenate untrusted values into shell text.

## Selection

Add setup only when the skill has prerequisites that can be installed, initialized, registered, or migrated. Add pre-flight when missing capabilities, credentials, configuration, permissions, services, disk space, repository state, or destructive scope would otherwise fail after work begins.

Skip a dedicated pre-flight when the coordinator has one cheap, local, side-effect-free operation whose normal input validation already gives an actionable failure.

## Skill Installer Pre-flight

Before installation:

1. Confirm `npx` is executable. When it is absent, return a blocker requesting a Node.js distribution that includes npm/npx; do not guess an operating-system package manager or elevate privileges.
2. Confirm the intended project root for project scope. If no project root is available, ask whether to create/select one or use global scope.
3. Validate the source form and trust boundary. For remote sources, surface the resolved host/repository/ref before approval. Prefer an immutable tag or commit for reproducible automation.
4. Discover before mutating:

   ```text
   npx --yes skills add <source> --list
   ```

5. Require the requested skill to appear in discovery. Do not silently substitute a similarly named skill.
6. Obtain supported agent IDs from current CLI output or discovery. Never maintain a hard-coded agent-directory map in the workflow.
7. Preview exact source, skills, agents, scope, and copy/link mode. Installing remote code, replacing an existing installation, changing global scope, or targeting all agents may require approval under host policy.

`--yes` approves npm's execution/download prompt and the skills CLI's interactive confirmation; it is not user authorization for an untrusted source or global mutation. Secure workflow approval must happen before invoking the command.

## Canonical Install

Build one argument vector from validated inputs:

```text
npx --yes skills add <source> \
  --skill <exact-skill> \
  --agent <agent-or-*> \
  --yes \
  [--global] \
  [--copy]
```

Rules:

- Omit `--global` for project scope; include it only for explicit user-level installation.
- Use `--agent '*'` for environment-agnostic installation across every agent supported by the installed CLI. Use explicit IDs when the user wants a bounded target.
- Use `--copy` for containers, CI, archives, cross-filesystem targets, immutable deployments, or when the source may disappear. Prefer the CLI's default linking behavior for a local skill repository under active development so edits are immediately visible.
- Use repeated values or the current CLI-supported list syntax for multiple skills/agents; do not assume comma parsing.
- Use `--all` only when the user explicitly requests every discovered skill for every supported agent. It is not a convenience substitute for validated selections.
- In automation, optionally pin the CLI (`npx --yes skills@<version> ...`) according to project policy. Do not blindly pin a stale version in runtime-neutral guidance.
- Invoke without a shell when the runtime offers an argument-vector process API. If only a shell exists, quote every validated argument using that shell's native safe mechanism; never interpolate raw input.

Supported source forms include:

```text
owner/repository
https://github.com/owner/repository
https://github.com/owner/repository/tree/<ref>/<path>
https://gitlab.com/group/repository
ssh-or-https-git-url
./local-path
```

Do not claim `npx skills` installs arbitrary operating-system packages, language runtimes, credentials, or services. It installs agent skills. Handle other prerequisites with existing environment-native tooling or return an actionable blocker; never guess a package manager.

## Verification and Repair

Installation success requires more than exit code zero:

1. Run the machine-readable listing in the same project context and scope:

   ```text
   npx --yes skills list --json [--global] [--agent <agent>]
   ```

2. Parse JSON rather than terminal text. Confirm each requested skill is listed for each explicit agent; for `--agent '*'`, compare the successful install destinations reported by the CLI with the current supported-agent set and report any per-agent omission.
3. Confirm installed `SKILL.md` is readable through each destination reported by the CLI. Validate its frontmatter name equals the exact requested skill name.
4. For linked local development installs, resolve the link and verify it points to the intended source. For copied installs, verify the installed copy is independent and warn that source edits require update/reinstall.
5. Start a fresh agent session when the host indexes skills only at startup.
6. If verification fails, report observed scope, agent, and installation mode. Retry only a transient source/network failure; do not switch scope, agent, source, or copy/link mode as an implicit repair.

Re-running the same validated command must converge without creating duplicate installations. For upgrades, use `npx --yes skills update` with `--project` or `--global` matching the install scope rather than deleting host directories manually. Use `npx --yes skills remove` with matching scope and agent selection for removal, then verify afterward.

Treat partial all-agent installation as partial failure even when the process exits successfully. Preserve successful destinations, report failed or unsupported agents individually, and retry only those the current CLI can target. Environment-agnostic means adapting through current CLI discovery—not promising that unknown hosts, absent runtimes, denied permissions, offline sources, or unsupported agents can always be installed.

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

- For agent-skill installation, prefer `npx skills`; let its current adapter select supported agent locations instead of writing those locations directly.
- Prefer repository-native or host-native installers and initializers for non-skill prerequisites.
- Pin or constrain versions according to project policy; verify installed version after setup.
- Use atomic writes and backups for configuration migration.
- Keep credentials in a secret store or protected environment, never setup logs or ordinary settings.
- Do not broaden permissions to make a check pass.
- Record setup changes separately from workflow run state.
- Re-run pre-flight from fresh observations after setup or repair.

## Focused Checks

Exercise:

- Already-ready environment: setup is a no-op and pre-flight is ready.
- `npx` missing: setup blocks without guessing OS, package manager, privilege escalation, or install location.
- Project and global scope, explicit agent and `*`, local and remote source, copy and default link mode.
- Discovery does not contain requested skill: setup blocks without fuzzy substitution.
- CLI succeeds but requested skill is absent from same-scope listing or unreadable at destination.
- Repeated identical install converges; update and remove preserve explicit scope.
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
