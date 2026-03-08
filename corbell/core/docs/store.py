"""Doc pattern store — save/load learned patterns as JSON."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import List

from corbell.core.docs.models import CandidateDoc, Decision, DocPattern


class DocPatternStore:
    """Persist :class:`DocPattern` objects to a JSON file in the .corbell directory."""

    def __init__(self, store_path: Path | str):
        """Initialize the store.

        Args:
            store_path: Path to the JSON file (e.g. ``.corbell/doc_patterns.json``).
        """
        self.path = Path(store_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, patterns: List[DocPattern]) -> None:
        """Serialize and save patterns to JSON.

        Args:
            patterns: List of :class:`DocPattern` objects.
        """
        data = [dataclasses.asdict(p) for p in patterns]
        self.path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load(self) -> List[DocPattern]:
        """Load patterns from JSON.

        Returns:
            List of :class:`DocPattern` objects, or empty list if file missing.
        """
        if not self.path.exists():
            return []
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            return [self._from_dict(d) for d in raw]
        except Exception:
            return []

    @staticmethod
    def _from_dict(d: dict) -> DocPattern:
        decisions = [
            Decision(
                id=dec.get("id", ""),
                summary=dec.get("summary", ""),
                rationale=dec.get("rationale"),
                source_file=dec.get("source_file", ""),
                services_mentioned=dec.get("services_mentioned", []),
            )
            for dec in d.get("decisions", [])
        ]
        return DocPattern(
            id=d.get("id", ""),
            source_file=d.get("source_file", ""),
            detected_type=d.get("detected_type", "unknown"),
            section_headings=d.get("section_headings", []),
            frontmatter_fields=d.get("frontmatter_fields", []),
            terminology=d.get("terminology", {}),
            decisions=decisions,
            format_example=d.get("format_example", ""),
        )

    def save_candidates(self, candidates: List[CandidateDoc]) -> None:
        """Save a list of candidate docs (pre-confirmation state)."""
        data = [dataclasses.asdict(c) for c in candidates]
        candidate_path = self.path.parent / "doc_candidates.json"
        candidate_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def load_candidates(self) -> List[CandidateDoc]:
        """Load previously saved candidate docs."""
        candidate_path = self.path.parent / "doc_candidates.json"
        if not candidate_path.exists():
            return []
        try:
            raw = json.loads(candidate_path.read_text(encoding="utf-8"))
            return [
                CandidateDoc(
                    path=c.get("path", ""),
                    detected_type=c.get("detected_type", "unknown"),
                    title=c.get("title", ""),
                    confirmed=c.get("confirmed", False),
                )
                for c in raw
            ]
        except Exception:
            return []
