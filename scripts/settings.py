#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Stdlib JSON settings-layer resolver with provenance and atomic writes.

Implements references/settings.md: layers merge in a fixed precedence order,
every resolved value reports which layer produced it, and a write either lands
whole or not at all.
"""

import argparse
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import EX_DATAERR, Failure, report_failure, run_self_check, take_self_check, wants_json


class SettingsError(Failure):
    """A settings layer that cannot be read as the contract requires.

    A data error rather than a usage error: the caller invoked the tool
    correctly and the file on disk is what is wrong, which is the distinction
    that tells a wrapper whether re-invoking could ever help.
    """

    def __init__(self, message):
        super().__init__(message, EX_DATAERR)


def read_object(path):
    try:
        value = json.loads(path.read_text())
    except FileNotFoundError as error:
        raise SettingsError(f"Settings file not found: {path}") from error
    except json.JSONDecodeError as error:
        raise SettingsError(f"Invalid JSON in {path}: {error}") from error
    if not isinstance(value, dict):
        raise SettingsError(f"Settings document must be an object: {path}")
    return value


def parse_override(raw_value):
    if raw_value is None:
        return None
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as error:
        raise SettingsError(f"Invalid invocation override JSON: {error}") from error
    if not isinstance(value, dict):
        raise SettingsError("Invocation override must be a JSON object")
    return value


def resolve(layers):
    effective = {}
    provenance = {}
    for layer_name, values in layers:
        if values is None:
            continue
        for key, value in values.items():
            effective[key] = value
            provenance[key] = layer_name
    return {"effective": effective, "provenance": provenance}


def file_digest(path):
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_write(path, value, expected_digest=None):
    current_digest = file_digest(path)
    if expected_digest is not None and current_digest != expected_digest:
        raise SettingsError(
            f"Concurrent update detected for {path}: expected {expected_digest}, found {current_digest}"
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    existing_mode = path.stat().st_mode & 0o777 if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        if existing_mode is not None:
            os.chmod(temporary, existing_mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def self_check():
    resolved = resolve(
        [
            ("default", {"enabled": True, "mode": "standard", "max_attempts": 3}),
            ("user", {"mode": "strict"}),
            ("project", {"max_attempts": 5}),
            ("invocation", {"mode": "focused"}),
        ]
    )
    assert resolved == {
        "effective": {"enabled": True, "mode": "focused", "max_attempts": 5},
        "provenance": {"enabled": "default", "mode": "invocation", "max_attempts": "project"},
    }

    with tempfile.TemporaryDirectory() as directory:
        destination = Path(directory) / "settings.json"
        atomic_write(destination, resolved["effective"])
        digest = file_digest(destination)
        atomic_write(destination, {"enabled": False}, expected_digest=digest)
        try:
            atomic_write(destination, {"enabled": True}, expected_digest=digest)
        except SettingsError:
            pass
        else:
            raise AssertionError("stale digest must reject concurrent update")


def main():
    if take_self_check(sys.argv[1:]):
        run_self_check(self_check)
        return
    parser = argparse.ArgumentParser(description="Resolve layered JSON skill settings with provenance.")
    parser.add_argument("--defaults", type=Path)
    parser.add_argument("--user", type=Path)
    parser.add_argument("--project", type=Path)
    parser.add_argument("--override", help="Invocation override as JSON object")
    parser.add_argument("--output", type=Path, help="Atomically write resolved result")
    parser.add_argument("--expect-sha256", help="Reject output write when current digest differs")
    arguments = parser.parse_args()

    if arguments.defaults is None:
        parser.error("--defaults is required")

    layers = [("default", read_object(arguments.defaults))]
    layers.extend(
        (name, read_object(path))
        for name, path in (("user", arguments.user), ("project", arguments.project))
        if path is not None
    )
    layers.append(("invocation", parse_override(arguments.override)))
    result = resolve(layers)

    if arguments.output:
        atomic_write(arguments.output, result, arguments.expect_sha256)
    else:
        print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except Failure as error:
        report_failure(error, wants_json(sys.argv[1:]), sys.stderr)
        raise SystemExit(error.code) from error
