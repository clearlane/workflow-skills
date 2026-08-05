# Skill Review Rules

Severity, evidence, and per-phase questions for a review run. The workflow is [review.md](../workflows/review.md); the contracts under test live in the resources each phase names.

## Evidence

Every finding cites a path, or a path and line, inside the reviewed skill. Cite the strongest form available:

1. A failing command and its output.
2. A file and line contradicting a contract this repository owns.
3. An activation case the metadata routes wrongly.

Do not record a finding whose only support is preference, style, or an unmeasured claim about model behavior. Prefer running an existing deterministic check over asserting what it would say.

Record the remedy alongside the evidence when the fix is already known. A finding that names the place and the contract but not the change leaves the next run to re-derive it, and a remediation run triages against that field rather than re-reading the prose.

## Severity

| Severity | Meaning | Test |
|---|---|---|
| `blocking` | Use of the skill can lose data, bypass a gate, or produce a wrong result silently | Would a normal run cause harm the user cannot undo or detect? |
| `major` | The skill works but a contract is violated, so it degrades under load, failure, or reuse | Does it break on interruption, concurrency, an unusual input, or a second run? |
| `minor` | Correct but costly: duplication, dead resources, naming drift, avoidable context | Would fixing it be a small targeted change? |

Severity ranks consequence, not confidence. An uncertain suspicion of a blocking defect is recorded as blocking and disposed of explicitly.

A severity states what a defect costs, which is a property of the skill. What a later run owes each severity is a property of that run, and [remediation.md](remediation.md) owns it.

## Disposition

A blocking finding gates the verdict until it carries one:

- `fixed` — the defect is gone; the note says what changed.
- `accepted` — the risk is real and taken deliberately; the note says who accepts it and why.
- `deferred` — the fix is scheduled; the note says what triggers it.

Never dispose of a finding by rewording it into a lower severity.

A minor finding is judged one at a time, against three questions: does fixing it genuinely improve the skill, is it a reviewer false positive, and does the current behavior serve a purpose the reviewer missed. Dismissing the whole class in one move answers none of them, so it is not a disposition.

## Always-Run Phases

### activation

Against [structure.md](structure.md):

- Does the description state observable user intent, trigger variants, and non-activation cases?
- Does a near-miss request route to the correct other skill?
- Would the skill activate for work a direct instruction already handles?
- Are prerequisites and inputs discoverable before the first mutation?

### structure

Against [structure.md](structure.md) and [naming.md](naming.md):

- Does each rule have exactly one canonical home, with no duplicated prose?
- Is control flow in executable code rather than numbered prose the agent must remember?
- Is every resource reachable from core instructions, and is every resource actually used?
- Do filenames follow the one-word or family-first convention?
- Does core guidance name capabilities rather than a host's own paths, leaving those to an adapter?
- Does core instruction size stay within budget, with detail deferred to references?
- Does the skill contain every file it reads, so copying the directory copies the skill?
- Does each document sit in the directory its own shape claims, with gated phases in `workflows/` and contracts in `references/`?

A finding here names material in the wrong place; it does not move it. When the fix is a set of file moves rather than an edit, [layout.md](layout.md) decides whether the arrangement is genuinely wrong and [restructure.md](../workflows/restructure.md) is the run that carries it out under approval.

### safety

Against [patterns.md](patterns.md):

- Is every irreversible action gated immediately before execution, with exact scope, or confined to a provably restorable snapshot?
- Is approval a runtime event rather than prose telling the agent to continue only if approved?
- Is every external input — arguments, paths, event payloads, settings, tool responses — validated before use, with no raw shell interpolation?
- Are volatile permissions, target identity, locks, and destructive scope revalidated at point of use?
- Are secrets kept out of settings, logs, and run artifacts?

## Surface Phases

Each surface phase names the resource holding its contract, and the coordinator imports that mapping from the design coordinator so the two never diverge. Read the named resource and test the skill against it. Across every surface, three questions repeat:

- Does this surface own exactly its own boundary, leaving global state to the coordinator?
- Is runtime-specific syntax confined to this adapter rather than leaking into core guidance?
- Does it fail safe — a validated error — rather than proceeding on malformed input?

The `coordinator` and `state` phases carry two more, since they own what the others delegate:

- Does executable code own ordering, branching, and bounded retries, with interrupted work resumable from durable state alone?
- Is concurrency set by runtime configuration rather than a fixed prose batch size?

## Machine-Readable Output

The verdict writes `report.sarif` beside `report.md`, so a review can gate CI or annotate a pull request without a human transcribing it. [SARIF 2.1.0](https://docs.oasis-open.org/sarif/sarif/v2.1.0/sarif-v2.1.0.html) is the contract, and severity maps onto its three levels:

| Severity | SARIF `level` |
|---|---|
| `blocking` | `error` |
| `major` | `warning` |
| `minor` | `note` |

The review phase becomes the `ruleId`, so results group by the concern that found them. Evidence maps to a location: `path:line` becomes a region, and a bare path stays file-level rather than being pinned to line 1, which would annotate an arbitrary line.

An `accepted` or `deferred` finding is emitted as a suppressed result, never omitted. Dropping it would report the review as having found nothing at that location, which is the opposite of what the disposition recorded.

## Checks

A review passes when a reader who was not present can act on `report.md`: each finding names a place, a contract, and a consequence.

Every question above is answered, with evidence, before the phase asking it closes. The coordinator parses this document for them, so a question added here becomes a question the next run must settle, and reports the count in `report.md` as `answered/asked`. It selects them by shape, so a rule belongs in a phase section only when it is phrased as a question a reviewer can answer against the skill; `scripts/check.py` rejects a bullet in those sections that is not, because a rule stated there and never asked reads in the record exactly like one that was asked and held. A phase can close with no finding, and often should; it cannot close with a question nobody addressed, for that same reason.

`not-applicable` is a real answer. A skill with no destructive action cannot gate one, and saying so on the record is different from staying silent. It still costs evidence, because the claim that a case cannot arise is a claim about the skill.
