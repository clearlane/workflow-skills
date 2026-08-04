#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Shared durable-run primitives for this repository's coordinators.

Every coordinator persists phase state outside conversation context, so the
JSON, digest, timestamp, and validation helpers live here once instead of per
script. references/artifacts.md owns the contract these implement.
"""

import errno
import fcntl
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import redirect_stderr
from datetime import datetime, timezone
from functools import cache, lru_cache
from pathlib import Path

try:
    import jsonschema
    import rfc8785
    from referencing import Registry, Resource
except ModuleNotFoundError as error:  # pragma: no cover - environment guard
    # Every coordinator imports this module, so an uninstalled dependency is
    # the first thing a new user meets. Unguarded it arrived as a traceback
    # naming state.py, which points at this repository's internals rather than
    # at the one action that fixes it. document.py already guarded its own
    # three; the coordinators' three were left to fail raw.
    raise SystemExit(
        f"Missing dependency {error.name!r}. Install with: python3 -m pip install -r requirements.txt"
    ) from error

from cli import (
    EX_DATAERR,
    EX_SOFTWARE,
    EX_TEMPFAIL,
    EX_UNAVAILABLE,
    SELF_CHECK,
    Failure,
    fail,
    report_failure,
    run_self_check,
    take_self_check,
    wants_json,
)

EXCLUDED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}
SCHEMA_DIRECTORY = Path(__file__).resolve().parent.parent / "schemas"
SCHEMA_BASE = "https://clearlane.github.io/workflow-skills/schemas/"
# Bumped when an artifact's meaning changes in a way that makes an in-flight run
# unresumable rather than merely older. Version 2 changed the digest algorithm
# to RFC 8785 and moved the transition log out of state.json, so a version 1 run
# would fail its own plan binding for a reason unrelated to its plan.
VERSION = 2
HISTORY_FILE = "history.jsonl"

# The transition log is the durable record of which phases actually finished,
# so the name a completion is written under is a contract between the
# coordinator that appends it and any reader that verifies against it. It was a
# literal in three coordinators, which is one rename away from a log that
# cannot be checked.
PHASE_COMPLETE_PREFIX = "phase-complete:"

# The phase a run holds once no working phase is pending. It is not a member of
# any coordinator's phase list, because it is where a run ends rather than
# something to work, which is exactly why a reader validating `phase` against
# that list has to know the name.
COMPLETE_PHASE = "complete"

# Where a run can legitimately end. absorb adds a discarded outcome, because a
# run that rolled back did not pass through `complete` and reporting it as
# finished would describe a discarded merge as a successful one.
TERMINAL_PHASES = (COMPLETE_PHASE, "rolled-back")


def phase_complete_event(phase):
    return f"{PHASE_COMPLETE_PREFIX}{phase}"


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


# A filesystem refusal that the caller's input caused, rather than one the
# machine imposed. Both are OSError; only the exit code should differ.
USAGE_ERRNOS = frozenset(
    {
        errno.ENAMETOOLONG,
        errno.EINVAL,
        errno.EISDIR,
        errno.ENOTDIR,
        errno.ELOOP,
        errno.EILSEQ,
    }
)

# Long enough to identify the path, short enough that a 5000-character argument
# does not become the whole diagnostic.
PATH_EXCERPT = 120


def shorten(value):
    return value if len(value) <= PATH_EXCERPT else f"{value[:PATH_EXCERPT]}... ({len(value)} characters)"


def run_cli(main, argv=None):
    """Run a coordinator entrypoint, rendering any failure through one path.

    Every coordinator previously relied on SystemExit printing its own message,
    which meant the exit code was always 1 and the output shape was whatever the
    string happened to be. Routing through here gives all of them the same
    failure class, the same stream, and the same `--output json` behaviour
    without each entrypoint restating it.

    OSError is caught alongside Failure because the filesystem rejects inputs
    this code cannot pre-validate: a path over the system limit, a permission
    denial, a name the filesystem will not encode. Those arrived as a raw
    traceback and exit 1, which is the one shape the contract promises never to
    emit, and it leaks absolute paths from the machine that ran it.
    """
    argv = sys.argv[1:] if argv is None else argv
    as_json = wants_json(argv)
    try:
        main()
    except Failure as error:
        report_failure(error, as_json, sys.stderr)
        raise SystemExit(error.code) from error
    except OSError as error:
        # errno distinguishes "you asked for something impossible" from "the
        # machine could not do it", which map to different sysexits codes.
        code = EX_DATAERR if error.errno in USAGE_ERRNOS else EX_UNAVAILABLE
        detail = error.strerror or type(error).__name__
        failure = Failure(f"{detail}: {shorten(str(error.filename or ''))}".rstrip(": "), code)
        report_failure(failure, as_json, sys.stderr)
        raise SystemExit(code) from error


def now():
    """The single timestamp source: RFC 3339 with an explicit UTC offset.

    Every `created_at`, `updated_at`, `recorded_at`, and history `at` field goes
    through here so a consumer never has to guess whether a local timezone crept
    in. `datetime.isoformat()` on an aware UTC value is RFC 3339 by
    construction; the `Z` form is used because it is the one the schemas' own
    `format: date-time` examples and every other tooling ecosystem expect.
    """
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


# A slug becomes a directory name in absorb's source ids, so it has to fit in
# a filesystem component. POSIX guarantees NAME_MAX is at least 255; the bound
# is set well below that so a caller-supplied prefix still fits.
SLUG_LIMIT = 64


def slug(value):
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    if len(normalized) <= SLUG_LIMIT:
        return normalized or "skill"
    # Truncation maps many names onto one slug, and a slug is an identity: two
    # skills differing only past the cut would be recorded as the same subject,
    # so provenance could not say which one a run was about. Spending the last
    # few characters on a digest of the full name keeps distinct inputs
    # distinct while leaving the readable prefix intact.
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:8]
    kept = normalized[: SLUG_LIMIT - len(digest) - 1].strip("-")
    return f"{kept}-{digest}" if kept else digest


def read_json(path):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"Missing file: {path}", EX_UNAVAILABLE, path)
    except json.JSONDecodeError as error:
        fail(f"Invalid JSON in {path}: {error}", EX_DATAERR, path)
    if not isinstance(value, dict):
        fail(f"Expected JSON object: {path}", EX_DATAERR, path)
    return value


LOCK_FILE = ".lock"

# Long enough that a slow but healthy writer is not interrupted, short enough
# that a crashed one does not block a run indefinitely.
LOCK_TIMEOUT_SECONDS = 30

# Held for the life of the command rather than a block, because the sequence
# that has to be exclusive spans open_run to save_state, which are separate
# calls in every coordinator. The OS drops it when the process ends, including
# when it crashes, so nothing has to remember to release it.
#
# Keyed by run directory so re-entry is free. flock is per open file
# description, so a second handle on the same file from this process would
# block against our own lock forever: a caller that opens one run twice, which
# a test or a batch driver does naturally, would deadlock against itself and
# then fail as though a stranger held it.
_HELD_LOCKS = {}


def acquire_run_lock(root):
    """Serialise the read-modify-write that advances a run.

    Each write is atomic on its own, but advancing a phase reads the state,
    edits it, and writes it back. Two coordinators against one run directory
    interleaved those steps, so both saw the same phase pending, both appended
    to the history, and the second state write discarded the first one's
    completion. The transition was recorded in the log and absent from the
    state, which is precisely the disagreement the log exists to settle.

    Advisory rather than mandatory: every writer reaches a run through
    open_run, so the lock only has to hold against this repository's own
    coordinators, and an advisory lock is released by the OS if a holder dies.
    """
    root.mkdir(parents=True, exist_ok=True)
    path = root / LOCK_FILE
    key = str(path.resolve())
    # Already ours: re-entry must not queue behind our own handle.
    if key in _HELD_LOCKS:
        return
    deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
    handle = path.open("w")
    while True:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            break
        except OSError:
            if time.monotonic() >= deadline:
                handle.close()
                fail(
                    f"{root}: another process has held the run lock for "
                    f"{LOCK_TIMEOUT_SECONDS}s; it may have stopped without releasing it",
                    EX_TEMPFAIL,
                    path,
                )
            time.sleep(0.05)
    _HELD_LOCKS[key] = handle


def write_json(path, value):
    """Replace a file atomically, without colliding with a concurrent writer.

    The temporary name carries the writer's pid: a fixed `.tmp` suffix meant two
    processes writing the same artifact shared one scratch file, so one could
    replace the target with a document the other was still writing. The rename
    itself is atomic on POSIX, which is what makes the swap safe once the
    content is complete.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
        temporary.replace(path)
    finally:
        # A failure between write and replace would otherwise leave scratch
        # files in a run directory that later reports its own contents.
        if temporary.exists():
            temporary.unlink()


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
        if excluded(relative.parts) or ignored(relative.as_posix(), prefixes):
            continue
        # is_file() follows the link, so a symlink out of the tree would be
        # recorded as an ordinary file whose bytes live somewhere this manifest
        # does not describe. That breaks both directions of a rollback: the
        # snapshot copies the link rather than the content, so the baseline is
        # never really captured, and the digest moves whenever the outside file
        # changes, so a restore that put every tracked path back still reports
        # that it could not. Refusing is right rather than merely safe, because
        # a skill whose content lives outside itself cannot be copied, shipped,
        # or restored as a unit.
        if path.is_symlink():
            destination = path.resolve()
            if not destination.is_relative_to(root):
                fail(
                    f"{path}: symlink leaves the tree ({destination}); "
                    "a skill must contain its own content to be snapshotted",
                    EX_DATAERR,
                    path,
                )
        if not path.is_file():
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
        fail(f"{name} must be list", EX_DATAERR)


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be non-empty string", EX_DATAERR)


