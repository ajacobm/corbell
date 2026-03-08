"""Spec reviewer — compares spec claims against graph, writes .review.md sidecar.

Never modifies spec body content. Only writes .review.md and updates front-matter review fields.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from corbell.core.docs.learner import DocLearner
from corbell.core.docs.models import DocPattern
from corbell.core.graph.schema import GraphStore
from corbell.core.llm_client import LLMClient
from corbell.core.spec.schema import ReviewBlock, parse_frontmatter, update_frontmatter

_REVIEW_SYSTEM_PROMPT = """\
You are a senior engineering reviewer evaluating a technical design document.

Your job is to produce a review report. The review covers:
1. **Architecture Accuracy** — Are service dependencies in the spec consistent with the actual graph?
2. **Completeness** — Are all required sections present and substantive?
3. **Risk Coverage** — Are failure modes and mitigations adequate?
4. **Constraint Compliance** — Are architectural constraints honored?
5. **Rollout Safety** — Is the rollout plan realistic and safe?

Format your output as Markdown with these sections:
## Summary
A 2–3 sentence overall assessment.

## Score
Completeness: X/10
Architecture Accuracy: X/10
Risk Coverage: X/10

## Issues Found
- [CRITICAL] ...
- [WARNING] ...
- [NOTE] ...

## Recommended Changes
- ...

## Open Questions
- ...
"""


class SpecReviewer:
    """Review a spec against the architecture graph and learned patterns.

    Writes a ``.review.md`` sidecar next to the spec file.
    Updates spec front-matter review block (status, score, report path)
    but NEVER modifies the spec body.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        doc_patterns: Optional[List[DocPattern]] = None,
        llm_client: Optional[LLMClient] = None,
    ):
        self.graph = graph_store
        self.doc_patterns = doc_patterns or []
        self.llm = llm_client

    def review(self, spec_path: Path | str, reviewer: str = "") -> Path:
        """Review a spec and produce a .review.md sidecar.

        Args:
            spec_path: Path to the spec ``.md`` file.
            reviewer: Name of the reviewer (optional).

        Returns:
            Path to the ``.review.md`` sidecar file.

        Raises:
            FileNotFoundError: If spec file does not exist.
        """
        spec_path = Path(spec_path)
        if not spec_path.exists():
            raise FileNotFoundError(f"Spec not found: {spec_path}")

        content = spec_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        # Graph checks
        graph_issues = self._check_graph_consistency(fm.services.primary, fm.services.related, body)

        # Structure checks
        structure_issues = self._check_structure(body)

        # LLM review (optional)
        if self.llm and self.llm.is_configured:
            review_body = self._llm_review(body, fm.services.primary, graph_issues, structure_issues)
        else:
            review_body = self._template_review(graph_issues, structure_issues)

        # Write .review.md sidecar
        review_path = spec_path.with_suffix(".review.md")
        review_header = f"# Review: {fm.title}\n\n*Reviewed: {date.today()} | Spec: {fm.id}*\n\n"
        review_path.write_text(review_header + review_body, encoding="utf-8")

        # Compute completeness score (0–10)
        score = self._compute_score(structure_issues, graph_issues)

        # Update spec front-matter (review block only)
        update_frontmatter(
            spec_path,
            **{
                "review.status": "reviewed",
                "review.reviewed_by": reviewer or "corbell",
                "review.reviewed_at": str(date.today()),
                "review.completeness_score": score,
                "review.review_report_path": str(review_path.name),
            },
        )

        return review_path

    # ------------------------------------------------------------------ #
    # Checks                                                               #
    # ------------------------------------------------------------------ #

    def _check_graph_consistency(
        self, primary: str, related: List[str], body: str
    ) -> List[str]:
        """Check that services mentioned in spec exist in graph."""
        issues = []
        all_svcs = self.graph.get_all_services()
        known_ids = {s.id for s in all_svcs}

        if primary and primary not in known_ids:
            issues.append(f"Primary service `{primary}` not found in graph — run `corbell graph:build`")

        for svc_id in related:
            if svc_id not in known_ids:
                issues.append(f"Related service `{svc_id}` not found in graph")

        # Check if spec mentions services that exist in graph for cross-reference
        for svc in all_svcs:
            if svc.id in body and svc.id not in ([primary] + related):
                issues.append(f"NOTE: service `{svc.id}` mentioned in spec body but not listed in front-matter")

        return issues

    def _check_structure(self, body: str) -> List[str]:
        """Check for required sections."""
        required = [
            ("## Context", "Context section"),
            ("## Current Architecture", "Current Architecture section"),
            ("## Proposed Design", "Proposed Design section"),
            ("## Reliability and Risk Constraints", "Reliability and Risk Constraints section"),
            ("## Rollout Plan", "Rollout Plan section"),
            ("<!-- CORBELL_GRAPH_START -->", "CORBELL_GRAPH markers"),
            ("<!-- CORBELL_CONSTRAINTS_START -->", "CORBELL_CONSTRAINTS markers"),
        ]
        issues = []
        for marker, label in required:
            if marker not in body:
                issues.append(f"MISSING: {label}")

        # Check for empty sections
        if "<!-- Add constraints" in body or len(body) < 500:
            issues.append("WARNING: Spec body appears incomplete or template-only")

        return issues

    def _compute_score(self, structure_issues: List[str], graph_issues: List[str]) -> int:
        score = 10
        for issue in structure_issues + graph_issues:
            if "MISSING" in issue.upper():
                score -= 2
            elif "WARNING" in issue.upper():
                score -= 1
        return max(0, score)

    # ------------------------------------------------------------------ #
    # Review generation                                                    #
    # ------------------------------------------------------------------ #

    def _llm_review(
        self,
        body: str,
        primary_service: str,
        graph_issues: List[str],
        structure_issues: List[str],
    ) -> str:
        """Use LLM to produce a rich review report."""
        assert self.llm

        graph_summary = self._get_graph_summary(primary_service)
        issues_block = "\n".join(
            [f"- {i}" for i in graph_issues + structure_issues]
        ) or "None found by static analysis."

        user = (
            f"## Spec Content\n{body[:8000]}\n\n"
            f"## Graph-Detected Issues\n{issues_block}\n\n"
            f"## Current Service Graph\n{graph_summary}\n\n"
            f"Now produce the review report following the system prompt structure."
        )

        return self.llm.call(
            system_prompt=_REVIEW_SYSTEM_PROMPT,
            user_prompt=user,
            max_tokens=3000,
            request_type="spec_review",
        )

    def _template_review(
        self, graph_issues: List[str], structure_issues: List[str]
    ) -> str:
        """Produce a template review when no LLM is configured."""
        all_issues = structure_issues + graph_issues
        lines = [
            "## Summary\n",
            "Static analysis complete (template mode — configure LLM for richer review).\n",
            "## Issues Found\n",
        ]
        if all_issues:
            for issue in all_issues:
                prefix = "[CRITICAL]" if "MISSING" in issue.upper() else "[WARNING]"
                lines.append(f"- {prefix} {issue}")
        else:
            lines.append("- No issues found.")
        lines.append("\n## Score\nCompleteness: N/A (template mode)\n")
        return "\n".join(lines)

    def _get_graph_summary(self, service_id: str) -> str:
        svc = self.graph.get_service(service_id)
        if not svc:
            return f"Service `{service_id}` not found in graph."
        deps = self.graph.get_dependencies(service_id)
        lines = [f"Service: {svc.id} ({svc.language})"]
        for dep in deps:
            lines.append(f"  → {dep.target_id} [{dep.kind}]")
        return "\n".join(lines)
