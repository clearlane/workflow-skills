# Absorbed Source: Plugin Settings

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev/skills/plugin-settings`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/plugin-settings) |
| Absorbed baseline | Installed `main` snapshot tree SHA-256 `67546a58c6562768b175670b5aed1c2f9a304899167d875959736fc2acd2eae3` |
| Absorbed on | 2026-08-01 |
| Plan hash | `7817f599855e36a227c7df70b0f1e11361546909bb38513fd17e29120427559b` |

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
