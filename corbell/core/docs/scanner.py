"""Doc scanner — finds candidate design documents in repos."""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import List

from corbell.core.docs.models import CandidateDoc

_DEFAULT_PATTERNS = [
    "*.design.md", "*-spec.md", "RFC-*.md", "ADR-*.md", "DESIGN.md",
    "*-design.md", "*_design.md", "ARCHITECTURE.md", "architecture.md",
    "*.rfc.md", "*.adr.md",
]

_TYPE_HINTS = {
    "adr": ["ADR", "Architecture Decision", "decision record"],
    "rfc": ["RFC", "Request for Comment", "Proposal"],
    "spec": ["Spec", "Specification", "spec:"],
    "design_doc": ["Design", "Architecture", "System Design", "Technical Design"],
}

_HDR_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
_TITLE_RE = re.compile(r"^#\s+(.+)$", re.MULTILINE)


class DocScanner:
    """Scan repository directories for candidate design/spec documents."""

    def __init__(self, patterns: List[str] | None = None):
        """Initialize with filename glob patterns to match.

        Args:
            patterns: Glob patterns for filenames (default: common ADR/RFC/design patterns).
        """
        self.patterns = patterns or _DEFAULT_PATTERNS

    def scan(self, paths: List[Path | str]) -> List[CandidateDoc]:
        """Scan a list of directories (or files) and return candidate docs.

        Args:
            paths: Directories or explicit file paths to search.

        Returns:
            List of :class:`CandidateDoc` (not yet confirmed).
        """
        candidates: List[CandidateDoc] = []
        seen: set = set()

        for root in paths:
            root = Path(root)
            if root.is_file():
                if root.suffix == ".md" and str(root) not in seen:
                    seen.add(str(root))
                    candidates.append(self._classify(root))
                continue
            if not root.is_dir():
                continue
            for fp in root.rglob("*.md"):
                if str(fp) in seen:
                    continue
                if not self._matches_pattern(fp.name):
                    continue
                seen.add(str(fp))
                candidates.append(self._classify(fp))

        return candidates

    def _matches_pattern(self, name: str) -> bool:
        return any(fnmatch.fnmatch(name, pat) for pat in self.patterns)

    def _classify(self, fp: Path) -> CandidateDoc:
        doc_type = "unknown"
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
            doc_type = self._detect_type(fp.name, content)
            title = self._extract_title(content) or fp.stem
        except Exception:
            title = fp.stem

        return CandidateDoc(
            path=str(fp),
            detected_type=doc_type,
            title=title,
        )

    def _detect_type(self, name: str, content: str) -> str:
        text = (name + " " + content[:2000]).lower()
        for dtype, hints in _TYPE_HINTS.items():
            if any(h.lower() in text for h in hints):
                return dtype
        return "design_doc"

    def _extract_title(self, content: str) -> str:
        m = _TITLE_RE.search(content)
        return m.group(1).strip() if m else ""
