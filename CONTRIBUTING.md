# Contributing

## Run the checks

```bash
python3 -m pip install -r requirements.txt
python3 scripts/check.py
```

This is the same suite CI runs, so a green local run means a green pull request. It needs Python 3.10 or later. Install [`ruff`](https://docs.astral.sh/ruff/) to get the lint check rather than a silent skip; its rules and the supported Python floor live in `pyproject.toml`.

External link checking is opt-in, because it reaches the network and a briefly unreachable host is not a defect in your change:

```bash
CHECK_EXTERNAL_LINKS=1 python3 scripts/check.py   # needs lychee
```

## What the checks enforce

Most of these exist because the invariant broke once and nothing noticed:

- **One canonical home per topic.** A repeated H2 in one document, or a second contract for a concern that already has an owner, fails.
- **Every resource is reachable.** A reference or workflow that no entry document links to is unreachable, and a README entry pointing at a missing file is a dead map.
- **Every derived phase has a distinct owner.** A phase whose resource is the document that dispatched the coordinator answers "what do I read now?" with "the file you came from".
- **Runtime neutrality.** Core guidance carries no host-specific syntax. Host syntax belongs in an adapter.
- **Format bounds.** `SKILL.md` frontmatter stays inside the limits in [references/structure.md](references/structure.md), which the Agent Skills format enforces by rejection.
- **Shebang and executable bit agree.** A file claiming an interpreter must be runnable, and vice versa.

## Adding a check

Prefer an existing validator. Add a new one only when nothing already answers the question, and make it fail on a real violation before you keep it: a check that cannot fail is indistinguishable from one that passes.

Checks that carry their own logic belong behind a `self-check` subcommand, so a check that quietly stopped rejecting bad input is itself caught.

## Changing guidance

Guidance stays runtime-neutral. When a change touches a coordinator's phases or capabilities, update the contract that owns them in the same commit; the suite checks that code and prose still agree.

Filenames use one lowercase word or a family-first hyphenated stem, so they survive every filesystem a skill gets installed onto.

## Commits

Write what changed and why the previous state was wrong. The existing history is the reference.
