# Absorbed Source: Plugin Structure

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`anthropics/claude-code/plugins/plugin-dev/skills/plugin-structure`](https://github.com/anthropics/claude-code/tree/main/plugins/plugin-dev/skills/plugin-structure), vendored at absorption time |
| Absorbed baseline | Snapshot tree SHA-256 `2ee40187a7a59dab446b2dcfc86c3def0c3c3af987a9fdc17a824abd7876136b` |
| Absorbed on | 2026-08-02 |
| Plan hash | `31df13de9ab55a174fe90901edba9fcf53286c7c0041e08e178b798423c06430` |

Absorbed:

- Bundle contract: identity, manifest location, component kinds, version, distribution metadata, and documentation.
- Discovery by convention, custom paths supplementing defaults, registration versus activation, and cross-bundle name-conflict policy.
- Portable intra-bundle path references, and rejection of absolute, home, working-directory-relative, and traversal paths.
- Layout selection by component count, shared internal library layering, and minimal-bundle shape.
- Manifest validation, semantic versioning, deprecation policy, cross-platform verification, and discovery troubleshooting.
- Skill-as-directory layout inside a bundle, and descriptive spelled-out component names.

Reworked or excluded:

- Generalized the vendor manifest path, bundle-root variable, manifest field names, invocation mapping, and external-tool configuration filename into runtime-neutral contracts; omitted vendor event names, worker metadata schema, and shell example code.
- Excluded the three worked example bundles, whose reusable shape is covered by layout and minimal-bundle rules, and whose remaining content is unrelated domain material.
- Excluded build-step handler merging, nested bundle families, and unverified load-time performance and restart claims; kept only the actionable stale-session check.
- Retained the target's route-based progressive disclosure and one-word-first filename convention over the source's word counts and fixed trees.
- Registered packaging as a selectable capability phase in the design coordinator rather than prose-only guidance.

Canonical destinations:

- `references/packaging.md`
- `references/structure.md`
- `references/naming.md`
- `scripts/design.py`
