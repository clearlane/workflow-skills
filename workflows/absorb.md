# Absorb Skills Into One Target

Use this workflow to merge one or many source skills into one runtime-neutral target skill without silently losing capabilities, triggers, resources, safety rules, or provenance. Merge semantically. Do not concatenate files.

Read [absorb.md](../references/absorb.md) before analysis or planning.

## When to Use

Use this workflow when consolidating overlapping skills, folding an upstream skill into an existing one, or refreshing absorbed guidance from a changed source.

Do not use it to copy a skill unchanged, to edit one skill in place, or to vendor a source tree as a nested skill folder.

## Inputs

Require:

- One target skill path. The target may exist or be created during the run.
- One or more source skill paths, each containing `SKILL.md`.
- One durable run directory outside the target and every source.
- Optional user priorities, exclusions, compatibility constraints, and maximum validation attempts.

Treat source order as non-authoritative. Prefer explicit user policy, then target identity, then the strongest evidence-supported design. The target contract stays runtime-neutral: generalize or omit vendor syntax, never copy it in.

## Coordinator Entry

The coordinator at `scripts/absorb.py` owns phases, plan binding, rollback scope, attempt bounds, and resume status. Start a run:

```bash
python3 scripts/absorb.py init \
  --target <target-skill> \
  --source <source-skill-1> \
  --source <source-skill-2> \
  --run-dir <run-directory> \
  --max-validation-attempts 3
```

Add `--new-target` only when the target does not exist yet. Do not create or edit the target during init.

Inspect phase and next action at any time, including after an interruption:

```bash
python3 scripts/absorb.py status --run-dir <run-directory>
```

Every phase transition uses the same command:

```bash
python3 scripts/absorb.py advance --run-dir <run-directory>
```

## 1. Analysis

Analyze the existing target plus one source per independent worker when the runtime bounds concurrency. Otherwise analyze sequentially. Give each worker the target inventory, one skill inventory, this workflow, and the absorption reference. Workers must not edit any skill. Skip target analysis only for `--new-target` runs.

Write `analyses/target.json` and one `analyses/<source-id>.json` per source, using the IDs in `inventory.json` and the schema in [absorb.md](../references/absorb.md). Every capability and every runtime dependency needs a stable ID and evidence paths. Suggested destinations are advice; synthesis decides.

Advance only after every source has a valid analysis.

## 2. Synthesis Plan

Compare all analyses together and write `plan.json`. Account for every target and source capability exactly once in `capability_map`, and every runtime dependency exactly once in `runtime_adapter_map`.

Organize the target around one canonical contract:

- Keep activation and essential execution guidance in `SKILL.md`, under 500 lines, with references one level away.
- Move detailed variants and domain knowledge into directly linked references.
- Keep deterministic repeated logic in scripts and output-only material in assets.
- Merge duplicate rules into one source of truth. Preserve variants only when their conditions differ materially.
- Never organize by absorbed-source name; source-shaped folders preserve duplication.

Mark every capability `integrate`, `retain`, or `omit`, and every runtime dependency `generalize` or `omit`. Nothing is discarded silently.

## 3. Plan Binding and Rollback Snapshot

Advancing from planning validates complete mappings, verifies unchanged inputs, binds the canonical plan hash internally, and snapshots the target baseline before any mutation.

This workflow does not pause for approval between planning, merge, repair, validation, and rollback. Its safety comes from reversibility: mutation is confined to the bound plan's paths, plus any path recorded with `extend-scope`, and every one of them sits inside a verified snapshot taken before mutation. Any unsafe evidence restores that snapshot automatically. If the plan must change, run `revise-plan`; the coordinator rolls the target back before returning to planning.

```bash
python3 scripts/absorb.py revise-plan --run-dir <run-directory>
```

## 4. Merge

Edit the target only. Sources stay read-only for the whole run.

