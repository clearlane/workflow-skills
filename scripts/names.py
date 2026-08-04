#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Deterministic portable filename check for skill resources.

Implements references/naming.md, including its ecosystem carve-out: a file that
is an importable module in a language whose own convention forbids hyphens is
checked against that language's convention instead of the hyphenated form.
"""

import argparse
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import EX_DATAERR, Failure, fail, report_failure, run_self_check, take_self_check, wants_json
from state import shipped_paths

PORTABLE_STEM = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PORTABLE_EXTENSIONS = re.compile(r"^(?:[a-z0-9]+)(?:\.[a-z0-9]+)*$")
# PEP 8: importable modules and packages are lower_case_with_underscores, and
# the language reserves its own dunder names. A hyphen there is not a style
# choice, it makes the module unimportable.
MODULE_SUFFIXES = {".py", ".pyi"}
MODULE_STEM = re.compile(r"^[a-z_][a-z0-9_]*$")
MODULE_DUNDER = re.compile(r"^__[a-z][a-z0-9_]*__$")
EXACT_NAMES = {
    "AGENTS.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "LICENSE",
    "LICENSE.md",
    "Makefile",
    "README.md",
    "SECURITY.md",
    "SKILL.md",
    "UPSTREAM.md",
}
# A repository that splits its terms names the parts `LICENSE-<PART>`, and
# license scanners look for exactly that shape. This is rule 8 of
# references/naming.md: an ecosystem contract outranks the house convention.
LICENSE_PART = re.compile(r"^LICENSE-[A-Z0-9]+(?:\.md)?$")
IGNORED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}


def authored_files(root):
    """Every shipped path whose name the convention governs, files and directories.

    Shipped, so a local scratch file cannot fail the check.

    A directory is a resource. `references/` and `command-create.md` are read
    the same way by someone scanning a tree, and the convention's own reasons --
    fast scanning, stable grouping, predictable discovery -- are about the
    names in a listing rather than about which of them happen to hold bytes.
    Checking only files left a gap nothing else covered: git tracks no
    directory of its own, so a directory could only ever be reached through the
    paths of the files inside it, and `content-plan/deposer-brevet/_archive`
    sat in the author's corpus with every file under it conforming.

    A directory is yielded once, from the paths shipped beneath it, because
    that is the only evidence git offers that it exists at all.
    """
    shipped = shipped_paths(root)
    seen = set()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if shipped is not None and relative.as_posix() not in shipped:
            continue
        if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts[:-1]):
            continue
        for depth in range(1, len(relative.parts)):
            directory = Path(*relative.parts[:depth])
            if directory not in seen:
                seen.add(directory)
                yield directory
        if path.name.startswith("."):
            continue
        yield relative


def filename_error(path):
    if path.name in EXACT_NAMES or LICENSE_PART.fullmatch(path.name):
        return None
    if path.suffix in MODULE_SUFFIXES:
        return module_error(path)
    stem, separator, extensions = path.name.partition(".")
    if PORTABLE_STEM.fullmatch(stem) and (not separator or PORTABLE_EXTENSIONS.fullmatch(extensions)):
        return None
    return "use one lowercase word or a family-first lowercase hyphenated stem"


def module_error(path):
    """Check an importable module against PEP 8 rather than the hyphenated form.

    A hyphen is rejected here for a stronger reason than style: `import
    sign-document` is a syntax error, so the hyphenated convention would produce
    a file the language cannot load.
    """
    stem = path.name[: -len(path.suffix)]
    if MODULE_DUNDER.fullmatch(stem) or MODULE_STEM.fullmatch(stem):
        return None
    return "use a PEP 8 lower_case_with_underscores module name"


def validate(root):
    return [(path, error) for path in authored_files(root) if (error := filename_error(path)) is not None]


def self_check():
    valid = [
        Path("settings.py"),
        Path("command-create.md"),
        Path("schema-v2.json"),
        Path("SKILL.md"),
        Path("agents/openai.yaml"),
        Path("archive.tar.gz"),
        # PEP 8 carve-out: importable modules keep the language's convention.
        Path("sign_document.py"),
        Path("scripts/__init__.py"),
        Path("state.pyi"),
        Path("LICENSE-CODE"),
    ]
    invalid = [
        Path("CreateCommand.md"),
        Path("command--create.md"),
        Path("command review.md"),
        Path("command-create.MD"),
        Path("-command.md"),
        # A hyphen makes a Python module unimportable, so it stays rejected.
        Path("sign-document.py"),
        Path("SignDocument.py"),
        Path("2fa.py"),
        Path("LICENSE-code"),
    ]
    assert all(filename_error(path) is None for path in valid)
    assert all(filename_error(path) is not None for path in invalid)

    # A directory is a resource whose name the convention governs, and it is
    # reached only through the files beneath it: git tracks no directory of its
    # own, so a check that yields files alone can never see one.
    with tempfile.TemporaryDirectory() as directory:
        tree = Path(directory)
        for relative in ("references/settings.md", "content-plan/_archive/note.md"):
            path = tree / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        walked = set(authored_files(tree))
        assert Path("content-plan") in walked and Path("content-plan/_archive") in walked, walked
        reported = {path.as_posix() for path, _ in validate(tree)}
        assert reported == {"content-plan/_archive"}, reported


def main():
    if take_self_check(sys.argv[1:]):
        run_self_check(self_check)
        return
    parser = argparse.ArgumentParser(description="Check portable skill resource filenames.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    arguments = parser.parse_args()

    failures = validate(arguments.root.resolve())
    if failures:
        # Diagnostics on stderr so a caller can pipe the passing case without a
        # failure appearing in the data stream.
        for path, error in failures:
            print(f"{path}: {error}", file=sys.stderr)
        fail(f"{len(failures)} filename(s) violate the convention", EX_DATAERR)
    print("filename check passed")


if __name__ == "__main__":
    try:
        main()
    except Failure as error:
        report_failure(error, wants_json(sys.argv[1:]), sys.stderr)
        raise SystemExit(error.code) from error
