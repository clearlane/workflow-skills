#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Repository check entrypoint: runs every deterministic project check.

Structural questions about documents go through scripts/document.py, so this
file declares what must hold rather than how markdown or YAML is parsed.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli
import design
import document
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
PHASE_SECTION = "Phases the Coordinator Always Runs"
DESIGN_WORKFLOW = "workflows/design.md"
REVIEW_WORKFLOW = "workflows/review.md"
README = "README.md"
CHECKER = "check.py"
README_SECTION = "Structure"
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
    "workflows/setup.md",
    "workflows/restructure.md",
    "workflows/review.md",
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
        for number, line in enumerate(parsed.text.splitlines(), 1):
            for token in VENDOR_TOKENS:
                if token in line:
                    failures.append(f"{parsed.path.relative_to(root)}:{number}: vendor token {token}")
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


def check_phase_owners(root):
    """Every derived phase must resolve to a distinct owning contract that exists.

    A phase whose resource is the document that dispatched the coordinator
    answers "what do I read now?" with "the file you came from". Requiring a
    distinct existing owner is a stronger guarantee than scanning prose for
    phase names, and it fails the moment a phase is added without a contract.
    """
    failures = []
    entry_documents = {DESIGN_WORKFLOW, REVIEW_WORKFLOW, "SKILL.md"}
    coordinators = (
        ("design", design.derive_phases(design.CAPABILITIES), design.phase_resource),
        ("review", review.derive_phases(review.SURFACES), review.phase_resource),
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
        ("skill contract", lambda: check_skill(ROOT)),
        ("links and anchors", lambda: document.broken_links(ROOT)),
        ("resource reachability", lambda: check_reachability(ROOT)),
        ("canonical sections", lambda: check_duplicate_headings(ROOT)),
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
