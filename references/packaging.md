# Bundle Packaging and Discovery

Package one or more skills, commands, workers, event handlers, and external-tool configurations as a bundle a host can discover, load, and distribute. This reference owns the packaging contract. Resource routing inside a single skill stays in [structure.md](structure.md), filenames stay in [naming.md](naming.md), and installation of an already-published skill stays in [install.md](install.md).

Use it when the skill ships inside a host bundle, when components fail to load, or when the bundle is published for others to install. Skip it for a single skill consumed directly from a repository path.

## Bundle Contract

A bundle is one directory with:

- One manifest declaring bundle identity and any non-default component locations.
- Component directories at bundle root, one per component kind the bundle actually provides.
- Optional shared internal library, documentation, and license files.

Record these before creating files:

| Decision | Rule |
|---|---|
| Identity | One stable identifier, unique among installed bundles, in the host's required identifier form |
| Manifest location | Exactly where the host looks; components stay at bundle root, not inside the manifest directory |
| Component kinds | Only the kinds the bundle provides; delete empty scaffolding |
| Version | Semantic version bumped whenever behavior, contracts, or activation change |
| Distribution metadata | Description, author, homepage, repository, license identifier, discovery keywords |
| Documentation | Purpose, installation, component inventory, required tools and versions |

Keep the manifest minimal. Declare a custom component path only when the layout genuinely requires it, because every declaration is another thing that can drift from the tree.

## Discovery

Hosts locate components by convention. Two rules make discovery predictable:

1. Put each component kind in the conventional root-level directory the host scans, with the filename and required core file the host expects.
2. Treat declared custom paths as supplements to those defaults, not replacements. Components found in both load; assume nothing is silently overridden.

Distinguish two moments, because they fail differently:

- **Registration** happens once when the host loads the bundle. It reads the manifest, scans component locations, parses component metadata, and registers what it found. Malformed metadata and wrong locations fail here, usually silently.
- **Activation** happens per component at use time: an invoked command, a selected worker, a skill matched by task context, a fired event, or a routed tool call. Wrong activation metadata fails here, while the component itself loaded fine.

Component names must be unique across installed bundles. When collision is plausible, prefix names with the bundle identity rather than hoping installations stay disjoint.

## Portable Paths

Every intra-bundle reference must resolve after installation, wherever the host placed the bundle.

- Reference bundle files through the host-provided bundle-root reference, in manifests, component files, and executed scripts alike.
- Never use absolute filesystem paths, home-directory shortcuts, or paths relative to the agent's working directory. Installation location, operating system, and invocation directory all vary.
- Keep declared component paths bundle-relative in the host's required relative form, with forward slashes, and without parent-directory traversal.
- Validate that every declared path exists before publishing; a path that resolves only on the author's machine is the most common broken bundle.

## Layout by Size

Start flat and reorganize when a boundary becomes real, not in anticipation.

| Component count | Layout | Cost |
|---|---|---|
| Up to roughly a dozen | One directory per component kind | None; pure default discovery |
| More, with real functional categories | One directory per category, each declared in the manifest | Manifest must list every category |
| Many, with multi-level categories | Nested directories, each leaf declared explicitly | Hosts rarely recurse; every leaf needs a declaration |

Nesting only helps when the host is told about each level. When a layout requires more manifest maintenance than it saves in navigation, flatten it.

Factor logic used by several components into one internal library directory referenced through the bundle root, so behavior stays consistent and fixes land once. Group that library by responsibility rather than by consuming component.

## Publishing and Change

- Complete metadata before publishing, and include the license file the declared identifier names.
- Test from a clean install rather than the development tree, so missing files and machine-specific paths surface.
- Verify on every operating system claimed as supported, and document required tools and versions instead of assuming them.
- Bump the version on every behavior change, and keep description and keywords matching actual capability.
- Mark a component deprecated before removing it, and document breaking changes for existing installations.

## Troubleshooting

When a component does not load, check in this order; each step is cheaper than the next.

| Symptom | Likely cause | Check |
|---|---|---|
| Component absent entirely | Wrong location or filename | Directory is at bundle root, not inside the manifest directory; required core filename is exact |
| Component absent, location correct | Invalid metadata | Metadata block parses and carries the host's required fields |
| Manifest ignored | Wrong manifest location or invalid syntax | Manifest sits exactly where the host looks and parses cleanly |
| Path errors at runtime | Non-portable reference | Every reference uses the bundle-root reference and resolves after install |
| Nothing loads | Bundle disabled or not installed in this scope | Bundle enabled in the scope being used |
| Old behavior persists | Session indexed the bundle at startup | Start a fresh session, then recheck |
| Duplicate or shadowed component | Name collision with another bundle | Names unique or bundle-prefixed |

## Checks

- Manifest parses, declares a valid identifier, and every declared path exists and is bundle-relative.
- Every component kind present in the tree is discoverable, and every declared path resolves from a clean install.
- No absolute path, home shortcut, or working-directory-relative reference remains in manifests, components, or scripts.
- Version, description, keywords, license identifier, and license file agree with each other.
- A fresh install in a clean environment registers every component and activates one of each kind.
