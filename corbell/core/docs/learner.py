"""Doc learner — extracts patterns, decisions, and conventions from design docs."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from corbell.core.docs.models import CandidateDoc, Decision, DocPattern

_HDR_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
_DECISION_RE = re.compile(
    r"(?:decided|chose|selected|we use|we chose|decision[:\s])\s+([^\n.]+)",
    re.IGNORECASE,
)
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)

# Keywords for categorising decision types
_CATEGORY_KEYWORDS = {
    "database_choice": ["database", "storage", "postgres", "dynamodb", "mongodb", "sql"],
    "async_processing": ["queue", "async", "kafka", "sqs", "background", "message"],
    "api_design": ["api", "rest", "graphql", "grpc", "endpoint"],
    "caching_strategy": ["cache", "redis", "memcached", "caching"],
    "authentication": ["auth", "login", "jwt", "oauth", "session"],
    "deployment": ["deploy", "docker", "kubernetes", "container"],
}


class DocLearner:
    """Extract patterns and decisions from confirmed design documents.

    Can optionally use an LLM for richer extraction; falls back to regex
    analysis when no LLM is configured.
    """

    def __init__(self, llm_client=None):
        """Initialize the learner.

        Args:
            llm_client: Optional :class:`~corbell.core.llm_client.LLMClient`.
                If None, uses regex-only extraction.
        """
        self.llm = llm_client

    def learn_from_docs(self, docs: List[CandidateDoc]) -> List[DocPattern]:
        """Process confirmed docs and return their extracted patterns.

        Args:
            docs: List of confirmed :class:`CandidateDoc` instances.

        Returns:
            List of :class:`DocPattern` objects.
        """
        patterns: List[DocPattern] = []
        for doc in docs:
            if not doc.confirmed:
                continue
            pattern = self._extract_pattern(Path(doc.path))
            if pattern:
                patterns.append(pattern)
        return patterns

    def _extract_pattern(self, path: Path) -> Optional[DocPattern]:
        try:
            content = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return None

        doc_id = path.stem

        # Detect type
        doc_type = self._detect_type(path.name, content)

        # Section headings
        headings = _HDR_RE.findall(content)[:20]

        # Front-matter fields
        fm_match = _FRONTMATTER_RE.match(content)
        fm_fields: List[str] = []
        if fm_match:
            fm_fields = re.findall(r"^(\w+):", fm_match.group(1), re.MULTILINE)

        # Terminology: pick capitalised multi-word terms
        term_re = re.compile(r"\b([A-Z][a-z]+(?:\s[A-Z][a-z]+)+)\b")
        terms = list(dict.fromkeys(term_re.findall(content)))[:20]
        terminology = {t: t for t in terms}

        # Decisions (regex)
        decisions = self._extract_decisions_regex(content, doc_id, path)

        # LLM-enhanced extraction
        if self.llm and self.llm.is_configured:
            decisions = self._extract_decisions_llm(content, doc_id, path, decisions)

        return DocPattern(
            id=doc_id,
            source_file=str(path),
            detected_type=doc_type,
            section_headings=headings,
            frontmatter_fields=fm_fields,
            terminology=terminology,
            decisions=decisions,
            format_example=content[:500],
        )

    def _detect_type(self, name: str, content: str) -> str:
        text = (name + " " + content[:1000]).lower()
        if any(k in text for k in ("adr", "architecture decision")):
            return "adr"
        if any(k in text for k in ("rfc", "request for comment")):
            return "rfc"
        if any(k in text for k in ("spec", "specification")):
            return "spec"
        if any(k in text for k in ("design", "architecture")):
            return "design_doc"
        return "unknown"

    def _extract_decisions_regex(
        self, content: str, doc_id: str, path: Path
    ) -> List[Decision]:
        decisions: List[Decision] = []
        for i, m in enumerate(_DECISION_RE.finditer(content)):
            summary = m.group(1).strip()
            services = self._extract_mentioned_services(content)
            decisions.append(
                Decision(
                    id=f"{doc_id}_d{i}",
                    summary=summary,
                    rationale=None,
                    source_file=str(path),
                    services_mentioned=services,
                )
            )
        return decisions[:10]  # cap

    def _extract_decisions_llm(
        self,
        content: str,
        doc_id: str,
        path: Path,
        fallback: List[Decision],
    ) -> List[Decision]:
        """Use LLM to extract richer decisions from the doc content."""
        system = (
            "You are analyzing a design document to extract specific design decisions.\n"
            "For each decision, return a JSON array with objects: "
            "{\"summary\": str, \"rationale\": str|null, \"services\": [str]}.\n"
            "Return ONLY a valid JSON array, no other text."
        )
        user = f"Extract design decisions from this document:\n\n{content[:4000]}"
        try:
            resp = self.llm.call(system, user, max_tokens=2000)
            # Clean markdown fences
            resp = resp.strip()
            if resp.startswith("```"):
                resp = re.sub(r"^```[a-z]*\n?", "", resp)
                resp = re.sub(r"\n?```$", "", resp)
            start = resp.find("[")
            end = resp.rfind("]")
            if start != -1 and end != -1:
                resp = resp[start : end + 1]
            items = json.loads(resp)
            return [
                Decision(
                    id=f"{doc_id}_d{i}",
                    summary=it.get("summary", ""),
                    rationale=it.get("rationale"),
                    source_file=str(path),
                    services_mentioned=it.get("services", []),
                )
                for i, it in enumerate(items)
                if isinstance(it, dict) and it.get("summary")
            ]
        except Exception:
            return fallback

    def _extract_mentioned_services(self, content: str) -> List[str]:
        # Simple heuristic: look for patterns like "X service" or "X-service"
        matches = re.findall(r"\b(\w[\w-]+(?:-service|-api|-worker|_service))\b", content)
        return list(dict.fromkeys(matches))[:5]

    # ------------------------------------------------------------------ #
    # Pattern formatting for LLM prompt
    # ------------------------------------------------------------------ #

    def format_patterns_for_prompt(self, patterns: List[DocPattern]) -> str:
        """Format stored patterns into a block suitable for LLM context.

        Args:
            patterns: List of :class:`DocPattern` to include.

        Returns:
            Formatted string block for injection into LLM prompts.
        """
        if not patterns:
            return "No established design patterns found for this project.\n"

        lines = ["## Established Design Patterns From Your Team's Docs\n"]
        lines.append("Follow these where relevant:\n")

        for i, pat in enumerate(patterns, 1):
            lines.append(f"### Pattern Source {i}: {pat.source_file} ({pat.detected_type})")
            if pat.section_headings:
                lines.append(f"**Sections**: {', '.join(pat.section_headings[:5])}")
            for dec in pat.decisions[:3]:
                lines.append(f"- **Decision**: {dec.summary}")
                if dec.rationale:
                    lines.append(f"  *Rationale*: {dec.rationale}")
            lines.append("")

        return "\n".join(lines)
