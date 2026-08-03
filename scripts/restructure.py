#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Restructure coordinator: audit a layout and execute approved file moves.

Implements workflows/restructure.md. Moves, renames, and deletions are
irreversible from the agent's side, so the approval gate is the reason this
coordinator exists: approval is recorded against the manifest's digest, and a
manifest edited after approval no longer matches it. Prose asking for "approval
for this exact operation set" cannot detect the edit.

The audit-only path is the same run stopped after propose, so an audit and a
mutation share one code path up to the point where they diverge.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import (
    EX_DATAERR,
    EX_UNAVAILABLE,
    fail,
)
from state import (
    VERSION,
    create_run,
    json_sha256,
    now,
    open_run,
    read_history,
    read_json,
    require_text,
    run_cli,
    safe_relative_path,
    save_state,
    schema_errors,
    slug,
    write_artifact,
)
from state import (
    print_status as print_envelope,
)

# Ordered phases, each with the resource holding its contract. Unlike design,
# the list is fixed: a restructure always gathers evidence before diagnosing and
# always validates after executing, whatever the scope turns out to contain.
PHASES = (
    ("evidence", "references/layout.md#ecosystem-evidence"),
    ("diagnose", "references/layout.md#classify-every-observation"),
    ("propose", "references/layout.md#test-a-proposed-structure"),
    ("approve", "references/checks.md#approval-placement"),
    ("execute", "references/migration.md#order-of-operations"),
    ("validate", "references/migration.md#checks"),
)
PHASE_NAMES = tuple(name for name, _ in PHASES)
# Operations that change the tree. A manifest of only these is a no-op proposal,
# and executing one would burn an approval on nothing.
MUTATING = frozenset({"move", "rename", "create", "delete"})
NEEDS_DESTINATION = frozenset({"move", "rename"})


def phase_resource(phase):
    for name, resource in PHASES:
        if name == phase:
            return resource
    return None


def pending(state):
    for phase in state["phases"]:
        if phase not in state["completed"]:
            return phase
    return None


def next_action(phase):
    if phase is None:
        return "All phases complete. Run the repository checks and hand off."
    if phase == "propose":
        return "Write manifest.json, then run propose --run-dir <run> to bind it."
    if phase == "approve":
        return (
            "Present the bound manifest to the user verbatim, then run approve "
            "--run-dir <run> --approved-by <who> once they approve this exact operation set."
        )
    if phase == "execute":
        return "Apply the manifest one boundary at a time, then run execute --run-dir <run>."
    return f"Work '{phase}' using {phase_resource(phase)}, then run complete-phase --phase {phase}."


def print_status(root, state):
    phase = pending(state)
    print_envelope(
        "restructure",
        root,
        phase,
        state["phases"],
        state["completed"],
        phase_resource(phase),
        next_action(phase),
        {
            "scope": state["scope"],
            "mode": state["mode"],
            "manifest_sha256": state.get("manifest_sha256"),
            "approval": state.get("approval"),
        },
    )


def require_phase(state, expected):
    """Refuse a verb out of order, naming what the run is actually waiting for.

    Executing before approval is the failure this whole coordinator exists to
    prevent, so the ordering check is not a convenience.
    """
    current = pending(state)
    if current != expected:
        found = current or "nothing; the run is complete"
        fail(f"Run is at {found!r}, not {expected!r}", EX_DATAERR)


def require_inside_scope(scope, relative, label):
    """Refuse a path that leaves the scope once symlinks are resolved.

    safe_relative_path is lexical, so it rejects `..` and absolute forms but
    cannot see that `link/a.py` resolves into another tree entirely. A manifest
    naming such a path passed every check and would have deleted a file outside
    the tree the user approved operations for.

    Resolution stops at the first symlinked component rather than following it,
    which is the same refusal inventory.py already makes when walking.
    """
    target = scope / relative
    current = scope
    for part in Path(relative).parts:
        current = current / part
        if current.is_symlink():
            fail(f"{label}: {relative} passes through symlink {part!r}; resolve it before proposing", EX_DATAERR)
    try:
        resolved = target.resolve()
    except OSError as error:
        fail(f"{label}: {relative} cannot be resolved: {error}", EX_DATAERR)
    if resolved != scope.resolve() and scope.resolve() not in resolved.parents:
        fail(f"{label}: {relative} resolves outside the scope", EX_DATAERR)


