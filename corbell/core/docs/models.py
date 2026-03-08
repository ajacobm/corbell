"""Dataclasses for doc pattern learning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class Decision:
    """A design decision extracted from an existing design document."""

    id: str
    summary: str
    rationale: Optional[str]
    source_file: str
    services_mentioned: List[str] = field(default_factory=list)


@dataclass
class DocPattern:
    """Learned patterns from a team's existing design documents."""

    id: str
    source_file: str
    detected_type: str  # adr | rfc | design_doc | spec | unknown
    section_headings: List[str] = field(default_factory=list)
    frontmatter_fields: List[str] = field(default_factory=list)
    terminology: Dict[str, str] = field(default_factory=dict)
    decisions: List[Decision] = field(default_factory=list)
    format_example: str = ""  # first 500 chars of the doc


@dataclass
class CandidateDoc:
    """A candidate file found during docs:scan."""

    path: str
    detected_type: str  # adr | rfc | design_doc | spec | unknown
    title: str
    confirmed: bool = False
