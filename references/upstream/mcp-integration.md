# Absorbed Source: MCP Integration

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev/skills/mcp-integration`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/mcp-integration) |
| Absorbed baseline | Installed `main` snapshot tree SHA-256 `03902fea89d355516383adf9f1cd782f064ab75b2bd0f030f8719975feb88d0f` |
| Absorbed on | 2026-08-01 |
| Plan hash | `a87ac90c76030720444618424c48ae45e2b8dd68b018a22006bfa7fa99ab8b82` |

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