def load_manifest(root, state, expect_unapplied=True):
    """Read the manifest and prove it describes the tree this run is scoped to.

    `expect_unapplied` distinguishes reading a proposal from reading it back
    after the agent applied it. A moved file is absent from its old path by
    then, so requiring the source to exist would reject exactly the manifests
    that were carried out correctly.
    """
    path = root / "manifest.json"
    if not path.is_file():
        fail(f"Missing {path}; the propose phase writes it", EX_UNAVAILABLE)
    value = read_json(path)
    errors = schema_errors("manifest.schema.json", value)
    if errors:
        fail(f"{path} violates its schema:\n  " + "\n  ".join(errors), EX_DATAERR)
    if value["scope"] != state["scope"]:
        fail(
            f"{path}: scope {value['scope']!r} is not this run's scope {state['scope']!r}",
            EX_DATAERR,
        )
    scope = Path(state["scope"])
    for index, operation in enumerate(value["operations"]):
        label = f"{path}: operations[{index}]"
        action = operation["action"]
        relative = safe_relative_path(operation["path"], f"{label}.path")
        has_destination = "destination" in operation
        if action in NEEDS_DESTINATION and not has_destination:
            fail(f"{label}: {action} requires a destination", EX_DATAERR)
        if action not in NEEDS_DESTINATION and has_destination:
            fail(f"{label}: {action} must not carry a destination", EX_DATAERR)
        if has_destination:
            safe_relative_path(operation["destination"], f"{label}.destination")
        # A create names a path that does not exist yet; everything else names
        # one that must, or the manifest was written against a stale tree.
        if expect_unapplied and action != "create" and not (scope / relative).exists():
            fail(f"{label}: {relative} does not exist in the scope", EX_DATAERR)
        for candidate in (relative, operation.get("destination")):
            if candidate:
                require_inside_scope(scope, candidate, label)
    return path, value


def command_init(args):
    scope = args.scope.expanduser().resolve()
    if not scope.is_dir():
        fail(f"Scope must be an existing directory: {scope}", EX_UNAVAILABLE)
    root = create_run(args.run_dir, (scope, "the scope being restructured"))
    require_text(args.name, "--name")
    root.mkdir(parents=True, exist_ok=True)
    (root / "decisions").mkdir()
    state = {
        "version": VERSION,
        "name": slug(args.name),
        "scope": str(scope),
        "mode": args.mode,
        "phases": list(PHASE_NAMES),
        "completed": [],
        "created_at": now(),
        "updated_at": now(),
    }
    state["phase"] = PHASE_NAMES[0]
    save_state(root, state, "initialized")
    print_status(root, state)


def command_status(args):
    root, state = open_run(args.run_dir)
    if args.history:
        print(json.dumps(read_history(root), indent=2, sort_keys=True))
        return
    print_status(root, state)


def command_complete_phase(args):
    """Advance a phase that needs only a recorded reason.

    propose, approve, and execute have their own verbs because each binds
    evidence; the rest are judgements whose record is the note.
    """
    root, state = open_run(args.run_dir)
    expected = pending(state)
    if expected is None:
        fail("All phases already complete", EX_DATAERR)
    if args.phase != expected:
        fail(f"Next phase is {expected!r}, not {args.phase!r}", EX_DATAERR)
    if expected in {"propose", "approve", "execute"}:
        fail(f"Phase {expected!r} advances with its own verb, not complete-phase", EX_DATAERR)
    require_text(args.note, "--note")
    record_decision(root, expected, args.note)
    advance(root, state, expected)
    print_status(root, state)


def record_decision(root, phase, note):
    write_artifact(
        root / "decisions" / f"{phase}.json",
        "decision.schema.json",
        {
            "phase": phase,
            "resource": phase_resource(phase),
            "note": note,
            "recorded_at": now(),
        },
    )


def advance(root, state, phase, event=None):
    state["completed"].append(phase)
    state["phase"] = pending(state) or "complete"
    save_state(root, state, event or f"phase-complete:{phase}")


