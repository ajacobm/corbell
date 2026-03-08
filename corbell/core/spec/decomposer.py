"""Spec decomposer — converts approved specs into parallel task tracks."""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from corbell.core.llm_client import LLMClient
from corbell.core.spec.schema import parse_frontmatter

_DECOMPOSE_SYSTEM_PROMPT = """\
You are a senior engineering lead decomposing a technical design document into
a set of parallel engineering tasks.

Your output MUST be valid YAML in this exact format:

spec_id: <spec_id>
title: <feature_title>
generated_at: <today>
tracks:
  - id: track-1
    name: "Track Name"
    description: "What this track achieves."
    owner_service: service-id
    can_start_after: []
    tasks:
      - id: task-1-1
        title: "Short task title"
        description: "Detailed description of what needs to be done."
        files_affected:
          - path/to/file.py
        estimated_days: 2

Rules:
1. Create 2–5 parallel tracks where possible (backend models, API, async jobs, tests, migrations).
2. Each task must be concrete (specific function/class/endpoint to create or modify).
3. Identify dependencies between tracks using can_start_after.
4. Estimated days should be honest (1–5 days per task).
5. Return ONLY the YAML, nothing else.
"""


class SpecDecomposer:
    """Convert an approved spec into a task YAML file.

    Requires ``status: approved`` in spec front-matter; raises ValueError otherwise.
    """

    def __init__(self, llm_client: Optional[LLMClient] = None):
        """Initialize the decomposer.

        Args:
            llm_client: Optional LLM client for intelligent decomposition.
                Falls back to template without LLM.
        """
        self.llm = llm_client

    def decompose(self, spec_path: Path | str, output_dir: Optional[Path] = None) -> Path:
        """Decompose an approved spec into a tasks YAML file.

        Args:
            spec_path: Path to the approved spec ``.md`` file.
            output_dir: Output directory for the tasks file.
                Defaults to the same directory as the spec.

        Returns:
            Path to the generated ``.tasks.yaml`` file.

        Raises:
            FileNotFoundError: If spec does not exist.
            ValueError: If spec status is not ``approved``.
        """
        spec_path = Path(spec_path)
        if not spec_path.exists():
            raise FileNotFoundError(f"Spec not found: {spec_path}")

        content = spec_path.read_text(encoding="utf-8")
        fm, body = parse_frontmatter(content)

        if fm.status != "approved":
            raise ValueError(
                f"Spec '{fm.id}' has status='{fm.status}'. "
                f"Only approved specs can be decomposed. "
                f"Run `corbell spec:approve` first."
            )

        output_dir = output_dir or spec_path.parent
        out_path = output_dir / f"{fm.id}.tasks.yaml"

        if self.llm and self.llm.is_configured:
            tasks_yaml = self._decompose_with_llm(fm.id, fm.title, fm.services.primary, body)
        else:
            tasks_yaml = self._template_decomposition(fm.id, fm.title, fm.services.primary)

        out_path.write_text(tasks_yaml, encoding="utf-8")

        # Update spec front-matter decomposition block
        from corbell.core.spec.schema import update_frontmatter
        update_frontmatter(
            spec_path,
            **{
                "decomposition.status": "decomposed",
                "decomposition.task_file": str(out_path.name),
            },
        )

        return out_path

    def _decompose_with_llm(
        self, spec_id: str, title: str, primary_service: str, body: str
    ) -> str:
        """Use LLM to produce intelligent task decomposition."""
        assert self.llm
        user = (
            f"spec_id: {spec_id}\ntitle: {title}\nprimary_service: {primary_service}\n\n"
            f"## Spec Body\n{body[:8000]}\n\n"
            "Decompose this spec into parallel implementation tracks and tasks."
        )
        raw = self.llm.call(
            system_prompt=_DECOMPOSE_SYSTEM_PROMPT,
            user_prompt=user,
            max_tokens=4000,
            temperature=0.1,
            request_type="spec_decompose",
        )
        # Validate YAML
        try:
            yaml.safe_load(raw)
            return raw
        except yaml.YAMLError:
            return self._template_decomposition(spec_id, title, primary_service)

    def _template_decomposition(self, spec_id: str, title: str, primary_service: str) -> str:
        """Template task decomposition without LLM."""
        return yaml.dump(
            {
                "spec_id": spec_id,
                "title": title,
                "generated_at": str(date.today()),
                "tracks": [
                    {
                        "id": "track-1",
                        "name": "Data Model & Schema",
                        "description": "Database migrations and model changes",
                        "owner_service": primary_service,
                        "can_start_after": [],
                        "tasks": [
                            {
                                "id": "task-1-1",
                                "title": "Create database migrations",
                                "description": "TODO: Add specific migration details from spec.",
                                "files_affected": [],
                                "estimated_days": 2,
                            }
                        ],
                    },
                    {
                        "id": "track-2",
                        "name": "Business Logic",
                        "description": "Core service implementation",
                        "owner_service": primary_service,
                        "can_start_after": ["track-1"],
                        "tasks": [
                            {
                                "id": "task-2-1",
                                "title": "Implement core feature logic",
                                "description": "TODO: Add specific implementation details from spec.",
                                "files_affected": [],
                                "estimated_days": 3,
                            }
                        ],
                    },
                    {
                        "id": "track-3",
                        "name": "Tests",
                        "description": "Unit and integration tests",
                        "owner_service": primary_service,
                        "can_start_after": ["track-1"],
                        "tasks": [
                            {
                                "id": "task-3-1",
                                "title": "Write unit tests",
                                "description": "TODO: Add specific test cases from spec.",
                                "files_affected": [],
                                "estimated_days": 2,
                            }
                        ],
                    },
                ],
            },
            default_flow_style=False,
            allow_unicode=True,
        )
