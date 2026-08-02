# Upstream Absorption Registry

Track absorbed sources here so later upstream changes can be reviewed for useful capabilities without reintroducing vendor coupling or duplicated workflow control.

## Source Baselines

| Source | Upstream location | Absorbed baseline | Absorbed on | Plan hash |
|---|---|---|---|---|
| Designing Workflow Skills | [`trailofbits/skills`](https://github.com/trailofbits/skills), removed path `plugins/workflow-skill-design/` | Commit [`09dfbd91537b888136c9203dca4ffdee5a595c69`](https://github.com/trailofbits/skills/commit/09dfbd91537b888136c9203dca4ffdee5a595c69) | 2026-08-01 | Initial adaptation; no absorption run |
| Command Development | [`anthropics/claude-code/plugins/plugin-dev/skills/command-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/command-development) | Installed `main` snapshot tree SHA-256 `4020f234432383b30dcfa5a5c4bf4a24ec251759c2d00254699b1b7a24261208` | 2026-08-01 | `5ec5b6fb9ce3ef67059d479ea81219205d44e34a1a9e0c04be4342d067b3acf0` |
| Agent Development | [`anthropics/claude-code/plugins/plugin-dev/skills/agent-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/agent-development) | Installed `main` snapshot tree SHA-256 `844fb26d8bb521f11e1dce254d6f23f8a36da4365e9a0640cb07498d2aa7b72e` | 2026-08-01 | `76b68fffb5e08064aa9467248a61c90140bf14b5a98a7cc058ddb10d061d8bbd` |
| Hook Development | [`anthropics/claude-code/plugins/plugin-dev/skills/hook-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/hook-development) | Installed `main` snapshot tree SHA-256 `9cb13ef507a97d92169d55b0f645a378ebc7aa6373353ff6aa9785037f0d0118` | 2026-08-01 | `a87ac90c76030720444618424c48ae45e2b8dd68b018a22006bfa7fa99ab8b82` |
| MCP Integration | [`anthropics/claude-code/plugins/plugin-dev/skills/mcp-integration`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/mcp-integration) | Installed `main` snapshot tree SHA-256 `03902fea89d355516383adf9f1cd782f064ab75b2bd0f030f8719975feb88d0f` | 2026-08-01 | `a87ac90c76030720444618424c48ae45e2b8dd68b018a22006bfa7fa99ab8b82` |
| Skill Development | [`anthropics/claude-code/plugins/plugin-dev/skills/skill-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/skill-development) | Installed `main` snapshot tree SHA-256 `f3547dd4fc0acee7f502f492a9cb61e743e3247ffd36956be79e9b92a8f265d5` | 2026-08-01 | `a87ac90c76030720444618424c48ae45e2b8dd68b018a22006bfa7fa99ab8b82` |
| Plugin Settings | [`anthropics/claude-code/plugins/plugin-dev/skills/plugin-settings`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/plugin-settings) | Installed `main` snapshot tree SHA-256 `67546a58c6562768b175670b5aed1c2f9a304899167d875959736fc2acd2eae3` | 2026-08-01 | `7817f599855e36a227c7df70b0f1e11361546909bb38513fd17e29120427559b` |

Anthropic baselines above are local skill-tree digests recorded by absorption runs, not upstream commit IDs. Future refreshes should record exact upstream commit SHA when available because `main` is mutable.

## Absorbed Coverage

### Designing Workflow Skills

Absorbed:

- Workflow routing, pipelines, ordered phases, dependency-aware work, feedback loops, and safety gates.
- Skill activation, resource routing, and workflow review criteria.

Reworked or excluded:

- Moved workflow state and transitions from prose into executable coordinators.
- Removed obsolete task tools, fixed batching guidance, mandatory final verification, and runtime-specific syntax.

### Command Development

Absorbed:

- Thin explicit command entrypoints.
- Argument contracts, input and path validation, context acquisition, failure rendering, interaction, and adapter tests.

Reworked or excluded:

- Coordinator owns phases, retries, checkpoints, rollback, approval, and resume.
- Excluded command directories, frontmatter fields, interpolation syntax, model names, marketplace guidance, and raw shell examples.

Canonical destinations:

- `references/commands.md`
- `references/patterns.md`
- `workflows/design.md`

### Agent Development

Absorbed:

- Direct handling versus delegated-worker selection.
- Bounded worker identity, activation, ownership, capabilities, output, failure, and scenario-test contracts.
- Least-privilege execution settings and project-context alignment.

Reworked or excluded:

- Coordinator retains global phases, progress, retries, approvals, and durable state.
- Excluded vendor model names, colors, tool arrays, namespaces, trigger markup, copied templates, fixed prompt lengths, and prose orchestration agents.

Canonical destinations:

- `references/workers.md`
- `references/patterns.md`
- `workflows/design.md`

### Hook Development

Absorbed:

- Event-boundary selection, deterministic versus model-evaluated handlers, structured outcomes, match routing, timeouts, conditional activation, and lifecycle testing.
- Pre-action safety, post-action reactions, completion contracts, cross-event state, concurrency, latency, external signals, and debugging boundaries.

Reworked or excluded:

- Hooks remain thin adapters; coordinator owns workflow state and transitions.
- Excluded vendor event names, config envelopes, environment variables, shell utilities, PID state, regex linters, external-service examples, and prompt-first security enforcement.

Canonical destinations:

- `references/events.md`
- `references/patterns.md`
- `workflows/design.md`

### MCP Integration

Absorbed:

- MCP and external-tool integration contracts.
- Transport selection, portable configuration, authentication, secrets, tenant scope, capability discovery, permissions, lifecycle, error classification, partial success, batching, caching, concurrency, testing, and documentation.

Reworked or excluded:

- Coordinator owns call graph, retries, batching, approval, partial-success state, and resume.
- Excluded exact config filenames, manifest fields, tool prefixes, client lifecycle claims, OAuth storage claims, package managers, SDKs, sample endpoints, and unsafe environment loading.

Canonical destinations:

- `references/tools.md`
- `references/patterns.md`
- `workflows/design.md`

### Skill Development

Absorbed:

- Workflow-skill package contract, concrete-use-case elicitation, reusable-resource planning, progressive disclosure, activation metadata, direct instruction style, resource linking, validation, activation testing, deployment shapes, and iteration from real use.

Reworked or excluded:

- Excluded mandatory third-person descriptions, fixed word counts, fixed directory trees, named CLIs, named review agents, and mandatory ZIP packaging.
- Did not copy duplicated reference material whose source snapshot referenced a missing license file.

Canonical destinations:

- `references/structure.md`
- `workflows/design.md`
- `SKILL.md`

### Plugin Settings

Absorbed:

- Typed optional skill settings, defaults, enabled behavior, project-local configuration, structured fields, and optional freeform context.
- Shared settings consumption by coordinator, commands, event handlers, workers, and external-tool adapters.
- Validation, templates, configuration-driven behavior, lazy loading, caching, atomic updates, security, lifecycle documentation, and error handling.

Reworked or excluded:

- Separated user preferences from mutable workflow progress, retries, approvals, artifacts, worker assignments, and completion state.
- Added user-local and invocation scopes, deterministic precedence, field provenance, schema versioning, migration, concurrency control, conflict detection, stable run snapshots, and rollback.
- Replaced line-oriented YAML parsing and raw text interpolation with host-native structured configuration or real parser and serializer contracts.
- Excluded vendor settings paths, filename suffixes, commands, hooks, agents, metadata fields, hook output schemas, restart claims, shell dependencies, terminal coordination, copied templates, and named examples.
- Moved credentials to secret-store boundary; ignore rules and fixed file modes are not treated as complete security controls.

Canonical destinations:

- `references/settings.md`
- `references/patterns.md`
- `workflows/design.md`
- `SKILL.md`

## Upstream Review Procedure

When any source changes upstream:

1. Record repository, exact commit SHA, source path, and review date.
2. Compare changed source tree against baseline above.
3. Classify each change as new capability, correctness or safety fix, runtime-adapter syntax, duplicate guidance, obsolete behavior, or provenance change.
4. Prefer runtime-neutral behavior, deterministic mechanisms, current protocol semantics, and repository-native validators.
5. Do not copy host-specific paths, tool names, model names, metadata fields, command syntax, event names, or unverified lifecycle claims into core guidance.
6. Run `$absorb-skills` with fresh source snapshot and this skill as target. Let coordinator produce complete capability and runtime-dependency maps.
7. Update this registry with new baseline commit or tree digest, absorption date, plan hash, retained changes, and explicit omissions.
8. Run skill validator, link check, runtime-neutral token scan, native discovery, focused script checks, and `git diff --check`.

Review upstream releases or source-path changes periodically even when changelog does not name these skills. Useful fixes may arrive through repository-wide sweeps.

## Changelog

### 2026-08-02

- Added one-word and family-first hierarchical resource filename guidance.
- Added a deterministic filename checker and renamed the settings resolver to `scripts/settings.py` to follow the convention.

### 2026-08-01

- Rebuilt removed Trail of Bits workflow skill around executable coordination and runtime-neutral adapters.
- Absorbed command-entrypoint design from `command-development`.
- Absorbed bounded delegated-worker design from `agent-development`.
- Absorbed event-hook design from `hook-development`.
- Absorbed MCP and external-tool integration design from `mcp-integration`.
- Absorbed progressive disclosure and workflow-skill packaging from `skill-development`.
- Absorbed runtime-neutral skill-settings design from `plugin-settings`.
- Added stdlib JSON resolver and neutral fixtures instead of copying vendor-specific shell examples.
- Deleted earlier absorbed project-local command, agent, hook, MCP, and skill-development sources after their successful runs; durable run artifacts retain evidence.
- Deleted project-local `plugin-settings` source after successful absorption; run artifacts retain inventory, analysis, plan, rollback baseline, and validation evidence.
