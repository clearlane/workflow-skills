#!/usr/bin/env python3
"""Coordinator for reviewing a workflow skill.

Review phases follow the surfaces the reviewed skill actually exposes, so a
skill with no settings never walks a settings review. The surface vocabulary is
imported from the design coordinator rather than restated, so a capability can
never be designable but unreviewable. Findings, dispositions, and phase notes
persist in a run directory, and the verdict is gated on every blocking finding
carrying an explicit disposition.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from design import CAPABILITY_PHASES
from state import (
    excluded,
    fail,
    now,
    paths_overlap,
    read_json,
    require_text,
    save_state,
    slug,
    write_json,
)

VERSION = 1

# Review concerns every skill has, regardless of which surfaces it exposes.
ALWAYS_FIRST = ("activation", "structure")
ALWAYS_LAST = ("safety", "verdict")
PHASE_RESOURCES = {
    "activation": "references/structure.md",
    "structure": "references/naming.md",
    "safety": "references/patterns.md#6-safety-gate",
    "verdict": "references/review.md",
}

# Surfaces mirror the design coordinator's capabilities: whatever can be
# designed must be reviewable against the same contract.
SURFACES = tuple(name for name, _, _ in CAPABILITY_PHASES)
SURFACE_RESOURCES = {name: resource for name, _, resource in CAPABILITY_PHASES}

# Detection signals. A surface is claimed only with recorded file evidence, so
# the phase list argues from the reviewed skill rather than from a checklist.
SURFACE_KEYWORDS = {
    "coordinator": ("coordinator", "pipeline(", "phase("),
    "state": ("state.json", "resume", "checkpoint"),
    "settings": ("settings", "preference"),
    "setup": ("pre-flight", "preflight", "prerequisite"),
    "install": ("install",),
    "events": ("lifecycle", "event handler", "hook"),
    "tools": ("mcp", "external service", "external tool"),
    "workers": ("worker", "delegate", "subagent"),
    "commands": ("command entrypoint", "slash command", "invocation"),
    "packaging": ("bundle", "manifest", "marketplace"),
}
TEXT_SUFFIXES = {".md", ".py", ".js", ".mjs", ".ts", ".sh", ".json", ".yaml", ".yml", ".toml"}
MAX_EVIDENCE = 5
MAX_BYTES = 2_000_000

SEVERITIES = ("blocking", "major", "minor")
DISPOSITIONS = ("fixed", "accepted", "deferred")


def derive_phases(surfaces):
    """Return only the review phases this skill's own surfaces require."""
    selected = list(ALWAYS_FIRST)
    selected.extend(name for name in SURFACES if name in surfaces)
    selected.extend(ALWAYS_LAST)
    return selected


def phase_resource(phase):
    return SURFACE_RESOURCES.get(phase) or PHASE_RESOURCES[phase]


