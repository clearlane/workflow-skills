# Check and Approval Placement

Decide where a workflow proves itself. Placement is the design decision; the checks themselves belong to the repository, not to prose.

## Placement Rules

Do not append a generic "verification phase" to every workflow. Put checks where failure becomes actionable:

- Validate inputs before mutation.
- Run schema or contract checks after producing the relevant artifact.
- Run repository-native checks such as `make check`, tests, linters, or validators before handoff when the task changes validated surfaces.
- Use postconditions around irreversible actions when needed for safety or data-loss prevention.

Prefer existing deterministic checks. Do not restate their logic as prompt instructions.

## Approval Placement

Put the approval gate immediately before the irreversible action, never at the start of a run whose scope can still change. The gate sequence itself is a safety boundary owned by the core instruction file; this reference decides only where in the workflow it sits.

Revalidate volatile facts at the point of use: permissions, target identity, locks, and destructive scope. A fact checked during analysis is not a fact at execution time.

## Decision Checkpoints

An approval gate stops for irreversibility. A checkpoint stops for cost and direction: a plan the user is about to pay for, a selection that determines everything built after it. Name the checkpoints in the contract, so stopping is a property of the workflow rather than a judgement the agent makes mid-run, and so a user who wants fewer of them can see which ones exist.

A checkpoint that gathers missing input is not satisfied by agreement. "Whatever you think is best" leaves the question open, so answer it with concrete recommendations and their consequences, and treat it as unresolved until one is chosen. Present what is still undecided grouped by what it affects, not one question at a time.

## Selecting a Check

| Failure you want to catch | Where the check belongs |
|---|---|
| Untrusted or malformed input | Before the first mutation |
| Wrong artifact shape | Immediately after the artifact is produced |
| Broken repository invariant | Repository-native check before handoff |
| Irreversible action on a changed target | Postcondition plus revalidation at the gate |
| Silent drift between code and its documentation | Deterministic check in the repository's own checker |
| A committed credential or insecure transport | Scan of every shipped file, including examples, before publication |

Add a new checker only when no repository-native validator already answers the question.

## Secrets and Transport

Scan every file the deliverable ships, and scan the example files by name. Sample material is where a credential most often survives review, because a reader classifies it as illustrative and a scanner does not. A hardcoded credential, a token in a configuration value, or an external service reached over cleartext transport is a blocking finding, not advice: publication makes it irreversible.

## Checks

- `scripts/check.py` proves placement rules that are structural: an approval gate that is prose rather than a bound runtime event, and a check appended as a generic trailing phase rather than placed where failure becomes actionable.
- Whether a check sits at the right boundary is a design judgement no parser makes. Review it by asking what a reader would have to do differently on failure, and moving the check to where that action is still possible.
