# Absorbed Source: Designing Workflow Skills

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`trailofbits/skills`](https://github.com/trailofbits/skills), removed path `plugins/workflow-skill-design/` |
| Baseline kind | Local tree digest of the installed snapshot |
| Absorbed baseline | Commit [`09dfbd91537b888136c9203dca4ffdee5a595c69`](https://github.com/trailofbits/skills/commit/09dfbd91537b888136c9203dca4ffdee5a595c69) |
| Absorbed on | 2026-08-01 |
| Plan hash | Initial adaptation; no absorption run |

Absorbed:

- Workflow routing, pipelines, ordered phases, dependency-aware work, feedback loops, and safety gates.
- Skill activation, resource routing, and workflow review criteria.

Reworked or excluded:

- Moved workflow state and transitions from prose into executable coordinators.
- Removed obsolete task tools, fixed batching guidance, mandatory final verification, and runtime-specific syntax.
