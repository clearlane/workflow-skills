#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Repository check entrypoint: runs every deterministic project check.

Structural questions about documents go through scripts/document.py, so this
file declares what must hold rather than how markdown or YAML is parsed.
"""

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from functools import partial
from pathlib import Path

# tomllib entered the standard library in 3.11, and the supported floor is
# 3.10. `tomli` is the same parser under its pre-adoption name, so the floor
# needs the dependency and every later runtime does not.
if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover - exercised by the CI job that runs the floor
    try:
        import tomli as tomllib
    except ModuleNotFoundError as error:
        raise SystemExit(
            "check.py needs a TOML parser on Python 3.10: python3 -m pip install -r requirements.txt"
        ) from error

try:
    import yaml
    from packaging.requirements import Requirement
    from packaging.specifiers import SpecifierSet
    from packaging.utils import canonicalize_name
except ModuleNotFoundError as error:
    raise SystemExit(f"check.py needs {error.name}: python3 -m pip install -r requirements.txt") from error

sys.path.insert(0, str(Path(__file__).resolve().parent))

import absorb
import cli
import design
import document
import remediate
import restructure
import review
import state
from design import CAPABILITY_PHASES
from validate import validate as validate_skill

ROOT = Path(__file__).resolve().parent.parent
TICK = chr(96)
# The bounds the Agent Skills format fixes live in scripts/validate.py, which
# is the copy that also runs against skills outside this repository. Restating
# them here is what let the two drift.
VENDOR_TOKENS = ("{baseDir}", "quick_validate", "approved_plan_sha256")
# Host names, which the token list previously omitted: it held only three
# legacy strings, so guidance could name a specific runtime and pass. These are
# checked only where neutrality is the rule. Quoting a host in the README, in
# vendored upstream material, or inside an installed third-party skill is not a
# neutrality violation, and scanning those would make the check unusable.
HOST_TOKENS = ("Claude Code", "~/.claude", "CLAUDE.md", ".cursor", "Cursor", "Copilot")
# A host is recognised by the shape of the path it owns, not only by its name.
# The list above can only ever hold the hosts someone thought to add, and
# AGENTS.md said so in as many words: a document naming `~/.windsurf` or
# `.aider/skills/` passed cleanly because nobody had met that host yet. These
# two patterns describe where an agent runtime keeps its material, so a host
# nobody has listed is caught the first time it is written down.
#
# Shape one: a per-user dotfile directory. Every host puts its configuration in
# one, and the only such paths that are not a host are the cross-host base
# directories the XDG specification defines and the shell's own rc files.
HOME_DOTFILE = re.compile(r"(?:~|\$HOME)/\.([A-Za-z][\w.-]*)")
# The XDG base directories are a freedesktop.org specification every host
# honours, so naming one is the opposite of naming a host: it is the neutral
# answer references/settings.md is required to give. Shell rc files belong to
# the shell rather than to any agent runtime.
CROSS_HOST_HOME = frozenset({"config", "cache", "local", "bashrc", "zshrc", "profile", "bash_profile", "zshenv"})
# Shape two: a project-local dot-directory holding agent material. The
# directory name alone is far too broad, since a skill legitimately names its
# own `.scrum/` or `.context/` state, so what is matched is the second segment:
# the places a host scans for skills, commands, and prompts. That is the claim
# neutrality is about, and it is what makes `.cursor/rules/` a violation while
# `.github/workflows/` stays unremarkable. The directory name itself is left
# unbounded in length, since the second segment is what carries the precision
# and a floor would only decide in advance that no host is named in two letters.
HOST_INSTALL_PATH = re.compile(
    r"(?<![\w.$)>/~\\-])(\.[a-z][a-z0-9_-]*)/(?:skills|rules|commands|agents|plugins|prompts|instructions)\b"
)
# The directories any repository has regardless of which agent reads it. These
# are conventions of git hosting and editors, not of an agent runtime.
CROSS_HOST_DIRECTORIES = frozenset({".github", ".gitlab", ".githooks", ".well-known", ".devcontainer", ".vscode"})
NEUTRAL_ROOTS = ("references", "workflows")
NEUTRAL_FILES = ("SKILL.md", "AGENTS.md", "CONTRIBUTING.md")
# Upstream material is vendored verbatim, so it describes the host it came from.
NEUTRAL_EXEMPT = ("references/upstream",)
PHASE_SECTION = "Phases the Coordinator Always Runs"
DESIGN_WORKFLOW = "workflows/design.md"
REVIEW_WORKFLOW = "workflows/review.md"
ABSORB_WORKFLOW = "workflows/absorb.md"
RESTRUCTURE_WORKFLOW = "workflows/restructure.md"
REMEDIATE_WORKFLOW = "workflows/remediate.md"
README = "README.md"
CHECKER = "check.py"
# The commands every coordinator must expose, so one run is driven the same way
# as another and a wrapper does not need to know which it is holding.
COORDINATORS = ("design.py", "review.py", "absorb.py", "restructure.py", "remediate.py")
# Canonical name for a reference's closing section. references/structure.md
# owns the skeleton; this is the one part of it a parser can confirm.
REFERENCE_CLOSING = "Checks"
# The counterpart for a workflow: where it says what it owns and which sibling
# owns the rest. A reader lands here before deciding to run anything.
WORKFLOW_SCOPE_SECTION = "When to Use"
CORE_VERBS = ("init", "status", "complete-phase", "self-check")
# An imperative may sit behind a condition or a connective and still be an
# order: "If the reviewer disagrees, loop back to phase 2" instructs as
# plainly as "loop back to phase 2" does. A negation stays included, because
# "never retry more than three times" states the same bound from the other
# side. What is excluded is a subject, which is what a description opens with.
PROSE_IMPERATIVE = (
    r"(?:(?:if|when|once|while|unless|after|on|for)\b[^,.;:]{0,120}?,\s*"
    r"|then\s+|otherwise,?\s+|instead,?\s+|next,?\s+|first,?\s+|finally,?\s+"
    r"|and\s+|or\s+|but\s+|do not\s+|don't\s+|never\s+|always\s+)*"
)
PROSE_REPEAT = r"(?:retry|repeat|iterate|loop|poll|re-?run|re-?try|re-?review|re-?check|attempt|try)"
PROSE_NUMBER = r"(?:\d+|one|two|three|four|five|six|seven|eight|nine|ten|twice|thrice)"
PROSE_COUNT = r"(?:times|attempts?|iterations?|passes|rounds?|cycles?)"
PROSE_BOUND = (
    rf"(?:\b(?:up to|at most|no more than|a maximum of|maximum of|no fewer than)\s+{PROSE_NUMBER}\b"
    rf"|\b{PROSE_NUMBER}\s+(?:\w+\s+)?{PROSE_COUNT}\b|\b(?:twice|thrice)\b)"
)
PROSE_JUMP = r"(?:return|go back|loop(?: back)?|jump|skip|fall back|route)\s+(?:back\s+)?to"
PROSE_CONTROL_FLOW = (
    (
        re.compile(rf"^{PROSE_IMPERATIVE}{PROSE_REPEAT}\b[^.;]{{0,80}}?{PROSE_BOUND}", re.I),
        "prose states a repeat bound the coordinator cannot prove held",
    ),
    (
        re.compile(rf"^{PROSE_IMPERATIVE}{PROSE_JUMP}\s+[`*_\"']*(?:phase|step|stage)\b", re.I),
        "prose transfers control to another phase, which no run can resume",
    ),
)
# Run-lifecycle functions state.py owns. A coordinator defining one of these
# has forked the lifecycle rather than composed it.
RUNTIME_OWNED = ("load_run", "open_run", "create_run", "current_phase", "pending_phase")
README_SECTION = "Structure"
# Where SKILL.md owns what a workflow's `scripts/<name>.py` resolves against.
COORDINATOR_PATH_SECTION = "Running a Coordinator"
ARTIFACT_REFERENCE = "references/artifacts.md"
# Third-party schemas, vendored so validation stays offline, pinned so a
# silent edit to one cannot turn a conformance claim into a private variant.
VENDORED_SCHEMAS = {
    "sarif-2.1.0.schema.json": "c3b4bb2d6093897483348925aaa73af03b3e3f4bd4ca38cef26dcb4212a2682e",
}
README_EXEMPT = {".gitignore", "LICENSE", "LICENSE-CODE", README, "skill-logic.workflow.json"}
# The repository is dual-licensed: prose carries the upstream share-alike
# obligation, executables are MIT so they can be vendored without it.
SPDX_TAG = "SPDX-License-Identifier:"
CODE_LICENCE = "MIT"
# Files under scripts/ that ship without the tag. Empty on purpose: nothing
# there is exempt today. The set exists so that dropping a file out of the
# licence boundary is a decision someone wrote down and justified here, the way
# README_EXEMPT names the files the README map does not cover. A format with no
# comment syntax, such as JSON, is the only reason to expect an entry.
LICENCE_EXEMPT = frozenset()
# Comment closers that can follow the licence expression on the same line, so a
# block or markup comment leader does not read as part of the expression.
COMMENT_CLOSERS = ("*/", "-->")
SKILL_LICENCE = "CC-BY-SA-4.0 AND MIT"
ENTRY_DOCUMENTS = (
    "SKILL.md",
    "workflows/design.md",
    "workflows/absorb.md",
    "references/setup.md",
    "workflows/restructure.md",
    "workflows/review.md",
    REMEDIATE_WORKFLOW,
)


def check_skill(root):
    """The core instruction file must stay discoverable and within budget.

    The name and description bounds come from the Agent Skills format, which
    rejects a skill that exceeds them rather than truncating it. This skill
    teaches those bounds in references/structure.md, so failing to hold itself
    to them would be the loudest possible contradiction.
    """
    failures = []
    # The format's own bounds are checked by the validator this repository
    # ships, not by a second copy here. Two implementations of one rule set is
    # the failure mode this repository is built to prevent, and the copy that
    # only ever ran against this tree was the one that drifted: it accepted a
    # consecutive hyphen and never compared name to directory, both of which
    # the format states and a third-party skill exercised.
    #
    # Running it here is also the only check that the tool users are handed
    # works. A validator exercised solely by its own self-check is tested
    # against the cases its author thought of.
    # Only an error fails the suite, matching the validator's own exit
    # contract: a warning is guidance an author may knowingly accept, and this
    # repository knowingly accepts one, since the checkout is named for the
    # project while the skill installs under its own name.
    for finding in validate_skill(root):
        if finding.severity == "error":
            failures.append(f"SKILL.md: {finding.message}")
    parsed = document.parse(root / "SKILL.md")
    # The strict YAML parse stays local: validate.py reads a flat scalar subset
    # on purpose, so it cannot report a frontmatter block that is malformed
    # rather than merely out of bounds.
    if parsed.frontmatter_error:
        failures.append(f"SKILL.md: invalid frontmatter: {parsed.frontmatter_error}")
    return failures


def host_paths(line):
    """Host-owned paths a line names, recognised by shape rather than by name.

    The token list beside this can only hold hosts someone has already met, so
    it is the shape of the path that has to carry the rule. Both patterns are
    narrowed by an allowlist of the paths that are genuinely cross-host: the
    XDG base directories, the shell's own files, and the repository
    conventions any project has whichever agent reads it.
    """
    found = []
    for match in HOME_DOTFILE.finditer(line):
        # `~/.local/state` names the XDG directory, not a `.local` host, so the
        # first segment is what the allowlist is asked about.
        if match.group(1).split("/")[0] not in CROSS_HOST_HOME:
            found.append(match.group(0))
    for match in HOST_INSTALL_PATH.finditer(line):
        if match.group(1) not in CROSS_HOST_DIRECTORIES:
            found.append(match.group(0))
    return found


def check_vendor_tokens(root):
    """Core guidance stays runtime-neutral; host syntax belongs in adapters.

    Naming each host was the whole of this check and it could only ever cover
    the hosts someone had already met. AGENTS.md admitted as much, saying that
    adding a name to the list was part of noticing the host, which makes the
    rule depend on the reviewer spotting exactly what the check exists to spot.
    A document writing `~/.windsurf` or `.aider/skills/` passed, and so would
    every host released after the list was last touched.

    A host is now also recognised by shape: the per-user dotfile directory it
    configures itself in, and the project-local directory a host scans for
    skills, commands, or prompts. Measured over the 1,034 neutral documents in
    the 200 skills on this machine, the two shapes flag `~/.claude`,
    `~/.hermes`, `~/.banana`, `~/.gam`, `~/.agents`, `~/.codex`, `~/.gemini`,
    `.agents/skills`, `.claude/skills`, `.claude/commands`, `.claude/plugins`
    and `.cursor/rules`, every one of them a host or an install path, and
    nothing else. Four of those the literal list would never have caught.

    The shapes complement the names rather than replace them: `Claude Code` and
    `CLAUDE.md` are prose and a filename, which no path shape can see.
    """
    failures = []
    for parsed in document.walk(root):
        relative = parsed.path.relative_to(root)
        posix = relative.as_posix()
        # A document is core guidance if it is a contract in references/ or
        # workflows/, or one of the top-level documents that speak for the
        # repository. Everything else may name a host freely.
        neutral = (relative.parts[0] in NEUTRAL_ROOTS or posix in NEUTRAL_FILES) and not posix.startswith(
            NEUTRAL_EXEMPT
        )
        tokens = VENDOR_TOKENS + (HOST_TOKENS if neutral else ())
        for number, line in enumerate(parsed.text.splitlines(), 1):
            for token in tokens:
                if token in line:
                    failures.append(f"{relative}:{number}: vendor token {token}")
            if not neutral:
                continue
            for path in host_paths(line):
                failures.append(f"{relative}:{number}: host-owned path {path}; name the capability, not the runtime")
    return failures


def check_duplicate_headings(root):
    """One canonical home per topic: reject a repeated heading under one parent.

    Only H2 was inspected, which read the rule as being about top-level
    sections when it is about a topic having one home. Two identical H3
    subsections inside one H2 are the same violation one level down, and they
    passed: a reader who finds the second has no way to know the first exists,
    and an author fixing one leaves the other stating the old rule. This
    repository was in that state, with two `### 2026-08-02` entries under
    UPSTREAM.md's changelog.

    The rule is scoped by parent rather than applied across the document,
    because a repeated subsection heading is only a duplicate when it competes
    with another for the same topic. A `Checks` or `Example` subsection under
    each of several parents is the opposite: it is the positional consistency
    references/structure.md asks for, and rejecting it would punish the shape
    the repository is trying to enforce. Across the 1343 markdown files on this
    machine the distinction is decisive - 178 headings repeat under different
    parents and every one is that pattern, while 5 repeat under one parent.

    Identical headings anywhere in a document also collide on their anchors,
    so a link to the second lands on the first. That is a weaker and different
    fault, and it is deliberately not what this check reports: the corpus says
    a rule strong enough to catch it would reject legitimate structure far more
    often than it would find a real conflict.
    """
    failures = []
    for parsed in document.walk(root):
        seen = set()
        for path, heading in parsed.heading_paths():
            if heading.level < 2:
                continue
            if (path, heading.text) in seen:
                location = " > ".join(path[1:]) or "the document"
                failures.append(
                    f"{parsed.path.relative_to(root)}:{heading.line}: duplicate section "
                    f"{heading.text!r} under {location}"
                )
            seen.add((path, heading.text))
    return failures


def check_shared_runtime(root):
    """The run lifecycle has one owner, so a coordinator cannot re-grow its own.

    These were three byte-identical copies before state.py owned them. The
    failure mode is not the duplication itself: it is that a fix to one copy
    silently leaves the other two wrong, which is invisible until a run resumes
    under the coordinator that was not fixed.
    """
    failures = []
    for name in COORDINATORS:
        source = (root / "scripts" / name).read_text(encoding="utf-8")
        for owned in RUNTIME_OWNED:
            if f"def {owned}(" in source:
                failures.append(f"scripts/{name}: defines {owned}, which state.py owns")
    return failures


def declared_verbs(module):
    """The subcommand names a coordinator's parser actually accepts.

    Built from the parser rather than read from --help, because --help is
    prose: it carries every description and epilog in the file, so a verb named
    in a sentence is indistinguishable there from a verb the parser accepts.
    An AST scan for add_parser("...") would miss the loop each coordinator uses
    to register its shared subcommands, so the parser itself is the source.
    """
    verbs = set()
    for action in module.parser()._actions:
        # argparse exposes no public accessor for registered subcommands, but
        # the action type is public and its `choices` mapping is the same
        # object argparse itself dispatches on, so this asks the parser what it
        # will accept rather than restating it.
        if isinstance(action, argparse._SubParsersAction):
            verbs |= set(action.choices)
    return verbs


def check_coordinator_verbs(root, modules=None):
    """The coordinators must drive a run with the same commands.

    An author who learns one coordinator should be able to drive the others, and
    a generic wrapper should be able to advance any run without knowing which
    coordinator it holds. Two grammars for one state machine make both
    impossible, and the divergence is invisible until someone tries.

    Substring-matching each verb against --help was the first answer and it
    proved nothing. The help text contains the author's own descriptions, so
    renaming `init` to `begin` while mentioning the old name in a sentence left
    the check reporting the verb present when no such subcommand existed. What
    the parser accepts is the fact this check is about, so it is what is asked.

    The coordinator set is a parameter so a stand-in can be passed. Without
    that seam the check reads only from imports, no fixture can reach it, and
    against a conforming tree an empty result is indistinguishable from a
    working one.
    """
    del root  # the coordinators are imported, so this reads the same tree
    failures = []
    for module in modules if modules is not None else (design, review, absorb, restructure, remediate):
        verbs = declared_verbs(module)
        missing = [verb for verb in CORE_VERBS if verb not in verbs]
        if missing:
            failures.append(f"scripts/{module.__name__}.py: registers no subcommand named {', '.join(missing)}")
    return failures


def check_coordinator_registration(root):
    """Every coordinator must be admitted by the closed contracts it writes to.

    A coordinator added on one branch and a schema closed on another merge
    without textual conflict and produce a tree where the new coordinator
    cannot write its own state: the conflict is between a new writer and a new
    constraint, which no textual merge can see. `state.schema.json` is closed
    to declared keys and `status.schema.json`'s `kind` is a closed enum, so
    joining either without the other is a merge that type-checks and does not
    run.
    """
    failures = []
    kinds = json.loads((root / "schemas" / "status.schema.json").read_text(encoding="utf-8"))
    declared = set(kinds["properties"]["kind"]["enum"])
    expected = {name.removesuffix(".py") for name in COORDINATORS}
    for missing in sorted(expected - declared):
        failures.append(f"schemas/status.schema.json: kind enum omits coordinator {missing!r}")
    for extra in sorted(declared - expected):
        failures.append(f"schemas/status.schema.json: kind {extra!r} has no scripts/{extra}.py")

    # The keys each coordinator seeds into shared state, read from the source
    # rather than from a list here, so adding a key to a coordinator cannot
    # drift from what the schema admits.
    state_schema = json.loads((root / "schemas" / "state.schema.json").read_text(encoding="utf-8"))
    allowed = set(state_schema.get("properties", {}))
    for name in COORDINATORS:
        for key in sorted(state_keys_written(root / "scripts" / name) - allowed):
            failures.append(f"scripts/{name}: writes state key {key!r} that state.schema.json does not declare")
    return failures


def state_keys_written(path):
    """Literal keys a coordinator assigns into its run state.

    Parsed rather than executed: the point is to fail before anything runs, and
    a coordinator that cannot write its state has no way to report that itself.
    Only literal keys are recoverable this way, which is the shape every
    coordinator uses to seed a run.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    keys = set()
    for node in ast.walk(tree):
        # state = {"key": ...}
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Dict):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "state" in targets:
                keys.update(
                    key.value for key in node.value.keys if isinstance(key, ast.Constant) and isinstance(key.value, str)
                )
        # state["key"] = ...
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Subscript)
                    and isinstance(target.value, ast.Name)
                    and target.value.id == "state"
                    and isinstance(target.slice, ast.Constant)
                    and isinstance(target.slice.value, str)
                ):
                    keys.add(target.slice.value)
    return keys


