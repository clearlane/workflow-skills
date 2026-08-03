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
| `status.schema.json` | printed status, not written to disk | coordinator |
| `inventory.schema.json` | `inventory.json` | coordinator |
| `skill.schema.json` | `target-after-merge.json`, and embedded in the inventory | coordinator |
| `analysis.schema.json` | `analyses/<source-id>.json` | agent |
| `plan.schema.json` | `plan.json` | agent |
| `apply.schema.json` | `apply.json` | agent |
| `validation.schema.json` | `validation.json` | agent |
| `feedback.schema.json` | `feedback.json` | agent |

Resolve `$ref` between schemas from disk. Publishing them under URLs makes them addressable and quotable; fetching them at validation time would make every run depend on a web host.

Vendor a third-party schema rather than fetching it, and pin the copy by digest. A vendored copy is trustworthy only if it is the published document: an edited one claims conformance to a standard while validating against a private variant of it.

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

## One Owner for the Run Lifecycle

Opening a run, creating one, and deciding which phase is current are the same operations regardless of what the workflow does. Give them one owner and let each coordinator compose it, keeping only its own vocabulary: which phases it derives, what evidence it requires, what it binds.

The cost of not doing so is not the duplication. It is that fixing one copy leaves the others wrong, and nothing reveals it until a run resumes under the coordinator that was not fixed.

Derive the current phase from the completed list rather than storing both. Two fields describing one fact can disagree, and then the run's own record is ambiguous.

## Reporting Where a Run Is

A coordinator's `status` is the answer to "where am I", and it is the one output a wrapper reads without knowing which coordinator it called. Give every coordinator the same envelope: the current phase, the full phase list, what is completed and remaining, the contract the current phase answers to, and the next action in one sentence.

Put anything specific to one coordinator under `detail`. A shared surface that grows a field every time one coordinator gains state is not shared, and a caller that must branch on the coordinator's name to find the phase gets no benefit from the envelope existing.

`phase` is null when no phase remains, which is how a caller distinguishes a finished run from one waiting on work. Derive `completed` from the phase reached where the progression is linear, rather than storing it: a stored list can disagree with the phase, and then two fields describe one fact.

Validate the envelope before printing it. A malformed status is the coordinator misreporting where the run is, which is worse than refusing to answer.

## How a Run Reports Failure

A run's exit is part of its output. A caller that can only see "nonzero" cannot tell a bad flag from a plan whose digest moved, so it cannot decide whether re-invoking, re-reading the artifact, or stopping is correct.

Use the [`sysexits.h`](https://man.freebsd.org/cgi/man.cgi?query=sysexits) codes, which are the nearest thing to a convention for command-line failure classes:

| Code | Class | The caller should |
|---|---|---|
| `64` | Usage: bad flag, unknown capability, wrong phase | Fix the invocation |
| `65` | Data: artifact violates its schema or a recorded digest moved | Fix the artifact, then retry |
| `69` | Unavailable: a required input or dependency is missing | Provide it |
| `70` | Software: an internal invariant broke | Report it; retrying will not help |
| `75` | Temporary: a bounded retry budget was exhausted | Decide whether to start again |

Exhausting a bound is a failure, not a completion. A run that rolls back and exits zero lets a wrapper report it as a success, which defeats the bound.

Emit failures as [RFC 9457 problem details](https://www.rfc-editor.org/rfc/rfc9457) when the caller asks for machine-readable output, with `status` carrying the exit code rather than an HTTP status, because no HTTP request is involved. Diagnostics go to stderr and data to stdout, so a caller can pipe a coordinator's JSON without a failure message landing in the stream.

## Malformed Evidence Is Not Unsafe Execution

A wrong field type means the run cannot read the evidence yet. Proof that a mutation went outside its bounds means the run did something it should not have.

Treating the two the same destroys correct work over a typo. Reject malformed evidence and hold the phase; reserve rollback for evidence that execution was actually unsafe.
