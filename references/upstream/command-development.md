# Absorbed Source: Command Development

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev/skills/command-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/command-development) |
| Baseline kind | Local tree digest of the installed snapshot; upstream `main` is mutable, so no commit was resolvable at absorption time |
| Absorbed baseline | Installed `main` snapshot tree SHA-256 `4020f234432383b30dcfa5a5c4bf4a24ec251759c2d00254699b1b7a24261208` |
| Absorbed on | 2026-08-01 |
| Plan hash | `5ec5b6fb9ce3ef67059d479ea81219205d44e34a1a9e0c04be4342d067b3acf0` |

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
