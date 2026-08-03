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

## Selecting a Check

| Failure you want to catch | Where the check belongs |
|---|---|
| Untrusted or malformed input | Before the first mutation |
| Wrong artifact shape | Immediately after the artifact is produced |
| Broken repository invariant | Repository-native check before handoff |
| Irreversible action on a changed target | Postcondition plus revalidation at the gate |
| Silent drift between code and its documentation | Deterministic check in the repository's own checker |

Add a new checker only when no repository-native validator already answers the question.
