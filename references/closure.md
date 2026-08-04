# Design Run Closure

Close a design run by testing owner boundaries against the run's own artifacts. [review.md](review.md) owns the boundary questions themselves; this reference owns what closing a design run adds to them.

## Ask the Review Questions of Your Own Run

Work the always-run phase questions in [review.md](review.md), plus the surface questions for each capability the contract selected. They are the same boundaries either way: a boundary that would fail an audit has already failed, whether or not an auditor has looked yet.

Answer every one from the run's own artifacts. A question that cannot be answered that way is itself a finding, because the run lacks the evidence it claimed to produce. This is the difference that makes closure a distinct phase rather than a review: a reviewer reads a finished skill and may inspect anything, while closure may read only what the run recorded, so an unanswerable question convicts the run rather than the skill.

## Questions Only a Design Run Can Ask

Two boundaries are invisible from outside, because they concern what the run chose rather than what the skill now contains:

- Do the checks this run added call existing validators instead of restating their logic? A review sees a passing check; only the run knows whether its logic was duplicated to get there.
- Is setup explicit, idempotent, and separate from activation, with route-specific pre-flight before mutable state? A review observes setup that ran; only the run knows which routes were considered.

## After Real Use

Fix missed activation, ambiguous routes, repeated manual logic, unused resources, and broken assumptions with the smallest targeted change. Re-run the repository checks and the focused checks owned by each capability the contract selected.

When real use produces more than a handful of such fixes, the skill has outgrown closure: audit it with [review.md](review.md) and drive the findings with [remediate.md](../workflows/remediate.md), rather than accumulating untracked repairs at the end of a design run.

## Checks

Each question is answered by the reference that owns the boundary, and that reference's own `## Checks` section says how a violation is detected. This document adds no check of its own; it routes.

Closure itself is a judgement: the questions are passed when a reader can point at the owning reference for every one, not when they feel answered.
