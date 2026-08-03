# Structural Migration

Use this reference when executing an approved layout change from [restructure.md](../workflows/restructure.md). [layout.md](layout.md) decides what should move; this file governs how a move preserves behavior.

## Discovery Contracts a Move Must Preserve

A path is rarely just a path. Before moving anything, know which of these the file participates in, and carry each one across the move in the same step:

- Import paths, package names, module identity, and namespace resolution.
- Executable entrypoints, console scripts, and host activation paths.
- Package publication contents, build outputs, and generated declarations.
- Test discovery roots and fixture resolution.
- Continuous integration paths, container build contexts, and deployment inputs.
- Skill and bundle discovery locations, manifest fields, and portable bundle-root references.
- Case-sensitive behavior on the filesystems that consume the repository.

A filesystem move that changes any of these is an interface change, not a cleanup. Treat it as one and plan an explicit migration for external consumers.

## Baseline Before Mutation

1. Capture version-control status and preserve unrelated user changes.
2. Record the exact source and destination of every operation.
3. Run the repository-native checks before mutation and keep the results as the comparison baseline.
4. Search for every old path, basename, import, package name, entrypoint, glob, and build-context reference.

## Order of Operations

1. Create only the destination directories the plan requires.
2. Move one coherent ownership boundary at a time.
3. Repair imports and local references immediately.
4. Repair manifests, aliases, exports, test discovery, build inputs, pipelines, containers, deployment, and documentation.
5. Run the focused checks for that boundary before starting the next one.
6. Remove an emptied directory only after proving it holds no required hidden file or ownership marker.

Preserve history with a version-control-native move when the tool supports it. Use temporary compatibility shims only when external consumers prevent an atomic cut, and document the owner, reason, removal condition, and tracking mechanism.

## Risk Cases

- **Case-only rename**: move through an intermediate name so version control and case-insensitive filesystems record the change.
- **Symlinks**: inspect link targets and consumers; never silently dereference them. A symlinked directory is never walked by a scan, so confirm it appears in the inventory before concluding it does not exist.
- **Generated files**: change the generator or source template, not only its output.
- **Migrations**: preserve ordering and immutability. Never reorganize applied migrations for tidiness.
- **Vendored content and submodules**: treat upstream ownership and version-control metadata as hard boundaries.
- **Binary or large files**: confirm storage rules and avoid unnecessary rewrites.
- **Public import or package paths**: a move can be an API break; plan the migration explicitly.
- **Dirty worktree**: separate user edits from the reorganization. Stop when overlap makes attribution unsafe.

## Checks

- Re-run the baseline commands in an equivalent environment and compare against the retained baseline.
- Run focused checks per moved boundary, then the complete quality stack before handoff.
- Search old paths and names, explain every remaining match, and confirm the new path is positively referenced with a control search.
- Confirm discovery still works where it matters: build artifacts, test collection, publication sets, container contexts, deployment inputs, and host discovery of skills or bundles.
- Inspect the version-control diff and status for unexpected content changes, permission changes, duplicates, omissions, and untracked leftovers.
