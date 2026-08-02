# Skill Settings

Use settings when skill behavior needs stable user-controlled preferences. Settings are configuration, not workflow memory.

## Ownership Invariant

| Data | Owner | Examples |
|---|---|---|
| Skill settings | Settings adapter | Enabled flag, mode, limits, feature flags, preferred provider, optional project context |
| Invocation overrides | Entrypoint adapter | One-run mode or limit override |
| Workflow state | Coordinator | Route, phase, item status, retry count, approval scope, artifacts, terminal errors |
| Secrets | Host secret store or protected environment | Tokens, passwords, private keys, client credentials |

Never use settings files for mutable progress, completion markers, worker assignments, approval state, or retry bookkeeping. Configuration changes should not masquerade as resume state.

## Contract

Define before choosing file path or format:

- Stable schema identifier and version.
- Field names, types, allowed values, ranges, and defaults.
- Required versus optional fields.
- Meaning of missing file, missing field, explicit null, and disabled state.
- Whether unknown fields are rejected, warned, or preserved for forward compatibility.
- User-local, project-local, and invocation scopes.
- Precedence, merge behavior, and provenance reporting.
- Reload, cache invalidation, migration, and rollback behavior.
- Which consumers receive each setting.

Keep schema small. Add a setting only when users need a stable choice. Do not expose coordinator internals as configuration.

## Scope and Precedence

Default order, lowest to highest priority:

1. Packaged schema defaults.
2. User-local settings.
3. Project-local settings.
4. Validated invocation overrides.

Host adapter may choose another order, but must document it. Merge structured objects by declared schema rules; do not invent deep-merge behavior implicitly. Replace lists unless schema explicitly defines union or keyed merge.

Return effective configuration with provenance:

```text
effective = resolve(defaults, user, project, invocation)
provenance = {
  mode: "project",
  maxAttempts: "invocation",
  enabled: "default"
}
```

Invocation overrides are ephemeral unless user explicitly requests persistence.

### Runnable Example

Resolve JSON layers with field provenance:

```bash
python3 scripts/settings.py \
  --defaults examples/skill-settings/defaults.json \
  --project examples/skill-settings/project.json \
  --override '{"mode":"focused"}'
```

Run built-in precedence, provenance, atomic-write, and stale-update check:

```bash
python3 scripts/settings.py \
  --defaults examples/skill-settings/defaults.json \
  --self-check
```

Resolver intentionally performs shallow schema-key replacement. Add schema-specific validation before resolution when target skill needs nested merge, coercion, unknown-field policy, or domain constraints.

## Format and Location

Settings adapter owns exact paths, filenames, discovery, format, metadata, reload semantics, and host integration. Core skill guidance must not hardcode one runtime's hidden directory or filename suffix.

Prefer, in order:

1. Host-native settings API or project-native configuration already used by repository.
2. Already-supported structured format with real parser and serializer.
3. Small stdlib-readable format when schema is flat enough.

Optional freeform context may live in a typed string field or companion document. Treat it as untrusted instructions, not executable control flow. Keep it size-bounded and identify its source.

Never parse YAML, TOML, JSON, or frontmatter with line-oriented substitutions. They mishandle nesting, quoting, comments, duplicate keys, multiline values, and malformed input.

## Load and Resolve

```text
locations = adapter.discoverSettings(scope)
documents = parseAndValidate(locations)
migrated = migrateKnownVersions(documents)
effective, provenance = resolvePrecedence(defaults, migrated, invocation)
return freeze({effective, provenance, digest(effective)})
```

Load path:

1. Discover only declared user and project locations.
2. Resolve symlinks and configured paths against allowed roots when path escape matters.
3. Read with size and timeout bounds.
4. Parse through host-native API or real parser.
5. Validate schema before any consumer sees values.
6. Migrate only known versions; preserve original on migration failure.
7. Resolve precedence and record field-level provenance.
8. Pass one immutable effective snapshot to coordinator and adapters.

Do not let every command, event handler, or worker independently parse settings. One adapter prevents divergent defaults and error handling.

## Consumer Boundaries

- **Coordinator** receives immutable settings snapshot and digest at run start. Record digest with run metadata when reproducibility matters.
- **Command adapter** validates invocation overrides and may expose explicit show, initialize, or update operations.
- **Event adapter** loads only when event can be affected; quick-exit before file I/O when possible.
- **Delegated worker** receives only fields needed for owned task, not full user configuration.
- **External-tool adapter** receives non-secret connection preferences; credentials come from secret boundary.

Define whether active run keeps initial snapshot or reloads settings. Default to stable snapshot for reproducibility. Hot reload only at explicit safe boundary with new digest recorded.

## Create and Update

Use structured input and serializer, never raw text interpolation.

Update transaction:

1. Validate requested field changes against current schema.
2. Read current version and content digest.
3. Apply migration before edit when required.
4. Serialize canonical document to securely created temporary file in same directory.
5. Flush when durability requirement warrants it.
6. Acquire lock or compare expected digest before replacement.
7. Atomically replace destination while preserving intended ownership and access policy.
8. Re-read and validate result.
9. Restore previous file or report recoverable conflict on failure.

Use adapter-native transaction or compare-and-swap when available. Atomic rename prevents partial files but does not solve concurrent writers.

Templates should include schema version, documented defaults, and only useful fields. Do not create empty scaffolding for hypothetical options.

## Error Policy

Classify failures:

- **Absent optional file** — use defaults.
- **Unreadable or malformed file** — fail closed for safety-critical behavior; otherwise report actionable error and use documented safe fallback.
- **Unknown schema version** — preserve file and require migration support.
- **Invalid optional field** — reject document or ignore field only when schema explicitly permits field-level fallback.
- **Conflicting concurrent update** — do not overwrite; reload and retry through bounded policy.
- **Missing secret** — report secret identifier and acquisition path without printing value.

Never delete malformed user settings automatically. Preserve evidence and provide repair path.

## Security

- Treat settings files, freeform context, paths, endpoints, and identifiers as untrusted.
- Validate allowed roots, schemes, hosts, numeric bounds, enumerations, and resource identifiers before use.
- Do not evaluate settings as code or splice values into shell commands.
- Keep credentials out of settings, logs, workflow artifacts, templates, and error output.
- Do not treat ignore rules as access control.
- Apply platform-appropriate ownership and access controls without assuming one OS permission model.
- Redact sensitive neighboring data when reporting parse or validation failures.

## Performance and Lifecycle

- Lazy-load only when configurable behavior is reached.
- Cache parsed settings by content digest or reliable modification identity.
- Bound cache lifetime and define invalidation on update, project switch, or host notification.
- Avoid repeated disk reads across concurrent workers; distribute one validated snapshot.
- Document startup-only, per-invocation, watched, or explicit-reload behavior in adapter.

## Checks

Exercise:

- Missing user and project files.
- Defaults only, each scope alone, all scopes, and invocation override.
- Precedence and provenance for every field class.
- Disabled behavior.
- Unknown fields, wrong types, invalid ranges, malformed syntax, duplicate keys, and unknown schema version.
- Unsafe paths, oversized context, secret-like values, and redaction.
- Atomic update interruption, concurrent writer conflict, failed migration, and rollback.
- Stable run snapshot versus documented reload boundary.
- Command, event, worker, external-tool, and coordinator consumption of same resolved values.

Document schema, locations by host, precedence, examples, defaults, enable or disable behavior, secret handling, reload semantics, migration, troubleshooting, and safe removal.
