"""Tests for spec schema, linter, generator, reviewer, and decomposer."""

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from corbell.core.spec.schema import (
    SpecFrontmatter,
    parse_frontmatter,
    serialize_frontmatter,
    update_frontmatter,
)
from corbell.core.spec.linter import SpecLinter
from corbell.core.spec.decomposer import SpecDecomposer


# ─── Schema tests ──────────────────────────────────────────────────────────

def test_parse_frontmatter_valid(sample_spec):
    content = sample_spec.read_text()
    fm, body = parse_frontmatter(content)
    assert fm.id == "test-feature"
    assert fm.title == "Test Feature"
    assert fm.status == "draft"
    assert fm.services.primary == "sample-service"
    assert "## Context" in body


def test_parse_frontmatter_no_frontmatter():
    content = "# Just a doc\n\nNo frontmatter."
    fm, body = parse_frontmatter(content)
    assert fm.id == ""
    assert "# Just a doc" in body


def test_serialize_frontmatter_roundtrip():
    fm = SpecFrontmatter(
        id="test-spec",
        title="Test Spec",
        status="draft",
    )
    fm.services.primary = "my-service"
    serialized = serialize_frontmatter(fm)
    assert serialized.startswith("---\n")
    fm2, _ = parse_frontmatter(serialized + "body here")
    assert fm2.id == "test-spec"
    assert fm2.services.primary == "my-service"


def test_update_frontmatter(sample_spec):
    update_frontmatter(sample_spec, status="in-review")
    content = sample_spec.read_text()
    fm, _ = parse_frontmatter(content)
    assert fm.status == "in-review"


# ─── Linter tests ──────────────────────────────────────────────────────────

@pytest.fixture
def linter():
    return SpecLinter()


def test_lint_valid_spec(linter, sample_spec):
    errors = linter.lint(sample_spec)
    assert errors == [], [str(e) for e in errors]


def test_lint_missing_section(linter, tmp_path):
    spec = tmp_path / "broken.md"
    spec.write_text(textwrap.dedent("""\
        ---
        id: broken
        title: Broken Spec
        status: draft
        services:
          primary: my-service
          related: []
        constraints:
          manual: []
          incident_derived: []
        ---

        ## Context
        Something.

        <!-- CORBELL_GRAPH_START -->
        <!-- CORBELL_GRAPH_END -->

        <!-- CORBELL_CONSTRAINTS_START -->
        <!-- CORBELL_CONSTRAINTS_END -->
    """))
    errors = linter.lint(spec)
    kinds = [e.kind for e in errors]
    assert "MISSING_SECTION" in kinds  # Missing Proposed Design, Rollout Plan etc.


def test_lint_missing_markers(linter, tmp_path):
    spec = tmp_path / "no_markers.md"
    spec.write_text(textwrap.dedent("""\
        ---
        id: test
        title: Test
        status: draft
        services:
          primary: svc
          related: []
        constraints:
          manual: []
          incident_derived: []
        ---

        ## Context
        x

        ## Current Architecture
        y

        ## Proposed Design
        ### Service Changes
        z
        ### Data Flow
        d
        ### Failure Modes and Mitigations
        f

        ## Reliability and Risk Constraints
        x

        ## Rollout Plan
        p
    """))
    errors = linter.lint(spec)
    kinds = [e.kind for e in errors]
    assert "MISSING_MARKER" in kinds


def test_lint_file_not_found(linter, tmp_path):
    errors = linter.lint(tmp_path / "missing.md")
    assert any(e.kind == "FILE_NOT_FOUND" for e in errors)


def test_lint_invalid_status(linter, tmp_path):
    spec = tmp_path / "invalstatus.md"
    spec.write_text(textwrap.dedent("""\
        ---
        id: x
        title: X
        status: unknown-status
        services:
          primary: svc
          related: []
        constraints:
          manual: []
          incident_derived: []
        ---

        ## Context
        ## Current Architecture
        <!-- CORBELL_GRAPH_START -->
        <!-- CORBELL_GRAPH_END -->
        ## Proposed Design
        ### Service Changes
        ### Data Flow
        ### Failure Modes and Mitigations
        ## Reliability and Risk Constraints
        <!-- CORBELL_CONSTRAINTS_START -->
        <!-- CORBELL_CONSTRAINTS_END -->
        ## Rollout Plan
    """))
    errors = linter.lint(spec)
    assert any(e.kind == "INVALID_STATUS" for e in errors)


# ─── Decomposer tests ──────────────────────────────────────────────────────

def test_decompose_raises_on_non_approved(sample_spec, tmp_path):
    decomposer = SpecDecomposer(llm_client=None)
    with pytest.raises(ValueError, match="approved"):
        decomposer.decompose(sample_spec)


def test_decompose_approved_template(approved_spec, tmp_path):
    decomposer = SpecDecomposer(llm_client=None)
    out = decomposer.decompose(approved_spec)
    assert out.exists()
    assert out.suffix == ".yaml"
    content = out.read_text()
    assert "tracks" in content
    assert "spec_id" in content


def test_decompose_approved_with_llm(approved_spec):
    mock_llm = MagicMock()
    mock_llm.is_configured = True
    mock_llm.call.return_value = textwrap.dedent("""\
        spec_id: approved-feature
        title: Approved Feature
        generated_at: 2025-01-01
        tracks:
          - id: track-1
            name: Backend
            description: Core logic
            owner_service: sample-service
            can_start_after: []
            tasks:
              - id: task-1-1
                title: Implement handler
                description: Write the main handler.
                files_affected:
                  - sample_service/handler.py
                estimated_days: 2
    """)
    decomposer = SpecDecomposer(llm_client=mock_llm)
    out = decomposer.decompose(approved_spec)
    assert out.exists()
    content = out.read_text()
    assert "track-1" in content


def test_decompose_updates_frontmatter(approved_spec):
    decomposer = SpecDecomposer(llm_client=None)
    decomposer.decompose(approved_spec)
    content = approved_spec.read_text()
    fm, _ = parse_frontmatter(content)
    assert fm.decomposition.status == "decomposed"
