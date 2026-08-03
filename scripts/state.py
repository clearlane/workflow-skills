#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Shared durable-run primitives for this repository's coordinators.

Every coordinator persists phase state outside conversation context, so the
JSON, digest, timestamp, and validation helpers live here once instead of per
script. references/artifacts.md owns the contract these implement.
"""

import hashlib
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from functools import cache, lru_cache
from pathlib import Path

import jsonschema
import rfc8785
from referencing import Registry, Resource

EXCLUDED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}
SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "schemas"
SCHEMA_BASE = "https://clearlane.github.io/workflow-skills/schemas/"
# Bumped when an artifact's meaning changes in a way that makes an in-flight run
# unresumable rather than merely older. Version 2 changed the digest algorithm
# to RFC 8785 and moved the transition log out of state.json, so a version 1 run
# would fail its own plan binding for a reason unrelated to its plan.
VERSION = 2
HISTORY_FILE = "history.jsonl"


def excluded(relative_parts):
    return any(part in EXCLUDED_DIRECTORIES for part in relative_parts)


def ignored_prefixes(root):
    """Paths the repository's own ignore rules exclude from tracked content.

    Absorption digests and snapshots must cover skill content, not local tool
    caches, build output, or editor state. The repository already declares that
    boundary, so read it instead of hard-coding tool names here.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--others", "--ignored", "--exclude-standard", "--directory", "-z"],
            cwd=str(root),
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return ()
    entries = [entry for entry in completed.stdout.decode().split("\0") if entry]
    return tuple(entry.rstrip("/") for entry in entries)


def ignored(relative_posix, prefixes):
    return any(relative_posix == prefix or relative_posix.startswith(prefix + "/") for prefix in prefixes)


