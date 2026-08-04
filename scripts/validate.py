#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Deterministic Agent Skills conformance check for any skill directory.

This repository's checks answered only for this repository: `scripts/check.py`
resolves its own root from `__file__` and every rule reaches for `workflows/`,
`schemas/`, or `COORDINATORS`. So the one claim the skill makes about other
people's skills — that it can review them — had nothing executable behind it,
and `scripts/review.py` asked a human every question including the ones a
parser answers exactly.

The bounds here are the format's, not this repository's preferences: a host
rejects a skill that breaks them rather than degrading it, which is what makes
them worth checking before a reviewer spends judgement on anything else.
See <https://agentskills.io/specification>.

Stdlib-only and dependency-free on purpose. A validator that must be installed
before it can say whether a skill is valid is one more thing between a user and
the answer, and the frontmatter subset a skill uses is a flat scalar map that
does not need a YAML engine.
"""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import EX_DATAERR, Failure, fail, report_failure, run_self_check, take_self_check, wants_json

# Fixed by the Agent Skills format. A skill outside these is rejected by the
# host, so they are bounds rather than style advice.
NAME_LIMIT = 64
DESCRIPTION_LIMIT = 1024
COMPATIBILITY_LIMIT = 500
# Lowercase alphanumerics and single inner hyphens. Written to exclude a
# consecutive hyphen directly, which the spec names as its own rule.
SKILL_NAME = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
# Recommended rather than fixed, and reported as a warning for that reason:
# a host loads the whole body on activation, so length is a context cost the
# author pays on every invocation, not a rejection.
LINE_BUDGET = 500
KNOWN_FIELDS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
REQUIRED_FIELDS = ("name", "description")


class Finding:
    """One conformance result, carrying whether it blocks the host from loading.

    Severity is the distinction that matters to a caller: `error` is the format
    rejecting the skill, `warning` is guidance the author may knowingly ignore.
    Collapsing the two would make the exit status useless for gating.
    """

    def __init__(self, severity, rule, message):
        self.severity = severity
        self.rule = rule
        self.message = message

    def as_dict(self):
        return {"severity": self.severity, "rule": self.rule, "message": self.message}


def split_frontmatter(text):
    """Return (frontmatter_text, body_line_count), or (None, count) when absent.

    The format requires the block to open on the very first line, so a file
    that merely contains `---` somewhere has no frontmatter rather than a
    late one.
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None, len(lines)
    for index in range(1, len(lines)):
        if lines[index].strip() in {"---", "..."}:
            return "\n".join(lines[1:index]), len(lines)
    return None, len(lines)


def parse_scalars(block):
    """Parse the flat `key: value` subset a skill's frontmatter actually uses.

    Deliberately not a YAML parser. Nested structures are reported as present
    rather than interpreted, because the fields this validator bounds are all
    scalars and guessing at the rest would mean claiming a certainty a 30-line
    parser does not have.
    """
    values = {}
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[:1].isspace() or line.lstrip().startswith("- "):
            continue  # a nested member of the previous key
        key, separator, value = line.partition(":")
        if not separator:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def check_frontmatter(values, findings):
    for field in REQUIRED_FIELDS:
        if not values.get(field):
            findings.append(Finding("error", "frontmatter", f"frontmatter missing non-empty {field}"))

    name = values.get("name", "")
    if name:
        if len(name) > NAME_LIMIT:
            findings.append(Finding("error", "name", f"name is {len(name)} characters, over the {NAME_LIMIT} limit"))
        if "--" in name:
            findings.append(Finding("error", "name", f"name {name!r} contains consecutive hyphens"))
        elif not SKILL_NAME.fullmatch(name):
            findings.append(
                Finding("error", "name", f"name {name!r} must be lowercase letters, digits, and inner hyphens")
            )

    for field, limit in (("description", DESCRIPTION_LIMIT), ("compatibility", COMPATIBILITY_LIMIT)):
        value = values.get(field)
        if value is not None and len(value) > limit:
            findings.append(Finding("error", field, f"{field} is {len(value)} characters, over the {limit} limit"))

    for field in sorted(set(values) - KNOWN_FIELDS):
        findings.append(
            Finding("warning", "frontmatter", f"frontmatter field {field!r} is not in the Agent Skills format")
        )


def strip_code(text):
    """Remove fenced blocks and inline code spans before scanning for links.

    A skill that documents link syntax writes `[text](url)` as an example, and
    reading that as a link reports a missing file for a string that was never a
    reference. Observed against a real third-party skill, where the only finding
    the scan produced was this false positive.
    """
    text = re.sub(r"^(```|~~~).*?^\1", "", text, flags=re.S | re.M)
    return re.sub(r"`+[^`]*`+", "", text)


def check_links(skill, text, findings):
    """Every relative link must resolve inside the skill.

    A link that resolves in the author's checkout and not after install is the
    most common broken skill, and it is invisible to anyone reading the file.
    """
    for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", strip_code(text)):
        path = target.split("#", 1)[0].strip()
        if not path or re.match(r"^[a-z][a-z0-9+.-]*:", path) or path.startswith("/"):
            continue
        if not (skill / path).exists():
            findings.append(Finding("error", "links", f"SKILL.md links {path}, which does not exist"))


