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

## Analysis Artifact

Write `analyses/target.json` for an existing target and `analyses/<source-id>.json` for every source:

```json
{
  "source_id": "001-example",
  "summary": "What this source contributes",
  "capabilities": [
    {
      "id": "stable-capability-id",
      "purpose": "Observable behavior or preserved constraint",
      "evidence": ["SKILL.md", "scripts/example.py"],
      "suggested_destination": "SKILL.md or references/topic.md",
      "notes": "Optional synthesis advice"
    }
  ],
  "triggers": ["user intent or context"],
  "resources": ["scripts/example.py"],
  "overlaps": [
    {
      "with": "target or another source ID",
      "topic": "shared behavior",
      "relationship": "duplicate, complement, or conflict"
    }
  ],
  "conflicts": [
    {
      "topic": "conflicting rule",
      "recommendation": "preferred resolution",
      "reason": "evidence-based reason"
    }
  ],
  "risks": ["migration or compatibility risk"],
  "runtime_dependencies": [
    {
      "id": "vendor-tool-name",
      "symbol": "VendorTool",
      "kind": "tool, model, path, metadata, environment, or syntax",
      "evidence": ["SKILL.md"],
      "notes": "Why this is runtime-specific"
    }
  ]
}
```

## Plan Artifact

Write `plan.json`:

```json
{
  "target_contract": {
    "name": "target-skill-name",
    "description": "Combined trigger contract",
    "runtime_policy": "runtime-neutral",
    "scope": ["included jobs"],
    "non_goals": ["excluded jobs"]
  },
  "capability_map": [
    {
      "key": "001-example:stable-capability-id",
      "decision": "integrate",
      "destination": "references/topic.md",
      "reason": "Canonical home for this capability"
    }
  ],
  "decisions": [
    {
      "topic": "design choice",
      "decision": "selected behavior",
      "sources": ["target", "001-example"],
      "reason": "why"
    }
  ],
  "file_operations": [
    {
      "op": "update",
      "path": "SKILL.md",
      "purpose": "Unify activation and workflow",
      "sources": ["target", "001-example"]
    }
  ],
  "omitted_items": [
    {
      "item": "obsolete guidance",
      "reason": "superseded by runtime behavior"
    }
  ],
  "runtime_adapter_map": [
    {
      "key": "001-example:vendor-tool-name",
      "decision": "generalize",
      "destination": "references/adapters.md",
      "reason": "Keep capability without vendor syntax"
    }
  ],
  "risks": ["risk requiring review"],
  "validation_commands": ["python3 scripts/check.py"]
}
```

For `omit`, `reason` is required and `destination` may be absent. For `integrate` and `retain`, `destination` is required. Every capability key from all analyses must appear exactly once, and every runtime dependency key exactly once with `generalize` or `omit`; both require a reason, and `generalize` requires a destination.

## Merge Evidence

`apply.json` records the bound `plan_sha256`, cumulative `changed_files`, cumulative `deleted_files`, and `notes`. `validation.json` records the bound `plan_sha256`, `passed`, a non-empty `checks` list of `name`, `command`, and `exit_code`, plus `remaining_gaps` and `notes`. A passing validation cannot contain a failed check or a remaining gap.
