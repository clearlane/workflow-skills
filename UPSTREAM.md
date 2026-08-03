# Absorption History

Per-source provenance — baselines, absorbed capabilities, deliberate
exclusions, and canonical destinations — lives in
[references/upstream/](references/upstream/README.md), one file per source.
That directory also owns the refresh procedure.

This file records the history of absorption runs and the coordinator changes
they produced, which is a timeline rather than a per-source fact.

## Changelog

### 2026-08-02 (latest)

- Absorbed `project-organizer` as the `restructure` workflow with `references/layout.md`, `references/migration.md`, and `scripts/inventory.py`, scoping layout work to skills, bundles, and their repositories.
- Separated malformed absorption evidence from unsafe execution: a mistyped field now holds the phase and preserves the merge instead of rolling the target back, after this run lost a complete, checked merge to one string-versus-list mistake.
- Made rollback non-lossy by preserving the in-progress target under `revisions/` before restoring the snapshot, so an out-of-scope path costs a re-bind rather than the whole merge.
- Fixed the absorbed inventory script so symlinked directories appear in the inventory instead of disappearing, and added a self-check proving no writes, no symlink following, exclusion handling, and honest truncation.
- Extended the repository check entrypoint to cover the new workflow's reachability and the inventory self-check.
- Added `extend-scope` so a repair discovered mid-merge records its extra paths with a reason instead of forcing a rebind-and-remerge, closing the defect deferred during the `project-organizer` run. Extensions stay additive and snapshot-covered, so rollback still reverses them.

### 2026-08-02 (later)

- Absorbed `plugin-structure` as `references/packaging.md`, adding a runtime-neutral bundle packaging, discovery, portable-path, and distribution contract, and made packaging a derivable design capability.
- Fixed three absorption-coordinator defects the run exposed: snapshots crashed on non-regular files, digests included repository-ignored local state, and plan revision discarded correct in-progress merge work.
- Made an explicit orchestrator verdict a completion requirement: a run cannot complete without `feedback.json`, and a `fixed` observation must name the files carrying the fix.

### 2026-08-02

- Replaced the sixteen prose steps in `workflows/design.md` with an executable coordinator at `scripts/design.py` that derives phases from the recorded contract, persists decisions, and resumes from artifacts, so the skill follows its own rule against prose-held workflow state.
- Extracted shared durable-run primitives into `scripts/state.py` and made both coordinators consume them instead of keeping private copies.
- Consolidated duplicated guidance so each rule has one canonical home: `SKILL.md` became a router, per-topic summaries were removed in favor of their references, the review checklist moved into `workflows/design.md`, and agent-skill installation moved from `workflows/setup.md` into `references/install.md`.
- Added `scripts/check.py` as the single deterministic check entrypoint, replacing ad-hoc validation.
- Excluded version-control and cache directories from absorption digests and snapshots, and made rollback restore tracked files instead of deleting the whole target tree.
- Absorbed the `absorb-skills` source into this skill as the `absorb` workflow, adding an evidence-bound absorption coordinator, workflow route, and reference.
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