def safe_relative_path(value, name):
    require_text(value, name)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value in {".", ""}:
        fail(f"{name} must stay inside target: {value}", EX_DATAERR)
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
        fail(f"Missing schema: {path}", EX_SOFTWARE, path)
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
        fail(f"Missing vendored schema: {path}", EX_SOFTWARE, path)
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
        fail(f"Document is not valid SARIF 2.1.0:\n  {detail}", EX_SOFTWARE)


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
        fail(f"Refusing to write {path}: does not satisfy {name}:\n  {detail}", EX_SOFTWARE, path)
    write_json(path, stamped)


def read_artifact(path, name):
    """Read an artifact, refusing one that violates its schema.

    Writes were validated and reads were not, so a coordinator trusted the
    shape of anything already on disk. An artifact edited by hand between two
    commands, or written by an older version, then reached the code that reads
    its fields and raised a KeyError naming one key, which tells the agent
    neither which file was wrong nor what it should have contained. Validating
    on the way in reports the same defect the way write_artifact reports it.
    """
    value = read_json(path)
    errors = schema_errors(name, value)
    if errors:
        detail = "\n  ".join(errors)
        fail(f"Refusing to read {path}: does not satisfy {name}:\n  {detail}", EX_DATAERR, path)
    return value


def print_status(kind, root, phase, phases, completed, resource, next_action, detail):
    """Print the one status shape every coordinator shares.

    Three coordinators previously returned three different objects to the same
    question, so a wrapper had to know which one it had called before it could
    find the phase. Coordinator-specific state goes under `detail`, which keeps
    the shared surface stable as any one of them grows more state.
    """
    envelope = stamp(
        "status.schema.json",
        {
            "kind": kind,
            "run_dir": str(root),
            "phase": phase,
            "phases": list(phases),
            "completed": list(completed),
            "remaining": [item for item in phases if item not in completed],
            "resource": resource,
            "next_action": next_action,
            "detail": detail,
        },
    )
    errors = schema_errors("status.schema.json", envelope)
    if errors:
        # A malformed status is the coordinator lying about where the run is,
        # which is worse than refusing to answer.
        detail_text = "\n  ".join(errors)
        fail(f"Refusing to print an invalid status envelope:\n  {detail_text}", EX_SOFTWARE)
    print(json.dumps(envelope, indent=2, sort_keys=True))


