# Design Run Closure

Close a design run by testing owner boundaries. Each question probes one boundary; the reference that owns the boundary holds the rule itself.

## Closure Questions

- Does executable code own ordering, branching, and bounded retries, with interrupted work resumable from durable state?
- Is concurrency set by runtime configuration rather than a fixed prose batch size?
- Are destructive actions gated immediately before execution, or confined to a provably restorable snapshot?
- Do checks call existing validators instead of restating their logic?
- Does each adapter — event, external-tool, worker, command, settings — own exactly its own boundary while the coordinator retains global state?
- Are runtime-specific names and syntax confined to adapters?
- Is every external input validated before use, without raw shell interpolation?
- Is setup explicit, idempotent, and separate from activation, with route-specific pre-flight before mutable state?
- Are volatile permissions, target identity, locks, and destructive scope revalidated at point of use?
- Does each rule have exactly one canonical home, with no duplicated prose or unused scaffolding?
- Do new or renamed resources follow the filename convention?

A question that cannot be answered from the run's own artifacts is itself a finding: the run lacks the evidence it claimed to produce.

## After Real Use

Fix missed activation, ambiguous routes, repeated manual logic, unused resources, and broken assumptions with the smallest targeted change. Re-run the repository checks and the focused checks owned by each capability the contract selected.

Closure differs from review. This file closes a run that just designed or refactored a skill. Auditing an existing skill from the outside follows [review.md](review.md) instead.

## Checks

Each question above is answered by the reference that owns the boundary, and that reference's own `## Checks` section says how a violation is detected. This document adds no check of its own; it routes.

Closure itself is a judgement: the questions are passed when a reader can point at the owning reference for every one, not when they feel answered.
