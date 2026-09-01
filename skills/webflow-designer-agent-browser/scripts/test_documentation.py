#!/usr/bin/env python3
"""Validate the Webflow skill's reader-facing documentation and diagrams."""

from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unittest
from urllib.parse import unquote, urlsplit
import xml.etree.ElementTree as ElementTree


SKILL_DIR = Path(__file__).resolve().parents[1]
ROOT_DIR = SKILL_DIR.parents[1]
sys.path.insert(0, str(SKILL_DIR / "lib"))

from webflow_browser import cli as lifecycle_cli
from webflow_browser import core as lifecycle_core


README = SKILL_DIR / "README.md"
MARKDOWN_FILES = [ROOT_DIR / "README.md", SKILL_DIR / "SKILL.md", README, *sorted((SKILL_DIR / "references").glob("*.md"))]
HTML_FILES = sorted((SKILL_DIR / "references").glob("*.html"))
MARKDOWN_LINK = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
MERMAID_BLOCK = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
SVG_BLOCK = re.compile(r"<svg\b.*?</svg>", re.DOTALL)
CLI_EXAMPLE = re.compile(
    r'cat <<JSON \| "\$CLI" (prepare|verify|finish)\n(.*?)\nJSON', re.DOTALL
)
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


class DocumentParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tags: list[str] = []
        self.external_sources: list[str] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.json_scripts: list[str] = []
        self.svg_labels: list[str | None] = []
        self.stack: list[str] = []
        self.structure_errors: list[str] = []
        self._json_depth = 0
        self._json_parts: list[str] = []
        self._network_text_depth = 0
        self._network_text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        if tag not in VOID_TAGS:
            self.stack.append(tag)
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(str(values["id"]))
        source = values.get("src")
        if source and urlsplit(source).scheme in {"http", "https"}:
            self.external_sources.append(source)
        if values.get("href"):
            self.links.append(str(values["href"]))
            rel = str(values.get("rel", "")).lower()
            if tag == "link" and "stylesheet" in rel and urlsplit(str(values["href"])).scheme:
                self.external_sources.append(str(values["href"]))
        if tag == "svg":
            self.svg_labels.append(
                values.get("aria-label") or values.get("aria-labelledby")
            )
        if tag == "script" and values.get("type") == "application/json":
            self._json_depth = 1
            self._json_parts = []
        if tag in {"script", "style"}:
            self._network_text_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if not self.stack or self.stack[-1] != tag:
            current = self.stack[-1] if self.stack else "<empty>"
            self.structure_errors.append(f"expected </{current}>, found </{tag}>")
        else:
            self.stack.pop()
        if tag == "script" and self._json_depth:
            self.json_scripts.append("".join(self._json_parts))
            self._json_depth = 0
        if tag in {"script", "style"} and self._network_text_depth:
            self._network_text_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._json_depth:
            self._json_parts.append(data)
        if self._network_text_depth:
            self._network_text_parts.append(data)

    @property
    def network_text(self) -> str:
        return "\n".join(self._network_text_parts)


def markdown_anchors(path: Path) -> set[str]:
    anchors: set[str] = set()
    counts: dict[str, int] = {}
    fenced = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("```"):
            fenced = not fenced
            continue
        if fenced or not line.startswith("#"):
            continue
        heading = line.lstrip("#").strip().lower()
        slug = re.sub(r"[^\w\- ]", "", heading, flags=re.UNICODE).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(slug if count == 0 else f"{slug}-{count}")
    return anchors


def html_ids(path: Path) -> set[str]:
    parser = DocumentParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser.ids


class WebflowDocumentationTests(unittest.TestCase):
    def test_reader_guide_has_the_four_required_visuals(self) -> None:
        source = README.read_text(encoding="utf-8")
        diagrams = MERMAID_BLOCK.findall(source)
        self.assertEqual(len(diagrams), 4)
        for diagram in diagrams:
            lines = [line.strip() for line in diagram.splitlines() if line.strip()]
            self.assertTrue(lines[0].startswith("flowchart "))
            self.assertEqual(
                sum(line.startswith("subgraph ") for line in lines),
                sum(line == "end" for line in lines),
            )

    def test_local_markdown_links_resolve(self) -> None:
        failures: list[str] = []
        for path in MARKDOWN_FILES:
            source = path.read_text(encoding="utf-8")
            for raw_target in MARKDOWN_LINK.findall(source):
                target = raw_target.strip().split(maxsplit=1)[0].strip("<>")
                parts = urlsplit(target)
                if parts.scheme:
                    continue
                relative = unquote(parts.path)
                destination = (path.parent / relative).resolve() if relative else path.resolve()
                if not destination.exists():
                    failures.append(f"{path.relative_to(ROOT_DIR)} -> {target}")
                    continue
                if parts.fragment:
                    if destination.suffix == ".md":
                        anchors = markdown_anchors(destination)
                    elif destination.suffix == ".html":
                        anchors = html_ids(destination)
                    else:
                        continue
                    if unquote(parts.fragment) not in anchors:
                        failures.append(f"{path.relative_to(ROOT_DIR)} -> {target}")
        self.assertEqual(failures, [])

    def test_reader_cli_examples_match_the_protocol_and_exit_contract(self) -> None:
        source = README.read_text(encoding="utf-8")
        examples = CLI_EXAMPLE.findall(source)
        self.assertEqual([command for command, _body in examples], ["prepare", "verify", "finish"])
        transaction = "00000000-0000-4000-8000-000000000000"
        for command, body in examples:
            normalized = body.replace("$DESIGNER_URL", "https://design.webflow.com/?pageId=synthetic-page")
            normalized = normalized.replace("<transaction-id-from-prepare>", transaction)
            request = lifecycle_core.parse_request(normalized)
            self.assertEqual(request["operation"], command)
        self.assertEqual(lifecycle_cli.EXIT_FAILURE, 1)
        self.assertEqual(lifecycle_cli.EXIT_INPUT, 2)
        self.assertEqual(lifecycle_cli.EXIT_BLOCKED, 3)
        self.assertEqual(lifecycle_cli.EXIT_CONFLICT, 4)
        self.assertEqual(
            lifecycle_cli._exit_code({"status": "blocked", "classification": "auth_required"}),
            lifecycle_cli.EXIT_BLOCKED,
        )

    def test_html_guides_have_valid_structure_svg_and_timeline_json(self) -> None:
        self.assertGreaterEqual(len(HTML_FILES), 4)
        for path in HTML_FILES:
            with self.subTest(path=path.name):
                source = path.read_text(encoding="utf-8")
                parser = DocumentParser()
                parser.feed(source)
                parser.close()
                self.assertEqual(parser.structure_errors, [])
                self.assertEqual(parser.stack, [])
                self.assertIn("title", parser.tags)
                self.assertIn("h1", parser.tags)
                self.assertEqual(parser.external_sources, [])
                self.assertNotRegex(
                    parser.network_text,
                    r"(?i)@import\s|url\(\s*['\"]?https?://|\b(fetch|XMLHttpRequest|WebSocket|EventSource)\s*\(",
                )
                self.assertTrue(all(parser.svg_labels))
                for target in parser.links:
                    parts = urlsplit(target)
                    if parts.scheme or target.startswith("#") or not parts.path:
                        continue
                    self.assertTrue(
                        (path.parent / unquote(parts.path)).resolve().exists(),
                        f"{path.name} -> {target}",
                    )
                for timeline in parser.json_scripts:
                    self.assertIsInstance(json.loads(timeline), (dict, list))
                for svg in SVG_BLOCK.findall(source):
                    ElementTree.fromstring(svg)


if __name__ == "__main__":
    unittest.main()
