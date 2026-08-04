#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Remediation coordinator: drive a reviewed skill to the quality bar.

Implements workflows/remediate.md. A review ends read-only on its subject, so
the fixes it justifies need a run of their own. The loop this coordinator holds
is fix, then re-review, then repeat, and the property that makes it worth
executing rather than describing is that the check on an iteration is the next
review's verdict rather than the fixer's opinion of its own work.

The bound is the other reason it is code. A loop whose termination is a model's
judgement needs a counter something else owns, checked before the next
iteration spends anything, and an exhausted budget has to be reportable as the
failure it is.
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import (
    EX_DATAERR,
    EX_TEMPFAIL,
    fail,
)
from state import (
    VERSION,
    canonical_sha256,
    create_run,
    now,
    open_run,
    read_history,
    read_json,
    require_text,
    run_cli,
    save_state,
    schema_errors,
    slug,
    write_artifact,
)
from state import (
    print_status as print_envelope,
)
from validate import validate as validate_skill

# The loop's phases. Unlike design, the shape never varies: a remediation run
# always reads a verdict, always iterates, and always ends in a terminal status
# naming which of the three ways it stopped.
PHASE_RESOURCES = {
    "verdict": "references/review.md#disposition",
    "iterate": "references/remediation.md#triage",
    "complete": "references/remediation.md#ending-a-run",
    "exhausted": "references/patterns.md#5-bounded-feedback-loop",
    "cancelled": "references/commands.md#stopping-a-run",
}
WORKING_PHASES = ("verdict", "iterate")
# Where a remediation run can end. `complete` is shared with every other
# coordinator; the other two are this loop's own outcomes, and they exist
# separately because a caller cannot tell an exhausted budget from a met bar by
# looking at the subject.
TERMINAL_PHASES = ("complete", "exhausted", "cancelled")
PHASES = tuple(PHASE_RESOURCES)
# Severities carrying a fix obligation, so a run cannot complete while one is
# open. references/remediation.md owns why; this is the machine-readable half.
OBLIGED = ("blocking", "major")
DEFAULT_MAX_ITERATIONS = 5


def derive_phases(_capabilities=None):
    """Remediation's phases are fixed, so this takes no input.

    It exists so the repository's phase-owner check can treat every coordinator
    the same way rather than special-casing this one.
    """
    return list(PHASES)


def phase_resource(phase):
    return PHASE_RESOURCES.get(phase)


def walked_phases(phase):
    """The phase list for a run currently on `phase`.

    Progression is linear, so reaching a phase is what proves the earlier ones
    finished; there is no separate completed list to disagree with it.
    """
    terminal = phase if phase in TERMINAL_PHASES else TERMINAL_PHASES[0]
    return [*WORKING_PHASES, terminal]


def next_action(state):
    phase = state["phase"]
    if phase == "verdict":
        return (
            "Read findings.json from the review run, then run accept-verdict "
            "--run-dir <run> to start the loop against it."
        )
    if phase == "iterate":
        remaining = state["max_iterations"] - state["iterations"]
        return (
            f"Fix the obliged findings, write iterations/{state['iterations'] + 1:02d}.json, "
            f"re-review, then run record-iteration --run-dir <run>. {remaining} of "
            f"{state['max_iterations']} iterations remain."
        )
    if phase == "exhausted":
        return "Iteration bound reached with obligations open. The fixes remain; start a new run or widen the bound."
    if phase == "cancelled":
        return "Run cancelled. The fixes already applied remain in place."
    return "Quality bar met. Re-run the repository checks and hand off."


def print_status(root, state):
    phase = state["phase"]
    phases = walked_phases(phase)
    print_envelope(
        "remediate",
        root,
        phase,
        phases,
        phases[: phases.index(phase)],
        phase_resource(phase),
        next_action(state),
        {
            "skill": state["skill"],
            "review_run": state["review_run"],
            "iterations": state["iterations"],
            "max_iterations": state["max_iterations"],
            "accepted_obligations": state["accepted_obligations"],
            "outstanding": state["outstanding"],
        },
    )


def require_phase(state, expected):
    """Refuse a verb out of order, naming what the run is actually waiting for."""
    if state["phase"] != expected:
        fail(f"Run is on phase {state['phase']!r}, not {expected!r}", EX_DATAERR)