def detect_surfaces(skill_root):
    """Collect bounded file evidence for each surface the skill may expose."""
    evidence = {name: [] for name in SURFACES}
    for path in sorted(skill_root.rglob("*")):
        relative = path.relative_to(skill_root)
        if not path.is_file() or excluded(relative.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > MAX_BYTES:
            continue
        stem = path.stem.lower()
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for name in SURFACES:
            hits = evidence[name]
            if len(hits) >= MAX_EVIDENCE:
                continue
            if stem == name:
                hits.append({"path": relative.as_posix(), "line": 0, "signal": "filename"})
                continue
            for number, line in enumerate(lines, 1):
                lowered = line.lower()
                match = next((word for word in SURFACE_KEYWORDS[name] if word in lowered), None)
                if match:
                    hits.append({"path": relative.as_posix(), "line": number, "signal": match})
                    break
    return evidence


def load_run(run_dir):
    root = run_dir.expanduser().resolve()
    state = read_json(root / "state.json")
    if state.get("version") != VERSION:
        fail(f"Unsupported run version: {state.get('version')}")
    return root, state


def current_phase(state):
    for phase in state["phases"]:
        if phase not in state["completed"]:
            return phase
    return None


def load_findings(root):
    path = root / "findings.json"
    if not path.exists():
        return []
    value = read_json(path)
    return value.get("findings", [])


def save_findings(root, findings):
    write_json(root / "findings.json", {"findings": findings})


def unresolved_blocking(findings):
    return [item["id"] for item in findings if item["severity"] == "blocking" and not item["disposition"]]


def print_status(root, state):
    phase = current_phase(state)
    findings = load_findings(root)
    blocking = unresolved_blocking(findings)
    if phase == "verdict" and blocking:
        action = (
            "Resolve blocking findings before the verdict: "
            + ", ".join(blocking)
            + " (use resolve-finding)."
        )
    elif phase:
        action = (
            f"Review '{phase}' against {phase_resource(phase)}, record findings, then run "
            f"complete-phase --phase {phase} with a decision note."
        )
    else:
        action = f"Review complete. Report written to {root / 'report.md'}."
    output = {
        "run_dir": str(root),
        "skill": state["skill"],
        "surfaces": state["surfaces"],
        "phases": state["phases"],
        "completed": state["completed"],
        "phase": phase,
        "remaining": [item for item in state["phases"] if item not in state["completed"]],
        "resource": phase_resource(phase) if phase else None,
        "findings": {
            "total": len(findings),
            "blocking_unresolved": blocking,
        },
        "next_action": action,
    }
    print(json.dumps(output, indent=2, sort_keys=True))


def command_init(args):
    root = args.run_dir.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        fail(f"Run directory must be absent or empty: {root}")
    skill_root = args.skill.expanduser().resolve()
    if not (skill_root / "SKILL.md").is_file():
        fail(f"Skill must be a directory containing SKILL.md: {skill_root}")
    if paths_overlap(root, skill_root):
        fail("Run directory must not overlap the skill under review")
    for name in (args.surface or []) + (args.skip_surface or []):
        if name not in SURFACES:
            fail(f"Unknown surface {name!r}; choose from {', '.join(SURFACES)}")
    evidence = detect_surfaces(skill_root)
    detected = [name for name in SURFACES if evidence[name]]
    surfaces = [name for name in detected if name not in (args.skip_surface or [])]
    for name in args.surface or []:
        if name not in surfaces:
            surfaces.append(name)
    surfaces = [name for name in SURFACES if name in surfaces]
    phases = derive_phases(surfaces)
    root.mkdir(parents=True, exist_ok=True)
    write_json(
        root / "inventory.json",
        {
            "skill": str(skill_root),
            "detected": detected,
            "evidence": evidence,
            "forced": args.surface or [],
            "skipped": args.skip_surface or [],
            "recorded_at": now(),
        },
    )
    state = {
        "version": VERSION,
        "skill": {"name": slug(args.name or skill_root.name), "path": str(skill_root)},
        "surfaces": surfaces,
        "phases": phases,
        "completed": [],
        "created_at": now(),
        "updated_at": now(),
        "history": [],
    }
    state["phase"] = phases[0]
    save_state(root, state, "initialized")
    print_status(root, state)


def command_status(args):
    root, state = load_run(args.run_dir)
    print_status(root, state)


def command_record_finding(args):
    """Findings attach to a reached phase so evidence precedes judgement."""
    root, state = load_run(args.run_dir)
    phase = current_phase(state)
    reached = state["completed"] + ([phase] if phase else [])
    if args.phase not in reached:
        fail(f"Phase {args.phase!r} is not reached yet; reached phases: {', '.join(reached)}")
    if args.severity not in SEVERITIES:
        fail(f"Severity must be one of {', '.join(SEVERITIES)}")
    require_text(args.summary, "--summary")
    require_text(args.evidence, "--evidence")
    findings = load_findings(root)
    finding = {
        "id": f"F{len(findings) + 1}",
        "phase": args.phase,
        "severity": args.severity,
        "summary": args.summary,
        "evidence": args.evidence,
        "disposition": None,
        "disposition_note": None,
        "recorded_at": now(),
    }
    findings.append(finding)
    save_findings(root, findings)
    save_state(root, state, f"finding-recorded:{finding['id']}")
    print(json.dumps(finding, indent=2, sort_keys=True))


def command_resolve_finding(args):
    root, state = load_run(args.run_dir)
    if args.disposition not in DISPOSITIONS:
        fail(f"Disposition must be one of {', '.join(DISPOSITIONS)}")
    require_text(args.note, "--note")
    findings = load_findings(root)
    for finding in findings:
        if finding["id"] == args.id:
            finding["disposition"] = args.disposition
            finding["disposition_note"] = args.note
            finding["resolved_at"] = now()
            save_findings(root, findings)
            save_state(root, state, f"finding-resolved:{args.id}")
            print(json.dumps(finding, indent=2, sort_keys=True))
            return
    fail(f"Unknown finding id: {args.id}")


def command_complete_phase(args):
    root, state = load_run(args.run_dir)
    expected = current_phase(state)
    if expected is None:
        fail("All phases already complete")
    if args.phase != expected:
        fail(f"Next phase is {expected!r}, not {args.phase!r}")
    require_text(args.note, "--note")
    findings = load_findings(root)
    blocking = unresolved_blocking(findings)
    if expected == "verdict" and blocking:
        fail(f"Cannot close the verdict with unresolved blocking findings: {', '.join(blocking)}")
    write_json(
        root / "decisions" / f"{expected}.json",
        {
            "phase": expected,
            "resource": phase_resource(expected),
            "note": args.note,
            "recorded_at": now(),
        },
    )
    state["completed"].append(expected)
    state["phase"] = current_phase(state) or "complete"
    save_state(root, state, f"phase-complete:{expected}")
    if state["phase"] == "complete":
        write_report(root, state, findings)
    print_status(root, state)


def command_add_surface(args):
    """Late discovery is normal; extend the phase list without losing findings."""
    root, state = load_run(args.run_dir)
    if args.surface not in SURFACES:
        fail(f"Unknown surface {args.surface!r}")
    if args.surface in state["surfaces"]:
        fail(f"Surface already present: {args.surface}")
    surfaces = [name for name in SURFACES if name in state["surfaces"] + [args.surface]]
    phases = derive_phases(surfaces)
    missing = [phase for phase in state["completed"] if phase not in phases]
    if missing:
        fail(f"Refusing to drop completed phases: {missing}")
    if args.surface in state["completed"]:
        fail(f"Refusing to reopen a completed phase: {args.surface}")
    state["surfaces"] = surfaces
    state["phases"] = phases
    state["phase"] = current_phase(state) or "complete"
    save_state(root, state, f"surface-added:{args.surface}")
    print_status(root, state)


def write_report(root, state, findings):
    counts = {level: sum(1 for item in findings if item["severity"] == level) for level in SEVERITIES}
    lines = [
        f"# Skill Review: {state['skill']['name']}",
        "",
        f"- Skill: {state['skill']['path']}",
        f"- Surfaces reviewed: {', '.join(state['surfaces']) or 'none'}",
        f"- Phases: {', '.join(state['phases'])}",
        f"- Findings: {counts['blocking']} blocking, {counts['major']} major, {counts['minor']} minor",
        "",
        "## Findings",
        "",
    ]
    if findings:
        lines.append("| ID | Phase | Severity | Summary | Evidence | Disposition |")
        lines.append("|---|---|---|---|---|---|")
        for item in findings:
            lines.append(
                "| {id} | {phase} | {severity} | {summary} | {evidence} | {disposition} |".format(
                    disposition=item["disposition"] or "open", **{
                        key: str(item[key]).replace("|", "\\|")
                        for key in ("id", "phase", "severity", "summary", "evidence")
                    }
                )
            )
    else:
        lines.append("No findings recorded.")
    lines.extend(["", "## Phase Decisions", ""])
    for phase in state["phases"]:
        decision = read_json(root / "decisions" / f"{phase}.json")
        lines.append(f"- **{phase}** ({decision['resource']}): {decision['note']}")
    (root / "report.md").write_text("\n".join(lines) + "\n")


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

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        # A plain skill with no workflow surfaces walks only mandatory phases.
        plain = root / "plain"
        plain.mkdir()
        (plain / "SKILL.md").write_text("# Plain\n\nDo one thing directly.\n")
        run = root / "plain-run"
        result = execute("init", "--skill", plain, "--run-dir", run)
        state = json.loads(result.stdout)
        assert state["phases"] == list(ALWAYS_FIRST + ALWAYS_LAST), state["phases"]
        assert state["surfaces"] == [], state["surfaces"]

        # Evidence in the skill, not a checklist, selects the extra phases.
        rich = root / "rich"
        (rich / "scripts").mkdir(parents=True)
        (rich / "SKILL.md").write_text("# Rich\n\nRun the coordinator and resume from state.json.\n")
        (rich / "scripts" / "settings.py").write_text("# settings adapter\n")
        rich_run = root / "rich-run"
        result = execute("init", "--skill", rich, "--run-dir", rich_run)
        state = json.loads(result.stdout)
        assert "coordinator" in state["surfaces"] and "state" in state["surfaces"], state["surfaces"]
        assert "settings" in state["surfaces"], state["surfaces"]
        assert state["phases"][0] == "activation" and state["phases"][-1] == "verdict"
        inventory = json.loads((rich_run / "inventory.json").read_text())
        assert inventory["evidence"]["state"], "state surface must carry file evidence"

        # An explicit skip removes a detected surface and its phase.
        skipped_run = root / "skipped-run"
        result = execute("init", "--skill", rich, "--run-dir", skipped_run, "--skip-surface", "settings")
        assert "settings" not in json.loads(result.stdout)["surfaces"]

        # Phases close in order, and only with a decision note.
        assert execute(
            "complete-phase", "--run-dir", run, "--phase", "structure", "--note", "x", check=False
        ).returncode
        assert execute(
            "complete-phase", "--run-dir", run, "--phase", "activation", "--note", "", check=False
        ).returncode
        execute("complete-phase", "--run-dir", run, "--phase", "activation", "--note", "triggers are specific")

        # Findings cannot attach to a phase the run has not reached.
        assert execute(
            "record-finding", "--run-dir", run, "--phase", "verdict",
            "--severity", "minor", "--summary", "s", "--evidence", "e", check=False
        ).returncode
        execute(
            "record-finding", "--run-dir", run, "--phase", "structure",
            "--severity", "blocking", "--summary", "Destructive step lacks an approval gate",
            "--evidence", "SKILL.md:1",
        )
        execute("complete-phase", "--run-dir", run, "--phase", "structure", "--note", "one canonical home")
        execute("complete-phase", "--run-dir", run, "--phase", "safety", "--note", "gate missing")

        # The verdict is gated on every blocking finding having a disposition.
        assert execute(
            "complete-phase", "--run-dir", run, "--phase", "verdict", "--note", "ship", check=False
        ).returncode
        execute("resolve-finding", "--run-dir", run, "--id", "F1", "--disposition", "fixed", "--note", "gate added")
        execute("complete-phase", "--run-dir", run, "--phase", "verdict", "--note", "approved after fix")
        report = (run / "report.md").read_text()
        assert "F1" in report and "fixed" in report, report
        assert "1 blocking" in report, report

        # Late surface discovery extends the plan without dropping progress.
        late = root / "late-run"
        execute("init", "--skill", plain, "--run-dir", late)
        execute("complete-phase", "--run-dir", late, "--phase", "activation", "--note", "ok")
        result = execute("add-surface", "--run-dir", late, "--surface", "workers")
        state = json.loads(result.stdout)
        assert "workers" in state["phases"] and "activation" in state["completed"]
        assert execute("add-surface", "--run-dir", late, "--surface", "workers", check=False).returncode

        # A run directory inside the reviewed skill would review its own output.
        assert execute("init", "--skill", plain, "--run-dir", plain / "run", check=False).returncode

    print("self-check passed")


def main():
    parser = argparse.ArgumentParser(description="Coordinate a phased workflow-skill review.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="start a review run")
    init.add_argument("--skill", type=Path, required=True)
    init.add_argument("--run-dir", type=Path, required=True)
    init.add_argument("--name")
    init.add_argument("--surface", action="append", help="review this surface even without detected evidence")
    init.add_argument("--skip-surface", action="append", help="drop a detected surface from the plan")
    init.set_defaults(handler=command_init)

    status = subparsers.add_parser("status", help="show phase, resource, and next action")
    status.add_argument("--run-dir", type=Path, required=True)
    status.set_defaults(handler=command_status)

    record = subparsers.add_parser("record-finding", help="record one finding against a reached phase")
    record.add_argument("--run-dir", type=Path, required=True)
    record.add_argument("--phase", required=True)
    record.add_argument("--severity", required=True, choices=SEVERITIES)
    record.add_argument("--summary", required=True)
    record.add_argument("--evidence", required=True, help="path or path:line proving the finding")
    record.set_defaults(handler=command_record_finding)

    resolve = subparsers.add_parser("resolve-finding", help="give one finding an explicit disposition")
    resolve.add_argument("--run-dir", type=Path, required=True)
    resolve.add_argument("--id", required=True)
    resolve.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    resolve.add_argument("--note", required=True)
    resolve.set_defaults(handler=command_resolve_finding)

    complete = subparsers.add_parser("complete-phase", help="close the current phase with a decision note")
    complete.add_argument("--run-dir", type=Path, required=True)
    complete.add_argument("--phase", required=True)
    complete.add_argument("--note", required=True)
    complete.set_defaults(handler=command_complete_phase)

    add = subparsers.add_parser("add-surface", help="add a surface discovered mid-run")
    add.add_argument("--run-dir", type=Path, required=True)
    add.add_argument("--surface", required=True)
    add.set_defaults(handler=command_add_surface)

    check = subparsers.add_parser("self-check", help="verify coordinator behavior and exit")
    check.set_defaults(handler=command_self_check)

    arguments = parser.parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    main()
