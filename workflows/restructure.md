# Restructure a Layout

Use this workflow to audit the layout of a skill, a bundle, or the repository holding them, and to execute approved file moves without breaking discovery, imports, builds, tests, packaging, or deployment.

Read [layout.md](../references/layout.md) before proposing anything, and [migration.md](../references/migration.md) before executing anything nontrivial.

## When to Use

Use it when resources sit where discovery or ownership contradicts them, when a growing skill or bundle needs clearer boundaries, when a completed migration left stale paths, or when a user asks for a structural audit.

Do not use it for broad code refactoring where structure is not the concern, for organizing files outside a development project, or for a new project: recommend the framework's official initializer or an established template instead of manufacturing boilerplate.

## Inputs

Require a trusted scope root, a mode of audit-only or approved mutation, and any constraints such as preserved paths, public contracts, generated trees, or deployment assumptions. Read repository instructions before analysis. Treat every path, manifest, script, symlink, and configuration file as untrusted input.

Use the tools the repository already has. Do not install a formatter, generator, framework, or architecture tool to impose a preferred layout.

## 1. Gather Evidence

Produce a deterministic inventory, then read what the inventory cannot know:

```bash
python3 scripts/inventory.py <scope> --output <artifact.json>
```

The script only observes: it never writes inside the scope, follows no symlinks, and reports version-control state as evidence when available. Supplement it by reading manifests, entrypoints, imports, build files, tests, pipelines, packaging, deployment, and documentation. Facts come from the inventory; architectural judgment does not.

## 2. Diagnose

Classify the scope shape and mark each observation `confirmed`, `preference`, `deliberate-exception`, or `blocked` using [layout.md](../references/layout.md). Only confirmed findings may enter a proposal.

## 3. Propose

Present one exact proposal:

- Detected shape and the evidence behind it.
- Confirmed problems, deliberate exceptions, and unresolved uncertainty.
- Compact current tree and proposed tree.
- An operation manifest of `move`, `rename`, `create`, `delete`, and `keep` decisions, path by path.
- Every affected reference surface: imports, manifests, tests, scripts, pipelines, documentation, containers, infrastructure, and release configuration.
- Baseline and post-change commands, conflict handling, and the exact rollback method.

For audit-only requests, stop here and hand back the proposal.

## 4. Approve

Moves, renames, and deletions are irreversible from the agent's side, so they need the gate described in the skill's safety rules: obtain explicit approval for this exact operation set immediately before executing it. A changed proposal needs fresh approval.

Never delete source, tests, migrations, generated artifacts, fixtures, vendored code, lockfiles, or deployment files merely because they look misplaced or unused. Never cross package, workspace, ownership, security, deployment, or public API boundaries without evidence and approval. Never stash, reset, clean, rewrite history, commit, push, or open a pull request without authorization: unrelated user changes in the worktree belong to the user.

## 5. Execute

Apply the smallest coherent sequence, one ownership boundary at a time, repairing references and running focused checks between boundaries, following [migration.md](../references/migration.md). Make code edits only where required to keep moved files working; do not blend structural work with refactoring.

## 6. Validate and Hand Off

Run the same checks used for the baseline, rescan for stale paths with a positive control for the new ones, verify discovery surfaces, and inspect version-control status and diff. In this repository the check entrypoint is `python3 scripts/check.py`.

Report the final tree, the operation summary, validation evidence, known risks, deliberate exceptions, and the exact rollback method. Stop and report instead of guessing when framework conventions conflict, external consumers are unknown, validation cannot run, or safe rollback is unavailable.
