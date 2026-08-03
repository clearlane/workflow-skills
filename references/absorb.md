# Skill Absorption Reference

Use this reference for source analysis and combined-plan synthesis during [absorb.md](../workflows/absorb.md).

## Analysis Dimensions

Inspect evidence, not headings alone:

- **Contract**: purpose, inputs, outputs, invariants, prerequisites, exclusions.
- **Activation**: trigger intents, phrases, file types, platforms, and negative boundaries.
- **Execution**: routes, phases, loops, delegation, state, plan binding, retries, rollback, and failure policy.
- **Knowledge**: domain rules, schemas, examples, decision tables, and edge cases.
- **Resources**: scripts, references, assets, templates, host metadata, and runtime adapters.
- **Checks**: validators, tests, schemas, commands, and postconditions.
- **Safety**: trust boundaries, destructive actions, secrets, external effects, and data-loss controls.
- **Provenance**: license, attribution, copied material, and upstream restrictions.
- **Runtime coupling**: vendor tool names, model names, metadata fields, hidden directories, interpolation syntax, environment variables, and invocation APIs.

Record exact evidence paths. Never infer that similarly named sections provide equivalent behavior.

## Capability Model

A capability is an observable job the target can perform or a constraint it must preserve. Use stable IDs such as `route-provider`, `validate-frontmatter`, or `resume-item-state`.

Split capabilities when they differ in trigger conditions, inputs or outputs, safety boundaries, runtime requirements, or validation method.

Do not create a capability for every paragraph. Generic writing advice, duplicated explanations, and obsolete tool names are content candidates, not preserved behavior.

## Merge Decisions

Choose one disposition for every capability:

- `integrate`: add or combine the capability into a new canonical destination.
- `retain`: the target already covers it; keep the canonical target destination.
- `omit`: exclude it with an explicit reason such as obsolete, incompatible, unsafe, out of scope, or exact duplicate with a mapped replacement.

Prefer the stronger implementation in this order:

1. User policy and target contract
2. Safer or more correct behavior
3. Deterministic executable mechanism
4. Current runtime-neutral terminology
5. Existing repository-native validator or tool
6. Lower context and maintenance cost

Keep both variants only when their conditions differ materially, and add a route or decision table instead of blending incompatible instructions.

## Conflict Policy

Classify each conflict:

- **Terminology**: normalize to current runtime-neutral names.
- **Behavior**: choose by correctness, safety, and user policy; preserve the alternative only behind an explicit route.
- **Scope**: the target contract decides; record the excluded capability explicitly.
- **Tooling**: prefer the native or already-installed tool; do not add a dependency for small orchestration.
- **Validation**: prefer an executable repository check over a prose checklist.
- **License**: do not copy incompatible or unlicensed material. Re-express general ideas only when legally permitted; otherwise omit and report.

Never resolve a conflict by keeping contradictory sections side by side.

## Runtime Dependencies

Inventory every runtime-specific dependency separately from capabilities, then map each one to:

- `generalize`: preserve the underlying behavior through a runtime-neutral contract or an isolated host adapter.
- `omit`: remove the vendor coupling because it is obsolete, unsafe, irrelevant, or already covered by generic host primitives.

Name skill validation by role rather than by one vendor script: use the repository-native validator when it exists, otherwise the host-native one.

## Scalable Target Structure

Design for repeated absorption:

- One target contract and one trigger description.
- One canonical workflow per job shape.
- References split by domain or variant, linked directly from `SKILL.md`.
- Scripts split by deterministic responsibility, not by source origin.
- Assets grouped by output use, not by absorbed skill name.
- Provenance mapped to retained material.

Avoid folders named after each absorbed source unless source identity affects runtime behavior. Source-shaped organization scales linearly and preserves duplication.

## Run Artifacts

[artifacts.md](artifacts.md) owns the run directory, the schema and version stamp, and the coordinator/agent ownership split. The field-level shape of every artifact below lives in `schemas/`, which the coordinator validates against directly; this section owns only the rules a schema cannot express.

