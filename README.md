# Designing Workflow Skills

Runtime-neutral agent skill for designing, refactoring, and merging reliable multi-step workflows with executable orchestration instead of prose-held state.

> **Continuation of the `designing-workflow-skills` skill removed from [`trailofbits/skills`](https://github.com/trailofbits/skills) in July 2026.** Actively maintained, with executable coordinators replacing prose-held workflow state. See [Looking for the Trail of Bits Plugin](#looking-for-the-trail-of-bits-plugin) if that is what brought you here.

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
- Evidence-bound absorption of one or many skills into one target, with bounded validation and automatic rollback
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
- `references/checks.md` — where checks and approval gates belong so failure stays actionable
- `references/closure.md` — owner-boundary questions that close a design run
- `workflows/setup.md` — executable setup and pre-flight process, readiness reports, remediation, freshness, and revalidation
- `references/install.md` — agent-skill discovery, canonical install, and same-scope verification
- `references/events.md` — event-boundary handler design
- `references/tools.md` — MCP and external-service adapter design
- `references/patterns.md` — dynamic coordinator patterns
- `references/workers.md` — bounded runtime-neutral worker design
- `references/commands.md` — safe runtime-neutral command adapter design
- `references/settings.md` — validated skill preferences, scopes, precedence, lifecycle, and security
- `references/packaging.md` — bundle manifest, component discovery, and portable-path contract
- `references/layout.md` — evidence rules deciding when a layout is actually wrong
- `references/migration.md` — boundary-at-a-time move execution and reference repair
- `references/review.md` — review evidence, severity, and disposition rules
- `references/absorb.md` — capability model, merge dispositions, conflict policy, and absorption artifact schemas
- `workflows/absorb.md` — absorption workflow, coordinator entry, invariants, and rollback contract
- `workflows/restructure.md` — audit-then-approve layout restructuring workflow
- `workflows/review.md` — evidence-gated skill review workflow
- `scripts/absorb.py` — absorption coordinator with durable run state, plan binding, snapshot rollback, and self-check
- `scripts/design.py` — design coordinator deriving phases from the recorded contract, with durable decisions and resume
- `scripts/review.py` — review coordinator deriving phases from detected surfaces, with a disposition-gated verdict
- `scripts/state.py` — shared durable-run primitives used by both coordinators
- `scripts/document.py` — markdown and YAML document model backing the structural checks
- `scripts/inventory.py` — deterministic structural inventory for layout audits
- `scripts/check.py` — single entrypoint running every deterministic repository check
- `scripts/settings.py` — stdlib JSON layer resolver with provenance and atomic-write self-check
- `scripts/names.py` — deterministic portable filename check
- `examples/skill-settings/` — small runtime-neutral settings fixtures
- `workflows/design.md` — authoring and refactoring process
- `agents/openai.yaml` — Codex UI metadata
- `requirements.txt` — parser dependencies for the document-model checks
- `skills-lock.json` — pinned skill install manifest
- `UPSTREAM.md` — absorbed-source baselines, capability map summary, and refresh procedure

## Checks

Run every deterministic check with one command:

```bash
python3 scripts/check.py
```

It runs the filename convention, the shared-state, document-model, settings-resolver, design, review, absorption, and inventory self-checks, the skill contract and size budget, relative-link and anchor resolution, resource reachability, one-canonical-section-per-document, phase-owner distinctness, documented capabilities and review phases, README structure coverage, and a runtime-neutral token scan.

Two checks delegate to external tools and skip silently when the tool is absent, so the default run needs only the Python dependencies above:

- `ruff` reports Python lint errors in `scripts/`.
- `lychee` verifies external URLs, including the provenance links in this file and `UPSTREAM.md`. Network checking is opt-in, so the default run stays offline and deterministic:

```bash
CHECK_EXTERNAL_LINKS=1 python3 scripts/check.py
```

## Looking for the Trail of Bits Plugin

If you are searching for `designing-workflow-skills`, `workflow-skill-design`, or the deleted Trail of Bits workflow-skill plugin, you are in the right place. Trail of Bits removed `plugins/workflow-skill-design/` from [`trailofbits/skills`](https://github.com/trailofbits/skills) in [PR #215](https://github.com/trailofbits/skills/pull/215) on July 31, 2026. This repository is the continuation of that work, and it is actively maintained.

The skill you want is `designing-workflow-skills` — install it with the command above. Every capability of the original is still present, and the last pre-removal revision is preserved at commit [`09dfbd91537b888136c9203dca4ffdee5a595c69`](https://github.com/trailofbits/skills/commit/09dfbd91537b888136c9203dca4ffdee5a595c69) if you need to compare.

### What Changed Since the Original

The skill has diverged substantially from the version Trail of Bits published. The largest difference is architectural: workflow control moved out of prose and into executable coordinators.

- Ordering, branching, concurrency, retry, and resume logic now live in `scripts/design.py`, `scripts/review.py`, and `scripts/absorb.py` rather than in numbered instructions an agent had to remember.
- Phase lists are derived from a recorded contract, so a skill without settings never walks a settings phase.
- Runtime-specific tool guidance became runtime-neutral capability guidance, enforced by an automated token scan.
- Obsolete task tools, fixed batching advice, and mandatory prompt-level verification were removed.
- Generic skill-authoring guidance already covered by current skill tooling was dropped.
- Trail of Bits branding was removed while attribution was preserved.

Capabilities added since the fork include evidence-gated skill review with a disposition-gated verdict, evidence-bound absorption with snapshot rollback, layout restructuring, bundle packaging, validated skill settings, and a single deterministic check entrypoint.

### Attribution

This project began as an adaptation of Trail of Bits' `designing-workflow-skills` skill and remains licensed under the same terms. Credit for the original design belongs to [Trail of Bits](https://github.com/trailofbits).

Command-entrypoint guidance independently re-expresses generic concepts from project-local `command-development` source. No runtime-specific syntax, files, or examples were copied.

Delegated-worker guidance independently re-expresses generic concepts from project-local `agent-development` source. No runtime-specific syntax, templates, examples, or validator code were copied.

Skill-structure, event-hook, and external-tool guidance independently re-express generic concepts from project-local `skill-development`, `hook-development`, and `mcp-integration` sources. No runtime-specific syntax, shell utilities, templates, examples, or validator code were copied.

Skill-settings guidance independently re-expresses generic concepts from project-local `plugin-settings` source. It separates preferences from mutable workflow state and excludes vendor paths, metadata, reload claims, shell parsers, templates, and examples.

Absorption guidance and its coordinator come from the project-local `absorb-skills` source, absorbed through its own run. Host path interpolation and skill-mention syntax were dropped, its resources were renamed to this repository's filename convention, its separate host metadata file was merged into the existing one, and its legacy approval-run migration path was removed as unreachable here.

See [`UPSTREAM.md`](UPSTREAM.md) for source baselines, absorbed coverage, deliberate exclusions, monitoring procedure, and changelog.

## License

Licensed under [CC BY-SA 4.0](LICENSE), matching the upstream license. Adaptations are distributed under the same terms.
