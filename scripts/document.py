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
# A sentence ends at a terminator followed by space. A colon ends one too: a
# lead-in that introduces a clause is a boundary, not part of what follows.
SENTENCE_END = re.compile(r"(?<=[.;:!?])\s+")
# Markdown decoration a sentence may open with, none of which is a word: list
# bullets, ordered markers, quote carets, and emphasis or code runs. A caller
# asking whether a sentence starts with a verb must not be answered "no,
# it starts with a hyphen".
SENTENCE_LEAD = re.compile(r"^[\s>*_`\"'-]*(?:\d+[.)]\s*)?[\s>*_`\"'-]*")


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
    # Two views of the same blocks, because two callers need different
    # things and collapsing them loses one. `paragraphs` is the raw source
    # span, which keeps table pipes and line breaks that sentence splitting
    # depends on. `prose` is the rendered inline text of blocks at the top
    # level only, which is what a question about what a section states
    # should see: a paragraph inside a list item or a blockquote elaborates
    # its container rather than standing on its own.
    paragraphs: list = field(default_factory=list)
    prose: list = field(default_factory=list)
    # The code span each list item opens with, or None when it opens with
    # prose. An inventory entry names its subject first, so this is the
    # subject; anything later in the item is description.
    list_subjects: list = field(default_factory=list)

    @property
    def line_count(self):
        return len(self.text.splitlines())

    def anchors(self):
        return {heading.anchor for heading in self.headings}

    def headings_at(self, level):
        return [heading for heading in self.headings if heading.level == level]

    def heading_paths(self):
        """Each heading paired with the titles of the headings it sits under.

        Whether two headings are the same section or two parallel ones depends
        on what they hang off, and recovering that from a flat list means every
        caller re-deriving the same trail. A level skipped by the author is
        carried as written rather than repaired: the ancestry is what the
        document says, not what it would say if it were well-formed.
        """
        trail = {}
        paths = []
        for heading in self.headings:
            trail = {level: text for level, text in trail.items() if level < heading.level}
            paths.append((tuple(trail[level] for level in sorted(trail)), heading))
            trail[heading.level] = heading.text
        return paths

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

    def section_list_subjects(self, title, level=2):
        """The leading code span of each list item under one heading.

        An inventory entry names its subject first and then describes it, and
        the description may itself name things: the README's schemas entry
        mentions `common.schema.json` in prose, which is a real file elsewhere
        but not an entry to check for existence at that path. Taking the span
        that opens the item keeps the subject and leaves the prose alone.
        """
        start, end = self._section_bounds(title, level)
        if start is None:
            return []
        return [leading for line, leading in self.list_subjects if start.line < line <= end and leading is not None]

    def sentences(self):
        """Every prose sentence with its line, excluding fences and headings.

        A caller asking what the prose says has to know which lines are prose,
        and a line scan cannot tell: a fenced bash loop and a heading named
        "Iterate" read as sentences to a regex and are not. Paragraph tokens
        answer that from the parse, so callers ask for sentences rather than
        rediscovering the block structure and getting it wrong.

        Tables are paragraphs to CommonMark without the table plugin, so a row
        arrives as one line holding several cells. Each cell is its own
        fragment, and gluing them across the pipes would invent sentences the
        author never wrote.
        """
        for line, body in self.paragraphs:
            for offset, raw in enumerate(body.splitlines(), line):
                cells = raw.strip().strip("|").split("|") if raw.lstrip().startswith("|") else [raw]
                for cell in cells:
                    for piece in SENTENCE_END.split(cell):
                        stripped = SENTENCE_LEAD.sub("", piece).strip().strip("*_`\"' ")
                        if stripped:
                            yield offset, stripped

    def section_paragraphs(self, title, level=2):
        """Prose paragraphs under one heading, in document order.

        Paired with section_lists, this answers whether a section says anything
        at all. A caller stripping the section text would count an HTML comment
        or a stray marker as content, because that test asks whether characters
        are present rather than whether a reader is told anything.
        """
        start, end = self._section_bounds(title, level)
        if start is None:
            return []
        return [text for line, text in self.prose if start.line < line <= end]

    def opening_paragraphs(self):
        """Prose between the title and whatever heading follows it.

        This is the position a reader lands on, so it is worth naming rather
        than leaving each caller to recompute the window from a heading list
        and get the boundary subtly wrong. An untitled document has no opening,
        which is a different fault from an empty one and is reported as such by
        the caller that cares.
        """
        title = next((heading for heading in self.headings if heading.level == 1), None)
        if title is None:
            return []
        following = [heading.line for heading in self.headings if heading.line > title.line]
        end = following[0] if following else len(self.text.splitlines()) + 1
        return [text for line, text in self.prose if title.line < line < end]


