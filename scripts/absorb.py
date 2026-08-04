#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Absorption coordinator: merge many source skills into one target safely.

Implements workflows/absorb.md. The control flow that matters lives here rather
than in prose: a plan is bound to a digest before any mutation, the target is
snapshotted so every failure path is reversible, retries are bounded, and each
phase refuses to advance without the evidence its contract names.
"""

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import (
    EX_DATAERR,
    EX_SOFTWARE,
    EX_TEMPFAIL,
    EX_UNAVAILABLE,
    Failure,
    fail,
)
from state import (
    TERMINAL_PHASES,
    VERSION,
    canonical_sha256,
    copy_manifest_files,
    create_run,
    excluded,
    json_sha256,
    now,
    open_run,
    paths_overlap,
    read_history,
    read_json,
    read_status,
    relative_file_manifest,
    remove_path,
    require_text,
    run_cli,
    safe_relative_path,
    save_state,
    schema_errors,
    slug,
    stamp,
    tree_sha256,
    write_artifact,
    write_json,
)
from state import (
    print_status as print_envelope,
)
from validate import validate as validate_skill

CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Which schema governs each agent-authored artifact. The analyses directory
# holds one file per source, so it is keyed by directory rather than by name.
SCHEMA_FOR = {
    "plan.json": "plan.schema.json",
    "apply.json": "apply.schema.json",
    "validation.json": "validation.schema.json",
    "feedback.json": "feedback.schema.json",
}


class MalformedEvidence(Failure):
    """Evidence the run cannot read yet, as opposed to execution proven unsafe.

    Rolling back for a mistyped field destroys a merge that was never unsafe, so
    the coordinator rejects the evidence and keeps the target and phase intact.
    A data error rather than a usage error: the caller invoked the coordinator
    correctly and the artifact is what is wrong.
    """

    def __init__(self, message):
        super().__init__(message, EX_DATAERR)


def malformed(message):
    raise MalformedEvidence(message)


def inspect_skill(path, allow_missing=False):
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        if allow_missing:
            return {"path": str(resolved), "exists": False, "files": {}, "sha256": None}
        fail(f"Skill path does not exist: {resolved}", EX_UNAVAILABLE, resolved)
    if not resolved.is_dir() or not (resolved / "SKILL.md").is_file():
        fail(f"Skill must be directory containing SKILL.md: {resolved}")
    files = relative_file_manifest(resolved)
    return {"path": str(resolved), "exists": True, "files": files, "sha256": tree_sha256(files)}


def validate_analysis(path, expected_source_id):
    """Shape from the schema; identity and uniqueness from here.

    The schema owns every field rule, so the two cannot drift. It cannot own
    the remaining two questions: which source this file is supposed to describe
    is knowable only from the inventory, and uniqueness over one property of a
    list item is not expressible in JSON Schema.
    """
    value = read_json(path)
    require_schema(path, "analysis.schema.json", value)
    if value.get("source_id") != expected_source_id:
        malformed(f"{path}: source_id must be {expected_source_id}")
    require_unique_ids(path, value["capabilities"], "capability")
    require_unique_ids(path, value["runtime_dependencies"], "runtime dependency")
    return value


def require_unique_ids(path, items, label):
    seen = set()
    for item in items:
        identifier = item["id"]
        if identifier in seen:
            malformed(f"{path}: duplicate {label} id {identifier}")
        seen.add(identifier)


def require_schema(path, name, value):
    """Reject an artifact that does not satisfy its schema, listing every fault.

    Reported as malformed evidence rather than unsafe execution: a mistyped
    field means the run cannot read the file yet, which is not proof that
    anything was done wrong to the target.
    """
    errors = schema_errors(name, value)
    if errors:
        detail = "\n  ".join(errors)
        malformed(f"{path}: does not satisfy {name}:\n  {detail}")


def capability_keys(root, inventory):
    keys = []
    items = ([{"id": "target"}] if inventory["target"]["exists"] else []) + inventory["sources"]
    for item in items:
        analysis = validate_analysis(root / "analyses" / f"{item['id']}.json", item["id"])
        keys.extend(f"{item['id']}:{capability['id']}" for capability in analysis["capabilities"])
    return keys


def runtime_dependency_keys(root, inventory):
    keys = []
    items = ([{"id": "target"}] if inventory["target"]["exists"] else []) + inventory["sources"]
    for item in items:
        analysis = validate_analysis(root / "analyses" / f"{item['id']}.json", item["id"])
        keys.extend(f"{item['id']}:{dependency['id']}" for dependency in analysis["runtime_dependencies"])
    return keys


def validate_plan(root, inventory):
    """Shape from the schema; cross-artifact coverage and path safety from here.

    The schema decides whether a plan is well formed. It cannot decide whether
    the plan is complete, because completeness is a question about the analyses
    in another directory: every capability and every runtime dependency found
    there must be decided exactly once, so nothing is silently dropped between
    reading a source and merging it.
    """
    path = root / "plan.json"
    value = read_json(path)
    require_schema(path, "plan.schema.json", value)

    require_coverage(path, value["capability_map"], capability_keys(root, inventory), "capability")
    require_coverage(
        path,
        value["runtime_adapter_map"],
        runtime_dependency_keys(root, inventory),
        "runtime dependency",
    )

    # A destination is inside the target, which is a property of the filesystem
    # rather than of the document, so it stays imperative.
    for item in value["capability_map"] + value["runtime_adapter_map"]:
        if "destination" in item:
            safe_relative_path(item["destination"], f"{path}: {item['key']} destination")

    planned_paths = set()
    for operation in value["file_operations"]:
        planned_paths.add(safe_relative_path(operation["path"], f"{path}: file operation path"))
        if operation["op"] == "move" and operation.get("from") is not None:
            planned_paths.add(safe_relative_path(operation["from"], f"{path}: move source"))

    # A capability integrated into a file that no operation touches is a plan
    # that decided where something goes and then did not go there. The merge
    # writes the file anyway, the bound plan does not authorize it, and the run
    # is rolled back at the gate: the omission is the plan's, and it is visible
    # here, before any target file has been touched.
    #
    # Only `integrate` implies an edit. `retain` names the owner that already
    # holds the concern and `generalize` points at guidance the merge need not
    # rewrite, so both legitimately name files no operation touches.
    unplanned = {}
    for item in value["capability_map"] + value["runtime_adapter_map"]:
        if item.get("decision") != "integrate":
            continue
        destination = item.get("destination")
        if destination is None:
            continue
        # Destinations may name an anchor within a document; the file is what
        # a file operation can be compared against.
        target = destination.split("#", 1)[0].strip()
        if not target or target.endswith("/"):
            continue
        if target not in planned_paths:
            unplanned.setdefault(target, []).append(item["key"])
    if unplanned:
        detail = "\n  ".join(f"{file} (from {', '.join(sorted(keys))})" for file, keys in sorted(unplanned.items()))
        fail(
            f"{path}: these integration destinations have no file operation, so the "
            f"merge would touch a path the plan does not authorize:\n  {detail}",
            EX_DATAERR,
            path,
        )

    require_coordinator_contracts(path, value, planned_paths, Path(inventory["target"]["path"]))
    return value, planned_paths


# Contracts every coordinator joins. Each is an obligation only while it is
# actually closed against members it does not name: an open schema accepts a
# new coordinator without being edited, and demanding an edit anyway would
# reject a correct plan.
COORDINATOR_CONTRACTS = (
    "schemas/status.schema.json",
    "schemas/state.schema.json",
)


def closed_contracts(target_root):
    """The coordinator contracts that would reject an undeclared member.

    Read from the target rather than assumed, because whether a contract is
    closed changes over time: the same plan is correct against an open schema
    and incomplete against a closed one.
    """
    closed = []
    for relative in COORDINATOR_CONTRACTS:
        path = target_root / relative
        if not path.is_file():
            continue
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # Either shape refuses a coordinator nobody declared: a closed object
        # rejects its state keys, and a closed enum rejects its kind.
        if schema.get("additionalProperties") is False:
            closed.append(relative)
            continue
        kind = schema.get("properties", {}).get("kind", {})
        if isinstance(kind, dict) and kind.get("enum"):
            closed.append(relative)
    return closed


def require_coordinator_contracts(path, value, planned_paths, target_root):
    """A plan that adds a coordinator must also plan the closed contracts it joins."""
    added = sorted(
        operation["path"]
        for operation in value["file_operations"]
        if operation["op"] == "create"
        and operation["path"].startswith("scripts/")
        and operation["path"].endswith(".py")
    )
    if not added:
        return
    missing = [contract for contract in closed_contracts(target_root) if contract not in planned_paths]
    if missing:
        fail(
            f"{path}: creates {', '.join(added)} but does not plan "
            f"{', '.join(missing)}. These contracts are closed against members "
            f"they do not name, so a coordinator that joins them without being "
            f"declared cannot print a status or write its own state.",
            EX_DATAERR,
            path,
        )


def require_coverage(path, decided, expected, label):
    """Every known key decided exactly once, and no key invented.

    Absorption's whole promise is that nothing is lost. A missing key means a
    capability disappeared between analysis and plan; an unknown key means the
    plan decided something no source actually offers.
    """
    keys = [item["key"] for item in decided]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    if duplicates:
        malformed(f"{path}: duplicate {label} keys: {duplicates}")
    missing = sorted(set(expected) - set(keys))
    unknown = sorted(set(keys) - set(expected))
    if missing or unknown:
        fail(f"{path}: {label} coverage mismatch; missing={missing}, unknown={unknown}", EX_DATAERR)


def bound_paths(root, state, inventory):
    """Paths the run may mutate: the bound plan plus recorded scope extensions.

    Extensions are additive and never replace a planned path, so the bound plan
    stays the source of intent while a mid-run repair does not require discarding
    a correct merge.
    """
    _, planned = validate_plan(root, inventory)
    for extension in state.get("scope_extensions", []):
        planned.update(extension["paths"])
    return planned


def validate_sources_unchanged(inventory):
    for source in inventory["sources"]:
        current = inspect_skill(Path(source["path"]))
        if current["sha256"] != source["sha256"]:
            fail(f"Source skill changed during absorption: {source['path']}", EX_DATAERR)


def validate_target_baseline(inventory):
    expected = inventory["target"]
    current = inspect_skill(Path(expected["path"]), allow_missing=True)
    if current["exists"] != expected["exists"] or current["sha256"] != expected["sha256"]:
        fail("Target changed after run initialization; start a new run", EX_DATAERR)


def create_rollback_snapshot(root, state, inventory):
    rollback_root = root / "rollback"
    remove_path(rollback_root)
    rollback_root.mkdir()
    target = inspect_skill(Path(inventory["target"]["path"]), allow_missing=True)
    if target["exists"] != inventory["target"]["exists"] or target["sha256"] != inventory["target"]["sha256"]:
        fail("Target no longer matches run baseline", EX_DATAERR)
    if target["exists"]:
        snapshot_root = rollback_root / "target"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        copy_manifest_files(Path(target["path"]), snapshot_root, target["files"])
        snapshot = inspect_skill(rollback_root / "target")
        if snapshot["sha256"] != target["sha256"]:
            fail("Rollback snapshot does not match target baseline", EX_DATAERR)
    write_json(
        rollback_root / "snapshot.json",
        {
            "plan_sha256": state["execution_plan_sha256"],
            "target_exists": target["exists"],
            "target_sha256": target["sha256"],
            "scope": "baseline",
        },
    )
    state["rollback_scope"] = "baseline"


def restore_tracked_files(snapshot_root, target, target_existed):
    """Restore only snapshot-tracked files.

    Version-control directories and other excluded paths are never captured, so
    they must never be deleted. Restoring file-by-file keeps unrelated worktree
    state intact while still returning every tracked path to its baseline.
    """
    if not target_existed:
        remove_path(target)
        return
    expected = relative_file_manifest(snapshot_root)
    for relative in expected:
        source = snapshot_root / relative
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        remove_path(destination)
        shutil.copy2(source, destination, follow_symlinks=False)
    for relative in relative_file_manifest(target):
        if relative not in expected:
            remove_path(target / relative)
    for directory in sorted(target.rglob("*"), reverse=True):
        if not directory.is_dir() or excluded(directory.relative_to(target).parts):
            continue
        if not any(directory.iterdir()):
            directory.rmdir()


def preserve_target_work(inventory, destination):
    """Copy current target work aside before an intentional plan revision.

    Rollback exists to undo unsafe execution, but a revision is a deliberate
    change of intent: the merge work done so far is usually still useful for
    the next plan. Preserving it turns revision into a cheap operation instead
    of a reason to widen the bound diff.
    """
    target = inspect_skill(Path(inventory["target"]["path"]), allow_missing=True)
    if not target["exists"]:
        return
    destination.mkdir(parents=True, exist_ok=True)
    copy_manifest_files(Path(target["path"]), destination, target["files"])


def rollback_target(root, state, inventory, reason):
    rollback_root = root / "rollback"
    snapshot = read_json(rollback_root / "snapshot.json")
    if snapshot.get("plan_sha256") != state.get("execution_plan_sha256"):
        fail("Rollback snapshot does not match bound plan", EX_DATAERR)
    target = Path(inventory["target"]["path"])

    # Verify the snapshot before trusting it to overwrite the target. It was
    # checked when written, but a restore reads it back much later, and
    # restore_tracked_files deletes every tracked path the snapshot does not
    # list. A snapshot that lost its files therefore reads as "the baseline had
    # no files" and empties the target, destroying the very work rollback
    # exists to protect. Refusing here leaves the target untouched, which is
    # always recoverable; the alternative is not.
    if snapshot.get("target_exists"):
        # inspect_skill rejects a directory with no SKILL.md, which a damaged
        # snapshot is exactly one instance of. Catching it here turns every
        # kind of damage into the same refusal rather than an unrelated error
        # about a malformed skill, which would not say the target was spared.
        try:
            held = inspect_skill(rollback_root / "target", allow_missing=True)
            intact = held["exists"] and held["sha256"] == snapshot.get("target_sha256")
        except SystemExit:
            intact = False
        if not intact:
            fail(
                "Rollback snapshot is damaged; target left untouched. "
                f"Restore the baseline by hand from {rollback_root / 'target'}",
                EX_DATAERR,
            )

    # Restoring the baseline is safe but lossy: an out-of-scope path or a failed
    # attempt would otherwise destroy correct merge work. Keep a copy first so a
    # rollback costs a re-bind rather than the whole merge.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    preserve_target_work(inventory, root / "revisions" / f"{stamp}-rollback-target")
    restore_tracked_files(rollback_root / "target", target, snapshot.get("target_exists"))
    restored = inspect_skill(target, allow_missing=True)
    if restored["exists"] != snapshot.get("target_exists") or restored["sha256"] != snapshot.get("target_sha256"):
        fail("Automatic rollback could not restore target baseline", EX_SOFTWARE)
    state["phase"] = "rolled-back"
    state["rollback_reason"] = reason
    save_state(root, state, "target-rolled-back")


def rollback_after_error(root, state, inventory, error):
    # Failure carries the prose separately from the exit code, so the rollback
    # reason records what went wrong rather than the number it exited with.
    message = error.message
    rollback_target(root, state, inventory, message)
    fail(f"{message}; target rolled back", error.code)


def write_provenance(root, state, inventory):
    """Record what this run absorbed, in the form the registry publishes.

    The run is what knows the baselines and the bound plan digest, and a human
    transcribing them into a table produces a second copy that can disagree
    with the run that produced it. Sources absorbed together share a plan digest
    and a run id, so a repeated digest reads as one batched run rather than as
    a copy-paste error.
    """
    records = []
    for source in inventory["sources"]:
        records.append(
            {
                "source": source["id"].split("-", 1)[-1],
                "baseline_kind": "local_tree_digest",
                "baseline": source["sha256"],
                "absorbed_on": now()[:10],
                "plan_sha256": state.get("execution_plan_sha256"),
                "run_id": state["run_id"],
            }
        )
    write_artifact(
        root / "provenance.json",
        "provenance.schema.json",
        {"records": records},
    )


def target_diff(inventory):
    original = inventory["target"]["files"]
    current_skill = inspect_skill(Path(inventory["target"]["path"]))
    current = current_skill["files"]
    changed = sorted(path for path, metadata in current.items() if original.get(path) != metadata)
    deleted = sorted(set(original) - set(current))
    return changed, deleted, current_skill


def validate_apply(root, state, inventory):
    path = root / "apply.json"
    value = read_json(path)
    require_schema(path, "apply.schema.json", value)
    current_plan_hash = json_sha256(root / "plan.json")
    if current_plan_hash != state.get("execution_plan_sha256"):
        fail("plan.json changed after binding; run revise-plan", EX_DATAERR)
    if value.get("plan_sha256") != current_plan_hash:
        fail(f"{path}: plan_sha256 does not match bound plan", EX_DATAERR)
    declared_changed = sorted(safe_relative_path(item, f"{path}: changed_files") for item in value["changed_files"])
    declared_deleted = sorted(safe_relative_path(item, f"{path}: deleted_files") for item in value["deleted_files"])
    changed, deleted, current_skill = target_diff(inventory)
    if declared_changed != changed or declared_deleted != deleted:
        fail(f"{path}: target diff mismatch; actual changed={changed}, actual deleted={deleted}", EX_DATAERR)
    planned_paths = bound_paths(root, state, inventory)
    outside_plan = sorted((set(changed) | set(deleted)) - planned_paths)
    if outside_plan:
        fail(
            f"{path}: changed paths outside bound plan: {outside_plan}; record them with extend-scope or revert them",
            EX_DATAERR,
        )
    validate_sources_unchanged(inventory)
    write_artifact(root / "target-after-merge.json", "skill.schema.json", current_skill)


def validate_validation(root, state):
    """Shape from the schema; the binding to this run's plan from here.

    Whether a validation record is self-consistent is a property of the
    document, so the schema decides it. Whether it describes *this* run is not:
    only the coordinator knows which plan digest execution was bound to.
    """
    path = root / "validation.json"
    value = read_json(path)
    require_schema(path, "validation.schema.json", value)
    if value["plan_sha256"] != state.get("execution_plan_sha256"):
        fail(f"{path}: plan_sha256 does not match bound plan", EX_DATAERR)
    return value


def validate_feedback(root):
    """Require an explicit orchestrator verdict before a run may complete.

    Every absorption exercises this coordinator against real material, so each
    run is also a test of the orchestrator itself. Without a recorded verdict,
    defects observed during a run are lost when the run artifacts age out. The
    schema owns the shape, including that a claim of "fixed" must name files.
    """
    path = root / "feedback.json"
    value = read_json(path)
    require_schema(path, "feedback.schema.json", value)
    return value


# The contract each phase answers to. A phase whose resource is the workflow
# that dispatched the coordinator answers "what do I read now?" with "the file
# you came from", so every phase names a section that owns its rules.
PHASE_RESOURCES = {
    "analysis": "references/absorb.md#analysis-dimensions",
    "plan": "references/absorb.md#merge-decisions",
    "merge": "references/absorb.md#merge-evidence",
    "validation": "references/absorb.md#validation-evidence",
    "complete": "references/absorb.md#orchestrator-feedback",
    "rolled-back": "references/absorb.md#conflict-policy",
}
PHASES = tuple(PHASE_RESOURCES)
# The ordered walk, ending in whichever terminal state the run reached. Which
# names count as terminal is owned by state.py, because open_run validates a
# resumed run's phase against them.
WORKING_PHASES = ("analysis", "plan", "merge", "validation")


def derive_phases(_capabilities=None):
    """Absorption's phases are fixed: every run analyses, plans, merges, validates.

    Unlike design and review, the shape does not vary with the target, so this
    takes no input. It exists so the repository's phase-owner check can treat
    all three coordinators the same way.
    """
    return list(PHASES)


def walked_phases(phase):
    """The phase list for a run currently on `phase`.

    Absorption does not record a completed list, because its progression is
    linear: reaching a phase is what proves the earlier ones closed. Deriving
    the list means it cannot drift from the phase the run is actually on, and a
    validation failure returning to `merge` correctly reports analysis and plan
    as still done.
    """
    terminal = phase if phase in TERMINAL_PHASES else "complete"
    return [*WORKING_PHASES, terminal]


def phase_resource(phase):
    return PHASE_RESOURCES[phase]


def next_action(phase):
    return {
        "analysis": "Write analyses/<source-id>.json for every source, then run complete-phase --phase analysis.",
        "plan": "Write plan.json with complete capability coverage, then run complete-phase --phase plan.",
        "merge": "Edit target only, write apply.json, then run complete-phase --phase merge.",
        "validation": "Run relevant checks, write validation.json, then run complete-phase --phase validation.",
        "rolled-back": "Target restored after unsafe or exhausted execution. Revise plan or start new run.",
    }[phase]


def durability(target_path):
    """Whether the merged work would survive this run directory being deleted.

    A completed absorption has edited a working tree and nothing more. If that
    tree is a scratch copy or the edits are uncommitted, the run reports success
    over work that one `rm -rf` removes, and the only record that anything was
    absorbed is the run directory itself. Reporting it is the difference between
    a run that finished and a change that landed.
    """
    target = Path(target_path)
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=str(target),
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return {
            "durable": False,
            "detail": "The target is not a git repository, so the merge exists only as files on disk.",
        }
    if result.stdout.strip():
        return {
            "durable": False,
            "detail": "The target has uncommitted changes; commit them or the merge is lost with the working tree.",
        }
    # Committed is not the same as reachable. A run against a throwaway clone
    # commits happily and the work still exists in exactly one directory, which
    # is how a completed absorption ends up somewhere nobody will look again.
    unpushed = subprocess.run(
        ["git", "log", "--oneline", "@{upstream}..HEAD"],
        cwd=str(target),
        capture_output=True,
        text=True,
        check=False,
    )
    if unpushed.returncode != 0:
        return {
            "durable": False,
            "detail": (
                "The target's branch tracks nothing, so the merge exists only in this "
                "clone. Push it, or merge it into the tree that is actually published."
            ),
        }
    if unpushed.stdout.strip():
        count = len(unpushed.stdout.strip().splitlines())
        return {
            "durable": False,
            "detail": f"The merge is committed but {count} commit(s) are unpushed, so it exists only in this clone.",
        }
    return {"durable": True, "detail": "The target's merged work is committed and pushed."}


def completion_action(target_path):
    state = durability(target_path)
    if state["durable"]:
        return "Run complete and the merge is committed. Keep artifacts for audit or remove them explicitly."
    return f"Run complete, but the merge is not durable. {state['detail']}"


def print_status(root, state, inventory):
    phase = state["phase"]
    phases = walked_phases(phase)
    target_path = inventory["target"]["path"]
    action = completion_action(target_path) if phase == "complete" else next_action(phase)
    detail = {
        "target": target_path,
        "source_count": len(inventory["sources"]),
        "validation_attempts": state["validation_attempts"],
        "max_validation_attempts": state["max_validation_attempts"],
        "plan_sha256": state.get("plan_sha256"),
        "execution_plan_sha256": state.get("execution_plan_sha256"),
        "rollback_scope": state.get("rollback_scope"),
        "rollback_reason": state.get("rollback_reason"),
    }
    if phase == "complete":
        # Reported as data as well as prose, so a wrapper can refuse to treat an
        # uncommitted merge as a landed change without parsing a sentence.
        detail["durable"] = durability(target_path)["durable"]
    print_envelope(
        "absorb",
        root,
        phase,
        phases,
        phases[: phases.index(phase)],
        phase_resource(phase),
        action,
        detail,
    )


def command_init(args):
    target = inspect_skill(args.target, allow_missing=args.new_target)
    if not target["exists"] and not args.new_target:
        fail("Missing target requires --new-target")
    target_path = Path(target["path"])
    root = create_run(args.run_dir, (target_path, "target skill"))
    sources = []
    seen = set()
    for index, source_path in enumerate(args.source, 1):
        source = inspect_skill(source_path)
        resolved_source = Path(source["path"])
        if paths_overlap(target_path, resolved_source):
            fail("Target and source skills must not overlap")
        if paths_overlap(root, resolved_source):
            fail("Run directory must not overlap source skills")
        if source["path"] in seen:
            fail(f"Duplicate source: {source['path']}")
        if any(paths_overlap(resolved_source, Path(item["path"])) for item in sources):
            fail("Source skills must not overlap")
        seen.add(source["path"])
        source["id"] = f"{index:03d}-{slug(Path(source['path']).name)}"
        sources.append(source)
    root.mkdir(parents=True, exist_ok=True)
    (root / "analyses").mkdir()
    inventory = {"created_at": now(), "target": target, "sources": sources}
    state = {
        "version": VERSION,
        # Identifies this run in provenance records. Sources absorbed together
        # share it, which is what distinguishes one batched run from several
        # runs that coincidentally recorded the same plan digest.
        "run_id": canonical_sha256(inventory)[:16],
        "phase": "analysis",
        "validation_attempts": 0,
        "max_validation_attempts": args.max_validation_attempts,
        "plan_sha256": None,
        "execution_plan_sha256": None,
        "rollback_scope": None,
        "rollback_reason": None,
        "scope_extensions": [],
        "created_at": now(),
        "updated_at": now(),
    }
    write_artifact(root / "inventory.json", "inventory.schema.json", inventory)
    save_state(root, state, "initialized")
    print_status(root, state, inventory)


def command_status(args):
    root, state, inventory = open_run(args.run_dir, "inventory.json")
    if args.history:
        print(json.dumps(read_history(root), indent=2, sort_keys=True))
        return
    print_status(root, state, inventory)


def command_complete_phase(args):
    root, state, inventory = open_run(args.run_dir, "inventory.json")
    phase = state["phase"]
    # Asserted rather than inferred. Inferring the phase makes a resumed run
    # easy to advance by mistake, because the caller's belief about where the
    # run is never has to agree with the run's own record.
    if args.phase != phase:
        fail(f"Run is on phase {phase!r}, not {args.phase!r}")
    require_text(args.note, "--note")
    resource = phase_resource(phase)
    if phase == "analysis":
        capability_keys(root, inventory)
        state["phase"] = "plan"
        save_state(root, state, "analysis-complete")
    elif phase == "plan":
        validate_plan(root, inventory)
        validate_sources_unchanged(inventory)
        validate_target_baseline(inventory)
        state["plan_sha256"] = json_sha256(root / "plan.json")
        state["execution_plan_sha256"] = state["plan_sha256"]
        state["rollback_reason"] = None
        create_rollback_snapshot(root, state, inventory)
        state["phase"] = "merge"
        save_state(root, state, "plan-bound")
    elif phase == "merge":
        try:
            validate_apply(root, state, inventory)
        except MalformedEvidence:
            raise
        except SystemExit as error:
            rollback_after_error(root, state, inventory, error)
        state["phase"] = "validation"
        save_state(root, state, "merge-recorded")
    elif phase == "validation":
        try:
            validate_apply(root, state, inventory)
            value = validate_validation(root, state)
        except MalformedEvidence:
            raise
        except SystemExit as error:
            rollback_after_error(root, state, inventory, error)
        if value["passed"]:
            # A merge rewrites the target's SKILL.md, so it can leave a skill
            # the host will refuse to load while the run reports success. The
            # claim is contradicted by a fact the coordinator can check itself,
            # so it is rejected here rather than believed and passed on.
            #
            # Malformed evidence rather than a failed validation: the merge was
            # not proven unsafe, so rolling the target back would destroy good
            # work over a frontmatter defect. The target and phase stay intact,
            # no attempt is spent, and re-running succeeds once it is fixed.
            errors = [f for f in validate_skill(Path(inventory["target"]["path"])) if f.severity == "error"]
            if errors:
                detail = "\n".join(f"  {f.message}\n    fix: {f.remedy}" for f in errors)
                malformed(f"validation.json reports passed, but the merged target does not conform:\n{detail}")
            # A completion requirement, not unsafe merge evidence: a missing or
            # malformed verdict must not discard a correct merge.
            validate_feedback(root)
        state["validation_attempts"] += 1
        attempt = state["validation_attempts"]
        attempts = root / "attempts"
        attempts.mkdir(exist_ok=True)
        shutil.copy2(root / "validation.json", attempts / f"{attempt:02d}-validation.json")
        shutil.copy2(root / "apply.json", attempts / f"{attempt:02d}-apply.json")
        if value["passed"]:
            state["phase"] = "complete"
            write_provenance(root, state, inventory)
            save_state(root, state, "validation-passed")
        elif attempt >= state["max_validation_attempts"]:
            rollback_target(root, state, inventory, "validation attempt bound reached")
            # Exhausting the bound is a real outcome, not a completed run. Exiting
            # zero here would let a wrapper report a rolled-back absorption as a
            # success, which is the one thing the bound exists to prevent.
            fail(
                f"Validation failed {attempt} times, reaching the bound; target rolled back",
                EX_TEMPFAIL,
            )
        else:
            state["phase"] = "merge"
            save_state(root, state, "validation-failed")
    else:
        fail(f"Cannot advance phase: {phase}")
    # Written after the transition, so a rejected phase leaves no record of a
    # decision that was never made.
    write_artifact(
        root / "decisions" / f"{phase}.json",
        "decision.schema.json",
        {"phase": phase, "resource": resource, "note": args.note, "recorded_at": now()},
    )
    print_status(root, state, inventory)


def command_extend_scope(args):
    """Widen the mutable path set without discarding correct merge work.

    A repair discovered mid-merge - most often a defect in this coordinator -
    otherwise costs a full rebind and remerge, which makes the safe route the
    expensive one. Extensions are additive, reasoned, and still confined to the
    pre-mutation snapshot, so reversibility is unchanged.
    """
    root, state, inventory = open_run(args.run_dir, "inventory.json")
    if state["phase"] not in {"merge", "validation"}:
        fail(f"Cannot extend scope during phase: {state['phase']}")
    reason = args.reason.strip()
    if not reason:
        fail("--reason must be non-empty")
    _, planned = validate_plan(root, inventory)
    already = set(planned)
    for extension in state.get("scope_extensions", []):
        already.update(extension["paths"])
    added = sorted({safe_relative_path(item, "extend-scope path") for item in args.path} - already)
    if not added:
        fail("Every requested path is already inside the bound scope")
    state.setdefault("scope_extensions", []).append({"paths": added, "reason": reason, "recorded_at": now()})
    save_state(root, state, "scope-extended")
    print_status(root, state, inventory)


def command_revise_plan(args):
    root, state, inventory = open_run(args.run_dir, "inventory.json")
    if state["phase"] not in {"merge", "validation", "rolled-back"}:
        fail(f"Cannot revise plan during phase: {state['phase']}")
    revisions = root / "revisions"
    revisions.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if state["phase"] in {"merge", "validation"}:
        preserve_target_work(inventory, revisions / f"{stamp}-target")
        rollback_target(root, state, inventory, "plan revision requested")
    for name in ("plan.json", "apply.json", "validation.json"):
        path = root / name
        if path.exists():
            shutil.copy2(path, revisions / f"{stamp}-{name}")
    state["phase"] = "plan"
    state["plan_sha256"] = None
    state["execution_plan_sha256"] = None
    state["rollback_scope"] = None
    state["rollback_reason"] = None
    # Extensions authorize paths against one bound plan; a new plan re-decides them.
    state["scope_extensions"] = []
    remove_path(root / "rollback")
    save_state(root, state, "plan-revision-requested")
    print_status(root, state, inventory)


def command_self_check(_args):
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        executable = Path(__file__).resolve()

        def execute(*arguments, check=True):
            return subprocess.run(
                [sys.executable, str(executable), *map(str, arguments)],
                check=check,
                capture_output=True,
                text=True,
            )

        def advance(run, note="phase complete", check=True):
            """Close whichever phase the run is on.

            An agent reads status to learn the phase, then names it when closing
            it. The self-check does the same rather than hardcoding a phase at
            each call site, so a change to the phase order does not silently
            turn these into assertions about the wrong phase.
            """
            phase = read_status(execute("status", "--run-dir", run).stdout)["phase"]
            return execute("complete-phase", "--run-dir", run, "--phase", phase, "--note", note, check=check)

        def write_evidence(path, value):
            """Write an agent-authored artifact the way an agent would.

            The self-check stands in for the agent, so it must produce artifacts
            carrying the same schema stamp a real run would, or it would be
            exercising a path no real run takes.
            """
            write_json(path, stamp(SCHEMA_FOR.get(path.name, "analysis.schema.json"), value))

        def create_skill(path, name):
            path.mkdir()
            content = f"---\nname: {name}\ndescription: {name} skill.\n---\n\n# {name.title()}\n"
            (path / "SKILL.md").write_text(content)
            return content

        def prepare_run(name, source_count=1, max_attempts=2):
            target = root / f"{name}-target"
            sources = [root / f"{name}-source-{index:02d}" for index in range(1, source_count + 1)]
            run = root / f"{name}-run"
            baseline = create_skill(target, f"{name}-target")
            for index, source in enumerate(sources, 1):
                create_skill(source, f"{name}-source-{index:02d}")
            init_arguments = ["init", "--target", target, "--run-dir", run, "--max-validation-attempts", max_attempts]
            for source in sources:
                init_arguments.extend(("--source", source))
            execute(*init_arguments)
            source_ids = [item["id"] for item in read_json(run / "inventory.json")["sources"]]
            write_evidence(
                run / "analyses" / "target.json",
                {
                    "source_id": "target",
                    "summary": "Existing target behavior",
                    "capabilities": [
                        {"id": "target-baseline", "purpose": "Preserve target behavior", "evidence": ["SKILL.md"]},
                    ],
                    "triggers": [],
                    "resources": [],
                    "overlaps": [],
                    "conflicts": [],
                    "risks": [],
                    "runtime_dependencies": [],
                },
            )
            for index, source_id in enumerate(source_ids):
                runtime_dependencies = []
                if index == 0:
                    runtime_dependencies = [
                        {"id": "vendor-tool", "symbol": "VendorTool", "kind": "tool", "evidence": ["SKILL.md"]},
                    ]
                write_evidence(
                    run / "analyses" / f"{source_id}.json",
                    {
                        "source_id": source_id,
                        "summary": "Adds source behavior",
                        "capabilities": [
                            {"id": "source-behavior", "purpose": "Provide behavior", "evidence": ["SKILL.md"]},
                        ],
                        "triggers": [],
                        "resources": [],
                        "overlaps": [],
                        "conflicts": [],
                        "risks": [],
                        "runtime_dependencies": runtime_dependencies,
                    },
                )
            advance(run)
            capability_map = [
                {
                    "key": "target:target-baseline",
                    "decision": "retain",
                    "destination": "SKILL.md",
                    "reason": "Preserve target behavior",
                }
            ]
            capability_map.extend(
                {
                    "key": f"{source_id}:source-behavior",
                    "decision": "integrate",
                    "destination": "SKILL.md",
                    "reason": "Core behavior",
                }
                for source_id in source_ids
            )
            write_evidence(
                run / "plan.json",
                {
                    "target_contract": {
                        "name": f"{name}-target",
                        "description": "Combined target skill.",
                        "runtime_policy": "runtime-neutral",
                        "scope": ["behavior"],
                        "non_goals": [],
                    },
                    "capability_map": capability_map,
                    "runtime_adapter_map": [
                        {
                            "key": f"{source_ids[0]}:vendor-tool",
                            "decision": "generalize",
                            "destination": "SKILL.md",
                            "reason": "Use runtime-neutral host capability",
                        }
                    ],
                    "decisions": [],
                    "file_operations": [
                        {"op": "update", "path": "SKILL.md", "purpose": "Absorb behavior", "sources": source_ids},
                    ],
                    "omitted_items": [],
                    "risks": [],
                    "validation_commands": ["self-check"],
                },
            )
            advance(run)
            state = read_json(run / "state.json")
            assert state["phase"] == "merge"
            assert state["execution_plan_sha256"] == state["plan_sha256"] == json_sha256(run / "plan.json")
            assert (run / "rollback" / "snapshot.json").is_file()
            return target, sources, run, baseline, state["plan_sha256"]

        def write_apply(run, plan_hash, changed, deleted=(), notes=()):
            """Write one merge-apply report.

            The self-check writes this report ten times and varies only the
            changed set and the notes, so the shape lives here once.
            """
            write_evidence(
                run / "apply.json",
                {
                    "plan_sha256": plan_hash,
                    "changed_files": list(changed),
                    "deleted_files": list(deleted),
                    "notes": notes if isinstance(notes, str) else list(notes),
                },
            )

        target, sources, run, _baseline, plan_hash = prepare_run("success", source_count=10)
        (target / "SKILL.md").write_text(
            "---\nname: target\ndescription: Combined target skill.\n---\n\n# Target\n\nCombined.\n"
        )
        write_apply(run, plan_hash, ["SKILL.md"])
        advance(run)
        write_evidence(
            run / "validation.json",
            {
                "plan_sha256": plan_hash,
                "passed": False,
                "checks": [{"name": "first pass", "command": "self-check", "exit_code": 1}],
                "remaining_gaps": ["Needs repair"],
                "notes": [],
            },
        )
        advance(run)
        write_apply(run, plan_hash, ["SKILL.md"], notes=["Repaired"])
        advance(run)
        write_evidence(
            run / "validation.json",
            {
                "plan_sha256": plan_hash,
                "passed": True,
                "checks": [{"name": "second pass", "command": "self-check", "exit_code": 0}],
                "remaining_gaps": [],
                "notes": [],
            },
        )
        # A passing run cannot complete until the orchestrator verdict exists.
        missing_feedback = advance(run, check=False)
        assert missing_feedback.returncode != 0 and "feedback.json" in missing_feedback.stderr
        write_evidence(
            run / "feedback.json",
            {
                "observations": [
                    {
                        "issue": "Observed coordinator defect",
                        "evidence": "self-check",
                        "disposition": "fixed",
                        "changed_files": ["scripts/absorb.py"],
                    },
                    {
                        "issue": "Known limitation",
                        "evidence": "self-check",
                        "disposition": "accepted",
                        "reason": "Out of scope for this run",
                    },
                ],
                "improvements": ["Recorded during self-check"],
            },
        )
        # A "fixed" verdict must name the files that carry the fix.
        unproven = read_json(run / "feedback.json")
        unproven["observations"][0].pop("changed_files")
        write_evidence(run / "feedback.json", unproven)
        unproven_result = advance(run, check=False)
        assert unproven_result.returncode != 0 and "changed_files" in unproven_result.stderr
        assert read_json(run / "state.json")["phase"] == "validation"
        unproven["observations"][0]["changed_files"] = ["scripts/absorb.py"]
        write_evidence(run / "feedback.json", unproven)

        # A merge that leaves the target non-conforming cannot pass, however
        # confident validation.json is: the merge rewrote SKILL.md, so it is
        # the run that can still fix it. Rejected as malformed evidence, so a
        # frontmatter defect neither rolls back a sound merge nor spends an
        # attempt, and the run resumes once the target is repaired.
        merged = (target / "SKILL.md").read_text()
        (target / "SKILL.md").write_text(merged.replace("name: target", "name: bad--target"))
        nonconforming = advance(run, check=False)
        assert nonconforming.returncode != 0 and "does not conform" in nonconforming.stderr
        assert "fix: " in nonconforming.stderr, nonconforming.stderr
        after = read_json(run / "state.json")
        assert after["phase"] == "validation", after["phase"]
        assert after["validation_attempts"] == 1, "a format defect must not spend a validation attempt"
        (target / "SKILL.md").write_text(merged)

        advance(run)
        state = read_json(run / "state.json")
        assert state["phase"] == "complete"
        assert state["validation_attempts"] == 2

        # A completed run records its own provenance, so the registry is a view
        # of what the run knew rather than a hand-transcribed second copy.
        provenance = read_json(run / "provenance.json")
        assert len(provenance["records"]) == len(read_json(run / "inventory.json")["sources"])
        assert {record["run_id"] for record in provenance["records"]} == {state["run_id"]}
        assert {record["plan_sha256"] for record in provenance["records"]} == {state["execution_plan_sha256"]}, (
            "sources absorbed in one run share its bound plan digest"
        )
        for record in provenance["records"]:
            assert record["baseline_kind"] == "local_tree_digest", record
        for source in sources:
            recorded = read_json(run / "inventory.json")["sources"]
            expected = next(item["sha256"] for item in recorded if item["path"] == str(source.resolve()))
            assert inspect_skill(source)["sha256"] == expected

        target, _sources, run, baseline, plan_hash = prepare_run("scope")
        (target / "SKILL.md").write_text("changed\n")
        (target / "EXTRA.md").write_text("outside plan\n")
        write_apply(run, plan_hash, ["EXTRA.md", "SKILL.md"])
        result = advance(run, check=False)
        assert result.returncode != 0 and "target rolled back" in result.stderr
        assert read_json(run / "state.json")["phase"] == "rolled-back"
        assert (target / "SKILL.md").read_text() == baseline
        assert not (target / "EXTRA.md").exists()
        # Rollback restores the baseline but must not destroy the merge attempt.
        preserved = [path for path in (run / "revisions").iterdir() if path.name.endswith("-rollback-target")]
        assert len(preserved) == 1, preserved
        assert (preserved[0] / "SKILL.md").read_text() == "changed\n"
        assert (preserved[0] / "EXTRA.md").read_text() == "outside plan\n"

        # A snapshot that lost its files must never be treated as a baseline
        # with no files: restoring from it would delete every tracked path and
        # leave the target empty, which is the one outcome rollback exists to
        # prevent. Refusing keeps the damaged merge, which is still recoverable.
        for damage in ("removed", "emptied", "tampered"):
            target, _sources, run, _baseline, plan_hash = prepare_run(f"damaged-{damage}")
            snapshot_target = run / "rollback" / "target"
            if damage == "removed":
                shutil.rmtree(snapshot_target)
            elif damage == "emptied":
                for path in snapshot_target.rglob("*"):
                    if path.is_file():
                        path.unlink()
            else:
                (snapshot_target / "SKILL.md").write_text("tampered\n")
            (target / "SKILL.md").write_text("changed\n")
            write_apply(run, plan_hash, ["EXTRA.md", "SKILL.md"])
            result = advance(run, check=False)
            assert result.returncode != 0, damage
            assert "Rollback snapshot is damaged" in result.stderr, (damage, result.stderr)
            # The target keeps the merge attempt rather than being emptied.
            assert (target / "SKILL.md").read_text() == "changed\n", damage
            assert read_json(run / "state.json")["phase"] == "merge", damage

        # Malformed evidence is a reporting mistake, not unsafe execution: the
        # merge survives, the phase holds, and a corrected file advances the run.
        target, _sources, run, _baseline, plan_hash = prepare_run("malformed")
        merged = "---\nname: target\ndescription: Combined target skill.\n---\n\n# Target\n\nMerged.\n"
        (target / "SKILL.md").write_text(merged)
        write_apply(run, plan_hash, ["SKILL.md"], notes="not a list")
        result = advance(run, check=False)
        assert result.returncode != 0 and "does not satisfy apply.schema.json" in result.stderr
        assert "notes" in result.stderr
        assert "rolled back" not in result.stderr
        assert read_json(run / "state.json")["phase"] == "merge"
        assert (target / "SKILL.md").read_text() == merged
        write_apply(run, plan_hash, ["SKILL.md"])
        advance(run)
        assert read_json(run / "state.json")["phase"] == "validation"
        write_evidence(
            run / "validation.json",
            {
                "plan_sha256": plan_hash,
                "passed": "yes",
                "checks": [],
                "remaining_gaps": [],
                "notes": [],
            },
        )
        result = advance(run, check=False)
        assert result.returncode != 0 and "rolled back" not in result.stderr
        assert read_json(run / "state.json")["phase"] == "validation"
        assert (target / "SKILL.md").read_text() == merged

        # A mid-run repair outside the bound plan is recordable, not fatal: the
        # merge survives, the extension is reasoned, and rollback still reverses it.
        target, _sources, run, baseline, plan_hash = prepare_run("extend")
        (target / "SKILL.md").write_text("merged\n")
        (target / "helper.py").write_text("fix\n")
        write_apply(run, plan_hash, ["SKILL.md", "helper.py"])
        blocked = advance(run, check=False)
        assert blocked.returncode != 0 and "extend-scope" in blocked.stderr
        assert read_json(run / "state.json")["phase"] == "rolled-back"

        target, _sources, run, baseline, plan_hash = prepare_run("extend-ok", max_attempts=1)
        (target / "SKILL.md").write_text("merged\n")
        (target / "helper.py").write_text("fix\n")
        write_apply(run, plan_hash, ["SKILL.md", "helper.py"])
        execute(
            "extend-scope",
            "--run-dir",
            run,
            "--path",
            "helper.py",
            "--reason",
            "Coordinator fix found during merge",
        )
        recorded = read_json(run / "state.json")["scope_extensions"]
        assert recorded and recorded[0]["paths"] == ["helper.py"] and recorded[0]["reason"]
        # An empty or duplicate extension is rejected rather than silently recorded.
        assert (
            execute(
                "extend-scope", "--run-dir", run, "--path", "helper.py", "--reason", "again", check=False
            ).returncode
            != 0
        )
        assert (
            execute("extend-scope", "--run-dir", run, "--path", "other.py", "--reason", " ", check=False).returncode
            != 0
        )
        advance(run)
        assert read_json(run / "state.json")["phase"] == "validation"
        write_evidence(
            run / "validation.json",
            {
                "plan_sha256": plan_hash,
                "passed": False,
                "checks": [{"name": "fails", "command": "self-check", "exit_code": 1}],
                "remaining_gaps": ["unresolved"],
                "notes": [],
            },
        )
        # Exhausting the attempt bound is a distinct outcome, so it exits
        # EX_TEMPFAIL rather than reporting the rolled-back run as a success.
        exhausted = advance(run, check=False)
        assert exhausted.returncode == EX_TEMPFAIL, exhausted.returncode
        assert "reaching the bound" in exhausted.stderr, exhausted.stderr
        assert read_json(run / "state.json")["phase"] == "rolled-back"
        # The extended path is snapshot-covered, so rollback removes it too.
        assert (target / "SKILL.md").read_text() == baseline
        assert not (target / "helper.py").exists()

        target, _sources, run, baseline, plan_hash = prepare_run("vcs")
        vcs = target / ".git"
        vcs.mkdir()
        (vcs / "HEAD").write_text("ref: refs/heads/main\n")
        assert inspect_skill(target)["sha256"] == read_json(run / "inventory.json")["target"]["sha256"]
        (target / "SKILL.md").write_text("changed\n")
        (target / "EXTRA.md").write_text("outside plan\n")
        write_apply(run, plan_hash, ["EXTRA.md", "SKILL.md"])
        result = advance(run, check=False)
        assert result.returncode != 0 and "target rolled back" in result.stderr
        assert (target / "SKILL.md").read_text() == baseline
        assert not (target / "EXTRA.md").exists()
        assert (vcs / "HEAD").read_text() == "ref: refs/heads/main\n"
        assert not (run / "rollback" / "target" / ".git").exists()

        target, _sources, run, baseline, plan_hash = prepare_run("bounded", max_attempts=1)
        (target / "SKILL.md").write_text("changed\n")
        write_apply(run, plan_hash, ["SKILL.md"])
        advance(run)
        write_evidence(
            run / "validation.json",
            {
                "plan_sha256": plan_hash,
                "passed": False,
                "checks": [{"name": "bounded failure", "command": "self-check", "exit_code": 1}],
                "remaining_gaps": ["Cannot complete safely"],
                "notes": [],
            },
        )
        bounded = advance(run, check=False)
        assert bounded.returncode == EX_TEMPFAIL, bounded.returncode
        assert read_json(run / "state.json")["phase"] == "rolled-back"
        assert (target / "SKILL.md").read_text() == baseline

        target, _sources, run, baseline, plan_hash = prepare_run("revision")
        (target / "SKILL.md").write_text("partially merged target\n")
        write_apply(run, plan_hash, ["SKILL.md"])
        advance(run)
        execute("revise-plan", "--run-dir", run)
        state = read_json(run / "state.json")
        assert state["phase"] == "plan"
        assert state["execution_plan_sha256"] is None
        assert (target / "SKILL.md").read_text() == baseline
        assert not (run / "rollback").exists()
        assert any(path.name.endswith("-plan.json") for path in (run / "revisions").iterdir())

        # A plan that adds a coordinator without planning the contracts it
        # joins is the omission that produced a rolled-back merge: the schemas
        # are closed against members they do not name, so the merge had to
        # touch a path the plan never authorized. The obligation follows the
        # target's actual schemas, since the same plan is complete against an
        # open contract and incomplete against a closed one.
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / "schemas").mkdir()
            assert closed_contracts(tree) == [], "a tree with no schemas obliges nothing"

            open_state = {"properties": {"phase": {"type": "string"}}}
            write_json(tree / "schemas" / "state.schema.json", open_state)
            assert closed_contracts(tree) == [], "an open schema was treated as an obligation"

            open_state["additionalProperties"] = False
            write_json(tree / "schemas" / "state.schema.json", open_state)
            assert closed_contracts(tree) == ["schemas/state.schema.json"]

            write_json(
                tree / "schemas" / "status.schema.json",
                {"properties": {"kind": {"enum": ["design"]}}},
            )
            assert len(closed_contracts(tree)) == 2, closed_contracts(tree)

            adding = {
                "file_operations": [{"op": "create", "path": "scripts/new.py"}],
                "capability_map": [],
                "runtime_adapter_map": [],
            }
            plan_path = Path("plan.json")
            try:
                require_coordinator_contracts(plan_path, adding, {"scripts/new.py"}, tree)
            except SystemExit as error:
                assert error.code == EX_DATAERR, error.code
            else:
                raise AssertionError("a coordinator joining closed contracts was accepted")

            complete = set(closed_contracts(tree)) | {"scripts/new.py"}
            require_coordinator_contracts(plan_path, adding, complete, tree)

            # A plan that adds no coordinator carries no such obligation.
            require_coordinator_contracts(
                plan_path,
                {"file_operations": [{"op": "update", "path": "SKILL.md"}]},
                {"SKILL.md"},
                tree,
            )

        # A completed run reports whether the merge would survive the run
        # directory being deleted. Reporting completion over an uncommitted or
        # scratch tree is how an absorption finishes and lands nowhere.
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            loose = tree / "loose"
            loose.mkdir()
            (loose / "SKILL.md").write_text("merged\n", encoding="utf-8")
            assert not durability(loose)["durable"], "a non-repository target was called durable"

            repository = tree / "repository"
            repository.mkdir()
            for command in (
                ["git", "init", "-q"],
                ["git", "config", "user.email", "absorb@example.invalid"],
                ["git", "config", "user.name", "absorb self-check"],
            ):
                subprocess.run(command, cwd=str(repository), check=True, capture_output=True)
            (repository / "SKILL.md").write_text("merged\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=str(repository), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "merge"],
                cwd=str(repository),
                check=True,
                capture_output=True,
            )
            assert not durability(repository)["durable"], "a clone whose branch tracks nothing was called durable"
            assert "not durable" in completion_action(repository)

            # With an upstream that has the commit, the work is reachable from
            # somewhere other than this directory.
            origin = tree / "origin.git"
            subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True, capture_output=True)
            for command in (
                ["git", "remote", "add", "origin", str(origin)],
                ["git", "push", "-q", "-u", "origin", "HEAD"],
            ):
                subprocess.run(command, cwd=str(repository), check=True, capture_output=True)
            assert durability(repository)["durable"], "a pushed merge was called fragile"
            assert "committed" in completion_action(repository)

            # A commit made after the push is again reachable from one place.
            (repository / "SKILL.md").write_text("merged further\n", encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=str(repository), check=True, capture_output=True)
            subprocess.run(
                ["git", "commit", "-q", "-m", "later"],
                cwd=str(repository),
                check=True,
                capture_output=True,
            )
            assert not durability(repository)["durable"], "an unpushed commit was called durable"

            (repository / "SKILL.md").write_text("uncommitted\n", encoding="utf-8")
            assert not durability(repository)["durable"], "an uncommitted merge was called durable"
            assert "not durable" in completion_action(repository)
    print("self-check passed")


def parser():
    root = argparse.ArgumentParser(description="Coordinate semantic absorption of many skills into one target.")
    # Global, so it precedes the subcommand like any other tool-wide flag. A
    # per-subcommand copy would let one run report failures in a shape another
    # run of the same coordinator does not.
    root.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="failure output shape: prose (default), or RFC 9457 problem details",
    )
    commands = root.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init")
    initialize.add_argument("--target", type=Path, required=True)
    initialize.add_argument("--source", type=Path, action="append", required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)
    initialize.add_argument("--new-target", action="store_true")
    initialize.add_argument("--max-validation-attempts", type=int, default=3)
    initialize.set_defaults(handler=command_init)

    complete = commands.add_parser("complete-phase")
    complete.add_argument("--run-dir", type=Path, required=True)
    complete.add_argument("--phase", required=True, choices=PHASES)
    complete.add_argument("--note", required=True, help="why this phase is done")
    complete.set_defaults(handler=command_complete_phase, history=False)

    for name, handler in (
        ("status", command_status),
        ("revise-plan", command_revise_plan),
    ):
        command = commands.add_parser(name)
        command.add_argument("--run-dir", type=Path, required=True)
        command.set_defaults(handler=handler, history=False)
        if name == "status":
            command.add_argument(
                "--history",
                action="store_true",
                help="show the run's transition log instead of its current status",
            )

    extend = commands.add_parser("extend-scope")
    extend.add_argument("--run-dir", type=Path, required=True)
    extend.add_argument("--path", action="append", required=True)
    extend.add_argument("--reason", required=True)
    extend.set_defaults(handler=command_extend_scope)

    self_check = commands.add_parser("self-check")
    self_check.set_defaults(handler=command_self_check)
    return root


def main():
    args = parser().parse_args()
    if getattr(args, "max_validation_attempts", 1) < 1:
        fail("--max-validation-attempts must be at least 1")
    args.handler(args)


if __name__ == "__main__":
    run_cli(main)