def load_findings(review_run):
    """Read the review's findings, proving they satisfy the review's own schema.

    The coupling to another coordinator's artifact is deliberate: a remediation
    run that re-derived findings would be a second reviewer with no shared
    contract. Validating at the boundary is what keeps it a consumer rather
    than a fork.
    """
    path = review_run / "findings.json"
    if not path.is_file():
        fail(f"Review run has no findings.json: {path}", EX_DATAERR, path)
    value = read_json(path)
    errors = schema_errors("findings.schema.json", value)
    if errors:
        detail = "\n  ".join(errors)
        fail(f"{path}: does not satisfy findings.schema.json:\n  {detail}", EX_DATAERR, path)
    return value


def require_review_of(skill_root, review_run):
    """Refuse a review that was not about the skill this run is fixing.

    The findings are obligations inherited from another run, so which skill
    that run examined decides whether they mean anything here. Nothing tied the
    two together: a review of one skill could be handed to a remediation of
    another, and the run would inherit obligations recorded against a tree it
    will never touch, then report them resolved when a re-review of a different
    skill came back clean.

    The path is what is compared, not the digest. The skill is expected to
    change, since fixing it is the point; what must hold is that both runs are
    talking about the same skill.

    findings.json is the contract this coordinator consumes, and a review's
    state.json is not part of it, so a findings set produced by other means is
    still accepted. The check applies to what a review run does record, rather
    than making a second artifact mandatory.
    """
    state_path = review_run / "state.json"
    if not state_path.is_file():
        return
    reviewed = (read_json(state_path).get("skill") or {}).get("path")
    if reviewed and Path(reviewed).resolve() != skill_root:
        fail(
            f"{review_run}: reviewed {reviewed}, not {skill_root}; its findings are obligations about another skill",
            EX_DATAERR,
            review_run,
        )


def obligations(findings):
    """Finding IDs a run may not complete while they remain open.

    A finding the review already disposed of is not an obligation: the review
    recorded who accepted it and why, and reopening that here would make one
    decision answer to two owners.
    """
    return [item["id"] for item in findings if item["severity"] in OBLIGED and not item["disposition"]]


def command_init(args):
    skill_root = args.skill.expanduser().resolve()
    if not (skill_root / "SKILL.md").is_file():
        fail(f"Skill must be a directory containing SKILL.md: {skill_root}", EX_DATAERR)
    review_run = args.review_run.expanduser().resolve()
    if args.max_iterations < 1:
        fail("--max-iterations must be at least 1", EX_DATAERR)
    findings = load_findings(review_run)["findings"]
    require_review_of(skill_root, review_run)
    root = create_run(
        args.run_dir,
        (skill_root, "the skill being remediated"),
        (review_run, "the review run being consumed"),
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / "decisions").mkdir()
    (root / "iterations").mkdir()
    state = {
        "version": VERSION,
        "skill": {"name": slug(args.name or skill_root.name), "path": str(skill_root)},
        "review_run": str(review_run),
        "phase": "verdict",
        "iterations": 0,
        "max_iterations": args.max_iterations,
        "accepted_obligations": obligations(findings),
        # What the latest re-review still reports. Seeded from the accepted
        # verdict so a run that has not iterated yet reports the work it owes
        # rather than zero, which would read as a met bar.
        "outstanding": len(obligations(findings)),
        "created_at": now(),
        "updated_at": now(),
    }
    save_state(root, state, "initialized")
    print_status(root, state)


def command_status(args):
    root, state = open_run(args.run_dir)
    if args.history:
        print(json.dumps(read_history(root), indent=2, sort_keys=True))
        return
    print_status(root, state)


def command_accept_verdict(args):
    """Start the loop, or refuse to start one with nothing to do.

    A run over a clean review would iterate zero times and report completion,
    which is indistinguishable from a run that fixed everything. Refusing says
    what actually happened.
    """
    root, state = open_run(args.run_dir)
    require_phase(state, "verdict")
    require_text(args.note, "--note")
    findings = load_findings(Path(state["review_run"]))["findings"]
    state["accepted_obligations"] = obligations(findings)
    state["outstanding"] = len(state["accepted_obligations"])
    if not state["accepted_obligations"]:
        fail("Review left no blocking or major finding open; there is nothing to remediate", EX_DATAERR)
    state["phase"] = "iterate"
    save_state(root, state, "verdict-accepted")
    record_decision(root, "verdict", args.note)
    print_status(root, state)


