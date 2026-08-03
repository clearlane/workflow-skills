#!/usr/bin/env python3
"""Coordinator for designing or refactoring a workflow skill.

Phases are derived from the recorded contract, not from a fixed prose list, so
a skill without settings never walks a settings phase. Progress persists in a
run directory and resumes from artifacts rather than conversational memory.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state import (
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

# Capability -> phase that designs it, and the resource holding its contract.
CAPABILITY_PHASES = (
    ("coordinator", "coordinator", "references/patterns.md"),
    ("state", "state", "references/patterns.md#state-and-resume"),
    ("settings", "settings", "references/settings.md"),
    ("setup", "setup", "workflows/setup.md"),
    ("install", "install", "references/install.md"),
    ("events", "events", "references/events.md"),
    ("tools", "tools", "references/tools.md"),
    ("workers", "workers", "references/workers.md"),
    ("commands", "commands", "references/commands.md"),
    ("packaging", "packaging", "references/packaging.md"),
)
ALWAYS_FIRST = ("contract",)
ALWAYS_LAST = ("resources", "checks", "review")
PHASE_RESOURCES = {
    "contract": "references/structure.md",
    "resources": "references/naming.md",
    "checks": "references/checks.md",
    "review": "references/closure.md",
}
CAPABILITIES = tuple(name for name, _, _ in CAPABILITY_PHASES)


def derive_phases(capabilities):
    """Return only the phases this skill's contract actually requires."""
    selected = list(ALWAYS_FIRST)
    selected.extend(phase for name, phase, _ in CAPABILITY_PHASES if name in capabilities)
    selected.extend(ALWAYS_LAST)
    return selected


def phase_resource(phase):
    for _, name, resource in CAPABILITY_PHASES:
        if name == phase:
            return resource
    return PHASE_RESOURCES[phase]


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


def print_status(root, state):
    phase = current_phase(state)
    remaining = [item for item in state["phases"] if item not in state["completed"]]
    output = {
        "run_dir": str(root),
        "skill": state["skill"],
        "capabilities": state["capabilities"],
        "phases": state["phases"],
        "completed": state["completed"],
        "phase": phase,
        "remaining": remaining,
        "resource": phase_resource(phase) if phase else None,
        "next_action": (
            f"Design '{phase}' using {phase_resource(phase)}, then run complete-phase "
            f"--phase {phase} with a decision note."
            if phase
            else "All phases complete. Record the result and run the repository checks."
        ),
    }
    print(json.dumps(output, indent=2, sort_keys=True))


