#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Exit codes and the structured failure shape, with no dependencies.

Separate from `state.py` because the standalone tools are deliberately
stdlib-only: `settings.py` and `inventory.py` are also examples a skill author
copies, and making them import a schema-validation layer to learn what exit 65
means would defeat that. Every script in the repository can import this one.

Codes follow `sysexits.h`, which is the closest thing to a convention for
command-line failure classes. A caller that only sees exit 1 cannot tell "you
passed a bad flag" from "the bound plan no longer matches", so it cannot decide
whether re-invoking, re-reading the artifact, or stopping is the right response.
"""

import json

EX_USAGE = 64
EX_DATAERR = 65
EX_UNAVAILABLE = 69
EX_SOFTWARE = 70
EX_TEMPFAIL = 75

# One problem type per failure class, as an identifier a caller can branch on
# without parsing prose. The URI is a stable name, not an endpoint to fetch.
PROBLEM_BASE = "https://clearlane.github.io/workflow-skills/problems/"
PROBLEM_TYPES = {
    EX_USAGE: ("usage", "Invalid invocation"),
    EX_DATAERR: ("data", "Artifact could not be read as its contract requires"),
    EX_UNAVAILABLE: ("unavailable", "A required input or dependency is missing"),
    EX_SOFTWARE: ("software", "An internal invariant broke"),
    EX_TEMPFAIL: ("tempfail", "A bounded retry budget was exhausted"),
}


class Failure(SystemExit):
    """A failure carrying its class, so a caller can act without parsing prose.

    Subclasses SystemExit because that is already how every script stops, and
    because a caller that only checks the exit status keeps working unchanged.
    """

    def __init__(self, message, code=EX_USAGE, instance=None):
        super().__init__(code)
        self.message = message
        self.code = code
        self.instance = instance

    def problem_details(self):
        """RFC 9457 problem details.

        `status` is the process exit code rather than an HTTP status: this is a
        command, and reporting an HTTP code here would name a protocol that is
        not involved. RFC 9457 allows extension members, so the mapping stays
        honest by putting the real code where a reader will look for it.
        """
        slug, title = PROBLEM_TYPES[self.code]
        details = {
            "type": PROBLEM_BASE + slug,
            "title": title,
            "status": self.code,
            "detail": self.message,
        }
        if self.instance is not None:
            details["instance"] = str(self.instance)
        return details


def fail(message, code=EX_USAGE, instance=None):
    """Stop with a message and a failure class.

    Defaults to a usage error because the common case is a caller asking for
    something the run cannot give. A malformed artifact is a data error, and
    that distinction is what lets a wrapper retry a temporary failure without
    also retrying a plan that will never parse.
    """
    raise Failure(message, code, instance)


def report_failure(error, as_json, stream):
    """Render a failure once, so every entrypoint says the same thing.

    Diagnostics go to stderr and data to stdout, which is the POSIX convention
    and the reason a caller can pipe a coordinator's JSON through a pipeline
    without a failure message corrupting the stream.
    """
    if as_json:
        print(json.dumps(error.problem_details(), indent=2, sort_keys=True), file=stream)
    else:
        print(error.message, file=stream)


def wants_json(argv):
    """Whether the caller asked for machine-readable failure output."""
    return "--output=json" in argv or ("--output" in argv and "json" in argv)


def self_check():
    """Prove the failure shape is what the contract claims.

    Cheap to run and the only thing standing between a documented exit code and
    a silently wrong one, since a caller branching on 65 has no way to notice
    that it started returning 64.
    """
    for code, (slug, _title) in PROBLEM_TYPES.items():
        error = Failure("something went wrong", code, "run/abc")
        details = error.problem_details()
        assert details["status"] == code, details
        assert details["type"].endswith(slug), details
        assert details["detail"] == "something went wrong", details
        assert details["instance"] == "run/abc", details
        # SystemExit.code is what the interpreter exits with, so the declared
        # class and the observed exit status cannot drift apart.
        assert error.code == code and SystemExit(error).code is not None

    assert Failure("m").code == EX_USAGE
    assert "instance" not in Failure("m").problem_details()
    assert wants_json(["status", "--output", "json"])
    assert wants_json(["status", "--output=json"])
    assert not wants_json(["status", "--output", "text"])
    print("self-check passed")


if __name__ == "__main__":
    self_check()
