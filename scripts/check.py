#!/usr/bin/env python3
"""Repository check entrypoint: runs every deterministic project check."""
import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FENCE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE = re.compile(r"`[^`]*`")
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKILL_LINE_BUDGET = 500
VENDOR_TOKENS = ("{baseDir}", "quick_validate", "approved_plan_sha256")
IGNORED_DIRECTORIES = {".git", "__pycache__", "node_modules"}


def documents(root):
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts):
            continue
        yield path


def prose_lines(text):
    """Yield lines outside fenced blocks, with inline code spans removed."""
    fenced = False
    for line in text.splitlines():
        if FENCE.match(line):
            fenced = not fenced
            continue
        if fenced:
            continue
        yield INLINE_CODE.sub("", line)


def check_links(root):
    failures = []
    for path in documents(root):
        for line in prose_lines(path.read_text()):
            for target in LINK.findall(line):
                if target.startswith(("http://", "https://", "#", "mailto:")):
                    continue
                resolved = (path.parent / target.split("#")[0]).resolve()
                if not resolved.exists():
                    failures.append(f"{path.relative_to(root)}: broken link {target}")
    return failures


def check_skill(root):
    failures = []
    skill = root / "SKILL.md"
    text = skill.read_text()
    lines = text.splitlines()
    if not text.startswith("---\n"):
        failures.append("SKILL.md: missing frontmatter block")
    else:
        frontmatter = text.split("---\n", 2)[1]
        for field in ("name:", "description:"):
            if field not in frontmatter:
                failures.append(f"SKILL.md: frontmatter missing {field}")
    if len(lines) > SKILL_LINE_BUDGET:
        failures.append(f"SKILL.md: {len(lines)} lines exceeds budget {SKILL_LINE_BUDGET}")
    return failures


def check_vendor_tokens(root):
    failures = []
    for path in documents(root):
        for number, line in enumerate(path.read_text().splitlines(), 1):
            for token in VENDOR_TOKENS:
                if token in line:
                    failures.append(f"{path.relative_to(root)}:{number}: vendor token {token}")
    return failures


def check_duplicate_headings(root):
    """One canonical home per topic: reject a repeated H2 within one document."""
    failures = []
    for path in documents(root):
        seen = set()
        for line in prose_lines(path.read_text()):
            if line.startswith("## "):
                heading = line[3:].strip()
                if heading in seen:
                    failures.append(f"{path.relative_to(root)}: duplicate section {heading!r}")
                seen.add(heading)
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
        ("settings resolver", lambda: run_script(ROOT, "settings.py", "--self-check")),
        ("design coordinator", lambda: run_script(ROOT, "design.py", "self-check")),
        ("absorption coordinator", lambda: run_script(ROOT, "absorb.py", "self-check")),
        ("skill contract", lambda: check_skill(ROOT)),
        ("relative links", lambda: check_links(ROOT)),
        ("canonical sections", lambda: check_duplicate_headings(ROOT)),
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
