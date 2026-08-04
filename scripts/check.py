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

ROOT = Path(__file__).resolve().parent.parent
TICK = chr(96)
SKILL_LINE_BUDGET = 500
# Fixed by the Agent Skills format: https://agentskills.io/specification
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 1024
COMPATIBILITY_LIMIT = 500
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
REQUIRED_FRONTMATTER = ("name", "description")
VENDOR_TOKENS = ("{baseDir}", "quick_validate", "approved_plan_sha256")
# Host names, which the token list previously omitted: it held only three
# legacy strings, so guidance could name a specific runtime and pass. These are
# checked only where neutrality is the rule. Quoting a host in the README, in
# vendored upstream material, or inside an installed third-party skill is not a
# neutrality violation, and scanning those would make the check unusable.
HOST_TOKENS = ("Claude Code", "~/.claude", "CLAUDE.md", ".cursor", "Cursor", "Copilot")
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
# Run-lifecycle functions state.py owns. A coordinator defining one of these
# has forked the lifecycle rather than composed it.
RUNTIME_OWNED = ("load_run", "open_run", "create_run", "current_phase", "pending_phase")
README_SECTION = "Structure"
# Where SKILL.md owns what a workflow's `scripts/<name>.py` resolves against.
COORDINATOR_PATH_SECTION = "Running a Coordinator"
ARTIFACT_REFERENCE = "references/artifacts.md"
# common holds shared definitions and skill is reached through inventory, so
# neither is named directly by a coordinator.
SCHEMA_INDIRECT = {"common.schema.json"}
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
SKILL_LICENCE = "CC-BY-SA-4.0 AND MIT"
DOCUMENTED_DIRECTORIES = ("references", "workflows", "scripts", "agents", "examples")
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
    parsed = document.parse(root / "SKILL.md")
    if parsed.frontmatter_error:
        failures.append(f"SKILL.md: invalid frontmatter: {parsed.frontmatter_error}")
    elif parsed.frontmatter is None:
        failures.append("SKILL.md: missing frontmatter block")
    else:
        for key in REQUIRED_FRONTMATTER:
            value = parsed.frontmatter.get(key)
            if not isinstance(value, str) or not value.strip():
                failures.append(f"SKILL.md: frontmatter missing non-empty {key}")
        failures.extend(frontmatter_limit_failures(parsed.frontmatter))
    if parsed.line_count > SKILL_LINE_BUDGET:
        failures.append(f"SKILL.md: {parsed.line_count} lines exceeds budget {SKILL_LINE_BUDGET}")
    return failures


def frontmatter_limit_failures(frontmatter):
    """Bounds the Agent Skills format fixes for every host."""
    failures = []
    name = frontmatter.get("name")
    if isinstance(name, str) and name.strip():
        if len(name) > NAME_LIMIT:
            failures.append(f"SKILL.md: name is {len(name)} characters, over the {NAME_LIMIT} limit")
        if not SKILL_NAME.fullmatch(name):
            failures.append(f"SKILL.md: name {name!r} must be lowercase letters, digits, and inner hyphens")
    for key, limit in (("description", DESCRIPTION_LIMIT), ("compatibility", COMPATIBILITY_LIMIT)):
        value = frontmatter.get(key)
        if isinstance(value, str) and len(value) > limit:
            failures.append(f"SKILL.md: {key} is {len(value)} characters, over the {limit} limit")
    return failures


def check_vendor_tokens(root):
    """Core guidance stays runtime-neutral; host syntax belongs in adapters."""
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
    return failures


def check_duplicate_headings(root):
    """One canonical home per topic: reject a repeated H2 within one document."""
    failures = []
    for parsed in document.walk(root):
        seen = set()
        for heading in parsed.headings_at(2):
            if heading.text in seen:
                failures.append(f"{parsed.path.relative_to(root)}:{heading.line}: duplicate section {heading.text!r}")
            seen.add(heading.text)
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


