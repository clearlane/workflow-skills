# Designing Workflow Skills

Runtime-neutral agent skill for designing reliable multi-step workflows with executable orchestration instead of prose-held state.

## What It Covers

- Routing and dispatch tables
- Parallel item pipelines with bounded concurrency
- Runtime-neutral skill structure and progressive disclosure
- Explicit idempotent setup and route-specific pre-flight readiness workflows
- Typed user-local and project-local skill settings with precedence and provenance
- Event-triggered guards and lifecycle reactions
- MCP and external-tool integration contracts
- Bounded delegated-worker contracts and selection tests
- Ordered executable phases
- Dependency graphs and resumable state
- Bounded feedback loops
- Approval gates for destructive actions
- Validator-backed checks at actionable boundaries
- Thin explicit command entrypoints with validated arguments
- Runtime-neutral command metadata, interaction, failure, and adapter testing contracts
- Runtime-neutral worker metadata, capability, output, failure, and adapter contracts
- Runtime-neutral transport, authentication, schema, lifecycle, partial-success, and hook contracts
- Runtime-neutral settings discovery, parsing, migration, atomic update, security, and reload contracts

## Install

Discover the skill before installing:

```bash
npx --yes skills add clearlane/workflow-skills --list
```

Install a portable project-local copy for every agent supported by the current `skills` CLI:

```bash
npx --yes skills add clearlane/workflow-skills \
  --skill designing-workflow-skills \
  --agent '*' \
  --yes \
  --copy
```

This writes one destination per supported agent and can be intentionally broad; replace `'*'` with explicit agent IDs when appropriate. Omit `--copy` when installing from an active local checkout and you want agents to follow repository edits through the CLI's default link mode. Add `--global` only for an explicit user-level install. Start a fresh agent session if the host discovers skills only at startup.

## Structure

- `SKILL.md` — activation and core workflow-design rules
- `references/structure.md` — skill contract, progressive disclosure, resources, and deployment shapes
- `references/naming.md` — one-word and family-first hierarchical filename convention
- `workflows/setup.md` — executable setup and pre-flight process, readiness reports, remediation, freshness, and revalidation
- `references/events.md` — event-boundary handler design
- `references/tools.md` — MCP and external-service adapter design
- `references/patterns.md` — dynamic coordinator patterns
- `references/workers.md` — bounded runtime-neutral worker design
- `references/commands.md` — safe runtime-neutral command adapter design
- `references/settings.md` — validated skill preferences, scopes, precedence, lifecycle, and security
- `scripts/settings.py` — stdlib JSON layer resolver with provenance and atomic-write self-check
- `scripts/names.py` — deterministic portable filename check
- `examples/skill-settings/` — small runtime-neutral settings fixtures
- `workflows/design.md` — authoring and refactoring process
- `agents/openai.yaml` — Codex UI metadata
- `UPSTREAM.md` — absorbed-source baselines, capability map summary, and refresh procedure

## Origin and Changes

This project adapts Trail of Bits' `designing-workflow-skills` skill from [`trailofbits/skills`](https://github.com/trailofbits/skills), using the last pre-removal revision at commit [`09dfbd91537b888136c9203dca4ffdee5a595c69`](https://github.com/trailofbits/skills/commit/09dfbd91537b888136c9203dca4ffdee5a595c69).

Trail of Bits removed the original plugin in [PR #215](https://github.com/trailofbits/skills/pull/215) on July 31, 2026. This adaptation:

- Moves ordering, branching, concurrency, retry, and resume logic into executable coordinators.
- Replaces runtime-specific tool guidance with runtime-neutral capability guidance.
- Removes obsolete task tools, fixed batching advice, and mandatory prompt-level verification.
- Removes duplicated generic skill-authoring guidance already covered by current skill tooling.
- Removes Trail of Bits branding while preserving attribution.

Command-entrypoint guidance independently re-expresses generic concepts from project-local `command-development` source. No runtime-specific syntax, files, or examples were copied.

Delegated-worker guidance independently re-expresses generic concepts from project-local `agent-development` source. No runtime-specific syntax, templates, examples, or validator code were copied.

Skill-structure, event-hook, and external-tool guidance independently re-express generic concepts from project-local `skill-development`, `hook-development`, and `mcp-integration` sources. No runtime-specific syntax, shell utilities, templates, examples, or validator code were copied.

Skill-settings guidance independently re-expresses generic concepts from project-local `plugin-settings` source. It separates preferences from mutable workflow state and excludes vendor paths, metadata, reload claims, shell parsers, templates, and examples.

See [`UPSTREAM.md`](UPSTREAM.md) for source baselines, absorbed coverage, deliberate exclusions, monitoring procedure, and changelog.

## License

Licensed under [CC BY-SA 4.0](LICENSE), matching the upstream license. Adaptations are distributed under the same terms.
