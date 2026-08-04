#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Mutation testing for the checks: prove each one can tell a bad tree from a good one.

The suite proves the repository conforms. It cannot prove the checks would
notice if it stopped. Those are different claims, and against a conforming tree
they produce identical output: a check that returns its real findings and a
check whose body is `return []` both report nothing.

This runs the experiment that separates them. Each `check_*` function has its
body replaced with an empty result in a throwaway copy of the tree, and the
owning script's self-check is run. A check whose case actually drives it fails;
one that survives has a case that observes nothing, and could have its logic
deleted without the suite noticing.

check.py's own `checks are wired` gate requires every check to be named inside
a self-check. This answers the question that gate cannot: whether the naming
does any work.
"""

import argparse
import ast
import concurrent.futures
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import cli
from cli import EX_DATAERR, EX_SOFTWARE, Failure, fail, report_failure, run_self_check, take_self_check, wants_json

# Copied rather than checked out, so a run cannot touch the working tree and
# needs no clean index. Build artifacts and version control are excluded
# because copying them is the slowest part and none of it is read.
NOISE = (".git", ".claude", "__pycache__", "tmp*", ".ruff_cache", ".pytest_cache")
PREFIX = "check_"
# The empty result every mutant returns. Every check in the repository reports
# by returning a list of failures, so this is the shape of "found nothing"
# rather than a shape that would crash the caller.
EMPTY = "    return []\n"
# The one script whose self-check is spelled with a leading `--`.
CHECKER = "check.py"


def owned_nodes(node):
    """The statements belonging to this function rather than to a nested one.

    ast.walk descends into nested definitions, which reads a closure's return
    as the outer function's own and misclassifies anything using a local
    helper. The distinction decides whether a function is gutted at all, so it
    cannot be approximated.
    """
    stack, owned = list(node.body), []
    nested = (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)
    while stack:
        current = stack.pop()
        owned.append(current)
        # Filtering children on the way in is not enough: a nested definition
        # reached from the body is still popped, and descending from there
        # collects its return as though it were the outer function's. The cut
        # has to happen when the nested node is visited, not when it is queued.
        if isinstance(current, nested):
            continue
        stack.extend(ast.iter_child_nodes(current))
    return owned


def reports_by_returning(node):
    """Whether this function answers by returning findings.

    Two different things in this repository are named `check_*`. A check
    reports by returning a list the caller inspects, and emptying it is a
    silent lie: the caller sees "nothing wrong" and continues. A self-check
    case instead asserts, or calls something that exits, and emptying it
    removes a test rather than corrupting an answer.

    Only the first is what this harness is about. Gutting a case proves the
    tautology that a deleted test does not run, and reporting it would leave a
    standing set of findings nobody can act on, which is how a check becomes
    something people learn to skim past.
    """
    return any(isinstance(inner, ast.Return) and inner.value is not None for inner in owned_nodes(node))


def check_functions(script):
    """The module-level checks in one script, with the lines of each body.

    Module level only: a nested helper named check_* is not what the suite
    registers, and replacing one would test the enclosing function instead.
    """
    tree = ast.parse(script.read_text(encoding="utf-8"))
    found = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or not node.name.startswith(PREFIX):
            continue
        if not reports_by_returning(node):
            continue
        body = node.body
        # A docstring is not behaviour, and replacing it along with the body
        # leaves the mutant undocumented rather than gutted. Keeping it also
        # avoids the subtler bug of writing the replacement into the middle of
        # a triple-quoted string, which produces a syntax error that looks
        # like a killed mutant.
        if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if not body:
            continue
        found.append((node.name, body[0].lineno, body[-1].end_lineno))
    return found


def self_check_argument(script):
    """How this script spells the request to check itself.

    check.py runs the list that includes every other script's self-check, so
    it cannot take a bare positional the way they do without the two spellings
    colliding. That asymmetry is the reason this function exists rather than a
    constant.
    """
    return "--" + cli.SELF_CHECK if script == CHECKER else cli.SELF_CHECK


def gut(source, start, end):
    """Replace a function body, given as a line span, with an empty result."""
    lines = source.splitlines(keepends=True)
    lines[start - 1 : end] = [EMPTY]
    return "".join(lines)


def survives(root, script, name, start, end, timeout=900):
    """Whether the self-check still passes with this check's body removed.

    Returns the outcome as prose rather than a bool because the two ways a
    mutant fails to prove anything are different problems: surviving means the
    case is weak, while failing to parse means this harness wrote something
    invalid and the result says nothing about the check at all.
    """
    with tempfile.TemporaryDirectory() as directory:
        work = Path(directory) / "tree"
        shutil.copytree(root, work, symlinks=True, ignore=shutil.ignore_patterns(*NOISE))
        target = work / "scripts" / script
        mutated = gut(target.read_text(encoding="utf-8"), start, end)
        try:
            ast.parse(mutated)
        except SyntaxError as error:
            return f"harness wrote invalid source for {name}: {error}"
        target.write_text(mutated, encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(target), self_check_argument(script)],
            cwd=str(work),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
        # A mutant is killed only when the self-check ran and rejected it. An
        # exit code alone does not say that: check.py spells its own
        # self-check with a leading `--`, and passing the bare form made
        # argparse exit 2 before running a single case, so every mutant looked
        # dead and the entire sweep was vacuous while reporting success. The
        # baseline gate below is what rules that out, because a spelling that
        # never reaches the cases cannot pass unmutated either.
        if cli.PASSED in result.stdout:
            return f"scripts/{script}: {name} survives an empty body; its self-check case observes nothing"
        return None


def baseline_failures(root, script, timeout=900):
    """Confirm this script's self-check passes before anything is mutated.

    Without this the sweep can succeed while proving nothing. If a mutant is
    rejected for a reason unrelated to the mutation, an unrecognised argument
    being the one that actually happened, every mutant dies and the report
    reads as a clean sweep. The baseline separates the two: a run that cannot
    pass on an unmodified tree could never have been measuring the cases, so
    it is a harness failure rather than a verdict about any check.
    """
    result = subprocess.run(
        [sys.executable, str(root / "scripts" / script), self_check_argument(script)],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0 or cli.PASSED not in result.stdout:
        detail = (result.stderr.strip() or result.stdout.strip() or "no output").splitlines()[-1]
        return [
            (
                f"scripts/{script}: self-check does not pass unmutated, so no mutant result from it "
                f"means anything: {detail}"
            )
        ]
    return []


def sweep(root, workers=8):
    """Run every mutant, reporting the ones whose self-check stayed green.

    Concurrent because each mutant is an independent copy and the wall time is
    dominated by copying and subprocess startup. Nothing is shared between
    them, so the only ordering that matters is the sorted report.
    """
    jobs, scripts = [], []
    for script in sorted((root / "scripts").glob("*.py")):
        found = check_functions(script)
        if found:
            scripts.append(script.name)
        for name, start, end in found:
            jobs.append((root, script.name, name, start, end))
    if not jobs:
        raise Failure("no check functions found; the sweep would pass without testing anything", EX_SOFTWARE)
    broken = [failure for script in scripts for failure in baseline_failures(root, script)]
    if broken:
        return len(jobs), sorted(broken)
    findings = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for finding in pool.map(lambda job: survives(*job), jobs):
            if finding is not None:
                findings.append(finding)
    return len(jobs), sorted(findings)


def self_check():
    """Prove the harness detects both outcomes it is meant to distinguish."""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        scripts = root / "scripts"
        scripts.mkdir()
        # A script whose self-check depends on the check: gutting it must be
        # caught. Written as a whole script rather than by mutating a real one
        # so the case does not change when the repository does.
        (scripts / "watched.py").write_text(
            "import sys\n"
            "def check_value(root):\n"
            '    """Doc."""\n'
            "    return ['always']\n"
            "def main():\n"
            "    assert check_value(None), 'gutted'\n"
            "    print('self-check passed')\n"
            "main()\n",
            encoding="utf-8",
        )
        total, findings = sweep(root, workers=2)
        assert total == 1, total
        assert findings == [], findings

        # The same script with a self-check that names the check and asserts
        # nothing about it. This is the shape the sweep exists to find: the
        # wiring gate sees the name and is satisfied, and the case is inert.
        (scripts / "watched.py").write_text(
            "def check_value(root):\n"
            '    """Doc."""\n'
            "    return ['always']\n"
            "def main():\n"
            "    check_value(None)\n"
            "    print('self-check passed')\n"
            "main()\n",
            encoding="utf-8",
        )
        total, findings = sweep(root, workers=2)
        assert total == 1, total
        assert findings and "check_value" in findings[0], findings

    # A function named check_* that asserts rather than returning findings is
    # a self-check case, not a check. Gutting one proves only that a deleted
    # test does not run, so it is excluded rather than reported forever.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        (root / "scripts" / "mixed.py").write_text(
            "def check_case(root):\n"
            '    """A self-check case."""\n'
            "    assert root is not None\n"
            "def check_real(root):\n"
            '    """A check."""\n'
            "    return []\n",
            encoding="utf-8",
        )
        selected = [name for name, _, _ in check_functions(root / "scripts" / "mixed.py")]
        assert selected == ["check_real"], selected

    # A nested return belongs to the closure, not to the function holding it,
    # so a case built entirely out of a local helper must still be excluded.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        (root / "scripts" / "nested.py").write_text(
            "def check_case(root):\n"
            '    """A case that builds a helper."""\n'
            "    def build():\n"
            "        return root\n"
            "    assert build() is not None\n",
            encoding="utf-8",
        )
        assert check_functions(root / "scripts" / "nested.py") == []

    # A body that is only a docstring has nothing to remove, so gutting it
    # would produce an identical file and a mutant that cannot fail. Skipping
    # it is correct; counting it would report a false survivor forever.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        (root / "scripts" / "hollow.py").write_text('def check_nothing(root):\n    """Doc only."""\n', encoding="utf-8")
        assert check_functions(root / "scripts" / "hollow.py") == []

    # The spelling bug that made a whole sweep vacuous: a mutant killed by an
    # argument error rather than by its case. A script that always exits
    # nonzero without printing the passing line must be reported as a harness
    # problem, not counted as thirty-two dead mutants.
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "scripts").mkdir()
        (root / "scripts" / "picky.py").write_text(
            "import sys\n"
            "def check_value(root):\n"
            '    """Doc."""\n'
            "    return []\n"
            "if sys.argv[1:] != ['--only-this-spelling']:\n"
            "    sys.exit(2)\n"
            "print('self-check passed')\n",
            encoding="utf-8",
        )
        _, findings = sweep(root, workers=2)
        assert findings and "does not pass unmutated" in findings[0], findings

    assert self_check_argument(CHECKER) == "--" + cli.SELF_CHECK
    assert self_check_argument("names.py") == cli.SELF_CHECK

    source = "def check_a(root):\n    x = 1\n    return [x]\n"
    assert gut(source, 2, 3) == "def check_a(root):\n" + EMPTY


def main():
    if take_self_check(sys.argv[1:]):
        run_self_check(self_check)
        return
    parser = argparse.ArgumentParser(description="Mutation-test the repository's checks.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--workers", type=int, default=8)
    arguments = parser.parse_args()

    total, findings = sweep(arguments.root.resolve(), workers=arguments.workers)
    if findings:
        for finding in findings:
            print(finding, file=sys.stderr)
        fail(f"{len(findings)} of {total} check(s) survive an empty body", EX_DATAERR)
    print(f"mutation sweep passed: {total} checks all fail when gutted")


if __name__ == "__main__":
    try:
        main()
    except Failure as error:
        report_failure(error, wants_json(sys.argv[1:]), sys.stderr)
        raise SystemExit(error.code) from error