def command_propose(args):
    """Bind the manifest, so approval has something exact to be given for."""
    root, state = open_run(args.run_dir)
    require_phase(state, "propose")
    path, manifest = load_manifest(root, state)
    mutating = [item for item in manifest["operations"] if item["action"] in MUTATING]
    if not mutating and state["mode"] == "mutate":
        fail(
            f"{path}: no mutating operation, so there is nothing to approve; use --mode audit for an audit-only run",
            EX_DATAERR,
        )
    state["manifest_sha256"] = json_sha256(path)
    state["operation_count"] = len(manifest["operations"])
    state["mutating_count"] = len(mutating)
    record_decision(root, "propose", f"Bound {len(mutating)} mutating operations of {len(manifest['operations'])}.")
    advance(root, state, "propose", f"proposed:{state['manifest_sha256'][:12]}")
    if state["mode"] == "audit":
        # An audit ends here by design: no approval token is issued, so no
        # later verb can execute against this run.
        state["completed"] = list(PHASE_NAMES)
        state["phase"] = "complete"
        save_state(root, state, "audit-complete")
    print_status(root, state)


def command_approve(args):
    """Record approval against the manifest digest, not against a promise.

    'A changed proposal needs fresh approval' is only enforceable if approval
    names what was approved. Re-digesting here is what turns a post-approval
    edit into a failure at execute rather than a silent extra operation.
    """
    root, state = open_run(args.run_dir)
    require_phase(state, "approve")
    if state["mode"] != "mutate":
        fail("An audit-only run has nothing to approve", EX_DATAERR)
    require_text(args.approved_by, "--approved-by")
    path, _ = load_manifest(root, state)
    current = json_sha256(path)
    if current != state.get("manifest_sha256"):
        fail(
            "manifest.json changed after propose; re-run propose to bind the new manifest, then obtain fresh approval",
            EX_DATAERR,
        )
    state["approval"] = {
        "manifest_sha256": current,
        "approved_by": args.approved_by,
        "approved_at": now(),
    }
    record_decision(root, "approve", f"Approved by {args.approved_by} for manifest {current[:12]}.")
    advance(root, state, "approve", f"approved:{current[:12]}")
    print_status(root, state)


def command_execute(args):
    """Refuse execution unless the tree still matches what was approved."""
    root, state = open_run(args.run_dir)
    require_phase(state, "execute")
    approval = state.get("approval")
    if not approval:
        fail("No approval recorded; run approve first", EX_DATAERR)
    path, manifest = load_manifest(root, state, expect_unapplied=False)
    current = json_sha256(path)
    if current != approval["manifest_sha256"]:
        fail(
            f"manifest.json no longer matches the approved operation set "
            f"(approved {approval['manifest_sha256'][:12]}, found {current[:12]}); "
            "obtain fresh approval for the changed proposal",
            EX_DATAERR,
        )
    require_text(args.note, "--note")
    scope = Path(state["scope"])
    applied = []
    for operation in manifest["operations"]:
        if operation["action"] not in MUTATING:
            continue
        destination = operation.get("destination")
        target = scope / operation["path"]
        if operation["action"] in NEEDS_DESTINATION and not (scope / destination).exists():
            fail(
                f"{operation['path']} was not moved to {destination}; "
                "execute records what the agent applied, and this operation is missing",
                EX_DATAERR,
            )
        if operation["action"] == "delete" and target.exists():
            fail(f"{operation['path']} still exists but the manifest deletes it", EX_DATAERR)
        if operation["action"] == "create" and not target.exists():
            fail(f"{operation['path']} was not created", EX_DATAERR)
        applied.append(operation["path"])
    state["applied"] = applied
    record_decision(root, "execute", args.note)
    advance(root, state, "execute", f"executed:{len(applied)}")
    print_status(root, state)