def validate(skill):
    """Check one skill directory, returning findings in reporting order."""
    findings = []
    core = skill / "SKILL.md"
    if not core.is_file():
        return [Finding("error", "structure", f"{skill}: no SKILL.md; a skill is a directory containing one")]

    text = core.read_text(encoding="utf-8", errors="replace")
    block, line_count = split_frontmatter(text)
    if block is None:
        findings.append(Finding("error", "frontmatter", "SKILL.md has no frontmatter block opening on line 1"))
    else:
        values = parse_scalars(block)
        check_frontmatter(values, findings)
        name = values.get("name")
        # The format requires the two to agree, and a host that discovers by
        # directory and reports by name shows a different skill than it loaded
        # when they diverge. Reported as a warning rather than an error because
        # the directory checked here is often a development checkout, whose
        # name the installer replaces with the skill's own: a repository named
        # for its project rather than its skill is not a broken skill. The
        # install-time name is what must match, and only an install can see it.
        if name and name != skill.name:
            findings.append(
                Finding(
                    "warning",
                    "name",
                    f"name {name!r} does not match the directory name {skill.name!r}; "
                    "the format requires them to agree once installed",
                )
            )

    if line_count > LINE_BUDGET:
        findings.append(
            Finding("warning", "size", f"SKILL.md is {line_count} lines, over the recommended {LINE_BUDGET}")
        )
    check_links(skill, text, findings)
    return findings


def self_check():
    import tempfile

    with tempfile.TemporaryDirectory() as directory:
        skill = Path(directory) / "good-skill"
        skill.mkdir()
        core = skill / "SKILL.md"

        def write(frontmatter, body=""):
            core.write_text(f"---\n{frontmatter}\n---\n{body}", encoding="utf-8")
            return validate(skill)

        assert write("name: good-skill\ndescription: does a thing") == []

        def rules(findings, severity="error"):
            return {f.rule for f in findings if f.severity == severity}

        # Each bound the format fixes, rejected one at a time, so a check that
        # silently stopped rejecting is not read as a passing skill.
        assert "name" in rules(write("name: good--skill\ndescription: d")), "consecutive hyphens accepted"
        assert "name" in rules(write("name: Good-Skill\ndescription: d")), "uppercase accepted"
        assert "name" in rules(write(f"name: {'x' * 65}\ndescription: d")), "over-long name accepted"
        assert "name" in rules(write("name: other-skill\ndescription: d"), "warning"), "name/directory mismatch"
        assert "frontmatter" in rules(write("name: good-skill")), "missing description accepted"
        assert "description" in rules(write(f"name: good-skill\ndescription: {'d' * 1025}")), "over-long accepted"
        assert "links" in rules(write("name: good-skill\ndescription: d", "[x](references/missing.md)")), (
            "a link to a missing file was accepted"
        )
        # An external link and an anchor are not this check's business.
        assert write("name: good-skill\ndescription: d", "[x](https://example.com) [y](#section)") == []
        # A skill documenting link syntax is not linking. This exact false
        # positive was the only finding produced across 43 third-party skills.
        assert write("name: good-skill\ndescription: d", "use `[text](url)` for externals") == []
        assert write("name: good-skill\ndescription: d", "```\n[x](missing.md)\n```\n") == []
        assert "size" in rules(write("name: good-skill\ndescription: d", "\n" * 600), "warning")

        core.write_text("no frontmatter here\n", encoding="utf-8")
        assert "frontmatter" in rules(validate(skill)), "a file with no frontmatter was accepted"

        # A quoted scalar is the common spelling for a description containing a
        # colon, and treating the quotes as content would misreport its length.
        core.write_text('---\nname: "good-skill"\ndescription: "d: e"\n---\n', encoding="utf-8")
        assert validate(skill) == [], "a quoted scalar was misparsed"

        # Nested values must not be read as top-level keys, or `author:` under
        # `metadata:` would report as an unknown field.
        core.write_text("---\nname: good-skill\ndescription: d\nmetadata:\n  author: someone\n---\n", encoding="utf-8")
        assert validate(skill) == [], "a nested mapping was misparsed as unknown fields"

        missing = Path(directory) / "not-a-skill"
        missing.mkdir()
        assert "structure" in rules(validate(missing)), "a directory with no SKILL.md was accepted"


def main():
    if take_self_check(sys.argv[1:]):
        run_self_check(self_check)
        return
    parser = argparse.ArgumentParser(description="Check a skill against the Agent Skills format.")
    parser.add_argument("skill", nargs="?", type=Path, default=Path.cwd())
    parser.add_argument("--output", choices=("text", "json"), default="text")
    arguments = parser.parse_args()

    skill = arguments.skill.resolve()
    findings = validate(skill)
    errors = [finding for finding in findings if finding.severity == "error"]

    if arguments.output == "json":
        print(json.dumps({"skill": str(skill), "findings": [f.as_dict() for f in findings]}, indent=2))
    else:
        for finding in findings:
            print(f"{finding.severity}: {finding.rule}: {finding.message}", file=sys.stderr)
    if errors:
        # Only a format error fails the run. A warning that blocked the exit
        # status would make the recommended budget indistinguishable from a
        # rule the host enforces by rejection.
        fail(f"{len(errors)} conformance error(s)", EX_DATAERR)
    if arguments.output != "json":
        print("conformance check passed")


if __name__ == "__main__":
    try:
        main()
    except Failure as error:
        report_failure(error, wants_json(sys.argv[1:]), sys.stderr)
        raise SystemExit(error.code) from error