def shipped_paths(root):
    """Repository-relative paths this project actually ships, or None outside git.

    Checks answer questions about the repository's own content. A contributor's
    untracked scratch file is not that content, and failing on it makes the
    suite depend on the state of one working tree rather than on what is
    committed. Git already knows the difference, so ask it. Returning None when
    git is unavailable lets callers fall back to walking the filesystem.
    """
    try:
        completed = subprocess.run(
            ["git", "ls-files", "--cached", "--exclude-standard", "-z"],
            cwd=str(root),
            capture_output=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return frozenset(entry for entry in completed.stdout.decode().split("\0") if entry)


def fail(message):
    raise SystemExit(message)


def now():
    """The single timestamp source: RFC 3339 with an explicit UTC offset.

    Every `created_at`, `updated_at`, `recorded_at`, and history `at` field goes
    through here so a consumer never has to guess whether a local timezone crept
    in. `datetime.isoformat()` on an aware UTC value is RFC 3339 by
    construction; the `Z` form is used because it is the one the schemas' own
    `format: date-time` examples and every other tooling ecosystem expect.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def slug(value):
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "skill"


def read_json(path):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"Missing file: {path}")
    except json.JSONDecodeError as error:
        fail(f"Invalid JSON in {path}: {error}")
    if not isinstance(value, dict):
        fail(f"Expected JSON object: {path}")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_sha256(value):
    """Digest a JSON value through RFC 8785 canonicalization.

    These digests are load-bearing: absorb binds a plan to one and refuses to
    execute a plan whose digest moved, which is what makes execution
    reversibility-equivalent to an approval. `json.dumps(sort_keys=True)` is
    RFC 8785 only by coincidence and diverges on number formatting and non-ASCII
    text, so the digest would agree with nothing but itself. JCS makes it
    reproducible by a verifier in another language.
    """
    return hashlib.sha256(rfc8785.dumps(value)).hexdigest()


def json_sha256(path):
    return canonical_sha256(read_json(path))


def relative_file_manifest(root):
    root = root.resolve()
    if not root.exists():
        return {}
    prefixes = ignored_prefixes(root)
    manifest = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        if not path.is_file() or excluded(relative.parts) or ignored(relative.as_posix(), prefixes):
            continue
        manifest[relative.as_posix()] = {
            "sha256": file_sha256(path),
            "size": path.stat().st_size,
        }
    return manifest


def copy_manifest_files(source_root, destination_root, manifest):
    """Copy exactly the manifest-tracked regular files.

    Copying the whole tree would also copy sockets, devices, and ignored local
    state, which cannot be restored and would not match the recorded digest.
    """
    for relative in manifest:
        source = source_root / relative
        destination = destination_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination, follow_symlinks=False)


def tree_sha256(manifest):
    return canonical_sha256(manifest)


def require_list(value, name):
    if not isinstance(value, list):
        fail(f"{name} must be list")


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be non-empty string")


def safe_relative_path(value, name):
    require_text(value, name)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value in {".", ""}:
        fail(f"{name} must stay inside target: {value}")
    return path.as_posix()


def paths_overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def remove_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


@lru_cache(maxsize=1)
def schema_registry():
    """Resolve $ref between schemas from disk, never over the network.

    The $id values are URLs so the schemas are addressable and quotable, but a
    validator that fetched them would make every run depend on a web host being
    up. Registering the local files under those identifiers keeps the published
    names and the offline behaviour.
    """
    resources = []
    for path in sorted(SCHEMA_DIRECTORY.glob("*.schema.json")):
        contents = json.loads(path.read_text(encoding="utf-8"))
        resources.append((SCHEMA_BASE + path.name, Resource.from_contents(contents)))
        # Sibling $refs are written relative, so the bare filename must resolve too.
        resources.append((path.name, Resource.from_contents(contents)))
    return Registry().with_resources(resources)


@cache
def schema_validator(name):
    path = SCHEMA_DIRECTORY / name
    if not path.is_file():
        fail(f"Missing schema: {path}")
    contents = json.loads(path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(contents, registry=schema_registry())


def schema_errors(name, value):
    """Every violation, deepest first, as messages an agent can act on.

    Reporting only the first error makes an artifact take one round trip per
    mistake to repair. The instance path is included because a model rewriting
    the file needs to know which element was wrong, not just what was wrong.
    """
    validator = schema_validator(name)
    messages = []
    for error in sorted(validator.iter_errors(value), key=lambda item: list(item.absolute_path)):
        location = "/".join(str(part) for part in error.absolute_path) or "<root>"
        messages.append(f"{location}: {error.message}")
    return messages


VENDOR_SCHEMA_DIRECTORY = SCHEMA_DIRECTORY / "vendor"


@cache
def vendored_validator(name):
    """Validate against a vendored copy of a third-party schema.

    The SARIF schema is draft-04 and lives outside this repository, so it is
    neither registered with our own schemas nor stamped like them. Vendoring it
    keeps the check offline and deterministic: fetching the published copy at
    validation time would make a run fail when a raw.githubusercontent host is
    down, which says nothing about the document being validated.
    """
    path = VENDOR_SCHEMA_DIRECTORY / name
    if not path.is_file():
        fail(f"Missing vendored schema: {path}")
    contents = json.loads(path.read_text(encoding="utf-8"))
    return jsonschema.validators.validator_for(contents)(contents)


def validate_sarif(document):
    """Refuse to claim SARIF output that a SARIF consumer would reject."""
    validator = vendored_validator("sarif-2.1.0.schema.json")
    messages = [
        f"{'/'.join(str(part) for part in error.absolute_path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(document), key=lambda item: list(item.absolute_path))
    ]
    if messages:
        detail = "\n  ".join(messages)
        fail(f"Document is not valid SARIF 2.1.0:\n  {detail}")


def stamp(name, value):
    """Attach the schema identity an artifact claims to satisfy.

    Someone who finds a run directory should be able to validate what is in it
    without knowing which coordinator wrote it or which version was current when
    it ran. The stamp is what makes the artifact self-describing.
    """
    return {"schema": SCHEMA_BASE + name, "version": VERSION, **value}


def write_artifact(path, name, value):
    """Write a stamped artifact, refusing to emit one that violates its schema.

    A coordinator that writes an invalid artifact turns its own bug into the
    agent's problem one phase later, where the evidence of what went wrong is
    gone. Validating on the way out keeps the failure at its cause.
    """
    stamped = stamp(name, value)
    errors = schema_errors(name, stamped)
    if errors:
        detail = "\n  ".join(errors)
        fail(f"Refusing to write {path}: does not satisfy {name}:\n  {detail}")
    write_json(path, stamped)


def check_version(state):
    """Refuse a run written by an incompatible artifact version, and say why.

    Version 2 changed the digest to RFC 8785 and moved the transition log out of
    state.json. A version 1 run re-read under version 2 would fail its own plan
    binding, because the recorded digest was produced by a different algorithm.
    Failing on the version says that plainly instead of reporting a plan
    mismatch the operator cannot act on.
    """
    found = state.get("version")
    if found == VERSION:
        return
    fail(
        f"Run artifacts are version {found!r}, this coordinator writes version {VERSION}. "
        "Digests and the transition log changed shape, so the run cannot be resumed; "
        "start a new run."
    )


def append_history(root, record):
    """Append one transition to the run's event log.

    An append-only audit trail does not belong inside the one document that is
    rewritten on every transition. Keeping it separate means a torn or failed
    state write cannot take the log with it, and a long run stops rewriting its
    whole history to record one more line. One JSON object per line, newline
    terminated, written in a single append so a reader never sees half a record.
    """
    path = root / HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, sort_keys=True) + "\n"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(line)


def read_history(root):
    """Every complete record in the log, skipping a torn final line.

    A crash mid-append can leave a partial line. That is a fact about the
    interrupted run, not a reason to refuse to report the transitions that did
    land, so it is dropped rather than raised.
    """
    path = root / HISTORY_FILE
    if not path.exists():
        return []
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def save_state(root, state, event):
    """Record a transition, then persist the state it produced.

    History is appended first: a state write that fails after the append leaves
    evidence that the transition was attempted, while the reverse order would
    lose it entirely.
    """
    state["updated_at"] = now()
    append_history(root, {"at": state["updated_at"], "event": event, "phase": state["phase"]})
    write_artifact(root / "state.json", "state.schema.json", state)


def check_canonical_digests(root):
    """Prove the digest follows RFC 8785 rather than merely being stable.

    A digest that only agrees with itself passes any round-trip test, so
    stability proves nothing. These are the two cases where the previous
    `json.dumps(sort_keys=True)` form diverged from the standard: `ensure_ascii`
    escaped non-ASCII text that JCS emits as UTF-8, and a float with a zero
    fraction serialized as `1.0` where JCS requires `1`.
    """
    assert rfc8785.dumps({"a": "é"}) == b'{"a":"\xc3\xa9"}'
    assert rfc8785.dumps({"a": 1.0}) == b'{"a":1}'
    # Key order in the input must not reach the digest.
    assert canonical_sha256({"b": 1, "a": 2}) == canonical_sha256({"a": 2, "b": 1})
    # Values that differ must not collide.
    assert canonical_sha256({"a": 1}) != canonical_sha256({"a": 2})
    write_json(root / "digest.json", {"z": "é", "a": 1.0})
    assert json_sha256(root / "digest.json") == canonical_sha256({"a": 1, "z": "é"})


def check_history_survives_state_loss(root):
    """The transition log must outlive the state document it describes.

    This is the whole reason the two are separate files. Simulating the failure
    is the only way to show it: destroy state.json exactly as a torn write
    would, and require that every transition recorded before it is still
    readable.
    """
    state = {"version": VERSION, "phase": "first", "created_at": now(), "updated_at": now()}
    save_state(root, state, "initialized")
    state["phase"] = "second"
    save_state(root, state, "advanced")
    remove_path(root / "state.json")
    recovered = read_history(root)
    assert [record["event"] for record in recovered] == ["initialized", "advanced"]
    assert [record["phase"] for record in recovered] == ["first", "second"]
    # A record torn by a crash mid-append must not hide the ones that landed.
    with (root / HISTORY_FILE).open("a", encoding="utf-8") as handle:
        handle.write('{"at": "2026-01-01T00:00:00')
    assert len(read_history(root)) == 2


def self_check():
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_json(root / "a.json", {"b": 1, "a": 2})
        assert read_json(root / "a.json") == {"a": 2, "b": 1}
        assert json_sha256(root / "a.json") == json_sha256(root / "a.json")
        (root / "keep").mkdir()
        (root / "keep" / "f.txt").write_text("x")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("ref")
        manifest = relative_file_manifest(root)
        assert "keep/f.txt" in manifest
        assert not any(key.startswith(".git") for key in manifest)
        assert safe_relative_path("a/b.md", "x") == "a/b.md"
        for bad in ("/abs", "../up", ".", ""):
            try:
                safe_relative_path(bad, "x")
            except SystemExit:
                pass
            else:
                raise AssertionError(f"accepted unsafe path {bad!r}")
        assert paths_overlap(Path("/a"), Path("/a/b"))
        assert not paths_overlap(Path("/a"), Path("/b"))
        assert slug("Absorb Skills!") == "absorb-skills"
        assert slug("---") == "skill"
        check_canonical_digests(root)
        check_history_survives_state_loss(root / "run")
        # Outside a repository there is nothing to ship, so callers must be told
        # to fall back rather than be handed an empty set they would read as
        # "this project ships no files".
        assert shipped_paths(root) is None

    repository = Path(__file__).resolve().parent.parent
    shipped = shipped_paths(repository)
    if shipped is not None:
        assert "scripts/state.py" in shipped
        assert not any(name.startswith(".git/") for name in shipped)
    print("self-check passed")


if __name__ == "__main__":
    self_check()