def command_self_check(_args):
    import subprocess
    import tempfile

    executable = Path(__file__).resolve()

    def execute(*arguments, check=True):
        return subprocess.run(
            [sys.executable, str(executable), *map(str, arguments)],
            check=check,
            capture_output=True,
            text=True,
        )

    def manifest(scope, operations, **extra):
        return {
            "schema": "manifest.schema.json",
            "version": VERSION,
            "created_at": now(),
            "scope": str(scope),
            "operations": operations,
            **extra,
        }

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        def fresh_scope(name):
            """Each case gets its own tree, since an executed case mutates one."""
            scope = root / name
            (scope / "src").mkdir(parents=True)
            (scope / "src" / "a.py").write_text("a\n")
            (scope / "b.py").write_text("b\n")
            return scope

        scope = fresh_scope("gate-scope")

        # A run refuses to execute before it has been approved.
        run = root / "gate"
        execute("init", "--name", "Gate", "--scope", scope, "--run-dir", run, "--mode", "mutate")
        operations = [{"action": "move", "path": "b.py", "destination": "src/b.py", "reason": "belongs with src"}]
        # Kept verbatim: restoring an equivalent manifest is not restoring the
        # approved one, because created_at alone changes the digest.
        approved = json.dumps(manifest(scope, operations))
        (run / "manifest.json").write_text(approved)
        result = execute("execute", "--run-dir", run, "--note", "x", check=False)
        assert result.returncode != 0 and "not 'execute'" in result.stderr, result.stderr

        execute("complete-phase", "--run-dir", run, "--phase", "evidence", "--note", "inventoried")
        execute("complete-phase", "--run-dir", run, "--phase", "diagnose", "--note", "classified")
        execute("propose", "--run-dir", run)

        # The gate itself: an edited manifest invalidates the approval that was
        # given for the previous one.
        execute("approve", "--run-dir", run, "--approved-by", "operator")
        edited = manifest(scope, [*operations, {"action": "delete", "path": "src/a.py", "reason": "snuck in"}])
        (run / "manifest.json").write_text(json.dumps(edited))
        result = execute("execute", "--run-dir", run, "--note", "x", check=False)
        assert result.returncode == EX_DATAERR, result.returncode
        assert "no longer matches the approved operation set" in result.stderr, result.stderr

        # Restoring the approved manifest lets the approved set execute, once
        # the agent has actually applied it to the tree.
        (run / "manifest.json").write_text(approved)
        (scope / "src" / "b.py").write_text((scope / "b.py").read_text())
        (scope / "b.py").unlink()
        applied = execute("execute", "--run-dir", run, "--note", "moved b", check=False)
        assert applied.returncode == 0, applied.stderr
        status = json.loads(applied.stdout)
        assert status["phase"] == "validate", status
        assert status["detail"]["approval"]["approved_by"] == "operator", status

        # A manifest edited between propose and approve is refused at approve.
        scope = fresh_scope("reorder-scope")
        run = root / "reorder"
        execute("init", "--name", "Reorder", "--scope", scope, "--run-dir", run, "--mode", "mutate")
        (run / "manifest.json").write_text(json.dumps(manifest(scope, operations)))
        execute("complete-phase", "--run-dir", run, "--phase", "evidence", "--note", "e")
        execute("complete-phase", "--run-dir", run, "--phase", "diagnose", "--note", "d")
        execute("propose", "--run-dir", run)
        (run / "manifest.json").write_text(
            json.dumps(manifest(scope, [*operations, {"action": "keep", "path": "src/a.py", "reason": "unchanged"}]))
        )
        result = execute("approve", "--run-dir", run, "--approved-by", "operator", check=False)
        assert result.returncode != 0 and "changed after propose" in result.stderr, result.stderr

        # An audit-only run completes at propose and issues no approval.
        scope = fresh_scope("audit-scope")
        run = root / "audit"
        execute("init", "--name", "Audit", "--scope", scope, "--run-dir", run, "--mode", "audit")
        (run / "manifest.json").write_text(
            json.dumps(manifest(scope, [{"action": "keep", "path": "b.py", "reason": "fine"}]))
        )
        execute("complete-phase", "--run-dir", run, "--phase", "evidence", "--note", "e")
        execute("complete-phase", "--run-dir", run, "--phase", "diagnose", "--note", "d")
        status = json.loads(execute("propose", "--run-dir", run).stdout)
        assert status["phase"] is None, status
        assert status["detail"]["approval"] is None, status
        result = execute("approve", "--run-dir", run, "--approved-by", "x", check=False)
        assert result.returncode != 0, result.stderr

        # A manifest naming a path outside its scope is rejected, not applied.
        scope = fresh_scope("escape-scope")
        run = root / "escape"
        execute("init", "--name", "Escape", "--scope", scope, "--run-dir", run, "--mode", "mutate")
        (run / "manifest.json").write_text(
            json.dumps(manifest(scope, [{"action": "delete", "path": "../outside.py", "reason": "no"}]))
        )
        execute("complete-phase", "--run-dir", run, "--phase", "evidence", "--note", "e")
        execute("complete-phase", "--run-dir", run, "--phase", "diagnose", "--note", "d")
        result = execute("propose", "--run-dir", run, check=False)
        assert result.returncode != 0, result.stderr

        # A symlink is a path that looks relative and is not. Lexical checks
        # pass it, so without this the manifest could delete outside the tree
        # the user approved operations for.
        scope = fresh_scope("symlink-scope")
        outside = root / "outside-tree"
        outside.mkdir()
        (outside / "secret.py").write_text("must survive\n")
        (scope / "link").symlink_to(outside)
        for label, operation in (
            ("through a symlinked directory", {"action": "delete", "path": "link/secret.py", "reason": "escape"}),
            (
                "as a move destination",
                {"action": "move", "path": "b.py", "destination": "link/b.py", "reason": "escape"},
            ),
        ):
            run = root / f"symlink-{label.split()[-1]}"
            execute("init", "--name", "Sym", "--scope", scope, "--run-dir", run, "--mode", "mutate")
            (run / "manifest.json").write_text(json.dumps(manifest(scope, [operation])))
            execute("complete-phase", "--run-dir", run, "--phase", "evidence", "--note", "e")
            execute("complete-phase", "--run-dir", run, "--phase", "diagnose", "--note", "d")
            result = execute("propose", "--run-dir", run, check=False)
            assert result.returncode != 0, f"symlink escape {label} was accepted"
            assert "symlink" in result.stderr, result.stderr
        assert (outside / "secret.py").read_text() == "must survive\n"

        # A run directory inside its own scope would restructure its own record.
        result = execute(
            "init", "--name", "Nested", "--scope", scope, "--run-dir", scope / "run", "--mode", "audit", check=False
        )
        assert result.returncode != 0 and "must not overlap" in result.stderr, result.stderr
    print("self-check passed")