def check_phase_owners(root, coordinators=None):
    """Every derived phase must resolve to a distinct owning contract that exists.

    A phase whose resource is the document that dispatched the coordinator
    answers "what do I read now?" with "the file you came from". Requiring a
    distinct existing owner is a stronger guarantee than scanning prose for
    phase names, and it fails the moment a phase is added without a contract.

    The coordinator table is a parameter for the same reason the verb check
    takes one: read only from imports, no fixture can reach the body, so a
    conforming tree cannot tell a working check from an empty result.
    """
    failures = []
    entry_documents = {
        DESIGN_WORKFLOW,
        REVIEW_WORKFLOW,
        ABSORB_WORKFLOW,
        RESTRUCTURE_WORKFLOW,
        REMEDIATE_WORKFLOW,
        "SKILL.md",
    }
    coordinators = coordinators or (
        ("design", design.derive_phases(design.CAPABILITIES), design.phase_resource),
        ("review", review.derive_phases(review.SURFACES), review.phase_resource),
        ("absorb", absorb.derive_phases(), absorb.phase_resource),
        ("restructure", restructure.PHASE_NAMES, restructure.phase_resource),
        ("remediate", remediate.derive_phases(), remediate.phase_resource),
    )
    owners = {}
    for coordinator, phases, resolve in coordinators:
        for phase in phases:
            label = f"scripts/{coordinator}.py: phase {phase!r}"
            resource = resolve(phase)
            path, _, fragment = resource.partition("#")
            if path in entry_documents:
                failures.append(f"{label} points at entry document {resource}; it needs a reference of its own")
            if not (root / path).exists():
                failures.append(f"{label} owner {resource} does not exist")
            elif fragment and fragment not in document.parse(root / path).anchors():
                failures.append(f"{label} owner {resource} has no such heading")
            owners.setdefault((coordinator, resource), []).append(phase)
    for (coordinator, resource), sharing in sorted(owners.items()):
        if len(sharing) > 1:
            failures.append(
                f"scripts/{coordinator}.py: phases {sorted(sharing)} share owner "
                f"{resource}; each phase needs one canonical contract"
            )
    return failures


def check_capability_rows(root):
    """Each derived capability phase must be explained in the design workflow."""
    failures = []
    parsed = document.parse(root / DESIGN_WORKFLOW)
    documented = {
        line.split("|")[1].strip().strip(TICK) for line in parsed.text.splitlines() if line.startswith("| " + TICK)
    }
    declared = {name for name, _, _ in CAPABILITY_PHASES}
    for missing in sorted(declared - documented):
        failures.append(
            f"{DESIGN_WORKFLOW}: capability {missing!r} has no row; design.py "
            "derives a phase the workflow never explains"
        )
    for extra in sorted(documented - declared):
        failures.append(f"{DESIGN_WORKFLOW}: capability {extra!r} is documented but design.py derives no phase for it")
    return failures


def check_review_phases(root, contract=None):
    """Every designable capability must be reviewable, and every review phase documented.

    review.py imports its surfaces from design.py, so the vocabularies cannot
    drift in code. This check covers the prose side: an always-run review phase
    added without explanation would otherwise pass silently.

    `contract` overrides the review contract's text, so the self-check can put
    a broken one in front of this function without editing a tracked file.
    """
    failures = []
    declared = {name for name, _, _ in CAPABILITY_PHASES}
    if set(review.SURFACES) != declared:
        failures.append(
            f"scripts/review.py: surfaces {sorted(set(review.SURFACES) ^ declared)} diverge from design capabilities"
        )
    parsed = document.parse(root / REVIEW_WORKFLOW)
    scope = parsed.section(PHASE_SECTION)
    if scope is None:
        failures.append(f"{REVIEW_WORKFLOW}: missing section {PHASE_SECTION!r}")
        return failures
    for phase in review.ALWAYS_FIRST + review.ALWAYS_LAST:
        if TICK + phase + TICK not in scope:
            failures.append(f"{REVIEW_WORKFLOW}: always-run phase {phase!r} is not described under {PHASE_SECTION!r}")

    # The gate closing a phase is driven by the questions parsed out of the
    # contract, so a phase the contract asks nothing of closes on a note alone
    # and reports the same as one that was worked through. Only `verdict` is
    # legitimately question-free: it decides what to do about answers the other
    # phases produced rather than asking anything new.
    questions = review.parse_questions(contract)
    for phase in review.ALWAYS_FIRST + review.ALWAYS_LAST + review.SURFACES:
        if phase == "verdict":
            continue
        if not questions.get(phase):
            failures.append(f"references/review.md: phase {phase!r} asks no reviewable question, so its gate is empty")

    # Each anchor maps an automatic finding onto the question it answers, by
    # matching a phrase rather than a position. Rewording that phrase would
    # otherwise silently stop the finding from answering anything, and the run
    # would demand a hand-written answer to a question it had already settled.
    for source in review.ANSWER_ANCHORS:
        try:
            if review.anchored_question(source, contract) is None:
                failures.append(f"scripts/review.py: answer anchor {source!r} resolves to nothing")
        except AssertionError as error:
            failures.append(f"scripts/review.py: {error}")

    # The anchors above are checked against themselves, which says nothing
    # about the rules nobody anchored. A conformance rule is seeded into
    # findings.json as `conformance:<rule>`, so a rule added to validate.py
    # without an anchor produces a finding that answers no question: the run
    # then asks the reviewer to establish by hand something it had already
    # proven, which is the tax that teaches people to type anything to get
    # past a gate. Rules are read from the source rather than by running the
    # validator, because a rule that fires on no fixture would be missed.
    emittable = {f"conformance:{rule}" for rule in conformance_rules()}
    assert emittable, "no conformance rules were found, so this check proves nothing"
    for source in sorted(emittable - set(review.ANSWER_ANCHORS) - review.UNREACHABLE_RULES):
        failures.append(f"scripts/review.py: {source!r} is seeded as a finding but answers no contract question")
    for source in sorted(review.UNREACHABLE_RULES - emittable):
        failures.append(f"scripts/review.py: {source!r} is exempted as unreachable but no rule emits it")
    return failures


def conformance_rules():
    """The rule names validate.py can attach to a finding.

    Read out of the source because a rule is only a string until something
    triggers it, and the rule most likely to be missed is the one no fixture
    reaches.
    """
    source = (ROOT / "scripts" / "validate.py").read_text(encoding="utf-8")
    return set(re.findall(r"""Finding\(\s*\n?\s*["'](?:error|warning)["'],\s*\n?\s*["']([a-z0-9-]+)["']""", source))


def check_reachability(root):
    """Every reference and workflow must be linked from an entry document.

    Subdirectories are walked, and a README inside one is an entry document for
    its own subtree. Globbing only the top level meant a document could be made
    unreachable by putting it one directory down, which is the opposite of what
    a directory is for: references/upstream/ holds twelve vendored files whose
    index nothing checked, so deleting a row from it silently orphaned a file
    that remained on disk and in the README's directory-prefix entry.
    """
    failures = []
    linked = set()
    entries = list(ENTRY_DOCUMENTS)
    for directory in ("references", "workflows"):
        entries += [
            path.relative_to(root).as_posix()
            for path in sorted((root / directory).rglob("README.md"))
            if path.is_file()
        ]
    for name in entries:
        parsed = document.parse(root / name)
        for link in parsed.links:
            if link.external or not link.path:
                continue
            resolved = (parsed.path.parent / link.path).resolve()
            if resolved.exists():
                linked.add(resolved)
    for directory in ("references", "workflows"):
        for path in sorted((root / directory).rglob("*.md")):
            # A subtree index is reached by the link that makes its subtree
            # worth having, so it is checked as any other document.
            if path.resolve() not in linked:
                failures.append(f"{path.relative_to(root)}: not linked from an entry document")
    return failures


def check_workflow_dispatch(root):
    """A workflow document must hand control to a coordinator, not hold it.

    restructure.md carried six numbered prose steps and an approval gate that
    nothing could enforce, and setup.md sat in workflows/ describing contracts
    with no run at all. Both read as workflows to anyone browsing the
    directory, so the rule SKILL.md states was invisible where it mattered.

    A workflow that names no coordinator either has control flow in prose or is
    a reference filed in the wrong directory.
    """
    failures = []
    for path in sorted((root / "workflows").glob("*.md")):
        name = path.relative_to(root)
        parsed = document.parse(path)
        coordinators = {
            fence.strip()
            for fence in re.findall(r"scripts/([a-z_-]+\.py)", parsed.text)
            if fence not in {"check.py", "inventory.py"}
        }
        if not coordinators:
            failures.append(
                f"{name}: names no coordinator; a workflow dispatches to scripts/, "
                "and a document that only states contracts belongs in references/"
            )
            continue
        for coordinator in sorted(coordinators):
            if not (root / "scripts" / coordinator).is_file():
                failures.append(f"{name}: dispatches to scripts/{coordinator}, which does not exist")
    return failures


