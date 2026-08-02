# Review a Workflow Skill

Audit an existing skill against the contracts this repository already owns, without re-deriving those contracts in review prose. The coordinator at `scripts/review.py` detects the surfaces the skill actually exposes and derives the phase list from that evidence, so a skill with no workers never walks a workers review.

Review is read-only on its subject. Record findings during the run and change the skill after the verdict, or in a separate design run when the fix is a redesign.

## When to Use

Use this workflow to audit a skill before release, after absorbing sources, when activation misfires in real use, or when a skill has grown past the design that shaped it.

Do not use it for copy-editing prose, for a skill you are still designing — run [design.md](design.md) instead — or as a verification step appended to another run. Checks belong where failure becomes actionable, not in a trailing audit.

## Inputs

Require:

- One skill directory containing `SKILL.md`.
- One durable run directory outside that skill.
- Optional surface overrides when detection under- or over-claims.

## Start a Run

```bash
python3 scripts/review.py init \
  --skill <skill-path> \
  --run-dir <run-directory>
```

Init records `inventory.json` with the file and line evidence behind every detected surface. Read it before accepting the plan: detection is a keyword scan, so it proposes surfaces rather than proving them.

Correct the plan when the evidence disagrees with the skill:

```bash
python3 scripts/review.py init --skill <skill-path> --run-dir <run-directory> \
  --surface workers \
  --skip-surface packaging
```

Use `--surface` for a real surface the scan missed, and `--skip-surface` for a keyword that matched documentation rather than behavior. Inspect phase, resource, and next action at any time:

```bash
python3 scripts/review.py status --run-dir <run-directory>
```

## Work Each Phase

`status` names one phase and the resource holding the contract that phase tests. Read that resource, audit the skill against it, and record what you find:

```bash
python3 scripts/review.py record-finding \
  --run-dir <run-directory> \
  --phase <phase> \
  --severity blocking \
  --summary "<observable defect>" \
  --evidence <path>:<line>
```

Every finding needs evidence in the reviewed skill. A claim with no path is an opinion, and the coordinator rejects it. Severity meanings and the question set for each phase live in [review.md](../references/review.md).

Close the phase with the judgement it reached:

```bash
python3 scripts/review.py complete-phase \
  --run-dir <run-directory> \
  --phase <phase> \
  --note "<what held, what did not>"
```

Phases close in order, findings cannot attach to an unreached phase, and each decision persists under `decisions/` so an interrupted review resumes from artifacts rather than memory. When a surface surfaces late:

```bash
python3 scripts/review.py add-surface --run-dir <run-directory> --surface events
```

## Phases the Coordinator Always Runs

`activation` opens every review: do the triggers describe observable intent, and would a near-miss request route elsewhere correctly?

`structure` tests resource routing, one canonical home per rule, progressive disclosure, and filenames.

`safety` tests every irreversible action, trust boundary, and gate placement, whatever surfaces the skill exposes.

`verdict` closes the run. It refuses to close while any blocking finding lacks a disposition, so a review cannot pass by leaving its worst finding unanswered. Give each one an outcome first:

```bash
python3 scripts/review.py resolve-finding \
  --run-dir <run-directory> \
  --id F1 \
  --disposition fixed \
  --note "<what changed, or why the risk is accepted>"
```

Completing `verdict` writes `report.md` with every finding, disposition, and phase decision.

## Exercise the Result

Run `python3 scripts/review.py self-check` for coordinator behavior, and `python3 scripts/check.py` for the repository checks. Then review one real skill end to end and confirm the run produced findings a reader can act on without the reviewer present.