def parser():
    return MarkdownIt("commonmark").use(front_matter_plugin)


def _inline_text(token):
    """Flatten an inline token to its text, with wrapped lines rejoined.

    A softbreak is where the author wrapped a line, and the words either side
    of it are separate. Dropping it silently glued them into one, which then
    failed to match the same sentence written on one line.

    Inline code carries its content in the token itself rather than in a text
    child, so collecting only text children dropped it. The words vanished
    from every caller at once: a heading rendered "With the  CLI", its anchor
    became "with-the--cli" where GitHub serves "with-the-skills-cli", and a
    README entry naming a path in backticks flattened to its description
    alone. The marker is not reinstated, because callers compare rendered
    text, and a reader sees the word, not the backticks around it.
    """
    parts = []
    for child in token.children or []:
        if child.type in {"text", "code_inline"}:
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
    paragraph = None
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
        elif token.type == "paragraph_open":
            # The raw span is recorded for every paragraph, nested or not,
            # because sentence splitting has to see a list item's text: an
            # instruction is as much an instruction for being a bullet.
            start, end = token.map
            parsed.paragraphs.append((line, "\n".join(parsed.text.splitlines()[start:end])))
            # The rendered view is narrower. Only a paragraph standing on its
            # own counts, since one nested in a list item or a blockquote
            # elaborates the block containing it, and treating it as
            # free-standing would let a document whose whole opening is a
            # bullet read as though it had an opening paragraph.
            if token.level == 0:
                paragraph = line
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
            elif paragraph is not None:
                parsed.prose.append((paragraph, _inline_text(token)))
                paragraph = None
            elif items is not None and list_depth == 1:
                items.append(_inline_text(token))
                # An entry names its subject in the span it opens with. Later
                # spans are description: the README's schemas entry mentions
                # another schema by name in its prose, which is a real file at
                # a different path and not an entry to resolve.
                children = token.children or []
                leading = children[0].content if children and children[0].type == "code_inline" else None
                parsed.list_subjects.append((line, leading))
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
        "## With the `skills` CLI",
        "",
        "- `path/to/file.md` — a described path",
        "",
        "## Iterate",
        "",
        "Retry once. Then stop.",
        "",
        "- If it fails, retry twice.",
        "",
        FENCE + "bash",
        "for i in 1 2 3; do retry; done",
        FENCE,
        "",
        "| Cell one | Cell two |",
        "|---|---|",
        "| retry here | and here |",
        "",
        "## Repeated Shape",
        "",
        "### Same",
        "",
        "> quoted rather than stated",
        "",
        "## Other Parent",
        "",
        "### Same",
        "",
    ]
)