def check_workflow_boundaries(root):
    """Every workflow must scope itself against the sibling that owns the rest.

    The five workflows partition the work by verb, but three of them said so
    nowhere: design.md had no scope section at all, and restructure.md and
    absorb.md named no sibling anywhere. The distinction between "the files are
    in the wrong place" and "the contract is wrong" lived only in SKILL.md's
    router table, which a reader who followed a direct link into a workflow
    never sees.

    Requiring the sibling link inside the scope section, rather than anywhere
    in the document, is what makes this catch design.md: it linked absorb.md
    from a body paragraph about sequencing, which tells a reader who has
    already chosen this workflow what to do next, not a reader deciding
    whether they are in the right document.

    This mirrors the '## Checks' rule for references. A workflow's boundary is
    the thing its readers need first, so it gets the section a reader can find
    by position.
    """
    workflows = sorted((root / "workflows").glob("*.md"))
    names = {path.name for path in workflows}
    failures = []
    for path in workflows:
        parsed = document.parse(path)
        name = path.relative_to(root)
        scope = parsed.section(WORKFLOW_SCOPE_SECTION)
        if scope is None:
            failures.append(f"{name}: no '## {WORKFLOW_SCOPE_SECTION}' section saying what it owns and excludes")
            continue
        siblings = {
            link.path.rsplit("/", 1)[-1]
            for link in parsed.links
            if not link.external
            and link.path
            and link.path.rsplit("/", 1)[-1] in names - {path.name}
            # section() returns the body, so a link counts only where a reader
            # deciding which workflow to run will actually meet it.
            and f"({link.path})" in scope
        }
        if not siblings:
            failures.append(
                f"{name}: '{WORKFLOW_SCOPE_SECTION}' links no sibling workflow, so nothing "
                "tells a reader in the wrong document which one owns their task"
            )
    return failures


def check_prose_control_flow(root):
    """A workflow must not instruct a bound or a phase jump in prose.

    AGENTS.md says control flow belongs in a coordinator, and until now
    check_workflow_dispatch was the whole of the enforcement: it asks whether a
    workflow names a coordinator at all. Every workflow here names one, so a
    document could name `scripts/design.py` in its first paragraph and then
    tell the agent "retry up to three times" or "if the reviewer disagrees, go
    back to Phase 2", and the suite would report the dispatch check green. A
    bound stated in prose cannot be proven to have held and a prose jump cannot
    be resumed, which is the whole reason the rule exists.

    The hard part is that describing what the coordinator does is legitimate
    and required: remediate.md must be able to say the bound defaults to five,
    and design.md must be able to list "retry bound reached" as behavior to
    exercise. So the discriminator is grammatical mood, not vocabulary. An
    imperative opens with its verb in base form, optionally behind a condition
    or connective, and that is an instruction to the reader. A description
    names a subject first - "the coordinator retries", "validation returns to
    merge", "`--max-iterations` is the hard bound" - and the verb is never the
    first word. Only a sentence in the imperative is read as an order.

    A vocabulary scan was tried first and refuted. Matching the words
    themselves - retry, loop, resume, bound, until, otherwise - hit 28 lines in
    this repository's own five workflows and 373 across the corpus's, and every
    one of the 28 was correct prose describing a coordinator. That check could
    only ever have shipped by deleting true statements, which is the failure
    mode AGENTS.md names: weakening the subject to satisfy the checker.

    Only two shapes are claimed, because only two survived measurement with no
    false positive: a repeat verb carrying a numeric bound, and a transfer of
    control naming a phase or step as its target. Conditional branching in
    general is deliberately not claimed. "If VAT is uncertain, stop for review"
    is a safety instruction with no control flow to resume, and no pattern
    separated that class from a genuine branch, so claiming it would have made
    the check noisy enough to be disabled. A narrow gate that never cries wolf
    is worth more than a broad one nobody trusts.
    """
    failures = []
    for path in sorted((root / "workflows").glob("*.md")):
        name = path.relative_to(root)
        for line, sentence in document.parse(path).sentences():
            for pattern, complaint in PROSE_CONTROL_FLOW:
                if pattern.match(sentence):
                    failures.append(f"{name}:{line}: {complaint}: {sentence[:80]!r}")
                    break
    return failures


def check_examples_validate(root):
    """Every JSON example must satisfy the schema it claims.

    An example is the shape an agent copies when prose is ambiguous, so a stale
    one teaches the wrong thing more effectively than no example at all. Two of
    these were wrong when first written, and only validation caught it.

    A self-describing artifact carries its schema, so nothing here maps
    filenames to schemas: an example that omits the stamp fails for that reason,
    which is the same failure a run would hit reading it.
    """
    failures = []
    for path in sorted((root / "examples").rglob("*.json")):
        name = path.relative_to(root)
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as error:
            failures.append(f"{name}: is not valid JSON: {error}")
            continue
        declared = value.get("schema") if isinstance(value, dict) else None
        if not declared:
            # Settings fixtures are the input to a resolver, not run artifacts,
            # so they carry no stamp and have no schema of their own.
            continue
        schema = str(declared).rsplit("/", 1)[-1]
        if not (root / "schemas" / schema).is_file():
            failures.append(f"{name}: claims unknown schema {schema}")
            continue
        for error in state.schema_errors(schema, value):
            failures.append(f"{name}: {error}")
    return failures


def check_reference_skeleton(root):
    """Every reference routes the same way, ending under one name for its checks.

    Eight references named this section eight different things, so finding how
    a violation is detected meant reading each document's ending to learn that
    document's word for it. The closing section drifts because every author has
    a preferred name for it, and prose asking for consistency did not hold.

    Two more parts of the skeleton were stated and unenforced. The section is
    the second: references/structure.md numbers a reference's shape as `#
    Title`, then "An opening paragraph naming what this reference owns and what
    owns the neighbouring concern instead", then the topic sections, then the
    closing. The title's presence and the closing's name were checked and the
    two middle parts were not, so a reference could jump from its title
    straight into an H2 and pass. That is the failure the skeleton exists to
    prevent, one position earlier: a reader who has to decide whether they are
    in the right document gets a heading and no answer.

    Only the paragraph's presence is required, not what it says. The sentence
    asks for two things, what this reference owns and what owns the
    neighbouring concern, and the second is a judgement no parser makes: seven
    of this repository's nineteen references link no neighbour from their
    opening because they have none to name, and demanding a link would be
    enforcing more than the contract states.

    The third is that the closing section had to exist and not to say anything.
    A reference ending in a bare `## Checks` heading passed, which is worse
    than closing under the wrong name: the reader is told there is an answer
    and then not given it. structure.md anticipates the reason an author would
    leave it empty and answers it - "A reference with no detectable violation
    states that explicitly rather than omitting the section, since a silent
    omission and a deliberate one are indistinguishable to the next reader."
    An empty section is that same silent omission wearing a heading.
    """
    failures = []
    for path in sorted((root / "references").glob("*.md")):
        parsed = document.parse(path)
        name = path.relative_to(root)
        titles = [heading.text for heading in parsed.headings_at(2)]
        if not parsed.headings_at(1):
            failures.append(f"{name}: no title heading")
        elif not any(text.strip() for text in parsed.opening_paragraphs()):
            failures.append(
                f"{name}: no opening paragraph under the title; a reader deciding whether they are in "
                "the right document meets a heading and the next section"
            )
        if REFERENCE_CLOSING not in titles:
            near = [title for title in titles if "check" in title.lower() or "test" in title.lower()]
            hint = f"; found {near[0]!r}" if near else ""
            failures.append(f"{name}: no '## {REFERENCE_CLOSING}' section{hint}")
        else:
            if titles[-1] != REFERENCE_CLOSING:
                failures.append(f"{name}: '{REFERENCE_CLOSING}' must be last, found {titles[-1]!r} after it")
            # A list is how most of these sections are written and a paragraph
            # is how the rest are, so either satisfies this. What does not is a
            # heading with nothing under it.
            said = [text for text in parsed.section_paragraphs(REFERENCE_CLOSING) if text.strip()]
            said += [item for items in parsed.section_lists(REFERENCE_CLOSING) for item in items if item.strip()]
            if not said:
                failures.append(
                    f"{name}: '{REFERENCE_CLOSING}' is empty; a heading with nothing under it tells a "
                    "reader an answer exists and withholds it"
                )
    return failures


def check_heading_code_markers(root):
    """A heading may not leave an inline-code marker unclosed.

    `references/structure.md` shipped a heading reading "Checks`, always under
    that name, saying how a violation is detected." for two commits: an
    editing accident dropped a sentence's opening clause and its leading
    backtick, and the remainder was promoted to an H2, swallowing the section
    that followed it. Every existing check passed. The skeleton check inspects
    only the last H2, and the document still ended with a clean one.

    An odd number of backticks in a heading is the mechanical signature of
    that accident: markdown cannot close the span, so the marker is rendered
    as a literal character in a title. Measured across 20,503 headings in the
    22 skills on this machine, no author writes one deliberately.
    """
    failures = []
    for parsed in document.walk(root):
        lines = parsed.text.splitlines()
        for heading in parsed.headings:
            # Counted on the source line rather than the parsed text so a
            # marker the parser consumed still registers: by the time a span
            # closes, the imbalance this looks for is gone.
            if lines[heading.line - 1].count(TICK) % 2:
                failures.append(
                    f"{parsed.path.relative_to(root)}:{heading.line}: heading leaves an inline-code "
                    f"marker unclosed: {heading.text!r}"
                )
    return failures


