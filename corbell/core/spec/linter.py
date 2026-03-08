"""Spec linter — validates spec structure for CI safety."""

from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

from corbell.core.spec.schema import parse_frontmatter

# Required markdown sections (h2)
_REQUIRED_SECTIONS = [
    "## Context",
    "## Current Architecture",
    "## Proposed Design",
    "## Reliability and Risk Constraints",
    "## Rollout Plan",
]

# Required Corbell marker pairs
_REQUIRED_MARKERS = [
    ("<!-- CORBELL_GRAPH_START -->", "<!-- CORBELL_GRAPH_END -->"),
    ("<!-- CORBELL_CONSTRAINTS_START -->", "<!-- CORBELL_CONSTRAINTS_END -->"),
]

_VALID_STATUSES = {"draft", "in-review", "approved", "implemented"}


class LintError:
    """A single linter error."""

    def __init__(self, kind: str, message: str):
        self.kind = kind
        self.message = message

    def __repr__(self):
        return f"[{self.kind}] {self.message}"


class SpecLinter:
    """Validate spec Markdown files for structure compliance.

    Safe to use in CI (returns errors, does not raise).
    """

    def lint(self, spec_path: Path | str) -> List[LintError]:
        """Lint a spec file and return all errors found.

        Args:
            spec_path: Path to the ``.md`` spec file.

        Returns:
            List of :class:`LintError`. Empty list means the file is valid.
        """
        path = Path(spec_path)
        errors: List[LintError] = []

        if not path.exists():
            return [LintError("FILE_NOT_FOUND", f"File not found: {path}")]

        content = path.read_text(encoding="utf-8")

        # 1. Front-matter parseable
        try:
            fm, body = parse_frontmatter(content)
        except Exception as e:
            return [LintError("FRONTMATTER_PARSE_ERROR", str(e))]

        # 2. Required front-matter fields
        if not fm.id:
            errors.append(LintError("MISSING_FIELD", "Front-matter 'id' is missing or empty"))
        if not fm.title or fm.title == "Untitled Feature":
            errors.append(LintError("MISSING_FIELD", "Front-matter 'title' is missing"))
        if not fm.services.primary:
            errors.append(LintError("MISSING_FIELD", "Front-matter 'services.primary' is missing"))
        if fm.status not in _VALID_STATUSES:
            errors.append(
                LintError(
                    "INVALID_STATUS",
                    f"status='{fm.status}' is invalid; must be one of {_VALID_STATUSES}",
                )
            )

        # 3. Required sections
        for section in _REQUIRED_SECTIONS:
            if section not in content:
                # Try case-insensitive
                if section.lower() not in content.lower():
                    errors.append(
                        LintError("MISSING_SECTION", f"Required section missing: {section}")
                    )

        # 4. Corbell markers
        for start_marker, end_marker in _REQUIRED_MARKERS:
            if start_marker not in content:
                errors.append(
                    LintError("MISSING_MARKER", f"Missing marker: {start_marker}")
                )
            if end_marker not in content:
                errors.append(
                    LintError("MISSING_MARKER", f"Missing marker: {end_marker}")
                )

        return errors

    def is_valid(self, spec_path: Path | str) -> bool:
        """Return True if there are no lint errors.

        Args:
            spec_path: Path to the spec file.
        """
        return len(self.lint(spec_path)) == 0
