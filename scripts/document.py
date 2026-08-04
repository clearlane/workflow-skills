#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
# Copyright (c) 2026 Clearlane
"""Markdown and YAML document model for this repository's checks.

Checks need structure - frontmatter fields, heading hierarchy, link targets -
not text patterns. Hand-written regex parsing rediscovers fenced blocks, inline
code, and link syntax badly, so parsing lives here once on top of a CommonMark
parser and a YAML parser, and callers ask structural questions instead.
"""

import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml
    from markdown_it import MarkdownIt
    from mdit_py_plugins.front_matter import front_matter_plugin
except ModuleNotFoundError as error:  # pragma: no cover - environment guard
    raise SystemExit(
        f"Missing dependency {error.name!r}. Install with: pip install markdown-it-py mdit-py-plugins PyYAML"
    ) from error

EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "tel:")
IGNORED_DIRECTORIES = {".git", ".hg", ".svn", "__pycache__", "node_modules"}
ANCHOR_STRIP = re.compile(r"[^\w\- ]+")


def anchor(text):
    """GitHub-compatible heading anchor for intra-document link targets."""
    return ANCHOR_STRIP.sub("", text.lower()).strip().replace(" ", "-")


@dataclass(frozen=True)
class Heading:
    level: int
    text: str
    line: int

    @property
    def anchor(self):
        return anchor(self.text)


@dataclass(frozen=True)
class Link:
    target: str
    text: str
    line: int

    @property
    def external(self):
        return self.target.startswith(EXTERNAL_SCHEMES)

    @property
    def path(self):
        """Target path without its fragment, empty for a same-document link."""
        return self.target.split("#", 1)[0]

    @property
    def fragment(self):
        _, separator, fragment = self.target.partition("#")
        return fragment if separator else ""


@dataclass
class Document:
    path: Path
    text: str
    frontmatter: dict | None = None
    frontmatter_error: str | None = None
    headings: list = field(default_factory=list)
    links: list = field(default_factory=list)
    fences: list = field(default_factory=list)
    lists: list = field(default_factory=list)

    @property
    def line_count(self):
        return len(self.text.splitlines())

    def anchors(self):
        return {heading.anchor for heading in self.headings}

    def headings_at(self, level):
        return [heading for heading in self.headings if heading.level == level]

    def section(self, title, level=2):
        """Body lines under one heading, ending at the next same-or-higher heading."""
        start, end = self._section_bounds(title, level)
        if start is None:
            return None
        return "\n".join(self.text.splitlines()[start.line : end])

    def _section_bounds(self, title, level):
        start = next((heading for heading in self.headings_at(level) if heading.text == title), None)
        if start is None:
            return None, None
        lines = self.text.splitlines()
        following = [heading.line for heading in self.headings if heading.line > start.line and heading.level <= level]
        return start, (following[0] - 1 if following else len(lines))

    def section_lists(self, title, level=2):
        """Bullet lists under one heading, each still a separate list.

        Two lists separated by a paragraph mean two different things, and the
        distinction is the parser's to make: a caller counting blank lines is
        reimplementing CommonMark and will disagree with it at the margins.
        """
        start, end = self._section_bounds(title, level)
        if start is None:
            return []
        return [items for line, items in self.lists if start.line < line <= end]


def parser():
    return MarkdownIt("commonmark").use(front_matter_plugin)


def _inline_text(token):
    """Flatten an inline token to its text, with wrapped lines rejoined.

    A softbreak is where the author wrapped a line, and the words either side
    of it are separate. Dropping it silently glued them into one, which then
    failed to match the same sentence written on one line.
    """
    parts = []
    for child in token.children or []:
        if child.type == "text":
            parts.append(child.content)
        elif child.type == "softbreak":
            parts.append(" ")
    return "".join(parts)


def _collect_links(inline, parsed, line):
    """Walk one inline token, pairing each link with its text and target."""
    depth = 0
    target = ""
    text = []
    for child in inline.children or []:
        if child.type == "link_open":
            if depth == 0:
                target = child.attrGet("href") or ""
                text = []
            depth += 1
        elif child.type == "link_close":
            depth -= 1
            if depth == 0:
                parsed.links.append(Link(target=target, text="".join(text), line=line))
        elif depth and child.type in {"text", "code_inline"}:
            text.append(child.content)
        elif child.type == "image":
            source = child.attrGet("src") or ""
            if source:
                parsed.links.append(Link(target=source, text=child.content or "", line=line))