def read_status(stdout):
    """Parse a coordinator's status and prove it satisfies the shared envelope.

    Used by the self-checks, so each coordinator validates its own output rather
    than only the schema file being well-formed. A coordinator that drifts from
    the envelope fails its own check instead of surfacing as a broken wrapper.
    """
    envelope = json.loads(stdout)
    errors = schema_errors("status.schema.json", envelope)
    if errors:
        raise AssertionError("status envelope violates its schema:\n  " + "\n  ".join(errors))
    return envelope


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
        "start a new run.",
        EX_DATAERR,
    )


def open_run(run_dir, *artifacts):
    """Open an existing run and refuse one this coordinator cannot resume.

    Every coordinator resolved the path, read state.json, and checked the
    version itself, which is three copies of the one rule that decides whether a
    run directory is safe to touch. Extra artifact names are read alongside the
    state, since a coordinator that needs its inventory needs it every time.

    The state is validated against the schema it was written under, not merely
    parsed as JSON. Writes always went through that schema and reads did not,
    so a state edited by hand or left behind by an older build was trusted on
    the way in and only failed later, at whichever field first surprised a
    coordinator.
    """
    root = run_dir.expanduser().resolve()
    # Taken before the read, so the state a command acts on cannot change under
    # it between here and the save_state that ends the transition.
    acquire_run_lock(root)
    state = read_json(root / "state.json")
    check_version(state)
    errors = schema_errors("state.schema.json", state)
    if errors:
        detail = "\n  ".join(errors)
        fail(
            f"{root / 'state.json'}: does not satisfy state.schema.json:\n  {detail}",
            EX_DATAERR,
            root / "state.json",
        )
    # The schema types `phase` as text because the phase names differ per
    # coordinator. Only the state knows its own list, so the cross-field rule
    # that `phase` is one of `phases` has to be checked here.
    phases = state.get("phases") or []
    # A finished run holds a phase that is deliberately not in its own list, so
    # the membership rule has to admit the terminal names alongside it.
    if phases and state.get("phase") not in [*phases, *TERMINAL_PHASES]:
        fail(
            f"{root / 'state.json'}: phase {state.get('phase')!r} is not one of {phases}",
            EX_DATAERR,
            root / "state.json",
        )
    unknown = [name for name in state.get("completed", []) if name not in phases] if phases else []
    if unknown:
        fail(
            f"{root / 'state.json'}: completed names phases that do not exist: {unknown}",
            EX_DATAERR,
            root / "state.json",
        )
    # `completed` is a set of phases wearing a list's clothes, and two rules
    # below read it as a length: the history bound compares its count to the
    # number of transitions, and pending_phase treats membership as done. A
    # repeated name satisfies the count while contributing one phase, so a
    # duplicate buys a free completion the log cannot contradict. Phases must
    # be distinct for the same reason: pending_phase returns the first name
    # not yet done, and a list that names one phase twice describes an order
    # that cannot be walked.
    for field in ("phases", "completed"):
        names = state.get(field) or []
        repeated = sorted({name for name in names if names.count(name) > 1})
        if repeated:
            fail(
                f"{root / 'state.json'}: {field} repeats {repeated}, so it no longer describes distinct phases",
                EX_DATAERR,
                root / "state.json",
            )
    # history.jsonl is the durable record: it is appended before the state is
    # written and survives losing it entirely. Every phase added to `completed`
    # goes through one save_state, so a state claiming more completions than
    # the log has transitions was edited after the fact, and trusting it would
    # let a run skip a phase's actual work.
    #
    # Counting rather than matching event names, because a coordinator may
    # record a completion under a domain-specific event that carries more
    # information, such as the digest a proposal was bound to.
    #
    # The initialising record is not a transition, so it is discounted. An
    # empty log means the history was lost rather than that nothing happened,
    # which read_history already reports, so only a present log is compared.
    history = read_history(root)
    completed = state.get("completed", [])
    if history and len(completed) > len(history) - 1:
        fail(
            f"{root / 'state.json'}: completed lists {len(completed)} phases "
            f"but the history records only {max(len(history) - 1, 0)} transitions",
            EX_DATAERR,
            root / "state.json",
        )
    if not artifacts:
        return root, state
    return root, state, *(read_json(root / name) for name in artifacts)


