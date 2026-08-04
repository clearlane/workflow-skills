# Restructure a Layout

Use this workflow to audit the layout of a skill, a bundle, or the repository holding them, and to execute approved file moves without breaking discovery, imports, builds, tests, packaging, or deployment.

Read [layout.md](../references/layout.md) before proposing anything, and [migration.md](../references/migration.md) before executing anything nontrivial.

## When to Use

Use it when resources sit where discovery or ownership contradicts them, when a growing skill or bundle needs clearer boundaries, when a completed migration left stale paths, or when a user asks for a structural audit.

Do not use it for broad code refactoring where structure is not the concern, for organizing files outside a development project, or for a new project: recommend the framework's official initializer or an established template instead of manufacturing boilerplate.

This workflow moves files and changes nothing about behavior. When the layout is wrong because the skill's contract is wrong, the move is a symptom: run [design.md](design.md) instead. When one tree should become part of another, that is a merge rather than a move, and [absorb.md](absorb.md) owns it. A layout finding raised by [review.md](review.md) arrives here as the scope of a run.

## Inputs

Require a trusted scope root, a mode of audit-only or approved mutation, and any constraints such as preserved paths, public contracts, generated trees, or deployment assumptions. Read repository instructions before analysis. Treat every path, manifest, script, symlink, and configuration file as untrusted input.

Use the tools the repository already has. Do not install a formatter, generator, framework, or architecture tool to impose a preferred layout.

## Start a Run

```bash
python3 scripts/restructure.py init \
  --name <run-name> \
  --scope <scope-root> \
  --run-dir <run-directory> \
  --mode audit
```

Use `--mode audit` for a structural audit and `--mode mutate` when the user has asked for the moves to be carried out. An audit run ends at `propose` and issues no approval, so it cannot execute anything later. The run directory must be empty and must not sit inside the scope.

Inspect the current phase, its owning resource, and the next action at any time:

```bash
python3 scripts/restructure.py status --run-dir <run-directory>
```

## Work Each Phase

`status` names one phase and the resource that holds its contract. The coordinator owns the ordering, the approval binding, and what each phase must produce; this document explains why the phases exist.

**Evidence.** Produce a deterministic inventory, then read what the inventory cannot know:

```bash
python3 scripts/inventory.py <scope> --output <run-directory>/inventory.json
```

The script only observes: it never writes inside the scope, follows no symlinks, and reports version-control state as evidence when available. Supplement it by reading manifests, entrypoints, imports, build files, tests, pipelines, packaging, deployment, and documentation. Facts come from the inventory; architectural judgment does not.

**Diagnose.** Classify the scope shape and mark each observation `confirmed`, `preference`, `deliberate-exception`, or `blocked` using [layout.md](../references/layout.md). Only confirmed findings may enter a proposal.

**Propose.** Write `manifest.json` in the run directory: every path-level `move`, `rename`, `create`, `delete`, and `keep` decision with its reason, and the reference surfaces each one affects. Record keeps as well as changes, so a reader can tell a considered decision from an overlooked file. Present alongside it the detected shape and its evidence, the confirmed problems and deliberate exceptions, the current and proposed trees, and the baseline commands, conflict handling, and rollback method.

A schema-valid example is in [examples/restructure-run/manifest.json](../examples/restructure-run/manifest.json).

```bash
python3 scripts/restructure.py propose --run-dir <run-directory>
```

This binds the manifest by digest. An audit run is complete here; hand back the proposal.

**Approve.** Moves, renames, and deletions are irreversible from the agent's side. Present the bound manifest to the user and obtain approval for that exact operation set:

```bash
python3 scripts/restructure.py approve \
  --run-dir <run-directory> \
  --approved-by <who approved>
```

Approval is recorded against the manifest digest, so a manifest edited afterwards no longer matches it and execution fails until fresh approval is obtained. Editing the manifest between propose and approve fails too, because the bound proposal is what was shown.

Never delete source, tests, migrations, generated artifacts, fixtures, vendored code, lockfiles, or deployment files merely because they look misplaced or unused. Never cross package, workspace, ownership, security, deployment, or public API boundaries without evidence and approval. Never stash, reset, clean, rewrite history, commit, push, or open a pull request without authorization: unrelated user changes in the worktree belong to the user.

**Execute.** Apply the smallest coherent sequence, one ownership boundary at a time, repairing references and running focused checks between boundaries, following [migration.md](../references/migration.md). Make code edits only where required to keep moved files working; do not blend structural work with refactoring. Then record what was applied:

```bash
python3 scripts/restructure.py execute \
  --run-dir <run-directory> \
  --note "<what was applied and in what order>"
```

The coordinator re-checks the approval binding and confirms every mutating operation actually landed, so a manifest carried out only in part is caught here rather than at handoff.

**Validate.** Run the same checks used for the baseline, rescan for stale paths with a positive control for the new ones, verify discovery surfaces, and inspect version-control status and diff. In this repository the check entrypoint is `python3 scripts/check.py`. Record the outcome:

```bash
python3 scripts/restructure.py complete-phase \
  --run-dir <run-directory> \
  --phase validate \
  --note "<checks run and their outcome>"
```

## Exercise the Result

Report the final tree, the operation summary, validation evidence, known risks, deliberate exceptions, and the exact rollback method. Stop and report instead of guessing when framework conventions conflict, external consumers are unknown, validation cannot run, or safe rollback is unavailable.