| Artifact | Schema | Written by |
|---|---|---|
| `analyses/target.json`, `analyses/<source-id>.json` | `analysis.schema.json` | agent, one per skill analysed |
| `plan.json` | `plan.schema.json` | agent |
| `apply.json` | `apply.schema.json` | agent |
| `validation.json` | `validation.schema.json` | agent |
| `feedback.json` | `feedback.schema.json` | agent |

A complete, schema-valid example of each is in
[examples/absorb-run/](../examples/absorb-run/). They are validated by the
repository's own checks, so an example that drifts from its schema fails rather
than quietly teaching the wrong shape.

### Rules Beyond the Schema

A schema checks one document against itself. These constraints span documents, so the coordinator checks them:

- **Coverage.** Every capability key from every analysis appears in `capability_map` exactly once, and every runtime dependency key exactly once. A plan that silently drops a capability is the failure absorption exists to prevent, and no single document can detect it.
- **Disposition consistency.** `omit` requires a reason and needs no destination. `integrate` and `retain` require a destination. `generalize` requires both.
- **Identity.** That an analysis describes the source it claims to is knowable only from the inventory.
- **Binding.** That a recorded `plan_sha256` matches the plan this run bound is a fact about the run, not about the file.
- **Path safety.** That a file operation stays inside the target is a question about the filesystem.

## Merge Evidence

`apply.schema.json` owns the declaration's shape. What it cannot state: the declaration must carry the `plan_sha256` this run actually bound, and it is checked against the real target diff. The declaration exists so a mismatch is detectable at all, since without it there is nothing to compare the diff to.

Edit the target and nothing else. A path outside the bound plan is either a mistake or a deliberate widening, and only one of those is safe: record the deliberate case with `extend-scope` and a reason. An unrecorded out-of-scope path is unsafe evidence.

Malformed evidence and unsafe execution are different failures. A wrong field type means the run cannot read the evidence yet, so the coordinator rejects it and holds the phase. Rollback is reserved for evidence that proves the mutation unsafe: a changed plan or source, a diff outside the bound plan, or a diff contradicting the declaration. Because a rollback is lossy, it preserves the in-progress target first, so a scope mistake costs a re-bind rather than the merge.

## Validation Evidence

`validation.schema.json` owns the verdict's shape. What it cannot state: a passing validation cannot contain a failed check or a remaining gap, and the verdict must carry the same bound `plan_sha256` as the merge it judges.

Run the target's own checks rather than asserting the merge looks right. A validation with an empty check list is malformed, not passing: it claims a verdict no observation supports.

Retries are bounded. A failed validation returns the run to `merge` so the next attempt has the previous verdict to work from, and each attempt is preserved rather than overwritten. Exhausting the bound rolls the target back and exits as a failure, because a rolled-back run reported as a success defeats the bound entirely.

## Orchestrator Feedback

Absorption is the one workflow that runs itself against unfamiliar material every time, so each run is the best available test of the coordinator. Treat friction as a finding rather than an obstacle to work around:

- A coordinator crash, an unhelpful rejection, or evidence the schema cannot express is a defect. Record it and prefer fixing it in the same run.
- A rule the run had to violate to make progress is either a wrong rule or a missing capability. Do not silently bypass it.
- Repeated manual steps between phases belong in the coordinator.

`feedback.schema.json` owns its shape. Each observation needs `issue`, `evidence`, and a `disposition` of `fixed`, `deferred`, or `accepted`. A `fixed` observation must name the `changed_files` carrying the fix, so the claim is checkable against the diff. A `deferred` or `accepted` observation must state its `reason`.

Coordinator fixes are target edits like any other, so they stay inside a recorded scope. Record the extra paths with `extend-scope` and a reason, which keeps the correct merge and still confines mutation to the pre-mutation snapshot. Reserve `revise-plan` for a change of intent. Never widen a diff silently: an unrecorded out-of-scope path is still unsafe evidence and still rolls the run back.

## Checks

- `scripts/absorb.py` enforces the mechanical parts: evidence bound to a digest, a plan that no longer matches its evidence rejected, a snapshot restored on unsafe execution.
- The target's own checks prove the merge did not break it, and run after every merged capability rather than once at the end.
- Whether a capability was genuinely absorbed rather than copied is a judgement. Test it by deleting the source and asking whether the target still answers the question the source answered.