def parser():
    root = argparse.ArgumentParser(description="Coordinate a layout restructure.")
    root.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="failure output shape: prose (default), or RFC 9457 problem details",
    )
    commands = root.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init")
    initialize.add_argument("--name", required=True)
    initialize.add_argument("--scope", type=Path, required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)
    initialize.add_argument(
        "--mode",
        choices=("audit", "mutate"),
        default="audit",
        help="audit stops after propose and issues no approval; mutate may execute",
    )
    initialize.set_defaults(handler=command_init)

    status = commands.add_parser("status")
    status.add_argument("--run-dir", type=Path, required=True)
    status.add_argument(
        "--history",
        action="store_true",
        help="show the run's transition log instead of its current status",
    )
    status.set_defaults(handler=command_status)

    complete = commands.add_parser("complete-phase")
    complete.add_argument("--run-dir", type=Path, required=True)
    complete.add_argument("--phase", required=True)
    complete.add_argument("--note", required=True)
    complete.set_defaults(handler=command_complete_phase)

    propose = commands.add_parser("propose")
    propose.add_argument("--run-dir", type=Path, required=True)
    propose.set_defaults(handler=command_propose)

    approve = commands.add_parser("approve")
    approve.add_argument("--run-dir", type=Path, required=True)
    approve.add_argument("--approved-by", required=True)
    approve.set_defaults(handler=command_approve)

    apply_operations = commands.add_parser("execute")
    apply_operations.add_argument("--run-dir", type=Path, required=True)
    apply_operations.add_argument("--note", required=True)
    apply_operations.set_defaults(handler=command_execute)

    check = commands.add_parser("self-check")
    check.set_defaults(handler=command_self_check)
    return root


def main():
    args = parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    run_cli(main)
