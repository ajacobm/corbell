"""Notion exporter — creates or updates a Notion page from a spec."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional


class NotionExporter:
    """Export a spec Markdown file to Notion as a page.

    Requires ``notion-client`` (install: ``pip install corbell[notion]``).
    Token is read from env var ``CORBELL_NOTION_TOKEN`` or the workspace config.
    """

    def __init__(self, token: Optional[str] = None, parent_page_id: Optional[str] = None):
        """Initialize the exporter.

        Args:
            token: Notion integration token.
                Falls back to ``CORBELL_NOTION_TOKEN`` env var.
            parent_page_id: ID of the Notion page to add content under.
                Falls back to ``CORBELL_NOTION_PAGE_ID`` env var.
        """
        self.token = token or os.environ.get("CORBELL_NOTION_TOKEN")
        self.parent_page_id = parent_page_id or os.environ.get("CORBELL_NOTION_PAGE_ID")

    def export(self, spec_path: Path | str) -> Dict[str, Any]:
        """Create or update a Notion page from a spec file.

        Args:
            spec_path: Path to the ``.md`` spec file.

        Returns:
            Dict with ``page_id`` and ``url`` of the created/updated page.

        Raises:
            ImportError: If ``notion-client`` is not installed.
            ValueError: If credentials are not configured.
        """
        spec_path = Path(spec_path)
        if not self.token:
            raise ValueError(
                "Notion token not configured. Set CORBELL_NOTION_TOKEN env var "
                "or 'integrations.notion.token' in workspace.yaml."
            )
        if not self.parent_page_id:
            raise ValueError(
                "Notion parent page ID not configured. Set CORBELL_NOTION_PAGE_ID env var "
                "or 'integrations.notion.parent_page_id' in workspace.yaml."
            )

        try:
            from notion_client import Client
        except ImportError:
            raise ImportError(
                "notion-client is not installed. Run: pip install corbell[notion]"
            )

        content = spec_path.read_text(encoding="utf-8")
        title, blocks = self._markdown_to_notion(content, spec_path.stem)

        client = Client(auth=self.token)
        page = client.pages.create(
            parent={"page_id": self.parent_page_id},
            properties={"title": {"title": [{"text": {"content": title}}]}},
            children=blocks[:100],  # Notion API limit
        )

        return {"page_id": page["id"], "url": page["url"]}

    def _markdown_to_notion(
        self, content: str, filename: str
    ) -> tuple[str, List[Dict[str, Any]]]:
        """Convert Markdown to Notion API blocks (simplified)."""
        from corbell.core.spec.schema import parse_frontmatter

        fm, body = parse_frontmatter(content)
        title = fm.title or filename

        blocks: List[Dict[str, Any]] = []
        lines = body.splitlines()
        i = 0
        in_code = False
        code_lang = ""
        code_lines: List[str] = []

        while i < len(lines):
            line = lines[i]

            # Code block
            if line.startswith("```"):
                if not in_code:
                    in_code = True
                    code_lang = line[3:].strip() or "text"
                    code_lines = []
                else:
                    blocks.append(
                        {
                            "object": "block",
                            "type": "code",
                            "code": {
                                "rich_text": [{"type": "text", "text": {"content": "\n".join(code_lines)[:2000]}}],
                                "language": code_lang if code_lang in ("python", "javascript", "typescript", "go", "java", "yaml", "json", "bash", "markdown") else "plain text",
                            },
                        }
                    )
                    in_code = False
                    code_lines = []
                i += 1
                continue

            if in_code:
                code_lines.append(line)
                i += 1
                continue

            # Headings
            h_match = re.match(r"^(#{1,3})\s+(.+)", line)
            if h_match:
                level = len(h_match.group(1))
                htype = {1: "heading_1", 2: "heading_2", 3: "heading_3"}[level]
                blocks.append(
                    {
                        "object": "block",
                        "type": htype,
                        htype: {"rich_text": [{"type": "text", "text": {"content": h_match.group(2)[:2000]}}]},
                    }
                )
                i += 1
                continue

            # Bullet list
            if line.startswith("- ") or line.startswith("* "):
                blocks.append(
                    {
                        "object": "block",
                        "type": "bulleted_list_item",
                        "bulleted_list_item": {
                            "rich_text": [{"type": "text", "text": {"content": line[2:].strip()[:2000]}}]
                        },
                    }
                )
                i += 1
                continue

            # Skip HTML comments
            if line.strip().startswith("<!--"):
                i += 1
                continue

            # Paragraph (non-empty)
            if line.strip():
                blocks.append(
                    {
                        "object": "block",
                        "type": "paragraph",
                        "paragraph": {
                            "rich_text": [{"type": "text", "text": {"content": line[:2000]}}]
                        },
                    }
                )

            i += 1

        return title, blocks
