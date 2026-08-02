#!/usr/bin/env python3
"""Shared durable-run primitives for this repository's coordinators.

Both coordinators persist phase state outside conversation context, so the
JSON, digest, and validation helpers live here once instead of per script.
"""
import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

EXCLUDED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}


def excluded(relative_parts):
    return any(part in EXCLUDED_DIRECTORIES for part in relative_parts)


def fail(message):
    raise SystemExit(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def slug(value):
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return normalized or "skill"


def read_json(path):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError:
        fail(f"Missing file: {path}")
    except json.JSONDecodeError as error:
        fail(f"Invalid JSON in {path}: {error}")
    if not isinstance(value, dict):
        fail(f"Expected JSON object: {path}")
    return value


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_sha256(path):
    encoded = json.dumps(read_json(path), sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def relative_file_manifest(root):
    root = root.resolve()
    if not root.exists():
        return {}
    manifest = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or excluded(path.relative_to(root).parts):
            continue
        manifest[path.relative_to(root).as_posix()] = {
            "sha256": file_sha256(path),
            "size": path.stat().st_size,
        }
    return manifest


def tree_sha256(manifest):
    encoded = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def require_list(value, name):
    if not isinstance(value, list):
        fail(f"{name} must be list")


def require_text(value, name):
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be non-empty string")


def safe_relative_path(value, name):
    require_text(value, name)
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or value in {".", ""}:
        fail(f"{name} must stay inside target: {value}")
    return path.as_posix()


def paths_overlap(first, second):
    return first == second or first in second.parents or second in first.parents


def remove_path(path):
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def save_state(root, state, event):
    state.setdefault("history", []).append(
        {"at": now(), "event": event, "phase": state["phase"]}
    )
    state["updated_at"] = now()
    write_json(root / "state.json", state)


def self_check():
    import tempfile

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        write_json(root / "a.json", {"b": 1, "a": 2})
        assert read_json(root / "a.json") == {"a": 2, "b": 1}
        assert json_sha256(root / "a.json") == json_sha256(root / "a.json")
        (root / "keep").mkdir()
        (root / "keep" / "f.txt").write_text("x")
        (root / ".git").mkdir()
        (root / ".git" / "HEAD").write_text("ref")
        manifest = relative_file_manifest(root)
        assert "keep/f.txt" in manifest
        assert not any(key.startswith(".git") for key in manifest)
        assert safe_relative_path("a/b.md", "x") == "a/b.md"
        for bad in ("/abs", "../up", ".", ""):
            try:
                safe_relative_path(bad, "x")
            except SystemExit:
                pass
            else:
                raise AssertionError(f"accepted unsafe path {bad!r}")
        assert paths_overlap(Path("/a"), Path("/a/b"))
        assert not paths_overlap(Path("/a"), Path("/b"))
        assert slug("Absorb Skills!") == "absorb-skills"
        assert slug("---") == "skill"
    print("self-check passed")


if __name__ == "__main__":
    self_check()
