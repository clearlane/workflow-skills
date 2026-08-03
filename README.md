<div align="center">

# Designing Workflow Skills

**An Agent Skill for building Agent Skills.**

<br />

[![Star this repo](https://img.shields.io/github/stars/clearlane/workflow-skills?style=for-the-badge&logo=github&label=%E2%AD%90%20Star%20this%20repo&color=yellow)](https://github.com/clearlane/workflow-skills/stargazers)

<br />

[![checks](https://img.shields.io/github/actions/workflow/status/clearlane/workflow-skills/checks.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=checks)](https://github.com/clearlane/workflow-skills/actions/workflows/checks.yml)
&nbsp;
[![License: CC BY-SA 4.0 and MIT](https://img.shields.io/badge/License-CC_BY--SA_4.0_%2B_MIT-blue?style=for-the-badge)](#license)
&nbsp;
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen?style=for-the-badge)](CONTRIBUTING.md)
&nbsp;
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](pyproject.toml)

---

Design, review, and merge multi-step AI agent workflows that hold their control flow in executable coordinators instead of prose an agent has to remember.

Works with Claude Code, Codex, Cursor, and any runtime that loads `SKILL.md` — the guidance stays runtime-neutral, and host-specific syntax is confined to adapters.

[Install](#install) · [Why This Exists](#why-this-exists) · [What It Covers](#what-it-covers) · [Structure](#structure) · [Contributing](#contributing)

</div>

> **Started as a fork of the `designing-workflow-skills` skill Trail of Bits removed in July 2026, and has since been rebuilt.** The prose workflow became 1,700 lines of executable coordinators, and seven further sources were absorbed. If the deleted plugin is what brought you here, see [Relationship to the Trail of Bits Plugin](#relationship-to-the-trail-of-bits-plugin).

## Why This Exists

Most multi-step skills keep their workflow in prose: numbered steps, "continue only if approved", "retry up to three times". That works until a run is interrupted, a step half-succeeds, or the model forgets step four. Prose cannot resume, cannot bound a retry, and cannot prove an approval was given for the exact action taken.

This skill moves that control flow into coordinators you can run:

```bash
python3 scripts/design.py init --name my-skill --skill ./my-skill --run-dir ./run \
  --capability coordinator --capability state
python3 scripts/design.py status --run-dir ./run
```

`status` names the current phase and the one document that owns its contract. Phases are derived from the capabilities you record, so a skill with no settings never walks a settings phase. Progress persists in a run directory, so an interrupted design resumes from artifacts rather than from conversation history.

## What It Covers

**Workflow patterns** — routing and dispatch tables, parallel item pipelines with bounded concurrency, ordered executable phases, dependency graphs with resumable state, bounded feedback loops, and approval gates for destructive actions.

**Skill architecture** — runtime-neutral structure, progressive disclosure across references and scripts, activation metadata, filename conventions, and bundle packaging for host discovery.

**Adapters** — MCP and external-tool integration, event-triggered guards and lifecycle reactions, bounded delegated workers, thin command entrypoints with validated arguments, and typed user-local and project-local settings with precedence and provenance.

**Operations** — idempotent setup with pre-flight readiness reports, validator-backed checks placed where failure is actionable, evidence-gated review with a disposition-gated verdict, and evidence-bound absorption of one or many skills into one target with bounded validation and automatic rollback.

## Who It Is For

Use it when you are writing a skill whose steps branch, retry, resume, run concurrently, or touch something irreversible. Skip it when a single direct instruction would do — the skill says so itself, and starting with plain instructions is the documented default.

## Install

### With the `skills` CLI

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

### Manually

Clone into the directory your agent scans for skills — commonly `.claude/skills/`, `.agents/skills/`, or `~/.codex/skills/`, depending on the host:

```bash
git clone https://github.com/clearlane/workflow-skills.git .agents/skills/designing-workflow-skills
```

The skill activates on its own when a task matches its description. To invoke it explicitly, mention it by name: *"use designing-workflow-skills to refactor this into a coordinator."*

## Structure

Core instructions load first; everything else is loaded on demand, which is the progressive-disclosure pattern the skill itself teaches.

**Entry point**

- `SKILL.md` — activation and core workflow-design rules

**Workflows** — multi-phase processes with coordinator entry

- `workflows/design.md` — authoring and refactoring process
- `workflows/review.md` — evidence-gated skill review workflow
- `workflows/absorb.md` — absorption workflow, coordinator entry, invariants, and rollback contract
- `workflows/restructure.md` — audit-then-approve layout restructuring workflow
- `workflows/setup.md` — executable setup and pre-flight process, readiness reports, remediation, freshness, and revalidation

**References** — one canonical contract per concern

- `references/structure.md` — skill contract, progressive disclosure, resources, and deployment shapes
- `references/patterns.md` — dynamic coordinator patterns
- `references/naming.md` — one-word and family-first hierarchical filename convention
- `references/checks.md` — where checks and approval gates belong so failure stays actionable
- `references/closure.md` — owner-boundary questions that close a design run
- `references/install.md` — agent-skill discovery, canonical install, and same-scope verification
- `references/events.md` — event-boundary handler design
- `references/tools.md` — MCP and external-service adapter design
- `references/workers.md` — bounded runtime-neutral worker design
- `references/commands.md` — safe runtime-neutral command adapter design
- `references/settings.md` — validated skill preferences, scopes, precedence, lifecycle, and security
- `references/packaging.md` — bundle manifest, component discovery, and portable-path contract
- `references/layout.md` — evidence rules deciding when a layout is actually wrong
- `references/migration.md` — boundary-at-a-time move execution and reference repair
- `references/review.md` — review evidence, severity, and disposition rules
- `references/absorb.md` — capability model, merge dispositions, conflict policy, and absorption artifact schemas
- `references/upstream/` — one provenance record per absorbed source, plus the refresh procedure

**Coordinators and tooling**

- `scripts/design.py` — design coordinator deriving phases from the recorded contract, with durable decisions and resume
- `scripts/review.py` — review coordinator deriving phases from detected surfaces, with a disposition-gated verdict
- `scripts/absorb.py` — absorption coordinator with durable run state, plan binding, snapshot rollback, and self-check
- `scripts/state.py` — shared durable-run primitives used by both coordinators
- `scripts/document.py` — markdown and YAML document model backing the structural checks
- `scripts/inventory.py` — deterministic structural inventory for layout audits
- `scripts/check.py` — single entrypoint running every deterministic repository check
- `scripts/settings.py` — stdlib JSON layer resolver with provenance and atomic-write self-check
- `scripts/names.py` — deterministic portable filename check
- `scripts/install-fanout.sh` — installs the shared skill set into every sibling project and links this skill live

**Supporting files**

- `examples/skill-settings/` — small runtime-neutral settings fixtures
- `agents/openai.yaml` — Codex UI metadata
- `pyproject.toml` — the single source of truth for dependency versions, the supported Python floor, and lint rules
- `requirements.txt` — a pointer to `pyproject.toml`, kept because CI caches on it
- `.editorconfig` — editor defaults so whitespace never becomes a diff
- `lychee.toml` — external link-check exclusions, each with a stated reason
- `skills-lock.json` — pinned skill install manifest
- `AGENTS.md` — working contract for agents changing this repository
- `UPSTREAM.md` — absorption history and the coordinator changes each run produced
- `CONTRIBUTING.md` — how to run the checks and what they enforce
- `LICENSE-CODE` — MIT terms covering `scripts/`, as described under [License](#license)

## Checks

Run every deterministic check with one command:

```bash
python3 scripts/check.py
```

It runs the filename convention, the checker's own logic, the shared-state, document-model, settings-resolver, design, review, absorption, and inventory self-checks, the skill contract including the Agent Skills name and description bounds, the size budget, relative-link and anchor resolution, resource reachability, one-canonical-section-per-document, phase-owner distinctness, documented capabilities and review phases, README structure coverage, shebang and executable-bit agreement, and a runtime-neutral token scan.

The checks need Python 3.10 or later and the parsers in `requirements.txt`. Lint rules and the supported Python floor live in `pyproject.toml`, so `ruff` reports the same findings everywhere.

Two checks delegate to external tools and skip silently when the tool is absent, so the default run needs only the Python dependencies above:

- `ruff` reports Python lint errors in `scripts/`.
- `lychee` verifies external URLs, including the provenance links in this file and under `references/upstream/`. Network checking is opt-in, so the default run stays offline and deterministic:

```bash
CHECK_EXTERNAL_LINKS=1 python3 scripts/check.py
```

GitHub Actions runs the deterministic suite on every push and pull request against both the declared floor and the current Python release. External link checking runs on a weekly schedule instead, so a briefly unreachable third-party host cannot fail an unrelated change.

## Relationship to the Trail of Bits Plugin

If you are searching for `designing-workflow-skills`, `workflow-skill-design`, or the deleted Trail of Bits workflow-skill plugin, this repository is where that line of work continued. Trail of Bits removed `plugins/workflow-skill-design/` from [`trailofbits/skills`](https://github.com/trailofbits/skills) in [PR #215](https://github.com/trailofbits/skills/pull/215) on July 31, 2026.

What you install here is not that plugin. It keeps the original's goal and covers what the original covered, but the design was rebuilt rather than maintained, and most of the surface is now new. The last pre-removal revision is preserved at commit [`09dfbd91537b888136c9203dca4ffdee5a595c69`](https://github.com/trailofbits/skills/commit/09dfbd91537b888136c9203dca4ffdee5a595c69) if you want the original behavior instead.

### How Far It Has Moved

The original was a prose skill: numbered steps an agent read and tried to follow. The workflow now lives in code.

- **Control flow is executable.** Ordering, branching, concurrency, retry, and resume logic live in roughly 1,700 lines across `scripts/design.py`, `scripts/review.py`, and `scripts/absorb.py`, not in instructions a model has to remember. An interrupted run resumes from artifacts on disk.
- **Phases are derived, not fixed.** The phase list comes from a recorded capability contract, so a skill without settings never walks a settings phase.
- **Guidance is runtime-neutral.** Runtime-specific tool advice became capability guidance, enforced by an automated token scan rather than by review.
- **Scope grew past the original.** Seven further sources were absorbed, and evidence-gated review with a disposition-gated verdict, evidence-bound absorption with snapshot rollback, layout restructuring, bundle packaging, validated skill settings, and a single deterministic check entrypoint did not exist in the original.
- **Dropped along the way.** Obsolete task tools, fixed batching advice, mandatory prompt-level verification, generic authoring guidance now covered by host tooling, and Trail of Bits branding.

### Attribution

This project began as an adaptation of Trail of Bits' `designing-workflow-skills` skill, and the adapted prose remains under the upstream license. Credit for the original design belongs to [Trail of Bits](https://github.com/trailofbits). Responsibility for everything built since is this repository's, and the current design should not be read as theirs.

Command-entrypoint guidance independently re-expresses generic concepts from the upstream `command-development` source. No runtime-specific syntax, files, or examples were copied.

Delegated-worker guidance independently re-expresses generic concepts from the upstream `agent-development` source. No runtime-specific syntax, templates, examples, or validator code were copied.

Skill-structure, event-hook, and external-tool guidance independently re-express generic concepts from the upstream `skill-development`, `hook-development`, and `mcp-integration` sources. No runtime-specific syntax, shell utilities, templates, examples, or validator code were copied.

Skill-settings guidance independently re-expresses generic concepts from the upstream `plugin-settings` source. It separates preferences from mutable workflow state and excludes vendor paths, metadata, reload claims, shell parsers, templates, and examples.

See [`references/upstream/`](references/upstream/README.md) for per-source baselines, absorbed coverage, deliberate exclusions, and the refresh procedure, and [`UPSTREAM.md`](UPSTREAM.md) for absorption history.

## Contributing

Pull requests are welcome. Run `python3 scripts/check.py` before opening one — it is the same suite CI runs, so a green local run means a green pull request.

[CONTRIBUTING.md](CONTRIBUTING.md) explains what each check enforces and why, including the rule that a new check must be shown to fail on a real violation before it is worth keeping.

## License

Dual-licensed, because the two halves of this repository carry different obligations.

- **Prose** — `SKILL.md`, `references/`, `workflows/`, and the repository's own documents: [CC BY-SA 4.0](LICENSE). This is the upstream license, and the share-alike obligation on the adapted guidance is inherited, not chosen.
- **Code** — everything under `scripts/`: [MIT](LICENSE-CODE). These coordinators are original work, not an adaptation of upstream prose, and share-alike on 3,000 lines of Python would make vendoring a single helper a licensing decision rather than a copy-paste.

Every file under `scripts/` carries an `SPDX-License-Identifier` header, so the boundary is readable per file rather than inferred from this section. `scripts/check.py` enforces that. `SKILL.md` declares `license: CC-BY-SA-4.0 AND MIT`. Copyright is held by Clearlane.

---

<div align="center">

Built by [Joachim Brindeau](https://github.com/joachimBrindeau)

<br />

**If this saved you time:**

[![Star this repo](https://img.shields.io/github/stars/clearlane/workflow-skills?style=for-the-badge&logo=github&label=%E2%AD%90%20Star%20this%20repo&color=yellow)](https://github.com/clearlane/workflow-skills/stargazers)

</div>
