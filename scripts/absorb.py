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

from state import (
    VERSION,
    check_version,
    copy_manifest_files,
    excluded,
    fail,
    json_sha256,
    now,
    paths_overlap,
    read_history,
    read_json,
    relative_file_manifest,
    remove_path,
    safe_relative_path,
    save_state,
    schema_errors,
    slug,
    stamp,
    tree_sha256,
    write_artifact,
    write_json,
)

CAPABILITY_ID = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
# Which schema governs each agent-authored artifact. The analyses directory
# holds one file per source, so it is keyed by directory rather than by name.
SCHEMA_FOR = {
    "plan.json": "plan.schema.json",
    "apply.json": "apply.schema.json",
    "validation.json": "validation.schema.json",
    "feedback.json": "feedback.schema.json",
}


class MalformedEvidence(SystemExit):
    """Evidence the run cannot read yet, as opposed to execution proven unsafe.

    Rolling back for a mistyped field destroys a merge that was never unsafe, so
    the coordinator rejects the evidence and keeps the target and phase intact.
    """


def malformed(message):
    raise MalformedEvidence(message)


def inspect_skill(path, allow_missing=False):
    resolved = path.expanduser().resolve()
    if not resolved.exists():
        if allow_missing:
            return {"path": str(resolved), "exists": False, "files": {}, "sha256": None}
        fail(f"Skill path does not exist: {resolved}")
    if not resolved.is_dir() or not (resolved / "SKILL.md").is_file():
        fail(f"Skill must be directory containing SKILL.md: {resolved}")
    files = relative_file_manifest(resolved)
    return {"path": str(resolved), "exists": True, "files": files, "sha256": tree_sha256(files)}


def load_run(run_dir):
    root = run_dir.expanduser().resolve()
    state = read_json(root / "state.json")
    inventory = read_json(root / "inventory.json")
    check_version(state)
    return root, state, inventory


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
    return value, planned_paths


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
        fail(f"{path}: {label} coverage mismatch; missing={missing}, unknown={unknown}")


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
            fail(f"Source skill changed during absorption: {source['path']}")


def validate_target_baseline(inventory):
    expected = inventory["target"]
    current = inspect_skill(Path(expected["path"]), allow_missing=True)
    if current["exists"] != expected["exists"] or current["sha256"] != expected["sha256"]:
        fail("Target changed after run initialization; start a new run")


def create_rollback_snapshot(root, state, inventory):
    rollback_root = root / "rollback"
    remove_path(rollback_root)
    rollback_root.mkdir()
    target = inspect_skill(Path(inventory["target"]["path"]), allow_missing=True)
    if target["exists"] != inventory["target"]["exists"] or target["sha256"] != inventory["target"]["sha256"]:
        fail("Target no longer matches run baseline")
    if target["exists"]:
        snapshot_root = rollback_root / "target"
        snapshot_root.mkdir(parents=True, exist_ok=True)
        copy_manifest_files(Path(target["path"]), snapshot_root, target["files"])
        snapshot = inspect_skill(rollback_root / "target")
        if snapshot["sha256"] != target["sha256"]:
            fail("Rollback snapshot does not match target baseline")
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
        fail("Rollback snapshot does not match bound plan")
    target = Path(inventory["target"]["path"])
    # Restoring the baseline is safe but lossy: an out-of-scope path or a failed
    # attempt would otherwise destroy correct merge work. Keep a copy first so a
    # rollback costs a re-bind rather than the whole merge.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    preserve_target_work(inventory, root / "revisions" / f"{stamp}-rollback-target")
    restore_tracked_files(rollback_root / "target", target, snapshot.get("target_exists"))
    restored = inspect_skill(target, allow_missing=True)
    if restored["exists"] != snapshot.get("target_exists") or restored["sha256"] != snapshot.get("target_sha256"):
        fail("Automatic rollback could not restore target baseline")
    state["phase"] = "rolled-back"
    state["rollback_reason"] = reason
    save_state(root, state, "target-rolled-back")


