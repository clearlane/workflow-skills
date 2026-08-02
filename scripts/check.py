#!/usr/bin/env python3
"""Repository check entrypoint: runs every deterministic project check.

Structural questions about documents go through scripts/document.py, so this
file declares what must hold rather than how markdown or YAML is parsed.
"""
import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import document  # noqa: E402
from design import ALWAYS_FIRST, ALWAYS_LAST, CAPABILITY_PHASES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TICK = chr(96)
SKILL_LINE_BUDGET = 500
REQUIRED_FRONTMATTER = ("name", "description")
VENDOR_TOKENS = ("{baseDir}", "quick_validate", "approved_plan_sha256")
PHASE_SECTION = "Phases the Coordinator Always Runs"
DESIGN_WORKFLOW = "workflows/design.md"
ENTRY_DOCUMENTS = (
    "SKILL.md",
    "workflows/design.md",
    "workflows/absorb.md",
    "workflows/setup.md",
    "workflows/restructure.md",
)


def check_skill(root):
    """The core instruction file must stay discoverable and within budget."""
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
    if parsed.line_count > SKILL_LINE_BUDGET:
        failures.append(f"SKILL.md: {parsed.line_count} lines exceeds budget {SKILL_LINE_BUDGET}")
    return failures


def check_vendor_tokens(root):
    """Core guidance stays runtime-neutral; host syntax belongs in adapters."""
    failures = []
    for parsed in document.walk(root):
        for number, line in enumerate(parsed.text.splitlines(), 1):
            for token in VENDOR_TOKENS:
                if token in line:
                    failures.append(
                        f"{parsed.path.relative_to(root)}:{number}: vendor token {token}"
                    )
    return failures


def check_duplicate_headings(root):
    """One canonical home per topic: reject a repeated H2 within one document."""
    failures = []
    for parsed in document.walk(root):
        seen = set()
        for heading in parsed.headings_at(2):
            if heading.text in seen:
                failures.append(
                    f"{parsed.path.relative_to(root)}:{heading.line}: "
                    f"duplicate section {heading.text!r}"
                )
            seen.add(heading.text)
    return failures


def check_phase_drift(root):
    """Documented phases must match the phases the coordinator actually derives.

    Prose cannot enforce order, but it can go stale. Renaming or adding a phase
    in design.py without updating the workflow would otherwise pass silently.
    """
    failures = []
    parsed = document.parse(root / DESIGN_WORKFLOW)
    documented = {
        line.split("|")[1].strip().strip(TICK)
        for line in parsed.text.splitlines()
        if line.startswith("| " + TICK)
    }
    declared = {name for name, _, _ in CAPABILITY_PHASES}
    for missing in sorted(declared - documented):
        failures.append(
            f"{DESIGN_WORKFLOW}: capability {missing!r} has no row; design.py "
            "derives a phase the workflow never explains"
        )
    for extra in sorted(documented - declared):
        failures.append(
            f"{DESIGN_WORKFLOW}: capability {extra!r} is documented but design.py "
            "derives no phase for it"
        )
    scope = parsed.section(PHASE_SECTION)
    if scope is None:
        failures.append(f"{DESIGN_WORKFLOW}: missing section {PHASE_SECTION!r}")
        return failures
    for phase in ALWAYS_FIRST + ALWAYS_LAST:
        if TICK + phase + TICK not in scope:
            failures.append(
                f"{DESIGN_WORKFLOW}: always-run phase {phase!r} is not described "
                f"under {PHASE_SECTION!r}"
            )
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
                failures.append(
                    f"{path.relative_to(root)}: not linked from SKILL.md or any workflow"
                )
    return failures


def run_script(root, name, *arguments):
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / name), *arguments],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return [f"scripts/{name} failed: {result.stdout.strip()} {result.stderr.strip()}".strip()]
    return []


def main():
    argparse.ArgumentParser(description="Run every deterministic repository check.").parse_args()
    checks = (
        ("filenames", lambda: run_script(ROOT, "names.py", str(ROOT))),
        ("shared state primitives", lambda: run_script(ROOT, "state.py")),
        ("document model", lambda: run_script(ROOT, "document.py", "self-check")),
        ("settings resolver", lambda: run_script(ROOT, "settings.py", "--self-check")),
        ("design coordinator", lambda: run_script(ROOT, "design.py", "self-check")),
        ("absorption coordinator", lambda: run_script(ROOT, "absorb.py", "self-check")),
        ("structural inventory", lambda: run_script(ROOT, "inventory.py", "--self-check")),
        ("skill contract", lambda: check_skill(ROOT)),
        ("links and anchors", lambda: document.broken_links(ROOT)),
        ("resource reachability", lambda: check_reachability(ROOT)),
        ("canonical sections", lambda: check_duplicate_headings(ROOT)),
        ("documented phases", lambda: check_phase_drift(ROOT)),
        ("runtime-neutral tokens", lambda: check_vendor_tokens(ROOT)),
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
