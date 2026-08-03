#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Produce a bounded, side-effect-free structural inventory of a development project."""

import argparse
import json
import os
import stat
import subprocess
import sys
from collections import Counter
from pathlib import Path

DEFAULT_EXCLUDES = {
    ".git",
    ".hg",
    ".svn",
    ".next",
    ".nuxt",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "coverage",
    "dist",
    "node_modules",
    "target",
    "vendor",
}

MARKERS = {
    "agent-skill": ["SKILL.md"],
    "javascript-node": ["package.json"],
    "python": ["pyproject.toml", "setup.py", "setup.cfg", "requirements.txt"],
    "rust": ["Cargo.toml"],
    "go": ["go.mod"],
    "ruby": ["Gemfile", "gemspec"],
    "php": ["composer.json"],
    "jvm": ["pom.xml", "build.gradle", "build.gradle.kts"],
    "dotnet": ["global.json", "Directory.Build.props"],
    "swift": ["Package.swift"],
    "docker": ["Dockerfile", "compose.yaml", "docker-compose.yml"],
    "terraform": [".terraform.lock.hcl"],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scope", nargs="?", default=".", help="project directory")
    parser.add_argument("--output", help="write JSON to this file instead of stdout")
    parser.add_argument("--max-files", type=int, default=100_000)
    parser.add_argument("--exclude", action="append", default=[], help="directory basename to skip")
    parser.add_argument("--self-check", action="store_true", help="verify inventory behavior and exit")
    return parser.parse_args()


def git_root(scope: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(scope), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return Path(result.stdout.strip()).resolve()


def git_status(root: Path) -> list[str] | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "status", "--short", "--untracked-files=normal"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return result.stdout.splitlines()


def marker_matches(root_files: set[str]) -> dict[str, list[str]]:
    found: dict[str, list[str]] = {}
    for profile, markers in MARKERS.items():
        matches = sorted(
            name for name in root_files if name in markers or (name.endswith(".gemspec") and "gemspec" in markers)
        )
        if matches:
            found[profile] = matches
    return found


def scan(scope: Path, excluded: set[str], max_files: int) -> dict[str, object]:
    """Walk the scope without following symlinks and without writing inside it."""
    files: list[dict[str, object]] = []
    directories: list[str] = []
    extensions: Counter[str] = Counter()
    symlinks: list[dict[str, str]] = []
    total_bytes = 0
    truncated = False

    for current, dirnames, filenames in os.walk(scope, topdown=True, followlinks=False):
        current_path = Path(current)
        relative_dir = current_path.relative_to(scope)
        if relative_dir != Path("."):
            directories.append(relative_dir.as_posix())
        # A symlinked directory is never walked, so record it here or it vanishes
        # from the inventory entirely - exactly the case a migration must not miss.
        linked = sorted(name for name in dirnames if (current_path / name).is_symlink())
        for name in linked:
            path = current_path / name
            try:
                target = os.readlink(path)
            except OSError as exc:
                target = f"<unreadable: {exc}>"
            symlinks.append({"path": path.relative_to(scope).as_posix(), "target": target, "directory": True})
        dirnames[:] = sorted(name for name in dirnames if name not in excluded and name not in set(linked))
        for name in sorted(filenames):
            path = current_path / name
            relative = path.relative_to(scope).as_posix()
            try:
                info = path.lstat()
            except OSError as exc:
                files.append({"path": relative, "error": str(exc)})
                continue
            if stat.S_ISLNK(info.st_mode):
                try:
                    target = os.readlink(path)
                except OSError as exc:
                    target = f"<unreadable: {exc}>"
                symlinks.append({"path": relative, "target": target, "directory": False})
            else:
                total_bytes += info.st_size
                extension = path.suffix.lower() or "<none>"
                extensions[extension] += 1
            files.append(
                {
                    "path": relative,
                    "size": info.st_size,
                    "mode": stat.filemode(info.st_mode),
                    "symlink": stat.S_ISLNK(info.st_mode),
                }
            )
            if len(files) >= max_files:
                truncated = True
                break
        if truncated:
            break

    root_files = {entry["path"] for entry in files if "/" not in str(entry["path"])}
    repository_root = git_root(scope)
    return {
        "schema_version": 1,
        "scope": str(scope),
        "repository_root": str(repository_root) if repository_root else None,
        "git_status": git_status(repository_root) if repository_root else None,
        "excluded_directory_names": sorted(excluded),
        "truncated": truncated,
        "counts": {
            "files": len(files),
            "directories": len(directories),
            "symlinks": len(symlinks),
            "bytes": total_bytes,
        },
        "root_entries": sorted(path.name for path in scope.iterdir()),
        "detected_profiles": marker_matches(root_files),
        "extension_counts": dict(sorted(extensions.items(), key=lambda item: (-item[1], item[0]))),
        "directories": directories,
        "files": files,
        "symlinks": symlinks,
    }


def self_check() -> None:
    """Prove the observable contract: no writes, no symlink following, honest truncation."""
    import tempfile

    with tempfile.TemporaryDirectory() as raw:
        scope = Path(raw)
        (scope / "SKILL.md").write_text("x", encoding="utf-8")
        (scope / "references").mkdir()
        (scope / "references" / "layout.md").write_text("y", encoding="utf-8")
        (scope / "node_modules").mkdir()
        (scope / "node_modules" / "ignored.js").write_text("z", encoding="utf-8")
        (scope / "dirlink").symlink_to(scope / "references")
        (scope / "filelink").symlink_to(scope / "SKILL.md")
        before = sorted(path.name for path in scope.rglob("*"))

        result = scan(scope, DEFAULT_EXCLUDES, 100)
        assert "agent-skill" in result["detected_profiles"], result["detected_profiles"]
        paths = {entry["path"] for entry in result["files"]}
        assert "references/layout.md" in paths, paths
        assert not any(path.startswith("node_modules") for path in paths), paths
        assert "dirlink/layout.md" not in paths, paths
        links = {entry["path"]: entry["directory"] for entry in result["symlinks"]}
        assert links == {"dirlink": True, "filelink": False}, result["symlinks"]
        assert sorted(path.name for path in scope.rglob("*")) == before, "scan mutated the scope"

        truncated = scan(scope, DEFAULT_EXCLUDES, 1)
        assert truncated["truncated"] is True and truncated["counts"]["files"] == 1, truncated


def main() -> int:
    args = parse_args()
    if args.self_check:
        self_check()
        print("self-check passed")
        return 0
    if args.max_files < 1:
        raise SystemExit("--max-files must be positive")
    scope = Path(args.scope).expanduser().resolve()
    if not scope.is_dir():
        raise SystemExit(f"scope is not a directory: {scope}")
    output = Path(args.output).expanduser().resolve() if args.output else None
    if output and output.exists() and output.is_dir():
        raise SystemExit(f"output is a directory: {output}")

    excluded = DEFAULT_EXCLUDES | set(args.exclude)
    if any(not name or "/" in name or name in {".", ".."} for name in excluded):
        raise SystemExit("excluded values must be safe directory basenames")

    result = scan(scope, excluded, args.max_files)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if output:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
