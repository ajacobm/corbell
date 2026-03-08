"""Shared test fixtures for Corbell OSS."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def tmp_db(tmp_path) -> Path:
    """Return a temporary SQLite database path."""
    return tmp_path / "test.db"


@pytest.fixture
def sample_repo(tmp_path) -> Path:
    """Create a minimal sample Python repo for testing."""
    repo = tmp_path / "sample-service"
    repo.mkdir()

    (repo / "__init__.py").write_text("")
    (repo / "auth_client.py").write_text(textwrap.dedent("""\
        import requests
        import redis

        class AuthClient:
            def get_token(self, user_id: str) -> str:
                cache = redis.Redis(host="localhost")
                cached = cache.get(f"token:{user_id}")
                if cached:
                    return cached.decode()
                resp = requests.get(f"http://auth-service/token/{user_id}")
                return resp.json()["token"]

            def validate_token(self, token: str) -> bool:
                resp = requests.post("http://auth-service/validate", json={"token": token})
                return resp.json().get("valid", False)
    """))

    (repo / "db.py").write_text(textwrap.dedent("""\
        import psycopg2
        from psycopg2 import sql

        class Database:
            def __init__(self, dsn: str):
                self.conn = psycopg2.connect(dsn)

            def get_user(self, user_id: str) -> dict:
                cursor = self.conn.cursor()
                cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
                return cursor.fetchone()
    """))

    (repo / "orchestrator.py").write_text(textwrap.dedent("""\
        from auth_client import AuthClient
        from db import Database

        class Orchestrator:
            def __init__(self):
                self.auth = AuthClient()
                self.db = Database("postgresql://localhost/mydb")

            def process(self, user_id: str, payload: dict) -> dict:
                token = self.auth.get_token(user_id)
                user = self.db.get_user(user_id)
                return {"user": user, "token": token, "payload": payload}
    """))

    return repo


@pytest.fixture
def sample_workspace_yaml(tmp_path, sample_repo) -> Path:
    """Write a valid workspace.yaml into tmp_path/corbell/."""
    ws_dir = tmp_path / "corbell"
    ws_dir.mkdir()
    yaml_content = f"""\
version: "1"
workspace:
  name: test-platform
  root: ..

services:
  - id: sample-service
    repo: {sample_repo}
    language: python
    tags: [core]

storage:
  graph:
    backend: sqlite
    path: .corbell/test.db
  embeddings:
    backend: sqlite
    path: .corbell/test.db
  model: all-MiniLM-L6-v2

spec:
  output_dir: specs/

llm:
  provider: anthropic
  model: claude-3-5-sonnet-20241022
"""
    ws_file = ws_dir / "workspace.yaml"
    ws_file.write_text(yaml_content)
    return ws_file


@pytest.fixture
def mock_llm():
    """Return a mock LLMClient that returns a canned design doc."""
    m = MagicMock()
    m.is_configured = True
    m.call.return_value = textwrap.dedent("""\
        # Feature: Test Feature

        ## Context
        This tests the design generator.

        ## Current Architecture
        <!-- CORBELL_GRAPH_START -->
        graph here
        <!-- CORBELL_GRAPH_END -->

        ## Proposed Design
        ### Service Changes
        Add endpoint to sample-service.

        ### Data Flow
        ```mermaid
        sequenceDiagram
            actor User
            participant SampleService
            User->>SampleService: POST /feature
        ```

        ### Failure Modes and Mitigations
        - Timeout: retry 3x with exponential backoff.

        ## Reliability and Risk Constraints
        <!-- CORBELL_CONSTRAINTS_START -->
        <!-- CORBELL_CONSTRAINTS_END -->

        ## Rollout Plan
        Phase 1: feature flag 10% canary.
    """)
    return m


@pytest.fixture
def sample_spec(tmp_path) -> Path:
    """Write a valid spec file for testing."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    spec_file = spec_dir / "test-feature.md"
    spec_file.write_text(textwrap.dedent("""\
        ---
        id: test-feature
        title: Test Feature
        status: draft
        services:
          primary: sample-service
          related: []
        author: tester
        review:
          status: null
          reviewed_by: null
          reviewed_at: null
          completeness_score: null
          review_report_path: null
        decomposition:
          status: null
          task_file: null
          linear_synced: false
          notion_synced: false
        constraints:
          manual: []
          incident_derived: []
        ---

        ## Context

        This is a test spec for a feature.

        ## Current Architecture

        <!-- CORBELL_GRAPH_START -->
        graph context
        <!-- CORBELL_GRAPH_END -->

        ## Proposed Design

        ### Service Changes
        Add new endpoint.

        ### Data Flow
        Data flows from A to B.

        ### Failure Modes and Mitigations
        Handle timeouts.

        ## Reliability and Risk Constraints

        <!-- CORBELL_CONSTRAINTS_START -->
        <!-- CORBELL_CONSTRAINTS_END -->

        ## Rollout Plan

        Phase 1: canary.
    """))
    return spec_file


@pytest.fixture
def approved_spec(tmp_path) -> Path:
    """Write an approved spec file."""
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir(exist_ok=True)
    spec_file = spec_dir / "approved-feature.md"
    spec_file.write_text(textwrap.dedent("""\
        ---
        id: approved-feature
        title: Approved Feature
        status: approved
        services:
          primary: sample-service
          related: []
        constraints:
          manual: []
          incident_derived: []
        ---

        ## Context
        Approved for implementation.

        ## Current Architecture
        <!-- CORBELL_GRAPH_START -->
        <!-- CORBELL_GRAPH_END -->

        ## Proposed Design
        ### Service Changes
        New worker service.
        ### Data Flow
        Worker consumes events.
        ### Failure Modes and Mitigations
        Dead-letter queue.

        ## Reliability and Risk Constraints
        <!-- CORBELL_CONSTRAINTS_START -->
        <!-- CORBELL_CONSTRAINTS_END -->

        ## Rollout Plan
        Blue/green deployment.
    """))
    return spec_file