def create_run(run_dir, *conflicts):
    """Resolve a new run directory, refusing one that would corrupt its own inputs.

    A run directory that already holds files would mix a previous run's evidence
    into this one, and one that overlaps a skill the run reads or writes makes
    the run's bookkeeping part of the tree it is digesting, so a snapshot would
    capture the snapshot.
    """
    root = run_dir.expanduser().resolve()
    # The lock is bookkeeping, not evidence: a crashed run leaves one behind,
    # and treating it as leftover content would make that directory unusable
    # for the retry it exists to allow.
    if root.exists() and any(entry.name != LOCK_FILE for entry in root.iterdir()):
        fail(f"Run directory must be absent or empty: {root}")
    for path, description in conflicts:
        if paths_overlap(root, path):
            fail(f"Run directory must not overlap {description}")
    return root


def pending_phase(state):
    """The first phase not yet completed, or None when the run is done.

    Derived rather than stored: a stored current phase and a stored completed
    list can disagree, and then two fields describe one fact.
    """
    for phase in state["phases"]:
        if phase not in state["completed"]:
            return phase
    return None


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


def check_open_run_rejects_edited_state(root):
    """A resumed run must not trust a state document that was edited.

    Writes always went through the schema and reads did not, so the way in was
    the unguarded direction: a state edited by hand, or left by an older build,
    was accepted and only failed later at whichever field first surprised a
    coordinator. These are the three shapes that reached a coordinator intact.
    """
    phases = ["first", "second"]

    def build(**overrides):
        remove_path(root)
        state = {
            "version": VERSION,
            "phase": "first",
            "phases": phases,
            "completed": [],
            "created_at": now(),
            "updated_at": now(),
        }
        save_state(root, state, "initialized")
        state.update(overrides)
        write_json(root / "state.json", stamp("state.schema.json", state))
        return state

    build()
    assert open_run(root)[1]["phase"] == "first"

    # A field whose type the schema forbids. Only the schema rejects this: the
    # cross-field rules below read `phases` and `completed` without asserting
    # what they are, so an edited state reached a coordinator intact.
    build(completed="not-a-list")
    try:
        open_run(root)
    except Failure as error:
        assert error.code == EX_DATAERR, error.code
        assert "state.schema.json" in error.message, error.message
    else:
        raise AssertionError("accepted a state that violates its own schema")

    # A phase outside the run's own list: status would report a derived phase
    # and silently disagree with the document it read.
    build(phase="not-a-phase")
    try:
        open_run(root)
    except Failure as error:
        assert error.code == EX_DATAERR, error.code
    else:
        raise AssertionError("accepted a phase outside the declared list")

    # The terminal phase is deliberately not a member, so it must be allowed.
    # Recorded through save_state so the log matches the completion it claims,
    # which is the state a genuinely finished run is in.
    remove_path(root)
    finished = {
        "version": VERSION,
        "phase": "first",
        "phases": phases,
        "completed": [],
        "created_at": now(),
        "updated_at": now(),
    }
    save_state(root, finished, "initialized")
    finished["completed"] = ["first"]
    finished["phase"] = COMPLETE_PHASE
    save_state(root, finished, phase_complete_event("first"))
    assert open_run(root)[1]["phase"] == COMPLETE_PHASE

    # More completions than the log has transitions: the log is appended first
    # and survives losing the state, so the state is the document that is wrong.
    build(completed=list(phases))
    try:
        open_run(root)
    except Failure as error:
        assert error.code == EX_DATAERR, error.code
    else:
        raise AssertionError("accepted more completions than the history records")

    # The bound above counts completions, so a repeated name pays for a phase
    # it did not run: the length still matches the log while one phase quietly
    # goes unfinished. This is the tamper the count alone cannot see, which is
    # why distinctness is checked rather than inferred.
    remove_path(root)
    advanced = {
        "version": VERSION,
        "phase": "first",
        "phases": phases,
        "completed": [],
        "created_at": now(),
        "updated_at": now(),
    }
    save_state(root, advanced, "initialized")
    for name in phases:
        advanced["completed"] = [*advanced["completed"], name]
        save_state(root, advanced, phase_complete_event(name))
    laundered = read_json(root / "state.json")
    laundered["completed"] = [phases[0], phases[0]]
    write_json(root / "state.json", stamp("state.schema.json", laundered))
    try:
        open_run(root)
    except Failure as error:
        assert error.code == EX_DATAERR, error.code
        assert "distinct" in error.message, error.message
    else:
        raise AssertionError("accepted a duplicate completion the history cannot contradict")

    # The same rule guards the phase list, which pending_phase walks in order.
    build(phases=[phases[0], phases[0]])
    try:
        open_run(root)
    except Failure as error:
        assert error.code == EX_DATAERR, error.code
    else:
        raise AssertionError("accepted a phase list that repeats a phase")