def parse(path, text=None):
    """Parse one markdown file into headings, links, fences, lists, and frontmatter."""
    path = Path(path)
    parsed = Document(path=path, text=text if text is not None else path.read_text())
    pending = None
    list_depth = 0
    items = None
    list_line = 0
    for token in parser().parse(parsed.text):
        line = (token.map[0] + 1) if token.map else 0
        if token.type == "front_matter":
            try:
                loaded = yaml.safe_load(token.content)
            except yaml.YAMLError as error:
                parsed.frontmatter_error = str(error).replace("\n", " ")
            else:
                if isinstance(loaded, dict):
                    parsed.frontmatter = loaded
                else:
                    parsed.frontmatter_error = "frontmatter is not a mapping"
        elif token.type == "heading_open":
            pending = (int(token.tag[1:]), line)
        elif token.type == "fence":
            parsed.fences.append((token.info.strip(), token.content, line))
        elif token.type in {"bullet_list_open", "ordered_list_open"}:
            # Only the outermost list is collected. A nested list elaborates
            # its parent item rather than standing as a separate list, and
            # flattening the two would merge distinctions the author drew.
            if list_depth == 0:
                items, list_line = [], line
            list_depth += 1
        elif token.type in {"bullet_list_close", "ordered_list_close"}:
            list_depth -= 1
            if list_depth == 0:
                parsed.lists.append((list_line, items))
                items = None
        elif token.type == "inline":
            if pending:
                parsed.headings.append(Heading(level=pending[0], text=_inline_text(token), line=pending[1]))
                pending = None
            elif items is not None and list_depth == 1:
                items.append(_inline_text(token))
            _collect_links(token, parsed, line)
    return parsed


def walk(root):
    """Every authored markdown file under root, skipping tooling directories."""
    root = Path(root)
    for path in sorted(root.rglob("*.md")):
        relative = path.relative_to(root)
        if any(part in IGNORED_DIRECTORIES or part.startswith(".") for part in relative.parts):
            continue
        yield parse(path)


def broken_links(root):
    """Report relative links whose file or heading anchor does not resolve."""
    root = Path(root)
    parsed = {item.path: item for item in walk(root)}
    failures = []
    for item in parsed.values():
        location = f"{item.path.relative_to(root)}"
        for link in item.links:
            if link.external or link.target.startswith("/"):
                continue
            if not link.path:
                if link.fragment and link.fragment not in item.anchors():
                    failures.append(f"{location}:{link.line}: no heading for anchor #{link.fragment}")
                continue
            resolved = (item.path.parent / link.path).resolve()
            if not resolved.exists():
                failures.append(f"{location}:{link.line}: broken link {link.target}")
                continue
            if link.fragment and resolved.suffix == ".md":
                target = parsed.get(resolved) or parse(resolved)
                if link.fragment not in target.anchors():
                    failures.append(f"{location}:{link.line}: {link.path} has no heading for anchor #{link.fragment}")
    return failures


FENCE = "```"
SELF_CHECK_SOURCE = "\n".join(
    [
        "---",
        "name: demo",
        "description: one line",
        "---",
        "",
        "# Title",
        "",
        "Real [one](other.md) and [two](other.md#deep-section) plus `[fake](nope.md)`.",
        "",
        FENCE + "bash",
        "see [fenced](missing.md)",
        FENCE,
        "",
        "## Deep Section",
        "",
        "Self [anchor](#deep-section) and [external](https://example.com/x.md).",
        "",
        "- first",
        "- second",
        "  wrapped onto a second line",
        "",
        "A paragraph between two lists.",
        "",
        "* third",
        "  - nested under third",
        "",
        "![shot](img/shot.png)",
        "",
    ]
)