def check_readme_structure(root):
    """Every shipped resource must appear in the README structure list.

    The list is the only human map of the repository, so an unlisted file is a
    resource a reader cannot find and a listed-but-absent file is a dead map
    entry. Both were true before this check existed.

    Every shipped file is checked, not those under a named set of directories.
    The allowlist meant a new top-level directory arrived unmapped and stayed
    that way, since being absent from the list was what exempted it: the check
    could only ever confirm the map covered the places the map already knew
    about. Untracked working files are excluded by asking git, which is the
    question the allowlist was standing in for.
    """
    failures = []
    parsed = document.parse(root / README)
    scope = parsed.section(README_SECTION)
    if scope is None:
        return [f"{README}: missing section {README_SECTION!r}"]
    listed = set(re.findall(r"^- " + TICK + r"([^" + TICK + r"]+)" + TICK, scope, re.M))
    for entry in sorted(listed):
        if not (root / entry).exists():
            failures.append(f"{README}: lists {entry}, which does not exist")
    shipped = state.shipped_paths(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        parts = relative.parts
        if any(part.startswith(".") for part in parts) or "__pycache__" in parts:
            continue
        name = relative.as_posix()
        # The README maps what this repository ships, not a contributor's
        # untracked working files.
        if shipped is not None and name not in shipped:
            continue
        if name in README_EXEMPT or name in listed:
            continue
        if any(entry.endswith("/") and name.startswith(entry) for entry in listed):
            continue
        failures.append(f"{README}: {name} is not listed under {README_SECTION!r}")
    return failures


def check_executable_bits(root):
    """A shebang and the executable bit must agree on every shipped file.

    A script whose first line names an interpreter is documenting that it can be
    run directly. If the committed mode says otherwise, `./scripts/check.py`
    fails for a reason no reader can see from the source, and the two facts
    drift apart silently. Git owns the mode, so compare against git rather than
    the local filesystem, where a permissive umask hides the difference.
    """
    listing = subprocess.run(
        ["git", "ls-files", "--stage", "-z"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if listing.returncode != 0:
        return []
    failures = []
    for entry in listing.stdout.split("\0"):
        if not entry.strip():
            continue
        mode, _, remainder = entry.partition(" ")
        name = remainder.split("\t", 1)[-1]
        path = root / name
        if not path.is_file():
            continue
        with path.open("rb") as handle:
            shebang = handle.read(2) == b"#!"
        executable = mode == "100755"
        if shebang and not executable:
            failures.append(f"{name}: declares a shebang but is not executable")
        elif executable and not shebang:
            failures.append(f"{name}: is executable but declares no shebang")
    return failures


def check_external_links(root):
    """Verify external URLs with lychee, which owns network link checking.

    Provenance and attribution URLs are claims that rot silently; nothing else
    in this suite touches the network. Opt-in via CHECK_EXTERNAL_LINKS=1 so the
    default run stays offline and deterministic.
    """
    if os.environ.get("CHECK_EXTERNAL_LINKS") != "1":
        return []
    executable = shutil.which("lychee")
    if executable is None:
        return ["lychee is not installed; external link checking was requested but cannot run"]
    result = subprocess.run(
        [
            executable,
            "--no-progress",
            "--max-concurrency",
            "4",
            "--include-fragments=full",
            "--config",
            str(root / "lychee.toml"),
            "--format",
            "compact",
            str(root),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    # A nonzero exit means lychee rejected something, so this must report at
    # least one failure. Filtering its output for known markers and returning
    # whatever survives would turn a format change in a future lychee release
    # into a silent pass: the run fails, the filter matches nothing, and the
    # suite reports the check green. The unparsed output is the fallback,
    # because an unreadable failure is still a failure.
    reported = [line.strip() for line in result.stdout.splitlines() if "[ERROR]" in line or "[404]" in line]
    if reported:
        return reported
    detail = (result.stdout + result.stderr).strip().splitlines()
    return [f"lychee exited {result.returncode} with no recognisable failure lines"] + [
        line.strip() for line in detail[-10:] if line.strip()
    ]


def check_schema_lint(root):
    """Validate the schemas as schemas, which jsonschema itself does not do.

    `jsonschema` validates instances against a schema and assumes the schema is
    correct, so a structurally invalid schema is only discovered when a run
    trips over it. `--check-metaschema` catches that class of fault.
    Skipped when check-jsonschema is absent, like the other external tools.
    """
    executable = shutil.which("check-jsonschema")
    if executable is None:
        return []
    schemas = sorted((root / "schemas").glob("*.schema.json"))
    if not schemas:
        return ["schemas/: no schema files found"]
    result = subprocess.run(
        [executable, "--check-metaschema", *[str(path) for path in schemas]],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    output = f"{result.stdout}\n{result.stderr}"
    return [line.strip() for line in output.splitlines() if line.strip()]


# JSON Schema 2020-12 keywords this repository's schemas are allowed to use.
SCHEMA_KEYWORDS = frozenset(
    {
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "$comment",
        "title",
        "description",
        "type",
        "enum",
        "const",
        "format",
        "properties",
        "required",
        "additionalProperties",
        "patternProperties",
        "propertyNames",
        "items",
        "prefixItems",
        "minItems",
        "maxItems",
        "uniqueItems",
        "contains",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "minLength",
        "maxLength",
        "pattern",
        "minProperties",
        "maxProperties",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "default",
        "examples",
        "deprecated",
    }
)

# Keys under these keywords are user-chosen names, not schema keywords.
SCHEMA_NAMED_MAPS = ("properties", "patternProperties", "$defs")

# Values of these keywords are themselves schemas.
SCHEMA_SUBSCHEMA_LISTS = ("allOf", "anyOf", "oneOf", "prefixItems")
SCHEMA_SUBSCHEMA_KEYS = (
    "items",
    "not",
    "if",
    "then",
    "else",
    "contains",
    "additionalProperties",
    "propertyNames",
)


def _walk_schema(node, path, failures):
    """Report keys sitting in schema position that are not known keywords.

    A misspelled keyword is valid JSON Schema: unknown keywords are annotations
    and are ignored, so `tpye` asserts nothing and the metaschema accepts it.
    The constraint silently stops being enforced, which is the failure mode a
    schema exists to prevent.
    """
    if not isinstance(node, dict):
        return
    for key, value in node.items():
        here = f"{path}.{key}" if path else key
        if key not in SCHEMA_KEYWORDS:
            failures.append(f"{here}: unknown schema keyword {key!r}")
            continue
        if key in SCHEMA_NAMED_MAPS and isinstance(value, dict):
            for name, subschema in value.items():
                _walk_schema(subschema, f"{here}.{name}", failures)
        elif key in SCHEMA_SUBSCHEMA_LISTS and isinstance(value, list):
            for index, subschema in enumerate(value):
                _walk_schema(subschema, f"{here}[{index}]", failures)
        elif key in SCHEMA_SUBSCHEMA_KEYS:
            _walk_schema(value, here, failures)


def check_schema_keywords(root):
    """Catch misspelled keywords, which the metaschema accepts as annotations."""
    failures = []
    for path in sorted((root / "schemas").glob("*.schema.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        found = []
        _walk_schema(document, "", found)
        failures.extend(f"schemas/{path.name}: {failure}" for failure in found)
    return failures


def check_vendored_schemas(root):
    """The vendored third-party schemas must stay byte-identical to what we fetched.

    A vendored copy is only trustworthy if it is the published document. Editing
    one to make a check pass would mean claiming conformance to a standard while
    validating against a private variant of it, which is worse than not
    validating at all. Refresh by re-fetching and updating the digest here.
    """
    failures = []
    for name, expected in VENDORED_SCHEMAS.items():
        path = root / "schemas" / "vendor" / name
        if not path.is_file():
            failures.append(f"schemas/vendor/{name}: missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != expected:
            failures.append(f"schemas/vendor/{name}: sha256 {actual} does not match the recorded {expected}")
    return failures


def string_literals(source):
    """Every string a module evaluates, excluding its docstrings.

    A docstring is a string expression the interpreter never uses for anything,
    so it is prose that happens to be parsed. Excluding it is the difference
    between "this name appears in the file" and "this name is a value the code
    works with".
    """
    tree = ast.parse(source)
    documented = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        first = node.body[0] if node.body else None
        if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
            documented.add(id(first.value))
    return {
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in documented
    }


def referenced_schemas(root, named):
    """Close a set of schema names under $ref, so indirection is proved not assumed.

    A schema reached only through another schema's $ref is genuinely in use,
    and no script will ever name it. Following the references answers that,
    where an exemption list only records that someone once decided it.
    """
    reachable, pending = set(named), list(named)
    while pending:
        name = pending.pop()
        path = root / "schemas" / name
        if not path.is_file():
            continue
        for reference in re.findall(r'"\$ref"\s*:\s*"([^"#]+)', path.read_text(encoding="utf-8")):
            target = reference.rsplit("/", 1)[-1]
            if target and target not in reachable:
                reachable.add(target)
                pending.append(target)
    return reachable


def check_schema_coverage(root):
    """Every schema must be documented, reachable, and actually used.

    A schema nothing writes against is a contract with no party to it, and a
    schema no document names cannot be found by the agent that has to satisfy
    it. Both failures look like a healthy directory listing.

    "Used" was a substring test over the concatenated source of every script,
    which a comment satisfied. Naming a schema in a sentence explaining that
    nothing writes it was enough to prove that something did. The names are
    read as string literals now, with docstrings excluded, because a docstring
    is prose the interpreter parses and never uses.

    That reading is exact enough to replace the indirection exemption with the
    reason behind it. common.schema.json was listed as exempt because no
    coordinator names it, which is true and says nothing about whether anything
    reaches it: the exemption asserted the conclusion. Following $ref from the
    schemas scripts do name proves it, and would report the file the day the
    last reference to it is deleted, which the exemption never could.
    """
    failures = []
    schemas = sorted(path.name for path in (root / "schemas").glob("*.schema.json"))
    if not schemas:
        return ["schemas/: no schema files found"]
    used = set()
    for path in sorted((root / "scripts").glob("*.py")):
        # This file is excluded because its self-check builds fixture trees
        # containing schema names. Counting those would let a check's own test
        # data stand in for a coordinator using the schema, which is the same
        # confusion between mentioning a name and using it that the literal
        # reading exists to end.
        if path.name != CHECKER:
            used |= string_literals(path.read_text(encoding="utf-8"))
    named = {name for name in schemas if any(name in literal for literal in used)}
    reachable = referenced_schemas(root, named)
    contract = (root / ARTIFACT_REFERENCE).read_text(encoding="utf-8")
    for name in schemas:
        if name not in contract:
            failures.append(f"{ARTIFACT_REFERENCE}: does not document {name}")
        if name not in reachable:
            failures.append(f"schemas/{name}: no script writes or validates against it")
        # An agent authors these files by hand, so a misspelled key is the most
        # likely mistake there is. An open root accepts it, the coordinator
        # reports the artifact valid, and the content is silently dropped: the
        # run proceeds as though the agent never wrote it. Closing the root
        # turns that into an error naming the key.
        document = json.loads((root / "schemas" / name).read_text(encoding="utf-8"))
        if document.get("type") != "object" or "properties" not in document:
            continue
        if document.get("additionalProperties") is not False:
            failures.append(f"schemas/{name}: root accepts undeclared keys; set additionalProperties false")
    return failures


def check_licence_headers(root):
    """Every executable file must name the licence that covers it.

    This repository is dual-licensed: prose carries the upstream share-alike
    obligation, executables do not. That boundary is only real if it is visible
    per file. Without a header, someone vendoring `state.py` has to reason about
    which half of the repository it belongs to, and will guess share-alike.

    Every shipped file under `scripts/` is required to carry the tag, not those
    whose suffix a list happened to name. The list was `.py` and `.sh`, so a
    `.js` helper, a `.toml` tool config, or a `.yml` job under `scripts/` landed
    with no tag at all and passed: being an unanticipated suffix was what
    exempted it. That is the opposite of what the README claims, which is that
    the boundary is readable per file rather than inferred. Exemptions are named
    in LICENCE_EXEMPT so dropping a file out of the boundary is written down.

    The comment leader is not assumed to be `#`, because requiring every suffix
    also means meeting formats whose comment syntax is `//` or `<!--`. SPDX
    itself only asks that the tag appear in a comment near the top, so the tag
    is located within the head and the expression after it is what must match.
    """
    failures = []
    shipped = state.shipped_paths(root)
    for path in sorted((root / "scripts").rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        name = relative.as_posix()
        if any(part.startswith(".") for part in relative.parts) or "__pycache__" in relative.parts:
            continue
        # A contributor's untracked scratch file is not what this repository
        # ships, so it is not what the licence boundary has to cover.
        if shipped is not None and name not in shipped:
            continue
        if name in LICENCE_EXEMPT:
            continue
        declared = tagged_licence(path)
        if declared is None:
            failures.append(f"{name}: missing '{SPDX_TAG} {CODE_LICENCE}' header")
        elif declared != CODE_LICENCE:
            failures.append(f"{name}: {SPDX_TAG} must be {CODE_LICENCE}, not {declared}")
    declared = document.parse(root / "SKILL.md").frontmatter or {}
    if declared.get("license") != SKILL_LICENCE:
        failures.append(f"SKILL.md: frontmatter license must be {SKILL_LICENCE!r}")
    return failures


def tagged_licence(path):
    """The licence expression this file declares in its head, or None.

    Read as bytes and decoded leniently because the caller now asks every
    shipped file, and a file this cannot decode carries no tag rather than
    crashing the suite on it.
    """
    head = path.read_bytes()[:4096].decode("utf-8", errors="replace").splitlines()[:5]
    for line in head:
        _, marker, expression = line.partition(SPDX_TAG)
        if not marker:
            continue
        expression = expression.strip()
        for closer in COMMENT_CLOSERS:
            expression = expression.removesuffix(closer).strip()
        return expression
    return None


def check_lint(root):
    """Delegate Python correctness to ruff rather than hand-rolling AST checks.

    Skipped when ruff is absent so the suite stays runnable with stdlib alone.
    """
    return run_ruff(root, "check", "--quiet", "--output-format", "concise")


def check_format(root):
    """Make formatting a check result rather than a reviewer's judgement.

    Whitespace disagreements otherwise surface as review comments on unrelated
    pull requests. `ruff format` owns the answer; this reports where the tree
    disagrees with it. Skipped when ruff is absent, like the lint check.
    """
    return run_ruff(root, "format", "--check", "--quiet")


def run_ruff(root, *arguments):
    executable = shutil.which("ruff")
    if executable is None:
        return []
    result = subprocess.run(
        [executable, *arguments, str(root / "scripts")],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return []
    output = f"{result.stdout}\n{result.stderr}"
    return [line.strip() for line in output.splitlines() if line.strip()]


def third_party_imports(path):
    """The distributions a module imports that are neither stdlib nor local.

    Read from the source rather than by importing, so the answer is the same on
    a machine where the dependency happens to be installed as on one where it
    is not.
    """
    local = {sibling.stem for sibling in path.parent.glob("*.py")}
    imported = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            imported.add(node.module.split(".")[0])
    return imported - set(sys.stdlib_module_names) - local


def declared_requirements(root, extra=None):
    """Distribution names one dependency table declares, canonicalised.

    Read with a TOML parser rather than by matching the array's text. The
    regex this replaces matched every quoted word between the brackets, so a
    comment inside the array naming a package read as a declaration of it.
    Dropping `referencing` from the array while explaining the removal in a
    comment left the check reporting the dependency as declared: the one
    defect the check exists to catch, hidden by the way the check looked.

    `packaging` parses the requirement, so an extra, a marker, or a version
    specifier is the parser's problem rather than another pattern here.
    """
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    project = data.get("project", {})
    table = project.get("optional-dependencies", {}).get(extra, []) if extra else project.get("dependencies", [])
    return {canonicalize_name(Requirement(spec).name) for spec in table}


def check_declared_dependencies(root):
    """Every third-party import must be declared, and must fail actionably.

    `state.py` imported `referencing` that pyproject.toml never declared. It
    resolved anyway because jsonschema depends on it, so the suite passed on
    every machine while the repository's stated dependency set was wrong: a
    jsonschema release that drops it would break every coordinator, and the
    file naming what this repository needs would not have changed.

    The guard is the same defect seen from the user's side. An undeclared or
    uninstalled dependency reaches a new user as a traceback ending in
    ModuleNotFoundError inside state.py, which names this repository's
    internals instead of the one command that fixes it. document.py had wrapped
    its own imports for exactly that reason; nothing required the others to.
    """
    declared = declared_requirements(root)
    if not declared:
        return ["pyproject.toml declares no dependencies table"]
    # An import name is not a distribution name, and the mapping is not
    # recoverable without the package installed. Resolving it through the
    # installed metadata would make the answer depend on what happens to be
    # present, which is the state this check exists to detect, so the few
    # names that do not normalise are stated here.
    aliases = {"yaml": "pyyaml", "markdown_it": "markdown-it-py", "mdit_py_plugins": "mdit-py-plugins"}
    failures = []
    for path in sorted((root / "scripts").glob("*.py")):
        imports = third_party_imports(path)
        for module in sorted(imports):
            distribution = canonicalize_name(aliases.get(module, module))
            if distribution not in declared:
                failures.append(
                    f"scripts/{path.name}: imports {module!r}, which pyproject.toml does not declare; "
                    "it resolves today only as some other package's transitive dependency"
                )
        # A module reached through an import of a guarded one inherits the
        # guard, so only the modules that import a third party directly need it.
        if imports and "ModuleNotFoundError" not in path.read_text(encoding="utf-8"):
            failures.append(
                f"scripts/{path.name}: imports {', '.join(sorted(imports))} without a ModuleNotFoundError guard; "
                "a missing dependency reaches the user as a traceback rather than an install command"
            )
    return failures


def check_coordinator_paths(root):
    """SKILL.md must say what the coordinator paths in workflows are relative to.

    Every workflow spells its coordinator `python3 scripts/<name>.py`, which
    resolves only when the working directory is this repository. An installed
    skill is almost never that directory: the run directory belongs to the
    user's project, so the documented command failed on the first invocation
    for anyone who installed rather than cloned.

    references/packaging.md already forbids exactly this, calling paths
    relative to the agent's working directory a broken bundle. The rule was
    stated for other people's skills and not applied to this one, which no
    check could notice because each workflow was internally consistent.

    The contract is owned once, in the entry document every host loads, rather
    than repeated in five workflows where it would drift.
    """
    dispatching = [
        path.relative_to(root).as_posix()
        for path in sorted((root / "workflows").glob("*.md"))
        if re.search(r"python3 scripts/[a-z_-]+\.py", path.read_text(encoding="utf-8"))
    ]
    if not dispatching:
        return []
    parsed = document.parse(root / "SKILL.md")
    if parsed.section(COORDINATOR_PATH_SECTION) is None:
        return [
            (
                f"SKILL.md: missing section {COORDINATOR_PATH_SECTION!r}; {len(dispatching)} workflows show a "
                "working-directory-relative command and nothing says what it resolves against"
            )
        ]
    return []


def tool_version_mismatches(root):
    """Report a shelled-out tool whose version is not the one pyproject.toml pins.

    The pins exist so an upgrade cannot silently widen or narrow what this
    repository considers an error. They only ever bound the copy pip installed:
    check.py resolves each tool with shutil.which, which returns whatever is
    first on PATH, so a system-wide install silently replaces the pinned one
    and enforces a different rule set. That is invisible either way round, as a
    finding the pinned version would not raise, or as a missed finding on a
    machine running something older.

    Derived from the dev extra rather than a second list here, so pinning a new
    tool covers it without editing this function. Reported rather than fatal,
    because a contributor with a different version should still be able to run
    the suite; the point is that they can see the substitution.
    """
    data = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    extra = data.get("project", {}).get("optional-dependencies", {}).get("dev")
    if not extra:
        return ["pyproject.toml declares no dev extra; the tool versions are unbounded"]
    failures = []
    # A specifier is a set of clauses, not a string to match: `ruff==0.16.*`
    # and `check-jsonschema~=0.37` both bound a major.minor, and the parser
    # says which. The pattern this replaces read the array's text, so a pin
    # commented out inside the array still counted as pinned.
    pinned = []
    for spec in extra:
        requirement = Requirement(spec)
        version = next((str(clause.version) for clause in requirement.specifier), None)
        parts = version.split(".") if version else []
        if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
            pinned.append((requirement.name, parts[0], parts[1]))
    if not pinned:
        return ["pyproject.toml pins no tool versions; the rule sets are unbounded"]
    for name, major, minor in pinned:
        executable = shutil.which(name)
        if executable is None:
            continue
        result = subprocess.run([executable, "--version"], capture_output=True, text=True, check=False)
        found = re.search(r"([0-9]+)\.([0-9]+)", result.stdout)
        if found is None:
            continue
        if found.group(1, 2) != (major, minor):
            failures.append(
                f"{name} on PATH is {found.group(0)} but pyproject.toml pins {major}.{minor}; results will not match CI"
            )
    return failures


def run_script(root, name, *arguments, expect=None):
    """Run a script, optionally requiring proof it did something.

    A self-check that exits zero without running anything is indistinguishable
    from a passing one on the exit code alone, so the caller can demand the line
    a real check prints.
    """
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / name), *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return [f"scripts/{name} failed: {result.stdout.strip()} {result.stderr.strip()}".strip()]
    if expect is not None and expect not in result.stdout:
        return [f"scripts/{name}: exited zero without printing {expect!r}; it has no real self-check"]
    return []


def discovered_self_checks(root):
    """Every script's own self-check, found rather than listed.

    A hand-written list silently under-reports: adding a script and forgetting
    to register it leaves its self-check unrun, and the suite still passes. That
    is the failure a checker exists to prevent, so the list is derived from the
    directory instead.
    """
    checks = []
    for path in sorted((root / "scripts").glob("*.py")):
        name = path.name
        # check.py runs this list, so it cannot be one of its own entries
        # without recursing.
        argument = "--self-check" if name == CHECKER else cli.SELF_CHECK
        checks.append(
            (
                f"{path.stem} self-check",
                partial(run_script, root, name, argument, expect=cli.PASSED),
            )
        )
    return checks


VERSION_BOUND = re.compile(r"(?<![\w.-])([a-zA-Z][\w.-]*)\s*(?:==|>=|<=|~=|!=)\s*v?\d")
# Files that would carry a package version if anyone put one there. The
# workflow is the one that matters; the others are where a pin migrates to
# when the workflow rejects it.
BOUND_FILES = (".github/workflows/checks.yml", "requirements.txt", "Dockerfile", "Containerfile")
# Task runners. Each would be a second way to run part of the suite.
RUNNER_FILES = ("Makefile", "justfile", "Justfile", "Taskfile.yml", "Taskfile.yaml", "noxfile.py", "tox.ini")


def check_single_version_source(root):
    """Package versions live in pyproject.toml and nowhere else.

    AGENTS.md states this as an absolute and nothing enforced it. A pin added
    to the CI workflow is the specific failure: it silently overrides the
    declared range for every run that matters, so the versions a contributor
    installs and the versions CI enforces diverge, and the file that claims to
    be the single source of truth stops being consulted.

    The Python version matrix is exempt because it is not a package bound: the
    workflow decides which runtimes are exercised, and check_ci_floor already
    holds it to the floor pyproject declares.
    """
    failures = []
    for name in BOUND_FILES:
        path = root / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#") or "python-version" in stripped:
                continue
            match = VERSION_BOUND.search(line)
            if match:
                failures.append(
                    f"{name}:{number}: version bound {match.group(0).strip()!r}; pyproject.toml owns versions"
                )
    return failures


def check_single_entrypoint(root):
    """scripts/check.py is the only way to run the checks.

    AGENTS.md states this too, and the reason is drift: a Makefile target
    naming three of the scripts runs a subset, passes, and reads as though the
    suite passed. The list of checks lives in check.py so CI, CONTRIBUTING.md,
    and AGENTS.md cannot disagree about it, which only holds while nothing
    else offers a second entrypoint.

    A runner invoking check.py itself is fine, and is the point: a convenience
    alias for the one command is not a parallel entrypoint.
    """
    failures = []
    for name in RUNNER_FILES:
        path = root / name
        if not path.is_file():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for script in re.findall(r"scripts/([a-z_]+\.py)", line):
                if script != CHECKER:
                    failures.append(
                        f"{name}:{number}: runs scripts/{script}; scripts/{CHECKER} is the only check entrypoint"
                    )
    return failures


def check_ci_floor(root):
    """The CI matrix must start at the floor pyproject.toml declares.

    The workflow comment says its first entry is that floor, but nothing tied
    the two together. Raising requires-python would leave CI proving the suite
    works on a version the project no longer claims to support; lowering it
    would leave the real floor untested. Both failures look like a green run.
    """
    pyproject = root / "pyproject.toml"
    workflow = root / ".github" / "workflows" / "checks.yml"
    if not pyproject.exists() or not workflow.exists():
        return []
    # Both files are read by their own parsers rather than by pattern. The
    # matrix pattern this replaces required a flow sequence on one line, so
    # rewriting the same list as a YAML block sequence, which is the more
    # common style and changes nothing, made the check report that it could
    # not find the matrix instead of comparing it.
    requires = tomllib.loads(pyproject.read_text(encoding="utf-8")).get("project", {}).get("requires-python")
    matrix = None
    for job in (yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}).get("jobs", {}).values():
        found = job.get("strategy", {}).get("matrix", {}).get("python-version")
        if found:
            matrix = [str(entry) for entry in found]
            break
    if not requires or not matrix:
        return ["could not read the Python floor from pyproject.toml or the CI matrix"]
    # The floor is the lowest version the specifier admits, which the
    # specifier itself knows: `>=3.10` and `>=3.10,<4` state the same floor
    # and the pattern would have read only the first number it saw.
    floor = next(
        (str(clause.version) for clause in SpecifierSet(requires) if clause.operator in {">=", "==", "~="}), None
    )
    if floor is None:
        return [f"pyproject.toml declares {requires!r}, which states no floor to test"]
    if matrix[0] != floor:
        return [
            (
                f"checks.yml tests {matrix[0]} first but pyproject.toml declares "
                f">={floor}; the declared floor would go untested"
            )
        ]
    return []


def registered_checks(source):
    """Names the suite registry runs, and the names its self-check exercises.

    Read from the source rather than by running either, because the question
    is what the file wires up, and a check that is never wired up cannot be
    observed by running it.
    """
    tree = ast.parse(source)
    defined = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name.startswith("check_") and node.name != "check_skill"
    }
    registry, exercised = set(), set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        called = {
            inner.func.id
            for inner in ast.walk(node)
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name)
        }
        if node.name == "main":
            registry |= called
        elif node.name == "self_check":
            exercised |= called
    return defined, registry, exercised


def check_checks_are_wired(root):
    """Every check must be registered by the suite and exercised by its self-check.

    A check_* function that nothing calls is indistinguishable from one that
    passes: the suite reports every registered check green and says nothing
    about the one it never ran. Adding real logic to this file and forgetting
    the one line that registers it leaves a repository that believes it is
    checking something it is not, and no existing check looks for that.

    Being exercised by self_check is the second half. AGENTS.md requires a new
    check to be shown failing on a real violation before it is kept, and
    whether the violation was real stays a human judgement, but whether
    anything at all drives the check is not: a registered check with no case
    behind it can have its condition inverted and the suite stays green. That
    is the shape mutation testing keeps finding.
    """
    source = (root / "scripts" / CHECKER).read_text(encoding="utf-8")
    defined, registry, exercised = registered_checks(source)
    failures = []
    for name in sorted(defined - registry):
        failures.append(f"scripts/{CHECKER}: {name} is defined but main() never registers it, so it never runs")
    for name in sorted(defined - exercised):
        failures.append(f"scripts/{CHECKER}: {name} has no case in self_check(), so nothing proves it can fail")
    return failures


def self_checks_assert_something(root):
    """Require each self-check to contain assertions that can fail.

    run_script demands the script print "self-check passed", which catches a
    self-check that stays silent. It does not catch one that prints the line
    and checks nothing: a stub whose whole body is that print passes the suite
    while proving nothing about the script it belongs to.

    Counting assertions was the first answer and it was not enough. `assert
    True` is an assertion, so a self-check gutted down to a single tautology
    satisfied the count while proving exactly as much as the empty stub this
    check was written to reject. That matters more here than anywhere else:
    this is the check standing behind every other script's self-check, so a
    hole in it is a hole in all of them at once.

    An assertion whose test is a literal cannot fail, so it is not counted. No
    judgement is made about whether the remaining assertions are good ones;
    the bar is that at least one of them can distinguish a working script from
    a broken one.
    """
    failures = []
    for path in sorted((root / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and "self_check" in node.name]
        if not functions:
            failures.append(f"scripts/{path.name}: no self-check function")
            continue
        asserts = [node for function in functions for node in ast.walk(function) if isinstance(node, ast.Assert)]
        # A constant test is decided before the program runs. Tuples and lists
        # of constants are the same mistake spelled differently, and `assert
        # (x, "message")` is the one that reads most like a real check.
        falsifiable = [node for node in asserts if not _is_constant(node.test)]
        if not falsifiable:
            detail = "contains no assertions" if not asserts else "asserts only constants, which cannot fail"
            failures.append(f"scripts/{path.name}: self-check {detail}; printing the line is not checking")
    return failures


def _is_constant(node):
    """Whether an expression's truth is fixed before the program runs."""
    if isinstance(node, ast.Constant):
        return True
    # A collection literal's truth is its length, which is fixed here whatever
    # the elements evaluate to. `assert (value, "message")` is the shape this
    # catches: it reads like an assertion carrying a message, and is a tuple
    # that can never be falsy.
    return isinstance(node, (ast.Tuple, ast.List, ast.Set))


def self_check():
    """Verify the checks that carry their own logic actually reject bad input.

    Most checks here delegate to a script that self-checks, or assert a fact
    about the repository that is visible when it breaks.

    The format bounds are no longer among them: scripts/validate.py owns those
    and proves them in its own self-check, which check.py discovers and runs.
    Asserting them again here would be the same duplication that let this
    file's copy drift from the format in the first place.
    """
    # The assertion counter is the check that catches a self-check which prints
    # the passing line and proves nothing, so it must reject exactly that stub.
    with tempfile.TemporaryDirectory() as directory:
        scripts = Path(directory) / "scripts"
        scripts.mkdir()
        (scripts / "impostor.py").write_text('def self_check():\n    print("self-check passed")\n', encoding="utf-8")
        assert self_checks_assert_something(Path(directory)), "a stub self-check was accepted"
        (scripts / "impostor.py").write_text(
            'def self_check():\n    assert True\n    print("self-check passed")\n', encoding="utf-8"
        )
        assert self_checks_assert_something(Path(directory)), "a tautology was counted as an assertion"
        (scripts / "impostor.py").write_text(
            'def self_check():\n    assert (value, "message")\n    print("self-check passed")\n', encoding="utf-8"
        )
        assert self_checks_assert_something(Path(directory)), "an always-truthy tuple was counted as an assertion"
        (scripts / "impostor.py").write_text(
            'def self_check():\n    assert parse("x") == 1\n    print("self-check passed")\n', encoding="utf-8"
        )
        assert self_checks_assert_something(Path(directory)) == [], "a real assertion was rejected"
        (scripts / "impostor.py").write_text("x = 1\n", encoding="utf-8")
        assert self_checks_assert_something(Path(directory)), "a script with no self-check was accepted"

    # Both AGENTS.md absolutes are replayed, since each passes on a tree that
    # obeys it whether or not the check does anything.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / ".github" / "workflows").mkdir(parents=True)
        workflow = tree / ".github" / "workflows" / "checks.yml"
        workflow.write_text(
            "jobs:\n  checks:\n    strategy:\n      matrix:\n        python-version: ['3.10', '3.13']\n"
            "    steps:\n      - run: python -m pip install -r requirements.txt\n",
            encoding="utf-8",
        )
        assert check_single_version_source(tree) == [], check_single_version_source(tree)
        workflow.write_text(
            "jobs:\n  checks:\n    steps:\n      - run: pip install -r requirements.txt 'ruff==0.5.0'\n",
            encoding="utf-8",
        )
        assert check_single_version_source(tree), "a pin in the CI workflow was accepted"
        (tree / "Makefile").write_text("check:\n\tpython3 scripts/check.py\n", encoding="utf-8")
        assert check_single_entrypoint(tree) == [], "a runner delegating to the one entrypoint was rejected"
        (tree / "Makefile").write_text("lint:\n\tpython3 scripts/names.py\n", encoding="utf-8")
        assert check_single_entrypoint(tree), "a Makefile running part of the suite was accepted"

    # A check nothing registers never runs, and a check with no case behind it
    # can have its condition inverted with the suite still green. Both holes
    # are invisible from the outside, so the wiring is read from the source.
    wired = (
        "def check_a(root):\n    return []\n\ndef main():\n    check_a(ROOT)\n\ndef self_check():\n    check_a(ROOT)\n"
    )
    assert registered_checks(wired) == ({"check_a"}, {"check_a"}, {"check_a"})
    unregistered = (
        "def check_a(root):\n    return []\n\ndef main():\n    pass\n\ndef self_check():\n    check_a(ROOT)\n"
    )
    defined, registry, exercised = registered_checks(unregistered)
    assert defined - registry == {"check_a"}, "a check main() never calls was treated as registered"
    unexercised = "def check_a(root):\n    return []\n\ndef main():\n    check_a(ROOT)\n\ndef self_check():\n    pass\n"
    defined, registry, exercised = registered_checks(unexercised)
    assert defined - exercised == {"check_a"}, "a check with no self-check case was treated as covered"
    # The check has to answer for itself too, and the only way to be exercised
    # by self_check() is to be called from it. Asserting only that the real
    # file passes would leave the check itself the one thing here that could be
    # gutted without the suite noticing, so a broken tree is replayed as well.
    assert check_checks_are_wired(ROOT) == [], "a check in this file is unregistered or has no case"
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "scripts").mkdir()
        (tree / "scripts" / CHECKER).write_text(unregistered, encoding="utf-8")
        assert check_checks_are_wired(tree), "an unregistered check was accepted"
        (tree / "scripts" / CHECKER).write_text(unexercised, encoding="utf-8")
        assert check_checks_are_wired(tree), "a check with no self-check case was accepted"
        (tree / "scripts" / CHECKER).write_text(wired, encoding="utf-8")
        assert check_checks_are_wired(tree) == [], "a fully wired check was rejected"

    # The floor check compares two files no other check reads together, so a
    # version drift between them would otherwise look like a green run.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / ".github" / "workflows").mkdir(parents=True)
        project = tree / "pyproject.toml"
        matrix = tree / ".github" / "workflows" / "checks.yml"

        def write_floor(requires, versions, style="flow"):
            project.write_text(f'[project]\nrequires-python = "{requires}"\n', encoding="utf-8")
            if style == "flow":
                listed = "[" + ", ".join(f'"{version}"' for version in versions) + "]"
                entries = f"        python-version: {listed}\n"
            else:
                entries = "        python-version:\n" + "".join(f'          - "{v}"\n' for v in versions)
            matrix.write_text(
                "jobs:\n  checks:\n    strategy:\n      matrix:\n" + entries,
                encoding="utf-8",
            )

        write_floor(">=3.10", ["3.10", "3.13"])
        assert check_ci_floor(tree) == []
        write_floor(">=3.11", ["3.10", "3.13"])
        assert check_ci_floor(tree), "a CI matrix below the declared floor was accepted"
        write_floor(">=3.11", ["3.11"])
        assert check_ci_floor(tree) == []
        # A block sequence is the same list written the other way. The pattern
        # this replaced saw no matrix at all and reported that it could not
        # read one, which is not the same answer as "the floor is untested".
        write_floor(">=3.11", ["3.10"], style="block")
        assert check_ci_floor(tree), "a block-sequence matrix below the floor was accepted"
        write_floor(">=3.11", ["3.11"], style="block")
        assert check_ci_floor(tree) == [], "a block-sequence matrix at the floor was rejected"
        # A bounded specifier states the same floor as a bare one.
        write_floor(">=3.11,<4", ["3.11"])
        assert check_ci_floor(tree) == [], "a bounded requires-python was misread"
        # A specifier stating only a ceiling names no version to test on, and
        # saying so is different from silently comparing against nothing.
        write_floor("<4", ["3.11"])
        assert check_ci_floor(tree), "a requires-python stating no floor was accepted"

        # A heading that leaves an inline-code marker unclosed is a truncated
        # sentence promoted to a title, which is how this repository lost a
        # section for two commits.
        (tree / "references").mkdir()
        (tree / "references" / "sane.md").write_text("# Title\n\n## `code` and prose\n", encoding="utf-8")
        assert check_heading_code_markers(tree) == [], "a balanced code span in a heading was rejected"
        (tree / "references" / "sane.md").write_text(
            "# Title\n\n## Checks`, always under that name\n", encoding="utf-8"
        )
        assert check_heading_code_markers(tree), "a heading with an unclosed code marker was accepted"

        # The pin check must notice a version that differs from the pin, and a
        # dev extra that pins nothing at all; both leave the rule set as
        # whatever the machine happens to have.
        project.write_text(
            '[project.optional-dependencies]\ndev = ["ruff==0.1.*"]\n',
            encoding="utf-8",
        )
        if shutil.which("ruff") is not None:
            assert tool_version_mismatches(tree), "a ruff differing from the pin was accepted"
        project.write_text('[project.optional-dependencies]\ndev = ["ruff"]\n', encoding="utf-8")
        assert tool_version_mismatches(tree), "a dev extra pinning nothing was accepted"

    # The review gate is driven by questions parsed out of the contract, so
    # both halves of that coupling are replayed against the real document: a
    # phase the prose stops asking anything of, and an anchor whose phrase has
    # been reworded. Each leaves a review that still passes while covering less
    # than it reports, which is the failure the parse was introduced to remove.
    #
    # The contract is copied rather than edited in place. A self-check that
    # mutates a tracked file leaves the repository broken if it is interrupted,
    # and this one deliberately runs failing cases.
    original = (ROOT / "references" / "review.md").read_text(encoding="utf-8")
    assert check_review_phases(ROOT) == [], "the real contract should agree with the coordinator"

    # Emptied of the questions every surface phase shares. That leaves those
    # phases gating on nothing while the anchors, which point only at
    # always-run phases, still resolve: the empty-gate check is the only thing
    # that can catch it, so this case isolates it.
    head, marker, tail = original.partition("## Surface Phases")
    assert marker, "the contract no longer has a surface phase section"
    body, output_marker, rest = tail.partition("## Machine-Readable Output")
    assert output_marker, "the contract no longer has a machine-readable output section"
    emptied = head + marker + re.sub(r"^- .*\n", "", body, flags=re.MULTILINE) + output_marker + rest
    assert emptied != original, "the surface questions were not removed, so the case proves nothing"
    assert check_review_phases(ROOT, contract=emptied), "a phase asking no question was accepted"

    # Reworded so an anchor stops matching. The finding it belongs to would go
    # on being seeded while answering no question, and the run would demand a
    # hand-written answer to something it had already settled.
    reworded = original.replace("no raw shell interpolation", "no unchecked shell interpolation")
    assert reworded != original, "the anchor phrase was not reworded"
    assert check_review_phases(ROOT, contract=reworded), "an anchor that answers nothing was accepted"

    # A rule validate.py can emit but nobody anchored, which is the state this
    # repository was actually in: `frontmatter` and `links` seeded findings
    # that settled no question, so a run reported them and then asked the
    # reviewer to establish the same thing by hand. The rules are read from
    # source, so both directions of the mapping are replayed: a rule with no
    # anchor, and an exemption for a rule nothing emits, which would otherwise
    # sit in the table forever hiding a rule that had been renamed.
    anchors = dict(review.ANSWER_ANCHORS)
    exempt = set(review.UNREACHABLE_RULES)
    rules = conformance_rules()
    assert rules, "no conformance rules were found, so the cases below prove nothing"
    try:
        dropped = f"conformance:{sorted(rules - {name.partition(':')[2] for name in exempt})[0]}"
        assert dropped in review.ANSWER_ANCHORS, dropped
        del review.ANSWER_ANCHORS[dropped]
        assert check_review_phases(ROOT), "a rule seeding findings that answer nothing was accepted"
        review.ANSWER_ANCHORS.update(anchors)
        review.UNREACHABLE_RULES.add("conformance:renamed-away")
        assert check_review_phases(ROOT), "an exemption for a rule nothing emits was accepted"
    finally:
        review.ANSWER_ANCHORS.clear()
        review.ANSWER_ANCHORS.update(anchors)
        review.UNREACHABLE_RULES.clear()
        review.UNREACHABLE_RULES.update(exempt)
    assert check_review_phases(ROOT) == [], "the cases above did not restore the real tables"

    # The registration check exists because a new coordinator and a newly
    # closed schema merge without conflict and produce a tree that cannot run.
    # Both halves are replayed here against a copy of the real contracts, since
    # a check that only ever sees a correct tree proves nothing.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "schemas").mkdir()
        (tree / "scripts").mkdir()
        for name in ("status.schema.json", "state.schema.json"):
            shutil.copy2(ROOT / "schemas" / name, tree / "schemas" / name)
        for name in COORDINATORS:
            shutil.copy2(ROOT / "scripts" / name, tree / "scripts" / name)
        assert check_coordinator_registration(tree) == [], "the real contracts should agree"

        status_path = tree / "schemas" / "status.schema.json"
        status = json.loads(status_path.read_text(encoding="utf-8"))
        dropped = status["properties"]["kind"]["enum"].pop()
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        assert check_coordinator_registration(tree), f"a coordinator missing from the kind enum was accepted: {dropped}"
        status["properties"]["kind"]["enum"].append(dropped)
        status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")

        state_path = tree / "schemas" / "state.schema.json"
        state = json.loads(state_path.read_text(encoding="utf-8"))
        state["properties"].pop("phase")
        state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")
        assert check_coordinator_registration(tree), "an undeclared state key was accepted"

    # A dependency that resolves only transitively is invisible until the
    # package that pulled it in stops doing so, so the check has to reject one.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "scripts").mkdir()
        (tree / "pyproject.toml").write_text(
            '[project]\ndependencies = [\n    "declared~=1.0",\n]\n',
            encoding="utf-8",
        )
        (tree / "scripts" / "guarded.py").write_text(
            "try:\n    import declared\nexcept ModuleNotFoundError:\n    raise SystemExit('install it')\n",
            encoding="utf-8",
        )
        assert check_declared_dependencies(tree) == [], "a declared, guarded import was rejected"
        (tree / "scripts" / "guarded.py").write_text(
            "try:\n    import undeclared\nexcept ModuleNotFoundError:\n    raise SystemExit('install it')\n",
            encoding="utf-8",
        )
        assert check_declared_dependencies(tree), "an undeclared third-party import was accepted"
        (tree / "scripts" / "guarded.py").write_text("import declared\n", encoding="utf-8")
        assert check_declared_dependencies(tree), "an unguarded third-party import was accepted"
        (tree / "scripts" / "guarded.py").write_text("import json\nimport pathlib\n", encoding="utf-8")
        assert check_declared_dependencies(tree) == [], "a stdlib-only module was required to carry a guard"

    # The path contract is only worth stating where a workflow shows a command,
    # so the check must key on that rather than demand the section always.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "workflows").mkdir()
        (tree / "SKILL.md").write_text("# S\n\n## Elsewhere\n\ntext\n", encoding="utf-8")
        assert check_coordinator_paths(tree) == [], "a tree with no dispatching workflow was failed"
        (tree / "workflows" / "w.md").write_text("# W\n\n`python3 scripts/w.py init`\n", encoding="utf-8")
        assert check_coordinator_paths(tree), "a dispatching workflow with no path contract was accepted"
        (tree / "SKILL.md").write_text(
            f"# S\n\n## {COORDINATOR_PATH_SECTION}\n\nRelative to this skill.\n", encoding="utf-8"
        )
        assert check_coordinator_paths(tree) == [], "the stated contract was not recognised"

    # Everything below replays a check against a purpose-built tree. These
    # cases were absent, which meant each of these checks could have its
    # condition inverted with the whole suite still green: the real tree is
    # correct, so a check that always returns [] is indistinguishable from one
    # that works. That is exactly the shape check_checks_are_wired now rejects.
    def guidance(tree, name, body):
        path = tree / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        # A host name is a violation in neutral guidance and unremarkable in
        # vendored upstream material, so both sides are replayed.
        guidance(tree, "references/neutral.md", "# N\n\nRun the coordinator.\n\n## Checks\n\n- one\n")
        assert check_vendor_tokens(tree) == [], "runtime-neutral guidance was rejected"
        guidance(tree, "references/neutral.md", f"# N\n\nOpen {HOST_TOKENS[0]}.\n\n## Checks\n\n- one\n")
        assert check_vendor_tokens(tree), "a host token in a reference was accepted"
        guidance(tree, "references/neutral.md", "# N\n\nRun it.\n\n## Checks\n\n- one\n")
        guidance(tree, "references/upstream/vendored.md", f"# V\n\nFrom {HOST_TOKENS[0]}.\n")
        assert check_vendor_tokens(tree) == [], "vendored upstream material was held to neutrality"
        guidance(tree, "references/upstream/vendored.md", f"# V\n\n{VENDOR_TOKENS[0]}\n")
        assert check_vendor_tokens(tree), "a vendor token was accepted anywhere"

        # The literal list only ever held the hosts someone had already met, so
        # the cases that matter are hosts nobody listed. Each is written the
        # way a document would naturally write it.
        guidance(tree, "references/upstream/vendored.md", "# V\n\nvendored\n")
        for unlisted in ("Store it in `~/.windsurf/config.json`.", "Install into `.aider/skills/`."):
            guidance(tree, "references/neutral.md", f"# N\n\n{unlisted}\n\n## Checks\n\n- one\n")
            assert check_vendor_tokens(tree), f"an unlisted host passed: {unlisted}"
            assert not any(token in unlisted for token in HOST_TOKENS), "the case was caught by name, not by shape"
        # Vendored material describes the host it came from, so the exemption
        # has to cover the shapes as well as the names.
        guidance(tree, "references/neutral.md", "# N\n\nRun it.\n\n## Checks\n\n- one\n")
        guidance(tree, "references/upstream/vendored.md", "# V\n\nSee `~/.windsurf/` and `.aider/skills/`.\n")
        assert check_vendor_tokens(tree) == [], "the upstream exemption stopped covering the path shapes"

    # The shapes are only worth having if they separate a host from the
    # cross-host paths that look identical, which is the whole difficulty:
    # references/settings.md is required to name the XDG directories, and any
    # repository has a .github/ whichever agent reads it.
    assert host_paths("Read `~/.windsurf/settings.json`.") == ["~/.windsurf"], "an unlisted host was not seen"
    assert host_paths('export HOME_DIR="$HOME/.aider"') == ["$HOME/.aider"], "the $HOME spelling was not seen"
    assert host_paths("Default to `~/.config`, then `~/.local/state`.") == [], "the XDG directories were flagged"
    assert host_paths("Source `~/.zshrc` first.") == [], "a shell rc file was called a host"
    assert host_paths("Install into `.windsurf/rules/`.") == [".windsurf/rules"], "an unlisted install path passed"
    assert host_paths("CI lives in `.github/workflows/`.") == [], "a repository convention was called a host"
    # Measured on the corpus: these are the shapes that made the unbounded
    # dot-directory pattern unusable. A skill naming its own state directory,
    # a URL, and a chain of method names all read as `.name/` and none of them
    # is a host, so the second segment is what the pattern keys on.
    assert host_paths("State lives in `.scrum/state/run.db`.") == [], "a skill's own state directory was flagged"
    assert host_paths("Match `drive\\.google\\.com/file/d`.") == [], "a URL host was read as a directory"
    assert host_paths("Modifiers: `.add/subtract/multiply`.") == [], "a chain of method names was read as a path"
    # A host free to call its directory anything is free to call it something
    # short, so the second segment rather than a length floor is what decides.
    assert host_paths("Copy into `.q/prompts/`.") == [".q/prompts"], "a short host directory was let through"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        guidance(tree, "references/a.md", "# A\n\n## One\n\nx\n\n## Two\n\ny\n")
        assert check_duplicate_headings(tree) == [], "distinct sections were called duplicates"
        guidance(tree, "references/a.md", "# A\n\n## One\n\nx\n\n## One\n\ny\n")
        assert check_duplicate_headings(tree), "a repeated H2 was accepted"
        # The rule is about a topic having one home, not about H2 in
        # particular, so the same collision one level down is the same fault.
        guidance(tree, "references/a.md", "# A\n\n## One\n\n### Deep\n\nx\n\n### Deep\n\ny\n")
        assert check_duplicate_headings(tree), "a repeated H3 under one parent was accepted"
        # And the case that decides the scoping: one subsection name reused
        # under separate parents is the positional consistency this repository
        # asks for, and rejecting it would punish the shape it enforces.
        guidance(tree, "references/a.md", "# A\n\n## One\n\n### Deep\n\nx\n\n## Two\n\n### Deep\n\ny\n")
        assert check_duplicate_headings(tree) == [], "a subsection repeated under different parents was rejected"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "scripts").mkdir()
        for name in COORDINATORS:
            (tree / "scripts" / name).write_text("import state\n", encoding="utf-8")
        assert check_shared_runtime(tree) == [], "coordinators composing the lifecycle were rejected"
        (tree / "scripts" / COORDINATORS[0]).write_text(
            f"def {RUNTIME_OWNED[0]}(path):\n    return None\n", encoding="utf-8"
        )
        assert check_shared_runtime(tree), "a coordinator re-growing the run lifecycle was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        rows = "".join(f"| {TICK}{name}{TICK} | why |\n" for name, _, _ in CAPABILITY_PHASES)
        guidance(tree, DESIGN_WORKFLOW, f"# D\n\n| Capability | Why |\n| --- | --- |\n{rows}")
        assert check_capability_rows(tree) == [], "the documented capability set was rejected"
        guidance(
            tree, DESIGN_WORKFLOW, f"# D\n\n| Capability | Why |\n| --- | --- |\n{rows}| {TICK}ghost{TICK} | x |\n"
        )
        assert check_capability_rows(tree), "a documented capability deriving no phase was accepted"
        trimmed = rows.split("\n", 1)[1]
        guidance(tree, DESIGN_WORKFLOW, f"# D\n\n| Capability | Why |\n| --- | --- |\n{trimmed}")
        assert check_capability_rows(tree), "a derived capability with no row was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "workflows").mkdir()
        guidance(tree, "references/reached.md", "# R\n")
        # The workflows are themselves subject to the rule, so SKILL.md links
        # each of them as well as the reference.
        links = "\n".join(f"[{name}]({name})" for name in ENTRY_DOCUMENTS if name != "SKILL.md")
        for name in ENTRY_DOCUMENTS:
            guidance(tree, name, f"# E\n\n[r](references/reached.md)\n\n{links}\n" if name == "SKILL.md" else "# E\n")
        assert check_reachability(tree) == [], "a reference linked from SKILL.md was called unreachable"
        guidance(tree, "references/orphan.md", "# O\n")
        assert check_reachability(tree), "a reference nothing links to was accepted"
        # Filing a document one directory down used to exempt it, so the
        # subtree and its index are both replayed.
        (tree / "references" / "orphan.md").unlink()
        guidance(tree, "references/vendor/README.md", "# V\n\n[one](one.md)\n")
        guidance(tree, "references/vendor/one.md", "# One\n")
        assert check_reachability(tree), "a subtree index nothing links to was accepted"
        guidance(tree, "SKILL.md", "# E\n\n[r](references/reached.md)\n\n[v](references/vendor/README.md)\n\n" + links)
        assert check_reachability(tree) == [], "a file linked from its subtree index was called unreachable"
        guidance(tree, "references/vendor/README.md", "# V\n\nno rows\n")
        assert check_reachability(tree), "a file dropped from its subtree index was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        body = f"# T\n\nOpening.\n\n## Topic\n\nx\n\n## {REFERENCE_CLOSING}\n\n- how\n"
        guidance(tree, "references/a.md", body)
        assert check_reference_skeleton(tree) == [], "a conforming reference was rejected"
        guidance(tree, "references/a.md", body.replace(f"## {REFERENCE_CLOSING}", "## Validation"))
        assert check_reference_skeleton(tree), "a reference closing under another name was accepted"
        guidance(tree, "references/a.md", body + "\n## Afterword\n\nx\n")
        assert check_reference_skeleton(tree), f"a section after '{REFERENCE_CLOSING}' was accepted"
        guidance(tree, "references/a.md", body.replace("# T\n", "", 1))
        assert check_reference_skeleton(tree), "a reference with no title was accepted"
        # The closing section had to exist and not to say anything, so a
        # reference could tell a reader an answer exists and withhold it.
        guidance(tree, "references/a.md", body.replace("- how\n", ""))
        assert check_reference_skeleton(tree), f"an empty '{REFERENCE_CLOSING}' section was accepted"
        guidance(tree, "references/a.md", body.replace("- how\n", "   \n"))
        assert check_reference_skeleton(tree), f"a whitespace-only '{REFERENCE_CLOSING}' section was accepted"
        # A block that renders to no words is the same silent omission. An
        # image is the shape that reaches here as a paragraph carrying an empty
        # string, so it is the case that makes the emptiness test falsifiable
        # rather than a formality the parser had already handled.
        guidance(tree, "references/a.md", body.replace("- how\n", "![diagram](d.png)\n"))
        assert check_reference_skeleton(tree), f"a wordless '{REFERENCE_CLOSING}' section was accepted"
        guidance(tree, "references/a.md", body.replace("- how\n", "- ![diagram](d.png)\n"))
        assert check_reference_skeleton(tree), f"a wordless '{REFERENCE_CLOSING}' bullet was accepted"
        # Prose says as much as a list here, so the check must not demand one
        # shape over the other.
        guidance(tree, "references/a.md", body.replace("- how\n", "The coordinator reports it.\n"))
        assert check_reference_skeleton(tree) == [], f"a prose '{REFERENCE_CLOSING}' section was rejected"
        # structure.md puts an opening paragraph between the title and the
        # first section. A reference jumping straight into an H2 gives a reader
        # deciding whether they are in the right document nothing to decide on.
        guidance(tree, "references/a.md", body.replace("Opening.\n\n", ""))
        assert check_reference_skeleton(tree), "a reference with no opening paragraph was accepted"
        # A bullet is not that paragraph: it elaborates something, and the
        # position exists to say what the document owns before elaborating.
        guidance(tree, "references/a.md", body.replace("Opening.\n", "- a bullet\n"))
        assert check_reference_skeleton(tree), "a leading bullet was accepted as the opening paragraph"
        # Nor is a banner image: it occupies the position without saying what
        # the document owns, which is the whole point of the position.
        guidance(tree, "references/a.md", body.replace("Opening.\n", "![banner](b.png)\n"))
        assert check_reference_skeleton(tree), "a wordless opening block was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "schemas").mkdir()
        schema = tree / "schemas" / "a.schema.json"
        valid = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
        schema.write_text(json.dumps(valid), encoding="utf-8")
        assert check_schema_keywords(tree) == [], "a schema using only real keywords was rejected"
        schema.write_text(json.dumps({**valid, "requred": ["a"]}), encoding="utf-8")
        assert check_schema_keywords(tree), "a misspelled keyword was accepted as an annotation"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "scripts").mkdir()
        guidance(tree, "SKILL.md", f"---\nname: s\nlicense: {SKILL_LICENCE}\n---\n\n# S\n")
        header = f"#!/usr/bin/env python3\n# {SPDX_TAG} {CODE_LICENCE}\n"
        (tree / "scripts" / "a.py").write_text(header, encoding="utf-8")
        assert check_licence_headers(tree) == [], "a correctly headed script was rejected"
        (tree / "scripts" / "a.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        assert check_licence_headers(tree), "a script with no licence header was accepted"
        (tree / "scripts" / "a.py").write_text(f"# {SPDX_TAG} Apache-2.0\n", encoding="utf-8")
        assert check_licence_headers(tree), "a script naming the wrong licence was accepted"
        (tree / "scripts" / "a.py").write_text(header, encoding="utf-8")
        # The suffix allowlist was `.py` and `.sh`, so these three shipped
        # outside the licence boundary and the check reported green. Each is a
        # plausible addition under scripts/ and each carries a different comment
        # leader, which is why the tag is no longer required to start with `#`.
        untagged = {
            "bootstrap.js": "console.log(1);\n",
            "tool.toml": "[tool]\nname = 'x'\n",
            "job.yml": "on: push\n",
        }
        for name, body in untagged.items():
            (tree / "scripts" / name).write_text(body, encoding="utf-8")
            assert check_licence_headers(tree), f"an untagged {name} was accepted"
            (tree / "scripts" / name).unlink()
        (tree / "scripts" / "bootstrap.js").write_text(f"// {SPDX_TAG} {CODE_LICENCE}\n", encoding="utf-8")
        assert check_licence_headers(tree) == [], "a tag behind a // leader was rejected"
        (tree / "scripts" / "page.html").write_text(f"<!-- {SPDX_TAG} {CODE_LICENCE} -->\n", encoding="utf-8")
        assert check_licence_headers(tree) == [], "a tag inside a markup comment was rejected"
        (tree / "scripts" / "page.html").write_text(f"<!-- {SPDX_TAG} Apache-2.0 -->\n", encoding="utf-8")
        assert check_licence_headers(tree), "a markup comment naming the wrong licence was accepted"
        (tree / "scripts" / "page.html").unlink()
        (tree / "scripts" / "bootstrap.js").unlink()
        guidance(tree, "SKILL.md", "---\nname: s\nlicense: MIT\n---\n\n# S\n")
        assert check_licence_headers(tree), "the wrong skill licence was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "schemas" / "vendor").mkdir(parents=True)
        name, digest = next(iter(VENDORED_SCHEMAS.items()))
        vendored = tree / "schemas" / "vendor" / name
        shutil.copy2(ROOT / "schemas" / "vendor" / name, vendored)
        assert check_vendored_schemas(tree) == [], "the published schema did not match its recorded digest"
        vendored.write_bytes(vendored.read_bytes() + b"\n")
        assert check_vendored_schemas(tree), f"an edited vendored schema was accepted against {digest[:8]}"
        vendored.unlink()
        assert check_vendored_schemas(tree), "a missing vendored schema was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "workflows").mkdir()
        (tree / "scripts").mkdir()
        (tree / "scripts" / "w.py").write_text("x = 1\n", encoding="utf-8")
        guidance(tree, "workflows/w.md", "# W\n\nRun `python3 scripts/w.py init`.\n")
        assert check_workflow_dispatch(tree) == [], "a workflow naming a real coordinator was rejected"
        guidance(tree, "workflows/w.md", "# W\n\nDo it by hand.\n")
        assert check_workflow_dispatch(tree), "a workflow holding control in prose was accepted"
        guidance(tree, "workflows/w.md", "# W\n\nRun `python3 scripts/ghost.py init`.\n")
        assert check_workflow_dispatch(tree), "a workflow dispatching to a missing coordinator was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "workflows").mkdir()
        scoped = f"# A\n\n## {WORKFLOW_SCOPE_SECTION}\n\nFor A. For B see [b.md](b.md).\n"
        guidance(tree, "workflows/a.md", scoped)
        guidance(tree, "workflows/b.md", f"# B\n\n## {WORKFLOW_SCOPE_SECTION}\n\nFor B. For A see [a.md](a.md).\n")
        assert check_workflow_boundaries(tree) == [], "workflows scoping each other were rejected"
        guidance(tree, "workflows/a.md", "# A\n\n## Steps\n\nFor B see [b.md](b.md).\n")
        assert check_workflow_boundaries(tree), "a workflow with no scope section was accepted"
        guidance(tree, "workflows/a.md", f"# A\n\n## {WORKFLOW_SCOPE_SECTION}\n\nAlways.\n\n## Body\n\n[b](b.md)\n")
        assert check_workflow_boundaries(tree), "a sibling link outside the scope section was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "workflows").mkdir()
        # Describing the coordinator is the whole point of a workflow document,
        # and every one of these sentences appears in shape in this repository.
        # A check that cannot tell them from an order is one that gets
        # satisfied by deleting true statements.
        described = (
            "# W\n\n"
            "The coordinator retries up to three times before returning a terminal result.\n\n"
            "`--max-iterations` is the hard bound, defaulting to five.\n\n"
            "Failed validation returns to merge until the configured attempt bound.\n\n"
            "- Retry bound reached, returning a terminal result rather than looping.\n\n"
            "A resumed run reaches its phase through recorded state, not by counting.\n\n"
            # These two carry the exact words an order would, mid-sentence and
            # behind a subject. They are what separates this check from the
            # vocabulary scan it replaced: that scan fired on both, and both
            # are true statements about a coordinator.
            "Validation fails when the run may retry up to three times without recording why.\n\n"
            "Whether a drifted plan must return to phase 2 is the coordinator's decision.\n\n"
            "## Iterate\n\n"
            "Each iteration triages every open obligation, twice over if the fixer asks.\n\n"
            "```bash\nfor attempt in 1 2 3; do retry; done\n```\n"
        )
        guidance(tree, "workflows/w.md", described)
        assert check_prose_control_flow(tree) == [], check_prose_control_flow(tree)
        guidance(tree, "workflows/w.md", described + "\nRetry up to three times.\n")
        assert check_prose_control_flow(tree), "a prose retry bound was accepted"
        guidance(tree, "workflows/w.md", described + "\nIf the reviewer disagrees, loop back to phase 2.\n")
        assert check_prose_control_flow(tree), "a prose jump to another phase was accepted"
        # A bound inside a fence is an example of a coordinator, not an order,
        # and a heading is a label rather than a sentence. Both matched the
        # line scan this check replaced.
        guidance(tree, "workflows/w.md", "# W\n\n## Retry twice\n\n```bash\nretry at most three times\n```\n")
        assert check_prose_control_flow(tree) == [], "a fenced or heading bound was reported as prose"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "examples").mkdir()
        example = tree / "examples" / "a.json"
        example.write_text('{"not": "stamped"}', encoding="utf-8")
        assert check_examples_validate(tree) == [], "an unstamped settings fixture was validated"
        example.write_text('{"schema": "ghost.schema.json"}', encoding="utf-8")
        assert check_examples_validate(tree), "an example claiming an unknown schema was accepted"
        example.write_text("{not json", encoding="utf-8")
        assert check_examples_validate(tree), "an unparseable example was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "scripts").mkdir()
        (tree / "schemas").mkdir()
        guidance(tree, ARTIFACT_REFERENCE, "# A\n\nThe run writes `a.schema.json`.\n")
        closed = {"type": "object", "properties": {"a": {"type": "string"}}, "additionalProperties": False}
        (tree / "schemas" / "a.schema.json").write_text(json.dumps(closed), encoding="utf-8")
        (tree / "scripts" / "w.py").write_text('SCHEMA = "a.schema.json"\n', encoding="utf-8")
        assert check_schema_coverage(tree) == [], "a documented, used, closed schema was rejected"
        (tree / "scripts" / "w.py").write_text("x = 1\n", encoding="utf-8")
        assert check_schema_coverage(tree), "a schema no script writes against was accepted"
        # The substring form of this check counted a mention in a comment or a
        # docstring as use, so the sentence saying nothing writes the schema
        # was itself the proof that something did.
        (tree / "scripts" / "w.py").write_text("# a.schema.json is written by nothing.\n", encoding="utf-8")
        assert check_schema_coverage(tree), "a schema named only in a comment was accepted as used"
        (tree / "scripts" / "w.py").write_text('"""Nothing writes a.schema.json."""\n', encoding="utf-8")
        assert check_schema_coverage(tree), "a schema named only in a docstring was accepted as used"
        # A schema reached only through another schema's $ref is in use, and no
        # script will ever name it. This replaced an exemption list, so both
        # sides are proved: reachable passes, and unreachable still fails.
        (tree / "scripts" / "w.py").write_text('SCHEMA = "a.schema.json"\n', encoding="utf-8")
        shared = {"$defs": {"text": {"type": "string"}}}
        (tree / "schemas" / "shared.schema.json").write_text(json.dumps(shared), encoding="utf-8")
        guidance(tree, ARTIFACT_REFERENCE, "# A\n\nThe run writes `a.schema.json` using `shared.schema.json`.\n")
        assert check_schema_coverage(tree), "a schema nothing references was accepted"
        (tree / "schemas" / "a.schema.json").write_text(
            json.dumps({**closed, "properties": {"a": {"$ref": "shared.schema.json#/$defs/text"}}}),
            encoding="utf-8",
        )
        assert check_schema_coverage(tree) == [], "a schema reached only by $ref was reported unused"
        (tree / "scripts" / "w.py").write_text('SCHEMA = "a.schema.json"\n', encoding="utf-8")
        guidance(tree, ARTIFACT_REFERENCE, "# A\n\nNothing.\n")
        assert check_schema_coverage(tree), "an undocumented schema was accepted"
        guidance(tree, ARTIFACT_REFERENCE, "# A\n\nThe run writes `a.schema.json`.\n")
        (tree / "schemas" / "a.schema.json").write_text(
            json.dumps({key: value for key, value in closed.items() if key != "additionalProperties"}),
            encoding="utf-8",
        )
        assert check_schema_coverage(tree), "a schema root accepting undeclared keys was accepted"

    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "references").mkdir()
        (tree / "references" / "a.md").write_text("# A\n", encoding="utf-8")
        guidance(tree, README, f"# R\n\n## {README_SECTION}\n\n- {TICK}references/a.md{TICK} — a\n")
        assert check_readme_structure(tree) == [], "a listed, present resource was rejected"
        (tree / "references" / "b.md").write_text("# B\n", encoding="utf-8")
        assert check_readme_structure(tree), "an unlisted shipped resource was accepted"
        (tree / "references" / "b.md").unlink()
        guidance(tree, README, f"# R\n\n## {README_SECTION}\n\n- {TICK}references/gone.md{TICK} — g\n")
        assert check_readme_structure(tree), "a listed but absent resource was accepted"
        guidance(tree, README, "# R\n\n## Elsewhere\n\ntext\n")
        assert check_readme_structure(tree), f"a README with no '{README_SECTION}' section was accepted"

    # The remaining checks delegate to a tool that owns the answer. Asserting
    # only that a missing tool is a skip was the previous bar, and it left all
    # four indistinguishable from a stub: against a tree that already passes,
    # a working delegation and an empty result agree. What each case adds is a
    # fixture the tool must reject, so the wiring is observed carrying a real
    # verdict back rather than merely being present.
    assert check_lint(ROOT) == [] or shutil.which("ruff"), "lint reported failures with no ruff installed"
    assert check_format(ROOT) == [] or shutil.which("ruff"), "format reported failures with no ruff installed"
    if shutil.which("ruff"):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / "scripts").mkdir()
            # An unused import is a lint error and not a formatting one; the
            # spacing is a formatting error and not a lint one. Keeping them
            # in separate files stops either case from passing on the other's
            # finding.
            (tree / "scripts" / "unlinted.py").write_text("import os\n", encoding="utf-8")
            assert check_lint(tree), "ruff accepted an unused import"
            (tree / "scripts" / "unlinted.py").unlink()
            (tree / "scripts" / "unformatted.py").write_text("x = {  'a' :1}\n", encoding="utf-8")
            assert check_format(tree), "ruff accepted misformatted source"

    assert check_schema_lint(ROOT) == [] or shutil.which("check-jsonschema")
    if shutil.which("check-jsonschema"):
        with tempfile.TemporaryDirectory() as directory:
            tree = Path(directory)
            (tree / "schemas").mkdir()
            assert check_schema_lint(tree), "a schemas directory with no schemas was accepted"
            # Valid JSON, invalid schema: `type` takes a string or a list of
            # them, so this is exactly the fault jsonschema would not report
            # when validating an instance, which is why the metaschema pass
            # exists.
            (tree / "schemas" / "broken.schema.json").write_text('{"type": 7}', encoding="utf-8")
            assert check_schema_lint(tree), "check-jsonschema accepted an invalid schema"

    assert os.environ.get("CHECK_EXTERNAL_LINKS") == "1" or check_external_links(ROOT) == []
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        shutil.copy(ROOT / "lychee.toml", tree / "lychee.toml")
        # A port nothing listens on fails without reaching the network, so the
        # case is deterministic and offline while still exercising the path
        # where lychee exits nonzero and this function must report something.
        (tree / "rotted.md").write_text("[gone](http://127.0.0.1:9/missing)\n", encoding="utf-8")
        previous = os.environ.get("CHECK_EXTERNAL_LINKS")
        os.environ["CHECK_EXTERNAL_LINKS"] = "1"
        try:
            reported = check_external_links(tree)
        finally:
            if previous is None:
                del os.environ["CHECK_EXTERNAL_LINKS"]
            else:
                os.environ["CHECK_EXTERNAL_LINKS"] = previous
        assert reported, "an unreachable URL was accepted, or a nonzero lychee exit reported nothing"

    assert check_executable_bits(ROOT) == [], "the shipped tree disagrees with git about executable bits"
    # Git owns the mode, so the case needs a repository rather than a
    # directory. Both directions of the disagreement are replayed, since the
    # check reports each with a different message and an implementation
    # covering only one would still pass a single-sided case.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)

        def git(*arguments):
            return subprocess.run(["git", *arguments], cwd=str(tree), capture_output=True, text=True, check=True)

        git("init", "--quiet")
        (tree / "runnable.py").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
        (tree / "plain.py").write_text("value = 1\n", encoding="utf-8")
        git("add", "-A")
        assert check_executable_bits(tree), "a shebang with no executable bit was accepted"
        git("update-index", "--chmod=+x", "runnable.py")
        assert check_executable_bits(tree) == [], "an agreeing pair was rejected"
        git("update-index", "--chmod=+x", "plain.py")
        assert check_executable_bits(tree), "an executable bit with no shebang was accepted"
    # The old form of this check substring-matched --help, so a coordinator
    # that renamed a verb and mentioned the old name in its description passed.
    # A stand-in parser replays exactly that.
    assert check_coordinator_verbs(ROOT) == [], "a coordinator stopped exposing the core verbs"

    class Renamed:
        __name__ = "renamed"

        @staticmethod
        def parser():
            root = argparse.ArgumentParser(description=f"Runs {' '.join(CORE_VERBS)} for you.")
            commands = root.add_subparsers(dest="command", required=True)
            for verb in CORE_VERBS:
                commands.add_parser("begin" if verb == "init" else verb)
            return root

    assert declared_verbs(Renamed) == set(CORE_VERBS) - {"init"} | {"begin"}
    assert "init" in Renamed.parser().format_help(), "the case does not reproduce the substring hole"
    # Reading declared_verbs is not enough on its own: it proves the helper
    # while leaving the check that consumes it unobserved. Passing the
    # stand-in through the check is what ties the two together.
    assert check_coordinator_verbs(ROOT, modules=(Renamed,)), "a coordinator missing a core verb was accepted"

    assert check_phase_owners(ROOT) == [], "a derived phase lost its owning contract"
    # Each way a phase can lose its contract is replayed separately, since the
    # check reports them with different messages and an implementation
    # covering one would pass a case that only exercised another.
    assert check_phase_owners(ROOT, coordinators=[("stub", ["one"], lambda _: DESIGN_WORKFLOW)]), (
        "a phase owned by the document that dispatched it was accepted"
    )
    assert check_phase_owners(ROOT, coordinators=[("stub", ["one"], lambda _: "references/absent.md")]), (
        "a phase owned by a file that does not exist was accepted"
    )
    assert check_phase_owners(
        ROOT, coordinators=[("stub", ["one"], lambda _: f"{ARTIFACT_REFERENCE}#no-such-heading")]
    ), "a phase owned by a heading that does not exist was accepted"
    assert check_phase_owners(ROOT, coordinators=[("stub", ["one", "two"], lambda _: ARTIFACT_REFERENCE)]), (
        "two phases sharing one owner were accepted"
    )
    assert check_phase_owners(ROOT, coordinators=[("stub", ["one"], lambda _: ARTIFACT_REFERENCE)]) == [], (
        "a phase with a distinct existing owner was rejected"
    )

    # check_skill is the one check registered_checks exempts, because the
    # bounds belong to validate.py and restating them here is the duplication
    # that let the old copy drift. What is left for this file to prove is that
    # it reports what the validator returns and that the strict frontmatter
    # parse it keeps locally is reached, so neither half can quietly go empty.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / "SKILL.md").write_text(
            "---\nname: workflow-skills\ndescription: " + "x" * 2000 + "\n---\n\n# S\n",
            encoding="utf-8",
        )
        assert check_skill(tree), "a description past the format bound was accepted"
        (tree / "SKILL.md").write_text("---\nname: [unclosed\n---\n\n# S\n", encoding="utf-8")
        assert any("invalid frontmatter" in failure for failure in check_skill(tree)), (
            "malformed frontmatter was not reported; validate.py reads a flat subset and cannot see it"
        )

    print("self-check passed")


def main():
    parser = argparse.ArgumentParser(description="Run every deterministic repository check.")
    parser.add_argument("--self-check", action="store_true", help="verify checker logic and exit")
    if parser.parse_args().self_check:
        self_check()
        return
    checks = (
        ("filenames", lambda: run_script(ROOT, "names.py", str(ROOT))),
        *discovered_self_checks(ROOT),
        ("single version source", lambda: check_single_version_source(ROOT)),
        ("single entrypoint", lambda: check_single_entrypoint(ROOT)),
        ("checks are wired", lambda: check_checks_are_wired(ROOT)),
        ("self-checks assert", lambda: self_checks_assert_something(ROOT)),
        # The last rung of the same ladder. `checks are wired` requires every
        # check to be named in a self-check, `self-checks assert` requires the
        # assertions to be falsifiable, and this requires the pair to actually
        # constrain the check: gut it, and its own case must notice.
        ("mutation sweep", lambda: run_script(ROOT, "mutate.py", str(ROOT))),
        ("CI tests the floor", lambda: check_ci_floor(ROOT)),
        ("tools match their pins", lambda: tool_version_mismatches(ROOT)),
        ("dependencies declared", lambda: check_declared_dependencies(ROOT)),
        ("coordinator paths resolve", lambda: check_coordinator_paths(ROOT)),
        ("skill contract", lambda: check_skill(ROOT)),
        ("links and anchors", lambda: document.broken_links(ROOT)),
        ("resource reachability", lambda: check_reachability(ROOT)),
        ("canonical sections", lambda: check_duplicate_headings(ROOT)),
        ("coordinator verbs", lambda: check_coordinator_verbs(ROOT)),
        ("coordinator registration", lambda: check_coordinator_registration(ROOT)),
        ("shared runtime", lambda: check_shared_runtime(ROOT)),
        ("reference skeleton", lambda: check_reference_skeleton(ROOT)),
        ("heading code markers", lambda: check_heading_code_markers(ROOT)),
        ("workflow dispatch", lambda: check_workflow_dispatch(ROOT)),
        ("workflow boundaries", lambda: check_workflow_boundaries(ROOT)),
        ("prose control flow", lambda: check_prose_control_flow(ROOT)),
        ("examples validate", lambda: check_examples_validate(ROOT)),
        ("phase owners", lambda: check_phase_owners(ROOT)),
        ("documented capabilities", lambda: check_capability_rows(ROOT)),
        ("documented review phases", lambda: check_review_phases(ROOT)),
        ("README structure coverage", lambda: check_readme_structure(ROOT)),
        ("executable bits", lambda: check_executable_bits(ROOT)),
        ("runtime-neutral tokens", lambda: check_vendor_tokens(ROOT)),
        ("licence headers", lambda: check_licence_headers(ROOT)),
        ("schema coverage", lambda: check_schema_coverage(ROOT)),
        ("schema lint", lambda: check_schema_lint(ROOT)),
        ("schema keywords", lambda: check_schema_keywords(ROOT)),
        ("vendored schemas", lambda: check_vendored_schemas(ROOT)),
        ("python lint", lambda: check_lint(ROOT)),
        ("python format", lambda: check_format(ROOT)),
        ("external links", lambda: check_external_links(ROOT)),
    )
    failures = []
    for name, run in checks:
        found = run()
        print(f"{'FAIL' if found else 'ok  '} {name}")
        failures.extend(found)
    for failure in failures:
        print(f"  {failure}")
    if failures:
        raise SystemExit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