def validate_iteration(root, state, findings):
    """Reject an iteration record that does not account for the whole review.

    Coverage is the property the schema cannot check, because the findings live
    in another run's directory. An iteration that silently skipped a finding
    would let the loop terminate with an obligation nobody ever looked at.
    """
    path = root / "iterations" / f"{state['iterations'] + 1:02d}.json"
    if not path.is_file():
        fail(f"Write the iteration record first: {path}", EX_DATAERR, path)
    value = read_json(path)
    errors = schema_errors("remediation.schema.json", value)
    if errors:
        detail = "\n  ".join(errors)
        fail(f"{path}: does not satisfy remediation.schema.json:\n  {detail}", EX_DATAERR, path)
    if value["iteration"] != state["iterations"] + 1:
        fail(
            f"{path}: records iteration {value['iteration']}, but the run is on {state['iterations'] + 1}",
            EX_DATAERR,
            path,
        )
    digest = canonical_sha256({"findings": findings})
    if value["findings_sha256"] != digest:
        fail(
            f"{path}: triaged a findings set that is not the review's current one",
            EX_DATAERR,
            path,
        )
    severities = {item["id"]: item["severity"] for item in findings}
    decided = [item["finding_id"] for item in value["triaged"]]
    duplicates = sorted({key for key in decided if decided.count(key) > 1})
    if duplicates:
        fail(f"{path}: decides {duplicates} more than once", EX_DATAERR, path)
    unknown = sorted(set(decided) - set(severities))
    missing = sorted(set(state["accepted_obligations"]) - set(decided))
    if unknown or missing:
        fail(
            f"{path}: triage does not match the review; missing={missing}, unknown={unknown}",
            EX_DATAERR,
            path,
        )
    for item in value["triaged"]:
        recorded = severities[item["finding_id"]]
        if item["severity"] != recorded:
            fail(
                f"{path}: {item['finding_id']} is {recorded!r} in the review, not {item['severity']!r}",
                EX_DATAERR,
                path,
            )
    return value


def command_record_iteration(args):
    """Record one iteration and let its re-review decide whether the loop ends.

    The bound is checked here rather than at the top of the next iteration, so
    a run that has spent its budget cannot be handed more work to do.
    """
    root, state = open_run(args.run_dir)
    require_phase(state, "iterate")
    require_text(args.note, "--note")
    findings = load_findings(Path(state["review_run"]))["findings"]
    value = validate_iteration(root, state, findings)
    state["iterations"] += 1
    recheck = value["recheck"]
    outstanding = sum(recheck[name] for name in OBLIGED)
    # The live count comes from the re-review, never from the accepted verdict,
    # which is static and would report the original obligations forever.
    state["outstanding"] = outstanding
    if outstanding == 0:
        # Reaching zero is the run's claim that the subject is fixed, and the
        # obligations it inherited include the format errors a host rejects.
        # Those the coordinator can re-check itself, so a recheck that reports
        # them closed while they are still in the file is refused rather than
        # believed. This is not a failed iteration: the fixes so far are kept
        # and the loop continues, so the run neither completes on a false claim
        # nor loses its work over one.
        errors = [f for f in validate_skill(Path(state["skill"]["path"])) if f.severity == "error"]
        if errors:
            detail = "\n".join(f"  {f.message}\n    fix: {f.remedy}" for f in errors)
            fail(
                f"Iteration reports no obliged findings open, but the skill still does not conform:\n{detail}",
                EX_DATAERR,
            )
        state["phase"] = "complete"
        save_state(root, state, "bar-met")
        record_decision(root, "iterate", args.note)
        print_status(root, state)
        return
    if state["iterations"] >= state["max_iterations"]:
        state["phase"] = "exhausted"
        save_state(root, state, "bound-exhausted")
        record_decision(root, "iterate", args.note)
        print_status(root, state)
        # Exhausting the bound is a failure result. Exiting zero would let a
        # wrapper report a subject with open obligations as remediated, which
        # is the one outcome the bound exists to make visible.
        fail(
            f"Iteration bound reached after {state['iterations']} iterations with "
            f"{outstanding} obliged findings open; fixes retained",
            EX_TEMPFAIL,
        )
    save_state(root, state, f"iteration-recorded:{state['iterations']}")
    record_decision(root, "iterate", args.note)
    print_status(root, state)


