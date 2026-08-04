# Absorbed Source: Plugin-Dev Components

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev), the `agent-creator`, `skill-reviewer`, and `plugin-validator` workers plus the `create-plugin` command |
| Baseline kind | Local tree digest of the installed snapshot; upstream `main` is mutable, so no commit was resolvable at absorption time |
| Absorbed baseline | Snapshot tree SHA-256 `c0ecbcda288265dbebdceec9dfa169ddbca8deca5a1d9757b6f09874eaa56b85` |
| Absorbed on | 2026-08-03 |
| Plan hash | One run absorbed this alongside `skill-improver`, so both share this digest: `f994c782d2e788fdb4b4823324902ae46a5d253b2f8866dbcff49d087f5557dd` |

The bundle's skills were absorbed separately in earlier runs; this record covers only its workers and command, which those runs did not read.

Absorbed:

- Turning a one-line description into a worker contract: extract the implied intent, narrow the scope by default, write selection conditions as triggering situations, and structure instructions as responsibilities, method, criteria, and output.
- Edge-case enumeration as a contract obligation, including that a warning must not become a failure and an unreadable item is reported and skipped rather than fatal to the batch.
- The generate-then-validate chain: route each generated component to the validator that owns its contract, then hand back what activates it, where it lives, and the exact next validation.
- Scaffolding the deliverable before any component exists, with directories only for the selected kinds, and the kind selection approved as an artifact first.
- Per-kind activation verification, which supplies the procedure the target's registration-versus-activation split named but never gave.
- Distribution readiness whose documentation obligations are selected by the kinds actually present.
- Named decision checkpoints that stop for cost and direction rather than irreversibility, including refusing to treat agreement as a resolved question.
- The credential and transport audit, with example files scanned by name because sample material is where a secret most often survives review.
- A finding carrying a concrete remedy, which a remediation run triages against.

Reworked or excluded:

- Excluded the guided build's prose phase list: the design coordinator already derives phases from recorded capabilities, and a prose list can neither resume nor prove a bound held. Only the stages it added landed, under the existing packaging capability.
- Folded its skill-quality audit into the target's own review contract rather than creating a second owner for activation and structure rules.
- Generalized worker metadata fields, execution tiers, host tool names, command metadata, invocation namespacing, event and external-tool configuration paths, the distribution catalog, and the project instructions file into capability contracts.
- Excluded the worker colour palette, the host skill-loading verb, named host validator scripts, and host CLI invocations.

Canonical destinations:

- `references/workers.md`
- `references/packaging.md`
- `references/checks.md`
- `workflows/design.md`
- `schemas/findings.schema.json`