def rollback_after_error(root, state, inventory, error):
    message = str(error)
    rollback_target(root, state, inventory, message)
    fail(f"{message}; target rolled back")


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
        fail("plan.json changed after binding; run revise-plan")
    if value.get("plan_sha256") != current_plan_hash:
        fail(f"{path}: plan_sha256 does not match bound plan")
    declared_changed = sorted(safe_relative_path(item, f"{path}: changed_files") for item in value["changed_files"])
    declared_deleted = sorted(safe_relative_path(item, f"{path}: deleted_files") for item in value["deleted_files"])
    changed, deleted, current_skill = target_diff(inventory)
    if declared_changed != changed or declared_deleted != deleted:
        fail(f"{path}: target diff mismatch; actual changed={changed}, actual deleted={deleted}")
    planned_paths = bound_paths(root, state, inventory)
    outside_plan = sorted((set(changed) | set(deleted)) - planned_paths)
    if outside_plan:
        fail(f"{path}: changed paths outside bound plan: {outside_plan}; record them with extend-scope or revert them")
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
        fail(f"{path}: plan_sha256 does not match bound plan")
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


def next_action(phase):
    return {
        "analysis": "Write analyses/<source-id>.json for every source, then run advance.",
        "plan": "Write plan.json with complete capability coverage, then run advance.",
        "merge": "Edit target only, write apply.json, then run advance.",
        "validation": "Run relevant checks, write validation.json, then run advance.",
        "complete": "Run complete. Keep artifacts for audit or remove them explicitly.",
        "rolled-back": "Target restored after unsafe or exhausted execution. Revise plan or start new run.",
    }[phase]


