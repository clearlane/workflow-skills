# Absorbed Source: Agent Development

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev/skills/agent-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/agent-development) |
| Absorbed baseline | Installed `main` snapshot tree SHA-256 `844fb26d8bb521f11e1dce254d6f23f8a36da4365e9a0640cb07498d2aa7b72e` |
| Absorbed on | 2026-08-01 |
| Plan hash | `76b68fffb5e08064aa9467248a61c90140bf14b5a98a7cc058ddb10d061d8bbd` |

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
