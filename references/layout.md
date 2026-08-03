# Layout Judgment

Use this reference while diagnosing a layout during [restructure.md](../workflows/restructure.md). It decides whether a structure is actually wrong; [migration.md](migration.md) decides how to change it safely.

Layout follows evidence, not a universal folder template. The first question is never "what is the ideal tree" but "what do the manifests, discovery rules, and build tools in this scope already require".

## Classify Before Proposing

Name the shape of the scope first. Each shape protects different contracts.

| Shape | Protected contracts |
|---|---|
| Skill or bundle | Host discovery paths, core instruction file at the directory root, manifest fields, component locations, portable bundle-root references |
| Single application | Runtime, test, configuration, docs, and operational ownership; framework discovery rules |
| Library or package | Import paths, exported symbols, publication contents, generated declarations, consumer fixtures |
| Monorepo or workspace | Workspace roots and package boundaries; shared code needs proven consumers and a stable contract |
| CLI | Executable names, entrypoint declarations, completions, manpages, bundled templates |
| Plugin or extension | Host manifests, activation entrypoints, schemas, localization, packaging exclusions |
| Infrastructure | Modules, environments, stacks, state backends, policies, pipelines |
| Documentation or content | Link roots, navigation configuration, generated indexes, asset pipelines |

For a skill or bundle, [packaging.md](packaging.md) owns the discovery and manifest contract, and [structure.md](structure.md) owns which material belongs in scripts, references, examples, and assets. This reference only decides whether the current arrangement violates them.

## Ecosystem Evidence

Read the manifests and observe actual tool behavior. These are prompts for what to inspect, not required trees.

- **JavaScript and TypeScript**: package manifest, workspace configuration, compiler config, exports and imports maps, bundler aliases, test and lint config, publication file lists.
- **Python**: project manifest, build backend, package discovery, namespace packages, console scripts, test paths, type-checker configuration, whether a source layout is already intended.
- **Go**: module and workspace files, internal and command directories, generated files, embed directives, import paths.
- **Rust**: workspace members, crate manifests, targets, examples, benches, build scripts, include paths.
- **JVM and .NET**: source-set conventions, namespaces, solution and project files, generated sources, resources, publication configuration.
- **Other ecosystems**: follow package-manager and framework autoload or discovery rules before proposing any move.

Never assume a conventional directory is correct when the framework or package already uses a recognized alternative. Moving a package can change imports and installed behavior even when local tests pass.

Always inspect the cross-cutting surfaces a move can break: continuous integration and release workflows, container files and build contexts, infrastructure definitions, code-generation inputs and outputs, database migrations and fixtures, documentation links, shared tooling configuration, ownership and license metadata, and submodules, symlinks, large-file storage, or vendored dependencies.

## Classify Every Observation

Mark each observation `confirmed`, `preference`, `deliberate-exception`, or `blocked`. Only confirmed findings may enter a proposal.

A finding is confirmed when:

- A file's location contradicts active framework, build, package, host-discovery, or test-discovery rules.
- One conceptual owner is split across unrelated roots, causing duplicated configuration, ambiguous imports, or drift.
- Generated output is mixed with hand-maintained source and ownership is unclear.
- Runtime code, tests, fixtures, examples, migrations, or assets are attached to the wrong package or deployment unit.
- Root-level clutter obscures entrypoints and the files have an evidenced canonical home.
- Old paths, duplicate trees, abandoned scaffolds, or copied packages remain after a completed migration.
- Boundaries permit accidental cross-layer imports or circular ownership.
- Documentation, scripts, continuous integration, or deployment configuration references stale paths.
- Naming or case differences break portability on case-sensitive systems.

A finding is only a preference when it replaces one accepted convention with another without measurable benefit, adds a familiar directory name for its own sake, deepens a shallow tree without distinct ownership, renames for style while creating broad churn, or reorganizes by technical layer where the scope deliberately uses domain ownership or the reverse.

## Test a Proposed Structure

- **Discoverability**: can a contributor predict where a new related file belongs?
- **Ownership**: does each directory have one coherent reason to change?
- **Coupling**: do boundaries follow dependency and deployment relationships?
- **Tool compatibility**: do framework, build, and host discovery still find every moved file?
- **Public stability**: are imports, package contents, entrypoints, and APIs preserved or explicitly migrated?
- **Operational alignment**: are pipelines, containers, deployment, migrations, and generated artifacts still correctly owned?
- **Scale**: does the target solve current evidence without speculative hierarchy?
- **Reversibility**: can every move be undone from version control or the operation manifest?

Prefer moving an existing file over recreating it. Avoid deep nesting and generic dumping grounds such as `utils`, `misc`, `common`, or `shared` that conceal ownership, and name resources by function rather than by origin, following [naming.md](naming.md).

## Priority

1. Correctness and broken tool or host discovery.
2. Security, deployment, migration, and publication risk.
3. Ambiguous ownership and duplicated structural sources of truth.
4. Contributor navigation and root-level clarity.
5. Cosmetic consistency.

Do not execute priority 5 alone unless the user explicitly asks for stylistic normalization.

## Checks

- `scripts/inventory.py` reports the observed tree without mutating it, which is the evidence a proposal must cite.
- Discovery survival is deterministic and belongs in the repository's own checks: build inputs, test collection, publication sets, and host discovery all still resolve after a move. [migration.md](migration.md) owns the ordering that keeps them resolvable.
- The eight questions above are judgements a parser cannot make. Answer them against recorded evidence rather than intuition, and record the answer with the proposal so a later reader can see which one justified the structure.