def self_check():
    import tempfile

    parsed = parse(Path("demo.md"), SELF_CHECK_SOURCE)
    assert parsed.frontmatter == {"name": "demo", "description": "one line"}
    assert parsed.frontmatter_error is None
    assert [heading.text for heading in parsed.headings] == [
        "Title",
        "Deep Section",
        "With the skills CLI",
        "Iterate",
        "Repeated Shape",
        "Same",
        "Other Parent",
        "Same",
    ]
    assert parsed.headings_at(2)[0].anchor == "deep-section"
    # Inline code is part of the rendered text. Dropping it silently deleted
    # words: this heading flattened to "With the  CLI" and anchored as
    # "with-the--cli", where GitHub serves "with-the-skills-cli", so a link
    # this parser called valid would have 404ed on the rendered page.
    assert parsed.headings_at(2)[1].anchor == "with-the-skills-cli", parsed.headings_at(2)[1]
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
    # The same loss in a list item: a README entry names its path in inline
    # code, so dropping it left the description with nothing to describe.
    assert parsed.section_lists("With the skills CLI")[0] == ["path/to/file.md — a described path"]

    # An inventory entry names its subject in the span it opens with, and the
    # rest of the item is description. The README check used to recover this
    # with a bullet regex anchored to a hyphen in column zero, so an asterisk
    # bullet or an indented one produced no entry at all, which exempted the
    # path it named from the existence check rather than failing it.
    subjects = parse(
        Path("subjects.md"),
        "## Inventory\n\n"
        "- `hyphen.md` — described\n"
        "* `asterisk.md` — described\n\n"
        "- prose first, then `not-a-subject.md`\n",
    ).section_list_subjects("Inventory")
    assert subjects == ["hyphen.md", "asterisk.md"], subjects
    # An indented bullet opening a section is an entry too. It is checked on
    # its own because indenting one under a preceding item makes it that
    # item's child in CommonMark, so the two cases cannot share a fixture.
    indented = parse(Path("indented.md"), "## Inventory\n\n  - `indented.md` — described\n")
    assert indented.section_list_subjects("Inventory") == ["indented.md"], indented.lists
    # A span inside the description is not the entry's subject: the README's
    # schemas entry names another schema in prose, at a path that does not
    # resolve where the entry sits.
    assert "not-a-subject.md" not in subjects, subjects

    # A heading means one thing under one parent and another under a different
    # one, so the ancestry travels with it. Two "Same" headings under two
    # parents are two sections; a caller comparing the flat list would see one
    # name twice and could not tell the two cases apart.
    repeated = [path for path, heading in parsed.heading_paths() if heading.text == "Same"]
    assert repeated == [("Title", "Repeated Shape"), ("Title", "Other Parent")], repeated
    assert parsed.heading_paths()[0][0] == (), "the title heading has no ancestry"

    # Whether a section says anything is a question about prose, not about
    # characters: this one holds a blockquote and nothing else, and a caller
    # stripping the section text would have called it populated.
    assert parsed.section_paragraphs("Same", level=3) == [], parsed.section_paragraphs("Same", level=3)
    # An image is a paragraph carrying no words, so it arrives here as one and
    # reads as empty. Dropping it at collection time would hide a block the
    # document really contains; a caller deciding what counts as content can
    # see it and decide.
    assert parsed.section_paragraphs("Deep Section") == [
        "Self anchor and external.",
        "A paragraph between two lists.",
        "",
    ], parsed.section_paragraphs("Deep Section")
    # A list item's prose is not a free-standing paragraph, or a document whose
    # entire opening is a bullet would read as though it had one. The raw view
    # deliberately does hold it, since an instruction is as much an instruction
    # for being a bullet, so the two views are asserted against each other.
    assert all("described path" not in text for _, text in parsed.prose), parsed.prose
    assert any("described path" in text for _, text in parsed.paragraphs), parsed.paragraphs
    # The opening window stops at the first heading of any level, so a document
    # whose title is followed straight by a subsection has an empty opening
    # rather than one borrowed from the section below it.
    assert parsed.opening_paragraphs() == ["Real one and two plus [fake](nope.md)."], parsed.opening_paragraphs()
    assert parse(Path("bare.md"), "# T\n\n## S\n\nprose\n").opening_paragraphs() == []
    assert parse(Path("none.md"), "no title, just prose\n").opening_paragraphs() == []
    assert parse(Path("only.md"), "# T\n\nprose\n").opening_paragraphs() == ["prose"]

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

    # Prose is what a reader reads. A heading named "Iterate" and a fenced
    # shell loop both look like control flow to a line scan and are neither,
    # so the block structure decides, not the text.
    spoken = list(parsed.sentences())
    said = [text for _, text in spoken]
    assert "Retry once." in said and "Then stop." in said, said
    assert "Iterate" not in said, said
    assert not any("done" in text for text in said), said
    # A list marker is decoration, so the sentence starts at its first word.
    assert "If it fails, retry twice." in said, said
    # A table row holds several fragments; gluing them across the pipes would
    # invent a sentence the author never wrote.
    assert "retry here" in said and "and here" in said, said
    assert all("retry here | and here" not in text for text in said), said
    # Every sentence carries the line it was written on, or a caller cannot
    # report where the problem is.
    line_of = {text: line for line, text in spoken}
    assert parsed.text.splitlines()[line_of["Retry once."] - 1] == "Retry once. Then stop.", spoken

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
