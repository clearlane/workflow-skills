# Tracked Baseline: Model Context Protocol Specification

## Baseline

| Field | Value |
|---|---|
| Upstream location | [`modelcontextprotocol.io/specification`](https://modelcontextprotocol.io/specification) |
| Baseline kind | Specification revision |
| Absorbed baseline | Revision `2026-07-28` |
| Absorbed on | 2026-08-03 |
| Plan hash | Not applicable; cited rather than absorbed |

This is a moving external specification, not an absorbed skill. No text was
copied from it. It is registered because [tools.md](../tools.md) generalizes
from it, and guidance derived from an unstated revision cannot be re-checked
when the source moves.

Generalized from:

- Adapter and transport selection, including the local-process and remote
  request-response shapes.
- Capability discovery and namespacing at the adapter boundary.
- Authorization, permission, and secret handling as adapter concerns.

Reworked or excluded:

- No protocol syntax, field names, method names, or wire format appears in
  guidance; those are the adapter's to own and the spec's to define.
- Coordinator owns retries, batching, approval, partial-success state, and
  resume, none of which the protocol dictates.

Canonical destinations:

- `references/tools.md`

## Refreshing

MCP increments its dated revision only for backwards-incompatible change, so a
newer revision is the signal that a claim here may no longer hold. Compare the
current revision against the one above, then re-check the transport lifecycle,
authorization, and tool-annotation claims in `tools.md`, which are the areas
that have moved across past revisions.
