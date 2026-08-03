# AGENTS.md

Working contract for agents changing this repository.

`SKILL.md` is the product: it tells an agent how to design *someone else's* skill. This file is the process: it tells an agent how to change *this repository*. When the two appear to conflict, this file wins for repository work and `SKILL.md` wins for skill design.

## The one command

```bash
python3 -m pip install -r requirements.txt
python3 scripts/check.py
```

`scripts/check.py` is the only check entrypoint. It runs every deterministic check, including each script's own `self-check`. Do not add a parallel entrypoint, a Makefile target that runs a subset, or a CI step that names individual checks: the list lives in the script so CI, `CONTRIBUTING.md`, and this file cannot drift from it.

A change is not done until that command exits zero.

## Rules that the checks cannot catch

The suite proves structure. These are the judgements it cannot make.

**One canonical owner per contract.** Before writing a paragraph, find the resource that already owns the concern and link to it. A second, slightly different statement of the same rule is the failure mode this repository is built to prevent. `references/` holds one contract per concern; `workflows/` holds process and defers to those contracts.

**Control flow belongs in a coordinator.** If a change adds ordering, branching, a bound, a retry, or a resume point to a workflow document in prose, it belongs in `scripts/` instead. Prose cannot resume and cannot prove a bound held.

**Guidance stays runtime-neutral.** Core guidance names capabilities, never a specific host's syntax, tool names, or file paths. Host-specific material belongs in an adapter document or `agents/`. The token scan catches known vendor strings, not new ones.

**Explain why, not what.** Comments and commit messages state what the previous state got wrong. The code already says what it does. Existing history and existing docstrings are the reference for tone and depth.

**Fix the cause.** A failing check is evidence about the repository, not an obstacle. Do not add an exemption, widen a pattern, or delete an assertion to make a check pass without a stated reason for why the check was wrong.

## Changing a check

Prefer an existing validator. A new check must be shown to fail on a real violation before it is kept: introduce the violation, watch it fail, revert. A check that cannot fail is indistinguishable from one that passes.

Checks carrying their own logic go behind a `self-check` subcommand, so the checker itself is checked.

## Dependencies

`pyproject.toml` is the single source of truth for versions and the supported Python floor. `requirements.txt` is a pointer to it, kept because CI caches on it. Never add a version bound anywhere else, including in a workflow file.

The floor is load-bearing: `scripts/document.py` evaluates a PEP 604 union at class-creation time, so it fails on import below the declared minimum. CI runs the floor and the current release.

## Filenames

`references/naming.md` owns the convention and `scripts/names.py` enforces it. One lowercase word, or a family-first hyphenated stem. Importable Python modules follow PEP 8 instead, because a hyphenated module cannot be imported.

## Commits

Commit as the work lands, not in one batch at the end. Each commit should leave `scripts/check.py` green.

Write what changed and why the previous state was wrong.
