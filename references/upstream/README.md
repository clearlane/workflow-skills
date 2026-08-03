# Absorbed Sources

One file per absorbed source. Each record carries the source location, baseline
digest, absorption date, and bound plan hash, followed by what was absorbed,
what was reworked or excluded, and the canonical destinations that now own the
behavior.

Provenance scales by adding a file rather than by growing a single registry that
every future absorption has to edit.

Record only sources a reader can obtain, meaning a skill installable from its
published repository. Local experiments and one-off scratch skills leave no
record here, because provenance a reader cannot resolve is not provenance.

| Source | Absorbed on | Record |
|---|---|---|
| `designing-workflow-skills` | 2026-08-01 | [designing-workflow-skills.md](designing-workflow-skills.md) |
| `command-development` | 2026-08-01 | [command-development.md](command-development.md) |
| `agent-development` | 2026-08-01 | [agent-development.md](agent-development.md) |
| `hook-development` | 2026-08-01 | [hook-development.md](hook-development.md) |
| `mcp-integration` | 2026-08-01 | [mcp-integration.md](mcp-integration.md) |
| `skill-development` | 2026-08-01 | [skill-development.md](skill-development.md) |
| `plugin-settings` | 2026-08-01 | [plugin-settings.md](plugin-settings.md) |
| `plugin-structure` | 2026-08-02 | [plugin-structure.md](plugin-structure.md) |

Moving external specifications that guidance generalizes from are tracked the
same way, because they carry the same refresh risk as an absorbed skill: the
source changes and nothing here notices.

| Tracked specification | Revision | Record |
|---|---|---|
| Model Context Protocol | 2026-07-28 | [mcp-specification.md](mcp-specification.md) |

Every record states its baseline kind, because a commit SHA and a local tree
digest are both hex strings and mean entirely different things: one resolves
upstream, the other only against a snapshot this repository took. Reading a
local digest as a commit sends a refresh looking for a revision that does not
exist. Future refreshes should record the exact upstream commit when available,
because `main` is mutable.

A completing absorption run writes `provenance.json` in its run directory with
these same fields, so the record added here is transcribed from the run rather
than reconstructed later. Sources absorbed in one run share a plan digest and a
run id; a repeated digest is a batched run, not a mistake.

Absorption history and coordinator changes live in
[UPSTREAM.md](../../UPSTREAM.md).

## Adding a Record

After an absorption run completes, first confirm the source is installable from
its published repository. If it is not, record the work in
[UPSTREAM.md](../../UPSTREAM.md) history and stop here.

Otherwise add one file named for the source, using the existing records as the
shape. Add its row to the table above. Do not fold a new source into an existing
record; one source, one file.

## Refreshing a Source

When any source changes upstream:

1. Record repository, exact commit SHA, source path, and review date.
2. Compare the changed source tree against the baseline digest in that source's record.
3. Classify each change as new capability, correctness or safety fix, runtime-adapter syntax, duplicate guidance, obsolete behavior, or provenance change.
4. Prefer runtime-neutral behavior, deterministic mechanisms, current protocol semantics, and repository-native validators.
5. Do not copy host-specific paths, tool names, model names, metadata fields, command syntax, event names, or unverified lifecycle claims into core guidance.
6. Run the absorption workflow in [absorb.md](../../workflows/absorb.md) with a fresh source snapshot and this skill as target. Let the coordinator produce complete capability and runtime-dependency maps.
7. Update that source's record with the new baseline digest or commit, absorption date, plan hash, retained changes, and explicit omissions.
8. Run the skill validator, link check, runtime-neutral token scan, native discovery, focused script checks, and `git diff --check`.

Run `python3 scripts/check.py` for the deterministic portion of step 8.

Review upstream releases or source-path changes periodically even when a
changelog does not name these skills. Useful fixes may arrive through
repository-wide sweeps.

A source with no upstream cannot be refreshed. Its record is a historical
account of where the behavior came from, not a tracking entry.
