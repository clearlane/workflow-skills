# Remediate a Reviewed Skill

Drive a skill to the quality bar that a completed review measured it against. The coordinator at `scripts/remediate.py` holds the loop: triage the review's findings, fix, re-review, repeat until the bar is met or the bound runs out.

The check on each iteration is the next review's verdict, not the fixer's own assessment. That separation is why this is a run rather than a phase of the review that produced the findings.

## When to Use

Use this workflow when a review left blocking or major findings and the fixes are worth driving to completion: a skill about to be released, one that failed an audit, one being brought up to a contract it predates.

Do not use it for a single obvious fix, where the loop costs more than the change. Do not use it to re-review: findings come from [review.md](review.md), and a remediation run that derived its own would be a second reviewer with no shared contract. Do not use it to redesign; when the fix is a redesign, run [design.md](design.md) against the skill instead.

## Inputs

Require:

- One skill directory containing `SKILL.md`.
- One completed review run directory holding `findings.json`.
- One durable run directory outside both.

## Start a Run

```bash
python3 scripts/remediate.py init \
  --skill <skill-path> \
  --review-run <review-run-directory> \
  --run-dir <run-directory> \
  --max-iterations 5
```

`--max-iterations` is the hard bound, defaulting to five. Init reads the review's findings, validates them against the review's own schema, and records which ones carry a fix obligation. A finding the review already disposed of is not one: that decision belongs to the run that made it.

Inspect phase, resource, next action, and remaining budget at any time:

```bash
python3 scripts/remediate.py status --run-dir <run-directory>
```

## Accept the Verdict

```bash
python3 scripts/remediate.py accept-verdict \
  --run-dir <run-directory> \
  --note "<what the review found and what this run will fix>"
```

A review with no open blocking or major finding is refused rather than reported as a completed remediation, because a run that iterates zero times and claims success is indistinguishable from one that fixed everything.

## Iterate

Each iteration triages every open obligation, applies the fixes, and then runs a fresh review whose counts it does not author. Record what happened in `iterations/<n>.json` against [remediation.schema.json](../schemas/remediation.schema.json), then:

```bash
python3 scripts/remediate.py record-iteration \
  --run-dir <run-directory> \
  --note "<what changed and what the re-review said>"
```

The coordinator rejects a record that skips an open obligation, decides a finding twice, restates a severity the review did not record, or triages a findings set that is no longer the review's. Dismissal is available to minor findings alone; the schema rejects a dismissed blocking or major finding, which is how a loop is stopped from terminating with the defect intact. Triage rules live in [remediation.md](../references/remediation.md).

## How a Run Ends

`complete` when a re-review reports no blocking and no major finding.

`exhausted` when the bound is reached with obligations still open. The command exits non-zero: an exhausted budget is a failure result, not a finished subject. The fixes already applied stay, and so do the artifacts.

`cancelled` when the run is stopped by hand:

```bash
python3 scripts/remediate.py cancel \
  --run-dir <run-directory> \
  --reason "<why the loop was stopped>"
```

Cancelling is not rolling back. The work already applied remains, and the run reports how far it got.

## Exercise the Result

Run `python3 scripts/remediate.py self-check` for coordinator behavior, and `python3 scripts/check.py` for the repository checks. Then drive one real review to a terminal status and confirm the outcome is legible from the run alone.
