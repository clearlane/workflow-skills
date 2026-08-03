# Absorbed Source: Project Organizer

## Baseline

| Field | Value |
|---|---|
| Upstream location | Project-local skill `project-organizer`, previously at `skills/project-organizer/` |
| Absorbed baseline | Snapshot tree SHA-256 `b500ca62b3fb7252cfd7c36f6f66b6bd5f6120deaee38f420e5bc9400e59d40e` |
| Absorbed on | 2026-08-02 |
| Plan hash | `b3c7f9f9b875aa474d4e229fff8e641e74ac37abf847f29d94e76fbea66113e0` |

Absorbed:

- Evidence-first layout diagnosis: classify the scope shape and its protected contracts before proposing any structure.
- Structural rubric separating confirmed problems from preferences, deliberate exceptions, and blocked items, with quality tests and a priority order.
- Ecosystem evidence prompts for JavaScript, Python, Go, Rust, JVM, .NET, and other package managers, plus the cross-cutting operational surfaces a move can break.
- Exact proposal contract: current and target trees, path-by-path operation manifest, affected reference surfaces, validation commands, and rollback.
- Approval gate immediately before moves, renames, or deletions, with an audit-only route that stops at the proposal.
- Boundary-at-a-time migration order, reference repair in the same step, and focused checks between boundaries.
- Risk cases: case-only renames, symlinks, generated files, applied migrations, vendored content, large files, public import paths, and dirty worktrees.
- Discovery-contract preservation across moves, stale-path search with a positive control, and structural handoff reporting.
- Deterministic side-effect-free structural inventory script, now with its own self-check in the repository check entrypoint.

Reworked or excluded:

- Scoped the domain to skills, bundles, and the repositories holding them instead of a general project-organization product, so activation stays bound to this skill's contract.
- Reorganized three source-shaped references into two job-shaped ones: `references/layout.md` for judgment and `references/migration.md` for execution.
- Condensed the ecosystem catalog into evidence prompts rather than per-framework tree prescriptions.
- Kept the untrusted-input and repository-native-check rules as the target's existing invariants instead of restating them.
- Left restructuring as a workflow with a deterministic inventory script and an approval gate; a linear, approval-gated, version-control-reversible run does not yet justify a coordinator.
- Omitted the source frontmatter, host metadata file, and host invocation token, and never absorbed the machine-local filesystem artifact in the source tree.
- Fixed a defect in the absorbed inventory script: symlinked directories are never walked, so they were missing from the inventory entirely; they are now recorded with a `directory` flag that the script's self-check enforces.

Canonical destinations:

- `workflows/restructure.md`
- `references/layout.md`
- `references/migration.md`
- `scripts/inventory.py`
- `SKILL.md`