def check_run_lock_serialises_writers(root):
    """Only one writer at a time may advance a run.

    Each write is atomic, but advancing a phase reads, edits, and writes back.
    Interleaving those steps let two writers both see a phase pending, both
    append to the log, and the second discard the first's completion, leaving a
    transition recorded in history and missing from the state.

    Exercised in-process with a second lock holder, because the failure is
    about exclusion rather than about any coordinator's phase rules.
    """
    root.mkdir(parents=True, exist_ok=True)
    acquire_run_lock(root)

    # A second holder in this process would be granted the lock again, since
    # flock is per open file description, so exclusion is proven from a child.
    script = (
        "import fcntl, pathlib, sys\n"
        "handle = pathlib.Path(sys.argv[1]).open('w')\n"
        "try:\n"
        "    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)\n"
        "except OSError:\n"
        "    sys.exit(3)\n"
        "sys.exit(0)\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script, str(root / LOCK_FILE)],
        capture_output=True,
        check=False,
    )
    assert result.returncode == 3, f"a second writer acquired a held run lock ({result.returncode})"

    # The lock is bookkeeping, so a directory holding only one is still empty
    # enough to start a fresh run in, which is what a crashed run leaves.
    assert create_run(root) == root.resolve()

    # Opening a run is what takes the lock. Checking the lock in isolation
    # would still pass if open_run stopped calling for it, which is the whole
    # protection: a coordinator reaches a run through open_run and nowhere else.
    fresh = root.parent / "opened"
    state = {
        "version": VERSION,
        "phase": "only",
        "phases": ["only"],
        "completed": [],
        "created_at": now(),
        "updated_at": now(),
    }
    save_state(fresh, state, "initialized")
    (fresh / LOCK_FILE).unlink(missing_ok=True)
    open_run(fresh)
    assert (fresh / LOCK_FILE).exists(), "open_run did not take the run lock"

    # Opening the same run twice in one process must not block. flock is per
    # open file description, so a second handle would queue behind the first
    # one this process already holds, wait out the whole timeout, and then
    # report that a stranger held the lock. Nothing would be contending: the
    # caller would be deadlocked against itself. A CLI exits between runs so it
    # never sees this, but a test or a batch driver opens one run repeatedly.
    started = time.monotonic()
    open_run(fresh)
    elapsed = time.monotonic() - started
    assert elapsed < LOCK_TIMEOUT_SECONDS / 2, (
        f"re-opening a run held by this process took {elapsed:.1f}s; the lock is not re-entrant"
    )


