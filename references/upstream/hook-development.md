# Absorbed Source: Hook Development

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev/skills/hook-development`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/hook-development) |
| Absorbed baseline | Installed `main` snapshot tree SHA-256 `9cb13ef507a97d92169d55b0f645a378ebc7aa6373353ff6aa9785037f0d0118` |
| Absorbed on | 2026-08-01 |
| Plan hash | `a87ac90c76030720444618424c48ae45e2b8dd68b018a22006bfa7fa99ab8b82` |

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