def print_status(root, state, inventory):
    output = {
        "run_dir": str(root),
        "phase": state["phase"],
        "target": inventory["target"]["path"],
        "source_count": len(inventory["sources"]),
        "validation_attempts": state["validation_attempts"],
        "max_validation_attempts": state["max_validation_attempts"],
        "plan_sha256": state.get("plan_sha256"),
        "execution_plan_sha256": state.get("execution_plan_sha256"),
        "rollback_scope": state.get("rollback_scope"),
        "rollback_reason": state.get("rollback_reason"),
        "next_action": next_action(state["phase"]),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


def command_init(args):
    root = args.run_dir.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        fail(f"Run directory must be absent or empty: {root}")
    target = inspect_skill(args.target, allow_missing=args.new_target)
    if not target["exists"] and not args.new_target:
        fail("Missing target requires --new-target")
    target_path = Path(target["path"])
    if paths_overlap(root, target_path):
        fail("Run directory must not overlap target skill")
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
    root, state, inventory = load_run(args.run_dir)
    if args.history:
        print(json.dumps(read_history(root), indent=2, sort_keys=True))
        return
    print_status(root, state, inventory)


def command_advance(args):
    root, state, inventory = load_run(args.run_dir)
    phase = state["phase"]
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
            save_state(root, state, "validation-passed")
        elif attempt >= state["max_validation_attempts"]:
            rollback_target(root, state, inventory, "validation attempt bound reached")
        else:
            state["phase"] = "merge"
            save_state(root, state, "validation-failed")
    else:
        fail(f"Cannot advance phase: {phase}")
    print_status(root, state, inventory)


def command_extend_scope(args):
    """Widen the mutable path set without discarding correct merge work.

    A repair discovered mid-merge - most often a defect in this coordinator -
    otherwise costs a full rebind and remerge, which makes the safe route the
    expensive one. Extensions are additive, reasoned, and still confined to the
    pre-mutation snapshot, so reversibility is unchanged.
    """
    root, state, inventory = load_run(args.run_dir)
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
    root, state, inventory = load_run(args.run_dir)
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
            execute("advance", "--run-dir", run)
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
            execute("advance", "--run-dir", run)
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
        execute("advance", "--run-dir", run)
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
        execute("advance", "--run-dir", run)
        write_apply(run, plan_hash, ["SKILL.md"], notes=["Repaired"])
        execute("advance", "--run-dir", run)
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
        missing_feedback = execute("advance", "--run-dir", run, check=False)
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
        unproven_result = execute("advance", "--run-dir", run, check=False)
        assert unproven_result.returncode != 0 and "changed_files" in unproven_result.stderr
        assert read_json(run / "state.json")["phase"] == "validation"
        unproven["observations"][0]["changed_files"] = ["scripts/absorb.py"]
        write_evidence(run / "feedback.json", unproven)
        execute("advance", "--run-dir", run)
        state = read_json(run / "state.json")
        assert state["phase"] == "complete"
        assert state["validation_attempts"] == 2
        for source in sources:
            recorded = read_json(run / "inventory.json")["sources"]
            expected = next(item["sha256"] for item in recorded if item["path"] == str(source.resolve()))
            assert inspect_skill(source)["sha256"] == expected

        target, _sources, run, baseline, plan_hash = prepare_run("scope")
        (target / "SKILL.md").write_text("changed\n")
        (target / "EXTRA.md").write_text("outside plan\n")
        write_apply(run, plan_hash, ["EXTRA.md", "SKILL.md"])
        result = execute("advance", "--run-dir", run, check=False)
        assert result.returncode != 0 and "target rolled back" in result.stderr
        assert read_json(run / "state.json")["phase"] == "rolled-back"
        assert (target / "SKILL.md").read_text() == baseline
        assert not (target / "EXTRA.md").exists()
        # Rollback restores the baseline but must not destroy the merge attempt.
        preserved = [path for path in (run / "revisions").iterdir() if path.name.endswith("-rollback-target")]
        assert len(preserved) == 1, preserved
        assert (preserved[0] / "SKILL.md").read_text() == "changed\n"
        assert (preserved[0] / "EXTRA.md").read_text() == "outside plan\n"

        # Malformed evidence is a reporting mistake, not unsafe execution: the
        # merge survives, the phase holds, and a corrected file advances the run.
        target, _sources, run, _baseline, plan_hash = prepare_run("malformed")
        merged = "---\nname: target\ndescription: Combined target skill.\n---\n\n# Target\n\nMerged.\n"
        (target / "SKILL.md").write_text(merged)
        write_apply(run, plan_hash, ["SKILL.md"], notes="not a list")
        result = execute("advance", "--run-dir", run, check=False)
        assert result.returncode != 0 and "does not satisfy apply.schema.json" in result.stderr
        assert "notes" in result.stderr
        assert "rolled back" not in result.stderr
        assert read_json(run / "state.json")["phase"] == "merge"
        assert (target / "SKILL.md").read_text() == merged
        write_apply(run, plan_hash, ["SKILL.md"])
        execute("advance", "--run-dir", run)
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
        result = execute("advance", "--run-dir", run, check=False)
        assert result.returncode != 0 and "rolled back" not in result.stderr
        assert read_json(run / "state.json")["phase"] == "validation"
        assert (target / "SKILL.md").read_text() == merged

        # A mid-run repair outside the bound plan is recordable, not fatal: the
        # merge survives, the extension is reasoned, and rollback still reverses it.
        target, _sources, run, baseline, plan_hash = prepare_run("extend")
        (target / "SKILL.md").write_text("merged\n")
        (target / "helper.py").write_text("fix\n")
        write_apply(run, plan_hash, ["SKILL.md", "helper.py"])
        blocked = execute("advance", "--run-dir", run, check=False)
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
        execute("advance", "--run-dir", run)
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
        execute("advance", "--run-dir", run)
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
        result = execute("advance", "--run-dir", run, check=False)
        assert result.returncode != 0 and "target rolled back" in result.stderr
        assert (target / "SKILL.md").read_text() == baseline
        assert not (target / "EXTRA.md").exists()
        assert (vcs / "HEAD").read_text() == "ref: refs/heads/main\n"
        assert not (run / "rollback" / "target" / ".git").exists()

        target, _sources, run, baseline, plan_hash = prepare_run("bounded", max_attempts=1)
        (target / "SKILL.md").write_text("changed\n")
        write_apply(run, plan_hash, ["SKILL.md"])
        execute("advance", "--run-dir", run)
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
        execute("advance", "--run-dir", run)
        assert read_json(run / "state.json")["phase"] == "rolled-back"
        assert (target / "SKILL.md").read_text() == baseline

        target, _sources, run, baseline, plan_hash = prepare_run("revision")
        (target / "SKILL.md").write_text("partially merged target\n")
        write_apply(run, plan_hash, ["SKILL.md"])
        execute("advance", "--run-dir", run)
        execute("revise-plan", "--run-dir", run)
        state = read_json(run / "state.json")
        assert state["phase"] == "plan"
        assert state["execution_plan_sha256"] is None
        assert (target / "SKILL.md").read_text() == baseline
        assert not (run / "rollback").exists()
        assert any(path.name.endswith("-plan.json") for path in (run / "revisions").iterdir())
    print("self-check passed")


def parser():
    root = argparse.ArgumentParser(description="Coordinate semantic absorption of many skills into one target.")
    commands = root.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init")
    initialize.add_argument("--target", type=Path, required=True)
    initialize.add_argument("--source", type=Path, action="append", required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)
    initialize.add_argument("--new-target", action="store_true")
    initialize.add_argument("--max-validation-attempts", type=int, default=3)
    initialize.set_defaults(handler=command_init)

    for name, handler in (
        ("status", command_status),
        ("advance", command_advance),
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
    main()