def self_check():
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_json(root / "a.json", {"b": 1, "a": 2})
        assert read_json(root / "a.json") == {"a": 2, "b": 1}

        # Writes were validated and reads were not, so an artifact edited
        # between two commands reached the code reading its fields and raised
        # a KeyError naming one key: nothing said which file was wrong. Both
        # directions of the same schema are now enforced at the boundary.
        artifact = root / "findings.json"
        write_artifact(artifact, "findings.schema.json", {"findings": []})
        assert read_artifact(artifact, "findings.schema.json")["findings"] == []
        broken = json.loads(artifact.read_text())
        broken["findings"].append({"id": "F1"})
        write_json(artifact, broken)
        try:
            read_artifact(artifact, "findings.schema.json")
        except SystemExit as error:
            assert error.code == EX_DATAERR, error.code
        else:
            raise AssertionError("an artifact violating its schema was read as valid")
        assert json_sha256(root / "a.json") == json_sha256(root / "a.json")
        (root / "keep").mkdir()
        (root / "keep" / "f.txt").write_text("x")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("ref")
        manifest = relative_file_manifest(root)
        assert "keep/f.txt" in manifest
        assert not any(key.startswith(".git") for key in manifest)
        # A manifest is the promise that a tree can be snapshotted and restored
        # as a unit, so a link to content outside it must be refused rather than
        # recorded as an ordinary file. A link within the tree is fine: its
        # content is captured either way.
        (root / "keep" / "inside.txt").symlink_to(root / "keep" / "f.txt")
        assert "keep/inside.txt" in relative_file_manifest(root)
        outside = Path(temporary).parent / f"outside-{os.getpid()}.txt"
        outside.write_text("not mine")
        try:
            (root / "keep" / "escape.txt").symlink_to(outside)
            try:
                relative_file_manifest(root)
            except Failure as error:
                assert error.code == EX_DATAERR, error.code
                assert "leaves the tree" in error.message, error.message
            else:
                raise AssertionError("manifest recorded content living outside the tree")
        finally:
            outside.unlink()
            (root / "keep" / "escape.txt").unlink()
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
        # A slug names a directory, so it must fit a filesystem component
        # whatever it was built from, and must never end on the cut separator.
        for source in ("a " * 400, "x" * 400, "word-" * 50):
            produced = slug(source)
            assert len(produced) <= SLUG_LIMIT, (source[:20], len(produced))
            assert not produced.startswith("-") and not produced.endswith("-"), produced
        # A slug is also an identity, so truncation must not merge two subjects
        # into one: names differing only past the cut have to stay distinct, or
        # a run's provenance cannot say which skill it was about.
        shared = "shared-prefix-" * 6
        truncated = {slug(f"{shared}{index}") for index in range(200)}
        assert len(truncated) == 200, f"truncation collided: {200 - len(truncated)} lost"
        assert slug("a" * 100) != slug("a" * 101), "length alone must change the slug"
        check_canonical_digests(root)
        check_history_survives_state_loss(root / "run")
        check_open_run_rejects_edited_state(root / "edited")
        check_run_lock_serialises_writers(root / "locked")
        # Outside a repository there is nothing to ship, so callers must be told
        # to fall back rather than be handed an empty set they would read as
        # "this project ships no files".
        assert shipped_paths(root) is None

        # A filesystem refusal must arrive as the same failure shape as any
        # other, not as a traceback: the exit code is the contract, and a
        # traceback also prints absolute paths from the machine that ran it.
        for error, expected in (
            (OSError(errno.ENAMETOOLONG, "File name too long", "x" * 400), EX_DATAERR),
            (OSError(errno.EACCES, "Permission denied", "/root/secret"), EX_UNAVAILABLE),
        ):

            def raise_error(error=error):
                raise error

            try:
                with redirect_stderr(io.StringIO()) as captured:
                    run_cli(raise_error, argv=[])
            except SystemExit as exit_error:
                assert exit_error.code == expected, (error, exit_error.code)
                assert error.strerror in captured.getvalue()
            else:
                raise AssertionError(f"{error} did not exit")
        assert len(shorten("y" * 400)) < 200
        assert shorten("short") == "short"

    repository = Path(__file__).resolve().parent.parent
    shipped = shipped_paths(repository)
    if shipped is not None:
        assert "scripts/state.py" in shipped
        assert not any(name.startswith(".git/") for name in shipped)


if __name__ == "__main__":
    if not take_self_check(sys.argv[1:]):
        fail(f"Usage: state.py {SELF_CHECK}")
    run_self_check(self_check)