def command_cancel(args):
    """End the run without undoing what it already fixed.

    Cancelling a remediation run is not rolling one back. Partial improvement
    is a legitimate outcome here, unlike the partial merge absorb discards, so
    this records where the run stopped and leaves the subject alone.
    """
    root, state = open_run(args.run_dir)
    if state["phase"] in TERMINAL_PHASES:
        fail(f"Run already ended as {state['phase']!r}", EX_DATAERR)
    require_text(args.reason, "--reason")
    state["phase"] = "cancelled"
    save_state(root, state, "cancelled")
    record_decision(root, "cancelled", args.reason)
    print_status(root, state)


def record_decision(root, phase, note):
    write_artifact(
        root / "decisions" / f"{phase}.json",
        "decision.schema.json",
        {"phase": phase, "resource": phase_resource(phase), "note": note, "recorded_at": now()},
    )


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

    def write_json(path, value):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")

    def finding(identifier, severity, disposition=None):
        item = {
            "id": identifier,
            "phase": "structure",
            "severity": severity,
            "summary": f"{severity} defect",
            "evidence": "SKILL.md:1",
            "disposition": disposition,
            "disposition_note": "accepted deliberately" if disposition else None,
            "recorded_at": "2026-01-01T00:00:00Z",
        }
        if disposition:
            item["resolved_at"] = "2026-01-01T00:00:00Z"
        return item

    def review_run(root, name, findings):
        path = root / name
        write_json(
            path / "findings.json",
            {
                "schema": "https://clearlane.github.io/workflow-skills/schemas/findings.schema.json",
                "version": VERSION,
                "findings": findings,
            },
        )
        return path

    def skill(root, name):
        path = root / name
        path.mkdir(parents=True, exist_ok=True)
        (path / "SKILL.md").write_text("---\nname: subject\ndescription: subject\n---\n", encoding="utf-8")
        return path

    def iteration(findings, number, triaged, recheck):
        return {
            "schema": "https://clearlane.github.io/workflow-skills/schemas/remediation.schema.json",
            "version": VERSION,
            "iteration": number,
            "findings_sha256": canonical_sha256({"findings": findings}),
            "triaged": triaged,
            "changed_files": ["SKILL.md"],
            "recheck": {"ran": "review.py status", **recheck},
            "notes": [],
        }

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        subject = skill(root, "subject")
        findings = [finding("F1", "blocking"), finding("F2", "minor")]
        review = review_run(root, "review", findings)

        # A run starts on the verdict and reports only the open obligations:
        # a disposed finding belongs to the review that disposed of it.
        run = root / "run"
        execute("init", "--skill", subject, "--review-run", review, "--run-dir", run, "--max-iterations", 2)
        state = read_json(run / "state.json")
        assert state["phase"] == "verdict", state["phase"]
        assert state["accepted_obligations"] == ["F1"], state["accepted_obligations"]

        # Findings are obligations inherited from another run, so they mean
        # something here only if that run examined this skill. A review naming a
        # different skill would otherwise be accepted, and its obligations
        # reported resolved once a re-review of an unrelated tree came back
        # clean. A review that records no subject is still accepted, because
        # findings.json is the contract and its state.json is not part of it.
        other = skill(root, "other-subject")
        stated = root / "stated-review"
        write_json(
            stated / "findings.json",
            {
                "schema": "https://clearlane.github.io/workflow-skills/schemas/findings.schema.json",
                "version": VERSION,
                "findings": findings,
            },
        )
        write_json(stated / "state.json", {"skill": {"name": "other", "path": str(other)}})
        mismatched = execute(
            "init",
            "--skill",
            subject,
            "--review-run",
            stated,
            "--run-dir",
            root / "mismatched",
            "--max-iterations",
            2,
            check=False,
        )
        assert mismatched.returncode == EX_DATAERR, mismatched.returncode
        assert "obligations about another skill" in mismatched.stderr, mismatched.stderr
        matched = execute(
            "init",
            "--skill",
            other,
            "--review-run",
            stated,
            "--run-dir",
            root / "matched",
            "--max-iterations",
            2,
            check=False,
        )
        assert matched.returncode == 0, matched.stderr

        # Recording an iteration before the verdict is accepted is refused.
        result = execute("record-iteration", "--run-dir", run, "--note", "early", check=False)
        assert result.returncode != 0 and "not 'iterate'" in result.stderr, result.stderr

        execute("accept-verdict", "--run-dir", run, "--note", "one blocking finding to fix")

        # Triage that omits an open obligation is rejected, so a loop cannot
        # terminate over a finding nobody looked at.
        write_json(
            run / "iterations" / "01.json",
            iteration(
                findings,
                1,
                [{"finding_id": "F2", "severity": "minor", "action": "dismissed", "reason": "false positive"}],
                {"blocking": 1, "major": 0, "minor": 0},
            ),
        )
        result = execute("record-iteration", "--run-dir", run, "--note", "partial", check=False)
        assert result.returncode != 0 and "missing=['F1']" in result.stderr, result.stderr

        # Dismissing an obliged finding is rejected by the schema, which is
        # what stops the loop ending with the defect intact.
        write_json(
            run / "iterations" / "01.json",
            iteration(
                findings,
                1,
                [{"finding_id": "F1", "severity": "blocking", "action": "dismissed", "reason": "looks fine"}],
                {"blocking": 0, "major": 0, "minor": 0},
            ),
        )
        result = execute("record-iteration", "--run-dir", run, "--note", "dismissed", check=False)
        assert result.returncode != 0 and "remediation.schema.json" in result.stderr, result.stderr

        # A fix whose re-review still reports an obligation keeps iterating.
        write_json(
            run / "iterations" / "01.json",
            iteration(
                findings,
                1,
                [
                    {
                        "finding_id": "F1",
                        "severity": "blocking",
                        "action": "fixed",
                        "reason": "gate now precedes the write",
                    },
                    {"finding_id": "F2", "severity": "minor", "action": "deferred", "reason": "after the blocking fix"},
                ],
                {"blocking": 0, "major": 1, "minor": 0},
            ),
        )
        execute("record-iteration", "--run-dir", run, "--note", "fixed the gate")
        status = json.loads(execute("status", "--run-dir", run).stdout)
        assert status["phase"] == "iterate", status["phase"]
        assert status["detail"]["iterations"] == 1, status["detail"]

        # Reaching the bound with an obligation open fails, and keeps the work.
        write_json(
            run / "iterations" / "02.json",
            iteration(
                findings,
                2,
                [
                    {"finding_id": "F1", "severity": "blocking", "action": "fixed", "reason": "still fixed"},
                    {"finding_id": "F2", "severity": "minor", "action": "dismissed", "reason": "reviewer preference"},
                ],
                {"blocking": 0, "major": 1, "minor": 0},
            ),
        )
        result = execute("record-iteration", "--run-dir", run, "--note", "second pass", check=False)
        assert result.returncode != 0 and "bound reached" in result.stderr, result.stderr
        state = read_json(run / "state.json")
        assert state["phase"] == "exhausted", state["phase"]
        assert (run / "iterations" / "02.json").is_file(), "artifacts must survive an exhausted run"

        # A clean re-review completes the run.
        clean = root / "clean"
        execute("init", "--skill", subject, "--review-run", review, "--run-dir", clean, "--max-iterations", 2)
        execute("accept-verdict", "--run-dir", clean, "--note", "same verdict")
        write_json(
            clean / "iterations" / "01.json",
            iteration(
                findings,
                1,
                [
                    {"finding_id": "F1", "severity": "blocking", "action": "fixed", "reason": "gate added"},
                    {"finding_id": "F2", "severity": "minor", "action": "fixed", "reason": "dead file removed"},
                ],
                {"blocking": 0, "major": 0, "minor": 0},
            ),
        )
        # Reaching zero outstanding is a claim about the subject, and the
        # format part of it is one the coordinator can settle. A recheck that
        # reports everything closed while the skill still would not load is
        # refused, and the loop keeps its fixes rather than ending on it.
        core = subject / "SKILL.md"
        sound = core.read_text()
        core.write_text(sound.replace("name: subject", "name: bad--subject"))
        result = execute("record-iteration", "--run-dir", clean, "--note", "all clear", check=False)
        assert result.returncode != 0 and "does not conform" in result.stderr, result.stderr
        assert "fix: " in result.stderr, result.stderr
        assert read_json(clean / "state.json")["phase"] == "iterate", "a false claim must not end the loop"
        core.write_text(sound)

        execute("record-iteration", "--run-dir", clean, "--note", "all clear")
        status = json.loads(execute("status", "--run-dir", clean).stdout)
        assert status["phase"] == "complete" and status["detail"]["outstanding"] == 0, status

        # Cancelling ends the run without touching the subject, and cannot be
        # applied twice.
        cancelled = root / "cancelled"
        execute("init", "--skill", subject, "--review-run", review, "--run-dir", cancelled, "--max-iterations", 3)
        execute("accept-verdict", "--run-dir", cancelled, "--note", "starting")
        execute("cancel", "--run-dir", cancelled, "--reason", "user stopped the loop")
        state = read_json(cancelled / "state.json")
        assert state["phase"] == "cancelled", state["phase"]
        assert (subject / "SKILL.md").is_file(), "cancel must not revert the subject"
        result = execute("cancel", "--run-dir", cancelled, "--reason", "again", check=False)
        assert result.returncode != 0 and "already ended" in result.stderr, result.stderr

        # A review with nothing obliged is refused rather than reported as a
        # completed remediation.
        settled = review_run(root, "settled", [finding("F1", "blocking", "accepted")])
        empty = root / "empty"
        execute("init", "--skill", subject, "--review-run", settled, "--run-dir", empty)
        result = execute("accept-verdict", "--run-dir", empty, "--note", "nothing", check=False)
        assert result.returncode != 0 and "nothing to remediate" in result.stderr, result.stderr

        # A bound below one and a missing review are rejected at init.
        result = execute(
            "init",
            "--skill",
            subject,
            "--review-run",
            review,
            "--run-dir",
            root / "bad",
            "--max-iterations",
            0,
            check=False,
        )
        assert result.returncode != 0 and "at least 1" in result.stderr, result.stderr
        result = execute(
            "init", "--skill", subject, "--review-run", root / "absent", "--run-dir", root / "bad", check=False
        )
        assert result.returncode != 0 and "no findings.json" in result.stderr, result.stderr
    print("self-check passed")


