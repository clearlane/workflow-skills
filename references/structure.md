# Runtime-Neutral Workflow Skill Structure

Package workflow behavior so activation stays precise, core context stays small, and repeated work remains deterministic.

## Contract and Use Cases

Start with representative requests and expected outcomes. Record:

- Purpose and non-goals.
- Positive, implicit, and negative activation cases.
- Inputs, outputs, prerequisites, trust boundaries, and side effects.
- Repeated decisions or logic needing deterministic implementation.
- Domain knowledge unavailable from project files or current host documentation.

Do not create skill when direct instruction, existing project command, or current host feature already solves task.

## Resource Routing

| Material | Destination |
|---|---|
| Activation, invariants, coordinator entry, safety boundaries | Core instruction file |
| Repeated deterministic logic | `scripts/` or repository-native executable location |
| Detailed domain knowledge, schemas, decision tables | `references/` |
| Runnable or copyable samples | `examples/` when host or repository uses them |
| Templates, media, boilerplate, output-only files | `assets/` |

Create only resources that task needs. Delete generated placeholders and empty scaffolding.

## Progressive Disclosure

- Keep activation metadata concise and specific.
- Keep core instructions focused on execution-critical guidance and direct resource links.
- Load detailed references only when their route applies.
- Add search hints for large references instead of copying summaries into core.
- Keep one canonical home for each rule, schema, or example.
- Prefer executable scripts for repeated exact transformations and checks.

Resource names should describe function, not absorbed source identity. Apply [naming.md](naming.md): prefer one-word filenames and use family-first hierarchical names only when one word is insufficient.

## Activation Metadata

Describe observable user intent and task context:

- What skill does.
- When it should activate.
- Important trigger variants.
- When it should not activate or which route handles overlap.

Use host-supported metadata grammar. Do not require one prose person, fixed phrase, frontmatter field, or example markup across runtimes.

## Instruction Style

- Use direct, action-oriented instructions.
- Include non-obvious procedure, constraints, safety, and domain knowledge.
- Remove motivational prose, repeated summaries, and facts available from current host documentation.
- Keep control flow in coordinator, not numbered prose that must be remembered.
- Link each resource directly from core instructions with purpose and use condition.

## Deployment Shapes

### Host-Managed Skill

Use host discovery and packaging adapter. Adapter owns directory, metadata, namespace, installation, reload, and distribution syntax. When the skill ships inside a bundle with other components, follow [packaging.md](packaging.md) for the manifest, discovery, portable-path, and distribution contract.

Inside a bundle, each skill stays one self-contained directory: its required core instruction file at the directory root, with its own references, examples, scripts, and assets beneath it. Do not scatter one skill's resources across bundle-level directories shared with other components.

### Standalone Skill

Use repository-native initializer or minimum required layout. Validate before packaging. Use host or repository package format only when deployment requires artifact.

Never assume one directory tree, archive type, or CLI across runtimes.

## Validation and Activation Tests

Run available executable checks for:

- Required metadata and core instruction presence.
- Referenced path existence and direct-link integrity.
- Script syntax, executability, focused behavior, and trust boundaries.
- Duplicate or unreachable resources.
- Filename syntax plus manual review of one-word preference and family-first hierarchy.
- Host discovery and metadata schema.
- Positive, negative, overlap, and missing-input activation scenarios.
- Representative task proving skill improves outcome, not only that it loads.

Use repository-native validator before adding another checker.

## Iteration

After real use, record:

- Missed or over-broad activation.
- Missing context, ambiguous route, or duplicated guidance.
- Repeated manual logic suitable for script.
- Resource never loaded or loaded unnecessarily.
- Broken assumptions, edge cases, and validation gaps.

Make smallest change that fixes observed behavior. Re-run activation and focused task checks.
