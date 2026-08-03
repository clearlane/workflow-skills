# Resource Filename Convention

Name skill resources for fast scanning, stable grouping, and predictable discovery.

## Rules

1. Prefer one lowercase word when it identifies the resource without ambiguity: `settings.py`, `commands.md`, `schema.json`.
2. When one word is not enough, use a hierarchical hyphenated name with the broad family first and the specific role second: `command-create.md`, `command-review.md`, `event-validate.py`.
3. Reuse the same singular family prefix for sibling resources so lexical sorting keeps them together.
4. Put the stable category before the variable action or subtype. Use `command-create`, not `create-command`; use `worker-review`, not `review-worker`.
5. Use lowercase ASCII letters and digits. Separate filename segments with single hyphens. Do not use spaces, underscores, camel case, repeated hyphens, or generic suffixes such as `helper`, `utils`, `misc`, or `new`.
   - **Ecosystem carve-out.** A file that is an importable module in a language whose own convention forbids hyphens follows that language's convention instead, because a hyphenated name there is not importable at all. In Python this is PEP 8: `sign_document.py`, `__init__.py`. The carve-out covers importable modules and packages only — markdown, JSON, shell scripts, and standalone executables keep the hyphenated form. This is rule 8 applied to a language rather than a host.
6. Spell each segment out. Prefer a full word over an abbreviation or acronym unless the abbreviation is the domain's standard term.
7. Keep the extension conventional for the file type. The extension is not part of the one-word or hierarchical stem.
8. Preserve exact names required by a host, protocol, ecosystem, or repository contract, such as `SKILL.md`, `README.md`, or `openai.yaml`.

Apply the convention to files created or renamed by the task. Do not churn unrelated existing files solely for naming unless the requested work includes a naming migration.

## Selection Process

For every new resource:

1. Write its stable responsibility in one noun or verb.
2. Use that word as the filename if it remains clear within its directory.
3. If multiple resources share that responsibility, choose one singular family word and append the distinguishing action or subtype.
4. Check the directory's lexical order and rename any new siblings that do not group consistently.
5. Run the repository-native filename check. When none exists, run `python3 scripts/names.py <skill-root>` if this script is available in the skill being used as guidance.

## Examples

| Prefer | Avoid | Reason |
|---|---|---|
| `settings.py` | `settings_resolver.py` | One word is sufficient. |
| `command-create.md` | `create-command.md` | Family-first names group command resources. |
| `command-review.md` | `review_command.md` | Same family sorts together; hyphens replace underscores. |
| `events.md` | `event-reference.md` | Do not add a second segment without a real sibling distinction. |
| `schema-v2.json` | `new-schema.json` | Stable subject precedes the version subtype. |
| `sign_document.py` | `sign-document.py` | PEP 8 carve-out: a hyphenated Python module cannot be imported. |

## Checks

The deterministic check can reject invalid characters and separators, but it cannot prove that one word was possible or that a hierarchy is semantically correct. Review multiword stems manually:

- Is every segment necessary?
- Is the first segment the stable family?
- Do related siblings use that exact prefix?
- Would a one-word name be equally clear?
- For an importable module, does the name satisfy the language's own convention rather than the hyphenated one?
