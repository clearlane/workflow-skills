# Run Artifacts

A workflow that can be interrupted needs its progress on disk, not in the conversation that produced it. This is the contract for what a coordinator writes there: what a run directory contains, which artifacts a coordinator owns and which an agent authors, and what every artifact must carry so a later reader can validate it without knowing who wrote it.

Coordinator design lives in [patterns.md](patterns.md). This document owns only the durable output.

## Run Directory

A run directory is created empty, lives outside every skill it operates on, and holds one workflow run:

```
run/
  state.json              current phase and bindings
  history.jsonl           append-only transition log
  decisions/<phase>.json  why each phase was considered done
  <artifact>.json         workflow-specific evidence
```

It must not overlap a skill the run reads or writes. An overlap makes the run's own bookkeeping part of the tree it is digesting, so a snapshot would capture the snapshot.

## Every JSON Artifact Carries Its Identity

Two fields, on every artifact, written by the coordinator:

| Field | Meaning |
|---|---|
| `schema` | Identifier of the schema this artifact claims to satisfy |
| `version` | Artifact format version |

Without them, a run directory found later is a pile of JSON whose meaning depends on which version of which coordinator produced it. With them, any tool can validate what it finds.

`version` changes only when a change makes an in-flight run **unresumable**, not merely older. Refuse a version you do not write, and say why: a resumed run whose digests were computed by a different algorithm fails its own binding check, which reads as a corrupt plan rather than as a version mismatch.

## Ownership

**Coordinator-written** artifacts are produced by code. They are validated on the way out, because a coordinator that emits an invalid artifact turns its own bug into the agent's problem one phase later, where the evidence is gone.

**Agent-written** artifacts are produced by a model from a schema. They are validated on the way in, and they are the least reliable link in the chain: prose asking for a field and code checking for it drift independently unless one document is the source of both.

Validate agent-written artifacts against a schema rather than field by field, and report **every** violation with its location. A validator that stops at the first fault costs one round trip per mistake.

## Canonical Contracts

| Concern | Contract | Why this one |
|---|---|---|
| Artifact shape | [JSON Schema 2020-12](https://json-schema.org/draft/2020-12) | Declarative, checkable, and readable by tools in any language |
| Digests | [RFC 8785 JSON Canonicalization Scheme](https://www.rfc-editor.org/rfc/rfc8785) | A digest another implementation can reproduce; sorted-key serialization agrees only with itself |
| Timestamps | [RFC 3339](https://www.rfc-editor.org/rfc/rfc3339) with the UTC `Z` offset | One writer, one format, no local timezone reaching disk |
| Event log | [JSON Lines](https://jsonlines.org) | Appendable without rewriting, and readable after a torn write |

Name the standard rather than describing the behavior. A skill that says "canonical JSON" produces digests only it can verify; a skill that says RFC 8785 produces digests a Go or JavaScript verifier reproduces.

## State and History Are Different Things

`state.json` is a mutable snapshot, rewritten on every transition. `history.jsonl` is an immutable event stream, appended to.

Keeping the log inside the state document puts an append-only record in the one structure guaranteed to be rewritten: a failed write risks the log along with the state, and a long run rewrites its entire history to add one line.

Append the transition **before** writing the state it produced. A crash between the two then leaves evidence that the transition was attempted, which is the more useful of the two failure modes.

## Schemas

Each artifact kind has one schema in `schemas/`, and shared vocabulary lives in `common.schema.json` so a field cannot mean one thing in a plan and another in an analysis:

| Schema | Artifact | Written by |
|---|---|---|
| `common.schema.json` | shared definitions | referenced, never written |
| `state.schema.json` | `state.json` | coordinator |
| `decision.schema.json` | `decisions/<phase>.json` | coordinator |
| `findings.schema.json` | `findings.json` | coordinator |
| `inventory.schema.json` | `inventory.json` | coordinator |
| `skill.schema.json` | `target-after-merge.json`, and embedded in the inventory | coordinator |
| `analysis.schema.json` | `analyses/<source-id>.json` | agent |
| `plan.schema.json` | `plan.json` | agent |
| `apply.schema.json` | `apply.json` | agent |
| `validation.schema.json` | `validation.json` | agent |
| `feedback.schema.json` | `feedback.json` | agent |

Resolve `$ref` between schemas from disk. Publishing them under URLs makes them addressable and quotable; fetching them at validation time would make every run depend on a web host.

### What a Schema Cannot Decide

Keep these imperative, and say so where the schema stops:

- **Path safety.** Whether a path stays inside the target is a question about the filesystem, not the document.
- **Cross-artifact coverage.** Whether a plan decided every capability requires reading the analyses in another directory.
- **Identity.** Whether this file describes the source it claims to is knowable only from the inventory.
- **Digest binding.** Whether a recorded digest matches the run's binding is a fact about the run.
- **Uniqueness over one property.** `uniqueItems` compares whole items, not a single key.

## Lifecycle

| Stage | Rule |
|---|---|
| Created | By the phase that produces it, never earlier |
| Validated | Coordinator artifacts on write, agent artifacts on read |
| Superseded | Copied into an attempt or revision directory, not overwritten in place |
| Retained | Until the run is complete or rolled back, then kept for audit |
| Deleted | Explicitly. A coordinator does not remove the evidence of its own run |

Preserve superseded evidence rather than overwriting it. An attempt that failed is the record of why the next one differed, and a run that quietly overwrites it cannot answer what changed.

## Malformed Evidence Is Not Unsafe Execution

A wrong field type means the run cannot read the evidence yet. Proof that a mutation went outside its bounds means the run did something it should not have.

Treating the two the same destroys correct work over a typo. Reject malformed evidence and hold the phase; reserve rollback for evidence that execution was actually unsafe.
