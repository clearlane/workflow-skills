#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Recognise a host by the shape of the path it owns, not only by its name.

`references/settings.md` states the rule: a skill that stores state in one
host's hidden directory has bound a runtime-neutral workflow to that host, and
moving it later means migrating live user state. Enforcing that by naming each
host can only ever cover the hosts someone has already met, so a document
naming a runtime released after the list was last touched passes.

The two shapes here describe where an agent runtime keeps its material, which
is a property of being a host rather than of being a particular one. Each is
narrowed by the paths that are genuinely cross-host, so the exemptions state a
reason instead of a roster.

Its own module because two callers need it and neither can own it. `check.py`
holds this repository to the rule and already imports `review.py`, so putting
the patterns there would make the checker depend on the reviewer for a rule
neither owns; `review.py` applies the same rule to skills the user is
reviewing. Stdlib-only, like `cli.py` and `names.py`, so a skill author can
copy it.
"""

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cli import run_self_check

# A per-user dotfile directory. Every host configures itself in one, so the
# shape is the host rather than any particular host. Both spellings are
# matched, since `$HOME` is what a shell snippet writes.
HOME_DOTFILE = re.compile(r"(?:~|\$HOME)/\.([A-Za-z][\w.-]*)")
# The XDG base directories are a freedesktop.org specification every host
# honours, so naming one is the opposite of naming a host: it is the neutral
# answer references/settings.md requires. Shell rc files belong to the shell.
CROSS_HOST_HOME = frozenset({"config", "cache", "local", "bashrc", "zshrc", "profile", "bash_profile", "zshenv"})
# A project-local dot-directory holding agent material. The directory name
# alone is far too broad, since a skill legitimately names its own `.scrum/` or
# `.context/` state, so the second segment is what is matched: the places a
# host scans for skills, commands, and prompts. That is the claim neutrality is
# about, and it is what makes `.cursor/rules/` a violation while
# `.github/workflows/` stays unremarkable. The directory name is unbounded in
# length, since the second segment carries the precision and a floor would only
# decide in advance that no host is named in two letters.
HOST_INSTALL_PATH = re.compile(
    r"(?<![\w.$)>/~\\-])(\.[a-z][a-z0-9_-]*)/(?:skills|rules|commands|agents|plugins|prompts|instructions)\b"
)
# The directories any repository has whichever agent reads it. These are
# conventions of git hosting and editors, not of an agent runtime.
CROSS_HOST_DIRECTORIES = frozenset({".github", ".gitlab", ".githooks", ".well-known", ".devcontainer", ".vscode"})

# Where the rule applies. A contract under references/ or workflows/, and the
# top-level documents that speak for a skill, are what an agent loads and
# follows, so a host path there binds the skill to that host.
#
# A README is deliberately outside it, and this is the distinction the scope
# exists to make: a README's install section has to tell a reader which
# directory their own host scans, so naming hosts there is the document doing
# its job. Reporting it would argue against the one place the information
# belongs. Adapters are excluded for the same reason: an adapter is where host
# syntax is supposed to live.
NEUTRAL_ROOTS = ("references", "workflows")
NEUTRAL_FILES = ("SKILL.md", "AGENTS.md", "CONTRIBUTING.md")
# Vendored upstream material is copied verbatim, so it describes the host it
# came from. Holding it to neutrality would demand editing a copy that is only
# worth having while it stays a copy.
NEUTRAL_EXEMPT = ("references/upstream",)


def is_core_guidance(relative):
    """Whether a path inside a skill is guidance the neutrality rule governs."""
    posix = relative.as_posix()
    if posix.startswith(NEUTRAL_EXEMPT):
        return False
    return relative.parts[0] in NEUTRAL_ROOTS or posix in NEUTRAL_FILES


def host_paths(line):
    """Host-owned paths a line names, recognised by shape rather than by name.

    Returns every match, because a line naming two hosts has made the mistake
    twice and reporting one would leave the second to a later run.
    """
    found = []
    for match in HOME_DOTFILE.finditer(line):
        # `~/.local/state` names the XDG directory, not a `.local` host, so the
        # first segment is what the allowlist is asked about.
        if match.group(1).split("/")[0] not in CROSS_HOST_HOME:
            found.append(match.group(0))
    for match in HOST_INSTALL_PATH.finditer(line):
        if match.group(1) not in CROSS_HOST_DIRECTORIES:
            found.append(match.group(0))
    return found


def self_check():
    """Prove the shapes separate a host from the paths that look like one.

    Both directions matter equally. A pattern that flags everything is as
    useless as one that flags nothing, and the cross-host cases below are the
    ones that make this hard: references/settings.md is required to name the
    XDG directories, and any repository has a `.github/` whichever agent reads
    it. The false-positive cases are drawn from what the unbounded forms of
    these patterns actually hit across the skills on the author's machine.
    """
    # A host nobody has listed is the case the literal token list could not
    # reach, so it is the case that matters most.
    assert host_paths("Read `~/.windsurf/settings.json`.") == ["~/.windsurf"]
    assert host_paths('export AGENT_HOME="$HOME/.aider"') == ["$HOME/.aider"]
    assert host_paths("Copy into `.aider/skills/`.") == [".aider/skills"]
    assert host_paths("Symlink `.zed/prompts/`.") == [".zed/prompts"]
    # A host free to name its directory anything may name it something short,
    # so the second segment rather than a length floor is what decides.
    assert host_paths("Copy into `.q/prompts/`.") == [".q/prompts"]
    # Two hosts on one line are two mistakes.
    assert host_paths("Either `~/.windsurf` or `.aider/skills/`.") == ["~/.windsurf", ".aider/skills"]

    # The XDG directories are the neutral answer, not a host.
    assert host_paths("Read `$XDG_CONFIG_HOME`, defaulting to `~/.config`.") == []
    assert host_paths("Durable state under `~/.local/state`.") == []
    assert host_paths("Cache under `~/.cache/skill-name`.") == []
    assert host_paths("Source `~/.zshrc` first.") == []
    # Repository conventions belong to git hosting and editors.
    assert host_paths("CI lives in `.github/workflows/checks.yml`.") == []
    assert host_paths("Hooks in `.githooks/pre-commit`.") == []
    # Measured across the corpus: these are the shapes that made an unbounded
    # dot-directory pattern unusable. A skill naming its own state directory, a
    # URL, and a chain of method names all read as `.name/`, and none is a host.
    assert host_paths("State lives in `.scrum/state/run.db`.") == []
    assert host_paths("Artifacts under `.context/plugin-verify/map.json`.") == []
    assert host_paths("Match `drive\\.google\\.com/file/d`.") == []
    assert host_paths("Modifiers: `.add/subtract/multiply`.") == []
    assert host_paths("WebP cached under `.png/.jpg` URLs.") == []
    # Prose naming no path at all must stay silent, or the rule would fire on
    # the capability language it exists to encourage.
    assert host_paths("Resolve the run directory through the host's settings API.") == []

    # The scope is half the rule. Applying the shapes everywhere reported a
    # README's install section, which has to name the directory each host
    # scans: that is the document doing its job, and reporting it would argue
    # against the one place the information belongs.
    assert is_core_guidance(Path("SKILL.md"))
    assert is_core_guidance(Path("references/settings.md"))
    assert is_core_guidance(Path("workflows/design.md"))
    assert not is_core_guidance(Path("README.md")), "a README's install section is not a neutrality breach"
    assert not is_core_guidance(Path("agents/host-adapter.md")), "an adapter is where host syntax belongs"
    assert not is_core_guidance(Path("references/upstream/vendored.md")), "vendored material describes its host"


def main():
    parser = argparse.ArgumentParser(description="Report host-owned paths in a file, by shape rather than by name.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("self-check", help="Verify the shapes against known cases.")
    scan = commands.add_parser("scan", help="Report host-owned paths in one file.")
    scan.add_argument("path", type=Path)
    arguments = parser.parse_args()
    if arguments.command == "self-check":
        run_self_check(self_check)
        return
    found = False
    for number, line in enumerate(arguments.path.read_text(errors="replace").splitlines(), 1):
        for path in host_paths(line):
            found = True
            print(f"{arguments.path}:{number}: host-owned path {path}")
    if found:
        raise SystemExit(1)
    print("no host-owned paths found")


if __name__ == "__main__":
    main()