- Apply the bound plan as a semantic rewrite, preferring deletion and consolidation over parallel duplicate sections.
- Preserve the target name unless the bound plan changes identity, and rewrite the description from the combined trigger surface without keyword dumping.
- Preserve licenses, attribution, and provenance required by absorbed material.
- Reject secrets, machine-private paths, generated caches, and unrelated project state.
- Express vendor tool names, model names, metadata fields, command syntax, environment variables, and hidden-directory conventions in runtime-neutral terms, or omit them.

Write `apply.json` with the bound `plan_sha256`, cumulative changed files, cumulative deleted files, and notes. Paths must be target-relative and match the actual target diff.

## 5. Bounded Validation

Run the checks relevant to the changed skill:

- The repository-native check entrypoint when one exists. In this repository that is `python3 scripts/check.py`; otherwise use the host-native skill validator.
- The focused check of every changed bundled script.
- Capability coverage against `plan.json`.
- Trigger wording and reference-path inspection.
- Any target repository check named in the bound plan.

Write `validation.json` with `plan_sha256`, `passed`, `checks`, `remaining_gaps`, and `notes`, then advance. Failed validation returns to merge until the configured attempt bound.

A changed plan, a changed source, an unrecorded out-of-scope diff, a diff that contradicts the declared evidence, or exhausted attempts restore the snapshot and end the run in `rolled-back`, after preserving the in-progress target under `revisions/`. When repair needs one more file, record it with `extend-scope`; when the intent itself changed, use `revise-plan`.

Evidence the coordinator cannot read, such as a wrong field type or an empty check list, is a reporting mistake rather than unsafe execution. It is rejected without rollback, leaving the target and phase intact so a corrected file advances the run.

## 6. Orchestrator Feedback

Every run is also a test of this workflow and its coordinator against real material. A passing validation does not complete the run until `feedback.json` records the verdict:

```json
{
  "observations": [
    {
      "issue": "What the coordinator or workflow got wrong",
      "evidence": "Command, phase, or artifact that exposed it",
      "disposition": "fixed",
      "changed_files": ["scripts/absorb.py"]
    },
    {
      "issue": "Friction not addressed in this run",
      "evidence": "Where it appeared",
      "disposition": "deferred",
      "reason": "Why it can wait"
    }
  ],
  "improvements": ["Orchestrator change made because of this run"]
}
```

Use `fixed` only with the files carrying the fix, and `deferred` or `accepted` with an explicit reason. Record an empty `observations` list only when the run genuinely surfaced nothing.

Fixing the coordinator during a run usually needs paths outside the bound plan. Record those paths with `extend-scope` and keep merging:

```bash
python3 scripts/absorb.py extend-scope --run-dir <run-directory> \
  --path scripts/absorb.py --reason "<why this repair is in scope>"
```

Extensions are additive and reasoned, and they never leave the pre-mutation snapshot, so reversibility is unchanged and rollback still reverses an extended path. Use `revise-plan` when the plan's intent changed rather than its file set; it preserves in-progress work under `revisions/` before restoring the baseline.

This feedback is a completion requirement, not merge evidence: a missing or malformed verdict blocks completion without discarding a correct merge.

## Invariants

- Coordinator state owns phase, bound plan hash, rollback scope, attempts, and resume status.
- Every analyzed capability receives an explicit disposition.
- Every runtime-specific dependency receives `generalize` or `omit`.
- The target contract remains runtime-neutral.
- The bound plan hash must still match before mutation evidence is accepted.
- Source skill digests must remain unchanged.
- The actual target diff must match `apply.json` and the bound plan paths, plus any recorded scope extension.
- Every scope extension is additive and carries an explicit reason; a new plan clears prior extensions.
- Validation retries remain bounded, and every run snapshots the pre-mutation target.
- A run completes only after recording an explicit orchestrator verdict.

## Record the Absorption

After a run completes, add one record per source under [references/upstream/](../references/upstream/README.md), named for the source. It carries the upstream location, absorbed baseline digest or commit, date, and plan hash, together with absorbed coverage, deliberate exclusions, and canonical destinations. One source, one file: never fold a new source into an existing record. Note the run in [UPSTREAM.md](../UPSTREAM.md), keep run artifacts as the durable evidence, then delete any project-local source copy the run consumed.
