#!/usr/bin/env python3
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from state import shipped_paths

PORTABLE_STEM = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PORTABLE_EXTENSIONS = re.compile(r"^(?:[a-z0-9]+)(?:\.[a-z0-9]+)*$")
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
IGNORED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}


def authored_files(root):
    """Files this repository ships, so a local scratch file cannot fail the check."""
    shipped = shipped_paths(root)
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if shipped is not None and relative.as_posix() not in shipped:
            continue
        if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts[:-1]):
            continue
        if path.name.startswith("."):
            continue
        yield relative


def filename_error(path):
    if path.name in EXACT_NAMES:
        return None
    stem, separator, extensions = path.name.partition(".")
    if PORTABLE_STEM.fullmatch(stem) and (
        not separator or PORTABLE_EXTENSIONS.fullmatch(extensions)
    ):
        return None
    return "use one lowercase word or a family-first lowercase hyphenated stem"


def validate(root):
    return [
        (path, error)
        for path in authored_files(root)
        if (error := filename_error(path)) is not None
    ]


def self_check():
    valid = [
        Path("settings.py"),
        Path("command-create.md"),
        Path("schema-v2.json"),
        Path("SKILL.md"),
        Path("agents/openai.yaml"),
        Path("archive.tar.gz"),
    ]
    invalid = [
        Path("resolve_settings.py"),
        Path("CreateCommand.md"),
        Path("command--create.md"),
        Path("command review.md"),
        Path("command-create.MD"),
        Path("-command.md"),
    ]
    assert all(filename_error(path) is None for path in valid)
    assert all(filename_error(path) is not None for path in invalid)


def main():
    parser = argparse.ArgumentParser(description="Check portable skill resource filenames.")
    parser.add_argument("root", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--self-check", action="store_true")
    arguments = parser.parse_args()

    if arguments.self_check:
        self_check()
        print("self-check passed")
        return

    failures = validate(arguments.root.resolve())
    if failures:
        for path, error in failures:
            print(f"{path}: {error}")
        raise SystemExit(1)
    print("filename check passed")


if __name__ == "__main__":
    main()
