# Remediation Runs

A review ends with a verdict and changes nothing. Remediation is the run that consumes that verdict and drives the skill to the quality bar: fix, re-review, repeat, until the bar is met or the budget is gone. The workflow is [remediate.md](../workflows/remediate.md); what a finding is and what each severity obliges stay in [review.md](review.md), and the loop's own properties stay in [patterns.md](patterns.md#5-bounded-feedback-loop).

Use it when a completed review left findings worth acting on. Skip it for a single obvious fix: a loop that costs more to drive than the change it makes is overhead.

## Why It Is a Separate Run

Review is read-only on its subject. That is what makes its verdict evidence rather than a description of work the reviewer already did, and it is why remediation cannot be an extra review phase. The separation buys the property the loop depends on: the check on an iteration's fix is the next review's verdict, produced by a run that did not make the fix and cannot rationalize it.

The consequence is a hard rule. A remediation iteration never grades its own work. It records what it changed and then defers to a fresh review, whose counts it does not author.

## Triage

Each iteration takes the current findings and decides every one of them, in severity order:

| Severity | Obligation | May the iteration end with it open? |
|---|---|---|
| `blocking` | Fix before anything else in this iteration | No |
| `major` | Fix | Only by deferring to a later iteration, with a reason |
| `minor` | Judge individually | Yes, once judged: fixed, deferred, or dismissed |

Dismissal is available to minor findings alone, because dismissing a finding that carries a fix obligation is how a loop terminates with the defect intact. Judge each minor finding one at a time, against the three questions [review.md](review.md#disposition) owns; dismissing the whole class in one move answers none of them.

Findings arrive from the review's artifact, not from re-reading the skill. A remediation run that re-derived its own findings would be a second reviewer with no shared contract, and the two would drift.

## Ending a Run

Three ways to stop, each recorded as its own terminal status because a caller cannot tell them apart from the subject alone:

- **complete** — a re-review found no blocking and no major finding. Minor findings may remain: they carry no fix obligation once judged, so requiring zero would make the bar a style gate.
- **exhausted** — the bound ran out with obligations still open. This is a failure result: reporting it as completion makes an unfinished subject indistinguishable from a finished one.
- **cancelled** — a stop entrypoint ended the run. The fixes already applied stay: partial improvement is a legitimate outcome, unlike a partial merge, which its coordinator rolls back. The run reports how far it got.

Every terminal status retains the run's artifacts. Deleting them at exit destroys the record of how many iterations ran and why the loop stopped, which is the only evidence that the run happened at all.

Exit before the bound when an iteration fails for a reason no further iteration can fix: the subject is unreadable, a prerequisite is missing, the review artifact does not validate. Spending the remaining budget reproducing one failure hides its cause.

## Checks

- Every finding in the review's artifact is decided by the iteration that claims to have triaged it; a missing decision fails the iteration rather than passing silently.
- No iteration record dismisses a blocking or major finding, which the schema rejects.
- The recheck counts come from a review run named in the record, never from the iteration's own assessment.
- A run that reaches its bound with obligations open exits with a failure status, and the artifacts survive.
- `python3 scripts/remediate.py self-check` exercises the loop, the bound, cancellation, and each terminal status.
