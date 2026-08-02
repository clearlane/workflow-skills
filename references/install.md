# Agent Skill Installation

Install agent skills through the open `skills` CLI invoked with `npx`. Do not invent host-specific skill directories, copy files manually, or assume one agent. The CLI owns source resolution, skill discovery, supported-agent paths, scope, lock metadata, and installation mode.

This reference covers installing skills only. For general prerequisite provisioning and readiness reporting, follow [setup.md](../workflows/setup.md).

## Inputs

Collect or derive these before constructing an install command:

- `source`: GitHub shorthand, Git/GitLab URL, direct repository subpath, or local path accepted by the CLI.
- `skills`: exact discovered skill names, or all skills only when explicitly requested.
- `agents`: explicit supported agent IDs, or `*` when installation should cover every supported agent detected by the CLI.
- `scope`: `project` or `global`; never infer global merely because project detection failed.
- `mode`: `copy` for portable, independent installation or the CLI default link mode for active local development.
- `cliVersion`: a project-pinned version when policy provides one; otherwise the version resolved by `npx`.

Treat source, skill names, agent IDs, scope, and mode as data passed as separate process arguments.

## Pre-flight

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

`--yes` approves npm's execution/download prompt and the CLI's interactive confirmation; it is not user authorization for an untrusted source or global mutation. Workflow approval must happen before invoking the command.

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
- In automation, optionally pin the CLI according to project policy. Do not blindly pin a stale version in runtime-neutral guidance.
- Invoke without a shell when the runtime offers an argument-vector process API. If only a shell exists, quote every validated argument using that shell's native safe mechanism.

Supported source forms include:

```text
owner/repository
https://github.com/owner/repository
https://github.com/owner/repository/tree/<ref>/<path>
https://gitlab.com/group/repository
ssh-or-https-git-url
./local-path
```

Do not claim this CLI installs arbitrary operating-system packages, language runtimes, credentials, or services. It installs agent skills. Handle other prerequisites with existing environment-native tooling or return an actionable blocker; never guess a package manager.

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

Re-running the same validated command must converge without creating duplicate installations. For upgrades, use the CLI's update command with the scope flag matching the install scope rather than deleting host directories manually. Use its remove command with matching scope and agent selection for removal, then verify afterward.

Treat partial all-agent installation as partial failure even when the process exits successfully. Preserve successful destinations, report failed or unsupported agents individually, and retry only those the current CLI can target. Environment-agnostic means adapting through current CLI discovery, not promising that unknown hosts, absent runtimes, denied permissions, offline sources, or unsupported agents can always be installed.

## Checks

- `npx` missing: setup blocks without guessing OS, package manager, privilege escalation, or install location.
- Project and global scope, explicit agent and `*`, local and remote source, copy and default link mode.
- Discovery does not contain requested skill: setup blocks without fuzzy substitution.
- CLI succeeds but requested skill is absent from same-scope listing or unreadable at destination.
- Repeated identical install converges; update and remove preserve explicit scope.
