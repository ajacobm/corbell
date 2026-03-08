"""Spec front-matter schema (Pydantic v2) and constraint handling."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class ConstraintManual(BaseModel):
    """A manually added constraint in a spec."""

    id: str
    text: str
    source: str = "manual"
    added_by: Optional[str] = None
    added_at: Optional[str] = None

    model_config = {"extra": "ignore"}


class ConstraintIncidentDerived(BaseModel):
    """An incident-derived constraint.

    OSS code only reads/writes this block — never auto-populates it.
    Population is the exclusive responsibility of Corbell SaaS.
    """

    id: str
    status: str = "proposed"
    source: str = "corbell-saas"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    rule: Dict[str, Any] = Field(default_factory=dict)

    model_config = {"extra": "ignore"}


class ConstraintsBlock(BaseModel):
    """Container for all constraint types."""

    manual: List[ConstraintManual] = Field(default_factory=list)
    incident_derived: List[ConstraintIncidentDerived] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class ReviewBlock(BaseModel):
    """Review metadata written by spec:review."""

    status: Optional[str] = None  # null | pending | reviewed | approved
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None
    completeness_score: Optional[int] = None
    review_report_path: Optional[str] = None

    model_config = {"extra": "ignore"}


class DecompositionBlock(BaseModel):
    """Decomposition metadata written by spec:decompose."""

    status: Optional[str] = None  # null | decomposed
    task_file: Optional[str] = None
    linear_synced: bool = False
    notion_synced: bool = False

    model_config = {"extra": "ignore"}


class ServicesBlock(BaseModel):
    """Service references in a spec."""

    primary: str
    related: List[str] = Field(default_factory=list)

    model_config = {"extra": "ignore"}


class SpecFrontmatter(BaseModel):
    """Pydantic model for spec YAML front-matter."""

    id: str = ""
    title: str = "Untitled Feature"
    feature_ref: str = ""
    services: ServicesBlock = Field(default_factory=lambda: ServicesBlock(primary=""))
    status: str = "draft"  # draft | in-review | approved | implemented
    author: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    context_refs: Dict[str, Any] = Field(default_factory=dict)
    review: ReviewBlock = Field(default_factory=ReviewBlock)
    decomposition: DecompositionBlock = Field(default_factory=DecompositionBlock)
    constraints: ConstraintsBlock = Field(default_factory=ConstraintsBlock)

    model_config = {"extra": "ignore"}


# ---------------------------------------------------------------------------
# Front-matter parsing helpers
# ---------------------------------------------------------------------------

_FM_RE = re.compile(r"^---\n(.*?)\n---\n?", re.DOTALL)


def parse_frontmatter(content: str) -> tuple[SpecFrontmatter, str]:
    """Parse YAML front-matter from a spec Markdown file.

    Args:
        content: Full file content.

    Returns:
        Tuple of (SpecFrontmatter, body_markdown).

    Raises:
        ValueError: If YAML cannot be parsed.
    """
    m = _FM_RE.match(content)
    if not m:
        return SpecFrontmatter(), content

    raw = yaml.safe_load(m.group(1)) or {}
    fm = SpecFrontmatter.model_validate(raw)
    body = content[m.end():]
    return fm, body


def serialize_frontmatter(fm: SpecFrontmatter) -> str:
    """Serialize a SpecFrontmatter to a YAML front-matter block.

    Args:
        fm: The front-matter model to serialize.

    Returns:
        String ``---\\n<yaml>\\n---\\n``.
    """
    data = fm.model_dump(exclude_none=False)
    return "---\n" + yaml.dump(data, default_flow_style=False, allow_unicode=True) + "---\n\n"


def update_frontmatter(spec_path, **updates) -> None:
    """Read a spec file, update front-matter fields, and write back.

    This function NEVER modifies the spec body — only the YAML front-matter.

    Args:
        spec_path: Path to the .md spec file.
        **updates: Field names and new values to update on the front-matter.
    """
    from pathlib import Path

    path = Path(spec_path)
    content = path.read_text(encoding="utf-8")
    fm, body = parse_frontmatter(content)

    for key, value in updates.items():
        if hasattr(fm, key):
            setattr(fm, key, value)
        elif "." in key:
            parts = key.split(".", 1)
            obj = getattr(fm, parts[0], None)
            if obj is not None and hasattr(obj, parts[1]):
                setattr(obj, parts[1], value)

    new_content = serialize_frontmatter(fm) + body
    path.write_text(new_content, encoding="utf-8")