def parser():
    root = argparse.ArgumentParser(description="Coordinate remediation of a reviewed skill.")
    root.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="failure output shape: prose (default), or RFC 9457 problem details",
    )
    commands = root.add_subparsers(dest="command", required=True)

    initialize = commands.add_parser("init")
    initialize.add_argument("--skill", type=Path, required=True)
    initialize.add_argument("--review-run", type=Path, required=True)
    initialize.add_argument("--run-dir", type=Path, required=True)
    initialize.add_argument("--name")
    initialize.add_argument(
        "--max-iterations",
        type=int,
        default=DEFAULT_MAX_ITERATIONS,
        help=f"hard bound on fix-and-recheck cycles (default: {DEFAULT_MAX_ITERATIONS})",
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

    accept = commands.add_parser("accept-verdict")
    accept.add_argument("--run-dir", type=Path, required=True)
    accept.add_argument("--note", required=True)
    accept.set_defaults(handler=command_accept_verdict)

    record = commands.add_parser("record-iteration")
    record.add_argument("--run-dir", type=Path, required=True)
    record.add_argument("--note", required=True)
    record.set_defaults(handler=command_record_iteration)

    # complete-phase is the shared verb every coordinator exposes. Here it
    # names the only phase an agent advances by hand; the loop's own phases
    # advance on evidence, so aliasing it keeps the grammar without inventing
    # a second way to skip the checks.
    complete = commands.add_parser("complete-phase")
    complete.add_argument("--run-dir", type=Path, required=True)
    complete.add_argument("--phase", required=True)
    complete.add_argument("--note", required=True)
    complete.set_defaults(handler=command_complete_phase)

    stop = commands.add_parser("cancel")
    stop.add_argument("--run-dir", type=Path, required=True)
    stop.add_argument("--reason", required=True)
    stop.set_defaults(handler=command_cancel)

    check = commands.add_parser("self-check")
    check.set_defaults(handler=command_self_check)
    return root


def command_complete_phase(args):
    """Advance the phase the caller asserts, refusing any it does not own.

    Only `verdict` advances by assertion. `iterate` ends on the evidence in an
    iteration record, so accepting it here would be a way to declare the loop
    finished without the re-review that decides it.
    """
    if args.phase == "verdict":
        command_accept_verdict(args)
        return
    fail(
        f"Phase {args.phase!r} does not advance by assertion; use record-iteration or cancel",
        EX_DATAERR,
    )


def main():
    args = parser().parse_args()
    args.handler(args)


if __name__ == "__main__":
    run_cli(main)