def command_init(args):
    root = args.run_dir.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        fail(f"Run directory must be absent or empty: {root}")
    skill_root = args.skill.expanduser().resolve()
    if paths_overlap(root, skill_root):
        fail("Run directory must not overlap the skill being designed")
    require_text(args.name, "--name")
    capabilities = []
    for capability in args.capability or []:
        if capability not in CAPABILITIES:
            fail(f"Unknown capability {capability!r}; choose from {', '.join(CAPABILITIES)}")
        if capability not in capabilities:
            capabilities.append(capability)
    phases = derive_phases(capabilities)
    root.mkdir(parents=True, exist_ok=True)
    (root / "decisions").mkdir()
    state = {
        "version": VERSION,
        "skill": {"name": slug(args.name), "path": str(skill_root)},
        "capabilities": capabilities,
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


def command_complete_phase(args):
    root, state = load_run(args.run_dir)
    expected = current_phase(state)
    if expected is None:
        fail("All phases already complete")
    if args.phase != expected:
        fail(f"Next phase is {expected!r}, not {args.phase!r}")
    require_text(args.note, "--note")
    decision = {
        "phase": expected,
        "resource": phase_resource(expected),
        "note": args.note,
        "recorded_at": now(),
    }
    write_json(root / "decisions" / f"{expected}.json", decision)
    state["completed"].append(expected)
    state["phase"] = current_phase(state) or "complete"
    save_state(root, state, f"phase-complete:{expected}")
    print_status(root, state)


def command_add_capability(args):
    """Late discovery is normal; extend the phase list without losing progress."""
    root, state = load_run(args.run_dir)
    if args.capability not in CAPABILITIES:
        fail(f"Unknown capability {args.capability!r}")
    if args.capability in state["capabilities"]:
        fail(f"Capability already present: {args.capability}")
    state["capabilities"].append(args.capability)
    ordered = [name for name in CAPABILITIES if name in state["capabilities"]]
    state["capabilities"] = ordered
    state["phases"] = derive_phases(ordered)
    missing = [phase for phase in state["completed"] if phase not in state["phases"]]
    if missing:
        fail(f"Refusing to drop completed phases: {missing}")
    state["phase"] = current_phase(state) or "complete"
    save_state(root, state, f"capability-added:{args.capability}")
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

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        # A minimal skill derives only the mandatory phases.
        run = root / "minimal"
        execute("init", "--name", "Minimal Skill", "--skill", root / "minimal-skill", "--run-dir", run)
        state = read_json(run / "state.json")
        assert state["phases"] == ["contract", "resources", "checks", "review"], state["phases"]

        # Capabilities insert exactly their own phases, in canonical order.
        run = root / "full"
        execute(
            "init", "--name", "Full Skill", "--skill", root / "full-skill", "--run-dir", run,
            "--capability", "commands", "--capability", "settings", "--capability", "coordinator",
        )
        state = read_json(run / "state.json")
        assert state["phases"] == [
            "contract", "coordinator", "settings", "commands", "resources", "checks", "review",
        ], state["phases"]

        # Out-of-order completion is rejected; in-order completion persists evidence.
        result = execute("complete-phase", "--run-dir", run, "--phase", "commands", "--note", "x", check=False)
        assert result.returncode != 0 and "Next phase is 'contract'" in result.stderr
        result = execute("complete-phase", "--run-dir", run, "--phase", "contract", "--note", "", check=False)
        assert result.returncode != 0
        execute("complete-phase", "--run-dir", run, "--phase", "contract", "--note", "Bounded merge workflow")
        decision = read_json(run / "decisions" / "contract.json")
        assert decision["resource"] == "references/structure.md"
        assert decision["note"] == "Bounded merge workflow"

        # Status resumes from artifacts alone.
        status = json.loads(execute("status", "--run-dir", run).stdout)
        assert status["phase"] == "coordinator"
        assert status["resource"] == "references/patterns.md"
        assert status["completed"] == ["contract"]

        # Late discovery extends the plan without losing completed work.
        execute("add-capability", "--run-dir", run, "--capability", "events")
        state = read_json(run / "state.json")
        assert "events" in state["phases"]
        assert state["completed"] == ["contract"]
        assert state["phases"].index("events") > state["phases"].index("coordinator")
        result = execute("add-capability", "--run-dir", run, "--capability", "events", check=False)
        assert result.returncode != 0
        result = execute("add-capability", "--run-dir", run, "--capability", "nope", check=False)
        assert result.returncode != 0

        # Unknown capability and overlapping run directory are rejected at init.
        result = execute(
            "init", "--name", "Bad", "--skill", root / "s2", "--run-dir", root / "r2",
            "--capability", "invalid", check=False,
        )
        assert result.returncode != 0
        skill = root / "overlap"
        result = execute(
            "init", "--name", "Bad", "--skill", skill, "--run-dir", skill / "run", check=False,
        )
        assert result.returncode != 0 and "must not overlap" in result.stderr

        # Every phase reaches completion and reports a terminal next action.
        run = root / "finish"
        execute("init", "--name", "Finish", "--skill", root / "finish-skill", "--run-dir", run)
        for phase in read_json(run / "state.json")["phases"]:
            execute("complete-phase", "--run-dir", run, "--phase", phase, "--note", f"did {phase}")
        status = json.loads(execute("status", "--run-dir", run).stdout)
        assert status["phase"] is None and status["remaining"] == []
        result = execute("complete-phase", "--run-dir", run, "--phase", "review", "--note", "x", check=False)
        assert result.returncode != 0 and "already complete" in result.stderr
    print("self-check passed")


def parser():
    root = argparse.ArgumentParser(description="Coordinate design of a workflow skill.")
    commands = root.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init")
    initialize.add_argument("--name", required=True)
    initialize.add_argument("--skill", type=Path, required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)
    initialize.add_argument("--capability", action="append", choices=CAPABILITIES)
    initialize.set_defaults(handler=command_init)

    status = commands.add_parser("status")
    status.add_argument("--run-dir", type=Path, required=True)
    status.set_defaults(handler=command_status)

    complete = commands.add_parser("complete-phase")
    complete.add_argument("--run-dir", type=Path, required=True)
    complete.add_argument("--phase", required=True)
    complete.add_argument("--note", required=True)
    complete.set_defaults(handler=command_complete_phase)

    add = commands.add_parser("add-capability")
    add.add_argument("--run-dir", type=Path, required=True)
    add.add_argument("--capability", required=True)
    add.set_defaults(handler=command_add_capability)

    check = commands.add_parser("self-check")
    check.set_defaults(handler=command_self_check)
    return root


def main():
    args = parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    main()