def self_check():
    import tempfile

    parsed = parse(Path("demo.md"), SELF_CHECK_SOURCE)
    assert parsed.frontmatter == {"name": "demo", "description": "one line"}
    assert parsed.frontmatter_error is None
    assert [heading.text for heading in parsed.headings] == ["Title", "Deep Section"]
    assert parsed.headings_at(2)[0].anchor == "deep-section"
    targets = [link.target for link in parsed.links]
    # Inline code and fenced blocks hold no links; a real parser knows this.
    assert "nope.md" not in targets and "missing.md" not in targets

    # Lists are exposed so callers do not scan for lines starting with a dash.
    # A paragraph between two lists separates them, and that boundary carries
    # meaning a caller may depend on, so it is the parser's to draw.
    groups = parsed.section_lists("Deep Section")
    assert [len(group) for group in groups] == [2, 1], groups
    # A wrapped item is one item, and an asterisk opens a list as surely as a
    # dash does. Both were mishandled by the line scan this replaced.
    assert groups[0][1] == "second wrapped onto a second line", groups[0]
    assert groups[1][0] == "third", groups[1]
    # A nested list elaborates its parent item rather than standing alone, so
    # flattening it here would merge a distinction the author drew.
    assert all("nested under third" not in item for group in groups for item in group), groups
    # A bullet inside a fence is an example, not a list.
    assert all("fenced" not in item for group in groups for item in group), groups
    assert targets == [
        "other.md",
        "other.md#deep-section",
        "#deep-section",
        "https://example.com/x.md",
        "img/shot.png",
    ], targets
    assert parsed.links[1].path == "other.md" and parsed.links[1].fragment == "deep-section"
    assert parsed.links[3].external and not parsed.links[0].external
    assert parsed.links[0].line == 8 and parsed.links[0].text == "one"
    assert parsed.fences[0][0] == "bash"
    body = parsed.section("Deep Section")
    assert "Self [anchor]" in body and "# Title" not in body
    assert parsed.section("Absent") is None

    broken = parse(Path("bad.md"), "---\nname: [unclosed\n---\n")
    assert broken.frontmatter is None and broken.frontmatter_error
    assert parse(Path("plain.md"), "---\njust text\n---\n").frontmatter_error
    assert parse(Path("n.md"), "# No Frontmatter\n").frontmatter is None

    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        (root / "other.md").write_text("# Deep Section\n")
        (root / "demo.md").write_text(SELF_CHECK_SOURCE)
        (root / "img").mkdir()
        (root / "img" / "shot.png").write_bytes(b"")
        (root / ".hidden").mkdir()
        (root / ".hidden" / "skip.md").write_text("[gone](nowhere.md)\n")
        assert broken_links(root) == []
        assert [item.path.name for item in walk(root)] == ["demo.md", "other.md"]

        (root / "wrong.md").write_text("[a](other.md#absent)\n\n[b](gone.md)\n\n[c](#absent)\n")
        failures = broken_links(root)
        assert len(failures) == 3, failures
        assert "no heading for anchor #absent" in failures[0]
        assert "broken link gone.md" in failures[1]

        # An image whose file is missing is a broken link like any other.
        (root / "shot.md").write_text("![missing](img/absent.png)\n")
        assert any("img/absent.png" in failure for failure in broken_links(root))
    print("self-check passed")


def main():
    root = argparse.ArgumentParser(description="Inspect markdown structure and links.")
    commands = root.add_subparsers(dest="command", required=True)

    links = commands.add_parser("links", help="Report unresolvable relative links and anchors.")
    links.add_argument("root", nargs="?", type=Path, default=Path.cwd())

    outline = commands.add_parser("outline", help="Print the heading outline of one document.")
    outline.add_argument("path", type=Path)

    commands.add_parser("self-check", help="Verify the parser against known cases.")
    arguments = root.parse_args()

    if arguments.command == "self-check":
        self_check()
        return
    if arguments.command == "outline":
        for heading in parse(arguments.path).headings:
            print(f"{heading.line:>5}  {'  ' * (heading.level - 1)}{heading.text}")
        return
    failures = broken_links(arguments.root.resolve())
    for failure in failures:
        print(failure)
    if failures:
        raise SystemExit(1)
    print("link check passed")


if __name__ == "__main__":
    main()
