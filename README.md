# Designing Workflow Skills

Runtime-neutral agent skill for designing reliable multi-step workflows with executable orchestration instead of prose-held state.

## What It Covers

- Routing and dispatch tables
- Parallel item pipelines with bounded concurrency
- Ordered executable phases
- Dependency graphs and resumable state
- Bounded feedback loops
- Approval gates for destructive actions
- Validator-backed checks at actionable boundaries

## Install

Install project-local copied files for Codex:

```bash
npx skills add clearlane/workflow-skills --agent codex --copy
```

Start a new Codex session after installation.

## Structure

- `SKILL.md` — activation and core workflow-design rules
- `references/workflow-patterns.md` — dynamic coordinator patterns
- `workflows/design-a-workflow-skill.md` — authoring and refactoring process
- `agents/openai.yaml` — Codex UI metadata

## Origin and Changes

This project adapts Trail of Bits' `designing-workflow-skills` skill from [`trailofbits/skills`](https://github.com/trailofbits/skills), using the last pre-removal revision at commit [`09dfbd91537b888136c9203dca4ffdee5a595c69`](https://github.com/trailofbits/skills/commit/09dfbd91537b888136c9203dca4ffdee5a595c69).

Trail of Bits removed the original plugin in [PR #215](https://github.com/trailofbits/skills/pull/215) on July 31, 2026. This adaptation:

- Moves ordering, branching, concurrency, retry, and resume logic into executable coordinators.
- Replaces Claude-specific tool guidance with runtime-neutral capability guidance.
- Removes obsolete task tools, fixed batching advice, and mandatory prompt-level verification.
- Removes duplicated generic skill-authoring guidance already covered by current skill tooling.
- Removes Trail of Bits branding while preserving attribution.

## License

Licensed under [CC BY-SA 4.0](LICENSE), matching the upstream license. Adaptations are distributed under the same terms.