def check_coordinator_verbs(root):
    """The three coordinators must drive a run with the same commands.

    An author who learns one coordinator should be able to drive the others, and
    a generic wrapper should be able to advance any run without knowing which
    coordinator it holds. Two grammars for one state machine make both
    impossible, and the divergence is invisible until someone tries.
    """
    failures = []
    for name in COORDINATORS:
        result = subprocess.run(
            [sys.executable, str(root / "scripts" / name), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            failures.append(f"scripts/{name}: --help failed")
            continue
        missing = [verb for verb in CORE_VERBS if verb not in result.stdout]
        if missing:
            failures.append(f"scripts/{name}: does not expose {', '.join(missing)}")
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


def check_phase_owners(root):
    """Every derived phase must resolve to a distinct owning contract that exists.

    A phase whose resource is the document that dispatched the coordinator
    answers "what do I read now?" with "the file you came from". Requiring a
    distinct existing owner is a stronger guarantee than scanning prose for
    phase names, and it fails the moment a phase is added without a contract.
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
    coordinators = (
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


def check_review_phases(root):
    """Every designable capability must be reviewable, and every review phase documented.

    review.py imports its surfaces from design.py, so the vocabularies cannot
    drift in code. This check covers the prose side: an always-run review phase
    added without explanation would otherwise pass silently.
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
    return failures


def check_reachability(root):
    """Every reference and workflow must be linked from an entry document."""
    failures = []
    linked = set()
    for name in ENTRY_DOCUMENTS:
        parsed = document.parse(root / name)
        for link in parsed.links:
            if link.external or not link.path:
                continue
            resolved = (parsed.path.parent / link.path).resolve()
            if resolved.exists():
                linked.add(resolved)
    for directory in ("references", "workflows"):
        for path in sorted((root / directory).glob("*.md")):
            if path.resolve() not in linked:
                failures.append(f"{path.relative_to(root)}: not linked from SKILL.md or any workflow")
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
    """
    failures = []
    for path in sorted((root / "references").glob("*.md")):
        parsed = document.parse(path)
        name = path.relative_to(root)
        titles = [heading.text for heading in parsed.headings_at(2)]
        if not parsed.headings_at(1):
            failures.append(f"{name}: no title heading")
        if REFERENCE_CLOSING not in titles:
            near = [title for title in titles if "check" in title.lower() or "test" in title.lower()]
            hint = f"; found {near[0]!r}" if near else ""
            failures.append(f"{name}: no '## {REFERENCE_CLOSING}' section{hint}")
        elif titles[-1] != REFERENCE_CLOSING:
            failures.append(f"{name}: '{REFERENCE_CLOSING}' must be last, found {titles[-1]!r} after it")
    return failures


def check_readme_structure(root):
    """Every shipped resource must appear in the README structure list.

    The list is the only human map of the repository, so an unlisted file is a
    resource a reader cannot find and a listed-but-absent file is a dead map
    entry. Both were true before this check existed.
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
        if len(parts) > 1 and parts[0] not in DOCUMENTED_DIRECTORIES:
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
    return [line.strip() for line in result.stdout.splitlines() if "[ERROR]" in line or "[404]" in line]


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


def check_schema_coverage(root):
    """Every schema must be documented, reachable, and actually used.

    A schema nothing writes against is a contract with no party to it, and a
    schema no document names cannot be found by the agent that has to satisfy
    it. Both failures look like a healthy directory listing.
    """
    failures = []
    schemas = sorted(path.name for path in (root / "schemas").glob("*.schema.json"))
    if not schemas:
        return ["schemas/: no schema files found"]
    sources = "\n".join(path.read_text(encoding="utf-8") for path in sorted((root / "scripts").glob("*.py")))
    contract = (root / ARTIFACT_REFERENCE).read_text(encoding="utf-8")
    for name in schemas:
        if name not in contract:
            failures.append(f"{ARTIFACT_REFERENCE}: does not document {name}")
        # common holds shared definitions and skill is referenced by inventory,
        # so neither is named directly by a coordinator.
        if name not in sources and name not in SCHEMA_INDIRECT:
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
    """
    failures = []
    for path in sorted((root / "scripts").rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".sh"}:
            continue
        head = path.read_text(encoding="utf-8").splitlines()[:5]
        if not any(line.startswith(f"# {SPDX_TAG}") for line in head):
            failures.append(f"{path.relative_to(root)}: missing '# {SPDX_TAG}' header")
        elif not any(line == f"# {SPDX_TAG} {CODE_LICENCE}" for line in head):
            failures.append(f"{path.relative_to(root)}: {SPDX_TAG} must be {CODE_LICENCE}")
    declared = document.parse(root / "SKILL.md").frontmatter or {}
    if declared.get("license") != SKILL_LICENCE:
        failures.append(f"SKILL.md: frontmatter license must be {SKILL_LICENCE!r}")
    return failures


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
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    block = re.search(r"^dependencies\s*=\s*\[(.*?)\]", text, re.S | re.M)
    if block is None:
        return ["pyproject.toml declares no dependencies table"]
    # Distribution names normalise to import names loosely, so compare on the
    # PEP 503 form of both rather than requiring them to match character for
    # character: `PyYAML` is imported as `yaml`, `markdown-it-py` as
    # `markdown_it`. Anything not resolved by normalisation is declared here.
    declared = {re.sub(r"[-_.]+", "-", name).lower() for name in re.findall(r'"([A-Za-z0-9_.-]+)', block.group(1))}
    aliases = {"yaml": "pyyaml", "markdown_it": "markdown-it-py", "mdit_py_plugins": "mdit-py-plugins"}
    failures = []
    for path in sorted((root / "scripts").glob("*.py")):
        imports = third_party_imports(path)
        for module in sorted(imports):
            distribution = aliases.get(module, re.sub(r"[-_.]+", "-", module).lower())
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
    text = (root / "pyproject.toml").read_text(encoding="utf-8")
    extra = re.search(r"dev\s*=\s*\[(.*?)\]", text, re.S)
    if extra is None:
        return ["pyproject.toml declares no dev extra; the tool versions are unbounded"]
    failures = []
    pinned = re.findall(r'"([A-Za-z0-9_.-]+)\s*[=~]=\s*([0-9]+)\.([0-9]+)', extra.group(1))
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
    declared = re.search(
        r"""requires-python\s*=\s*["'][>=~^\s]*([0-9.]+)""",
        pyproject.read_text(encoding="utf-8"),
    )
    matrix = re.search(
        r"""python-version:\s*\[([^\]]+)\]""",
        workflow.read_text(encoding="utf-8"),
    )
    if not declared or not matrix:
        return ["could not read the Python floor from pyproject.toml or the CI matrix"]
    versions = [entry.strip().strip("\"'") for entry in matrix.group(1).split(",")]
    if versions[0] != declared.group(1):
        return [
            (
                f"checks.yml tests {versions[0]} first but pyproject.toml declares "
                f">={declared.group(1)}; the declared floor would go untested"
            )
        ]
    return []


def self_checks_assert_something(root):
    """Require each self-check to contain assertions, not just the token.

    run_script demands the script print "self-check passed", which catches a
    self-check that stays silent. It does not catch one that prints the line
    and checks nothing: a stub whose whole body is that print passes the suite
    while proving nothing about the script it belongs to.

    Assertions are the structural difference between the two, so they are what
    is counted. The bar is deliberately low; the point is that zero is a
    mistake, not that any particular number is enough.
    """
    failures = []
    for path in sorted((root / "scripts").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        functions = [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and "self_check" in node.name]
        if not functions:
            failures.append(f"scripts/{path.name}: no self-check function")
            continue
        asserts = sum(1 for function in functions for node in ast.walk(function) if isinstance(node, ast.Assert))
        if not asserts:
            failures.append(
                f"scripts/{path.name}: self-check contains no assertions; printing the line is not checking"
            )
    return failures


def self_check():
    """Verify the checks that carry their own logic actually reject bad input.

    Most checks here delegate to a script that self-checks, or assert a fact
    about the repository that is visible when it breaks. The frontmatter bounds
    are different: while this repository stays well inside them, a check that
    silently stopped rejecting anything would look identical to a passing one.
    """
    valid = {"name": "ok-skill", "description": "d", "compatibility": "c" * COMPATIBILITY_LIMIT}
    assert frontmatter_limit_failures(valid) == []
    assert frontmatter_limit_failures({"name": "ok", "description": "d" * DESCRIPTION_LIMIT}) == []
    rejected = (
        {"name": "x" * (NAME_LIMIT + 1), "description": "d"},
        {"name": "Bad_Name", "description": "d"},
        {"name": "-leading", "description": "d"},
        {"name": "trailing-", "description": "d"},
        {"name": "ok", "description": "d" * (DESCRIPTION_LIMIT + 1)},
        {"name": "ok", "description": "d", "compatibility": "c" * (COMPATIBILITY_LIMIT + 1)},
    )
    for frontmatter in rejected:
        assert frontmatter_limit_failures(frontmatter), frontmatter

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
        assert self_checks_assert_something(Path(directory)) == []
        (scripts / "impostor.py").write_text("x = 1\n", encoding="utf-8")
        assert self_checks_assert_something(Path(directory)), "a script with no self-check was accepted"

    # The floor check compares two files no other check reads together, so a
    # version drift between them would otherwise look like a green run.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        (tree / ".github" / "workflows").mkdir(parents=True)
        project = tree / "pyproject.toml"
        matrix = tree / ".github" / "workflows" / "checks.yml"
        project.write_text('requires-python = ">=3.10"\n', encoding="utf-8")
        matrix.write_text('        python-version: ["3.10", "3.13"]\n', encoding="utf-8")
        assert check_ci_floor(tree) == []
        project.write_text('requires-python = ">=3.11"\n', encoding="utf-8")
        assert check_ci_floor(tree), "a CI matrix below the declared floor was accepted"
        matrix.write_text('        python-version: ["3.11"]\n', encoding="utf-8")
        assert check_ci_floor(tree) == []

        # The pin check must notice a version that differs from the pin, and a
        # dev extra that pins nothing at all; both leave the rule set as
        # whatever the machine happens to have.
        project.write_text('dev = ["ruff==0.1.*"]\n', encoding="utf-8")
        if shutil.which("ruff") is not None:
            assert tool_version_mismatches(tree), "a ruff differing from the pin was accepted"
        project.write_text('dev = ["ruff"]\n', encoding="utf-8")
        assert tool_version_mismatches(tree), "a dev extra pinning nothing was accepted"

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
        (tree / "pyproject.toml").write_text('dependencies = [\n    "declared~=1.0",\n]\n', encoding="utf-8")
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
        ("self-checks assert", lambda: self_checks_assert_something(ROOT)),
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
        ("workflow dispatch", lambda: check_workflow_dispatch(ROOT)),
        ("workflow boundaries", lambda: check_workflow_boundaries(ROOT)),
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
