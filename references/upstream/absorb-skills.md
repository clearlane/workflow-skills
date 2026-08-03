# Absorbed Source: Absorb Skills

## Baseline

| Field | Value |
|---|---|
| Upstream location | Project-local skill `absorb-skills`, previously vendored at `.agents/skills/absorb-skills/` |
| Absorbed baseline | Snapshot tree SHA-256 `e39465db1fe44d4085944150065c9500e91fefd5408cc7819cbd5097d20d2666` |
| Absorbed on | 2026-08-02 |
| Plan hash | `06a4b90b9236dec20bfcb0aa7cf4d2310513f3e5a182a12c038c901870453d50` |

Absorbed:

- Absorption contract, durable run initialization, status and resume, and read-only source guarantees.
- Bounded per-source analysis with stable capability IDs, evidence paths, triggers, overlaps, conflicts, risks, and runtime dependencies.
- Capability model, merge dispositions with preference order, conflict classification, and scalable non-source-shaped target structure.
- Synthesis plan with complete capability and runtime-dependency coverage, internal plan binding, pre-mutation snapshot, merge evidence, bounded validation, automatic rollback, and plan revision.
- Executable coordinator with its own deterministic self-check.

Reworked or excluded:

- Renamed resources to this repository's one-word filename convention: `workflows/absorb.md`, `references/absorb.md`, and `scripts/absorb.py`.
- Removed the legacy approval-phase run migration command, its status field, and its guard, because no legacy runs exist here and the path was unreachable.
- Replaced the source's separate host metadata file with the existing single metadata adapter, and removed host path interpolation and skill-mention syntax.
- Expressed the named skill validator by role as repository-native or host-native validation.
- Framed the no-pause execution model as reversibility-based safety in `SKILL.md` rather than an exception to the approval rule.
- Deleted the project-local source tree and its generated cache after the run; run artifacts retain inventory, analyses, plan, rollback baseline, and validation evidence.

Canonical destinations:

- `workflows/absorb.md`
- `references/absorb.md`
- `scripts/absorb.py`
- `SKILL.md`
