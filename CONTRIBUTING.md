# Contributing

## Run the checks

```bash
python3 -m pip install -r requirements.txt
python3 scripts/check.py
```

This is the same suite CI runs, so a green local run means a green pull request on the runtime you ran it with. It needs Python 3.10 or later, and CI runs both ends of that range; `CHECK_FLOOR=1` below runs the other end here.

`requirements.txt` installs the check dependencies and [`ruff`](https://docs.astral.sh/ruff/) together, which is why the lint and format checks run rather than silently skipping. Every version bound, and the supported Python floor, lives in `pyproject.toml` and nowhere else.

External link checking is opt-in, because it reaches the network and a briefly unreachable host is not a defect in your change:

```bash
CHECK_EXTERNAL_LINKS=1 python3 scripts/check.py   # needs lychee
```

So is running the suite on the declared floor, because it downloads that interpreter the first time. CI runs both ends of the matrix, so this is only needed to see a version-dependent failure without pushing:

```bash
CHECK_FLOOR=1 python3 scripts/check.py            # needs uv
```

## What the checks enforce

Most of these exist because the invariant broke once and nothing noticed:

- **One canonical home per topic.** A repeated H2 in one document, or a second contract for a concern that already has an owner, fails.
- **Every resource is reachable.** A reference or workflow that no entry document links to is unreachable, and a README entry pointing at a missing file is a dead map.
- **Every derived phase has a distinct owner.** A phase whose resource is the document that dispatched the coordinator answers "what do I read now?" with "the file you came from".
- **Runtime neutrality.** Core guidance carries no host-specific syntax. Host syntax belongs in an adapter.
- **Format bounds.** `SKILL.md` frontmatter stays inside the limits in [references/structure.md](references/structure.md), which the Agent Skills format enforces by rejection.
- **Shebang and executable bit agree.** A file claiming an interpreter must be runnable, and vice versa.
- **Licence boundary is visible per file.** This repository is dual-licensed, so every file under `scripts/` carries an SPDX header naming the terms that cover it. See [License](README.md#license).
- **Formatting is not a review comment.** `ruff format` owns the answer, so whitespace disagreements fail a check instead of a pull request conversation.

## Adding a check

Prefer an existing validator. Add a new one only when nothing already answers the question, and make it fail on a real violation before you keep it: a check that cannot fail is indistinguishable from one that passes.

Checks that carry their own logic belong behind a `self-check` subcommand, so a check that quietly stopped rejecting bad input is itself caught. Every script in `scripts/` exposes it under that exact name; [AGENTS.md](AGENTS.md#changing-a-check) owns what `check.py` demands of one and is the place to change that rule.

## Changing guidance

Guidance stays runtime-neutral. When a change touches a coordinator's phases or capabilities, update the contract that owns them in the same commit; the suite checks that code and prose still agree.

Filenames use one lowercase word or a family-first hyphenated stem, so they survive every filesystem a skill gets installed onto. Importable Python modules follow PEP 8 instead, because a hyphenated module cannot be imported; [references/naming.md](references/naming.md) owns both rules.

[AGENTS.md](AGENTS.md) states the same contract for agents working in this repository, including the judgements the checks cannot make.

## Commits

Write what changed and why the previous state was wrong. The existing history is the reference.
