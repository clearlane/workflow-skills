# Absorbed Source: Skill Improver

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`trailofbits/skills/plugins/skill-improver`](https://github.com/trailofbits/skills/tree/main/plugins/skill-improver), absorbed when the repository was named `trailofbits/claude-plugins` |
| Baseline kind | Local tree digest of the installed snapshot; upstream `main` is mutable, so no commit was resolvable at absorption time |
| Absorbed baseline | Snapshot tree SHA-256 `4431fa58669d6e5f863284eeda1f40f110564ce5bfe876b312858fe6045edaef` |
| Absorbed on | 2026-08-03 |
| Plan hash | One run absorbed this alongside `plugin-dev-components`, so both share this digest: `f994c782d2e788fdb4b4823324902ae46a5d253b2f8866dbcff49d087f5557dd` |

Absorbed:

- The remediation loop itself: consume a completed review verdict, triage, fix, re-review, repeat under a bound, with the re-review rather than self-assessment as the check on each fix.
- The fix obligation each severity class carries, which is what makes such a loop terminable, and per-finding adjudication of the lowest class.
- Loop termination properties: an exact whole-line completion signal rather than a natural-language self-report, a validated bound override with a documented default, a non-progress exit for failures no further iteration can fix, and named rejection of the self-serving early exits.
- Handler-issued continuations: re-entrancy detection, run-scoped ownership so concurrent runs cannot act on each other, and a continuation payload carrying position and pointers while the method stays in the skill.
- Command-adapter rules: resolving a loosely named subject to exactly one before any state exists, and a cancel entrypoint that ends a run without reverting its work.
- Best-effort pre-flight paired with a runtime backstop, stated as a limit rather than as certainty.

Reworked or excluded:

- Kept the target's `blocking`/`major`/`minor` scale, which ranks consequence to the user, over the source's classes defined by one host's parse and index failures; only the obligation column was absorbed, with `critical` mapped onto `blocking`.
- Refused the source's review-that-edits-its-subject shape. Review stays read-only, and remediation is the successor run, which is what makes the re-review an independent check.
- Refused deletion of run state at every exit and the zero exit on bound exhaustion: both make a spent budget indistinguishable from a met bar. Exhaustion is its own terminal status and exits non-zero, with artifacts retained.
- Excluded transcript scraping for the completion signal, hardcoded dependency search paths, ownership inferred from transcript text, and the host's event names, payload keys, bundle-root variable, interpolation token, and delegated reviewer handle.

Canonical destinations:

- `references/remediation.md`
- `scripts/remediate.py`
- `workflows/remediate.md`
- `schemas/remediation.schema.json`
- `references/review.md`
- `references/patterns.md`
- `references/events.md`
- `references/commands.md`
- `references/setup.md`
