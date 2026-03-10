"""Workspace configuration loader for Corbell."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator


class ServiceConfig(BaseModel):
    """A single service definition in workspace.yaml."""

    id: str
    repo: str
    language: str = "python"
    tags: List[str] = Field(default_factory=list)
    resolved_path: Optional[Path] = Field(default=None, exclude=True)

    model_config = {"extra": "ignore"}


class StorageBackendConfig(BaseModel):
    """Storage backend configuration."""

    backend: str = "sqlite"
    path: str = ".corbell/workspace.db"

    model_config = {"extra": "ignore"}


class StorageConfig(BaseModel):
    """Storage sub-config."""

    graph: StorageBackendConfig = Field(default_factory=StorageBackendConfig)
    embeddings: StorageBackendConfig = Field(default_factory=StorageBackendConfig)
    model: str = "all-MiniLM-L6-v2"

    model_config = {"extra": "ignore"}


class ExistingDocsConfig(BaseModel):
    """Configuration for existing design doc scanning."""

    auto_scan: bool = True
    paths: List[str] = Field(default_factory=list)
    patterns: List[str] = Field(
        default_factory=lambda: [
            "*.design.md",
            "*-spec.md",
            "RFC-*.md",
            "ADR-*.md",
            "DESIGN.md",
            "*-design.md",
            "*_design.md",
        ]
    )

    model_config = {"extra": "ignore"}


class SpecConfig(BaseModel):
    """Spec output configuration."""

    output_dir: str = "specs/"
    template: str = "default"

    model_config = {"extra": "ignore"}


class NotionIntegration(BaseModel):
    """Notion integration config."""

    token: Optional[str] = None
    parent_page_id: Optional[str] = None

    model_config = {"extra": "ignore"}


class LinearIntegration(BaseModel):
    """Linear integration config."""

    api_key: Optional[str] = None
    team_id: Optional[str] = None
    default_project_id: Optional[str] = None

    model_config = {"extra": "ignore"}


class IntegrationsConfig(BaseModel):
    """External integrations."""

    notion: NotionIntegration = Field(default_factory=NotionIntegration)
    linear: LinearIntegration = Field(default_factory=LinearIntegration)

    model_config = {"extra": "ignore"}


class LLMConfig(BaseModel):
    """LLM provider configuration.

    Local providers: openai, anthropic, ollama.
    Cloud providers: aws (Bedrock), azure (Azure OpenAI), gcp (Vertex AI).

    API key can be provided here or via env vars:
    ANTHROPIC_API_KEY, OPENAI_API_KEY, AZURE_OPENAI_API_KEY, CORBELL_LLM_API_KEY
    """

    provider: str = "anthropic"
    model: str = "claude-sonnet-4-5-20250929"
    api_key: Optional[str] = None

    # AWS Bedrock
    aws_region: Optional[str] = None

    # Azure OpenAI
    azure_endpoint: Optional[str] = None
    azure_deployment: Optional[str] = None
    azure_api_version: Optional[str] = None

    # GCP Vertex AI
    gcp_project: Optional[str] = None
    gcp_region: Optional[str] = None

    model_config = {"extra": "ignore"}

    def resolved_api_key(self) -> Optional[str]:
        """Return the API key, resolving env var placeholders if needed."""
        key = self.api_key or ""
        if key.startswith("${") and key.endswith("}"):
            var = key[2:-1]
            return os.environ.get(var)
        if key:
            return key
        # Cloud providers use their own credential chains (no API key needed)
        if self.provider in ("aws", "gcp"):
            return None
        # Fall back to well-known env vars
        env_map = {
            "openai": "OPENAI_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "azure": "AZURE_OPENAI_API_KEY",
            "ollama": None,
        }
        env_var = env_map.get(self.provider.lower(), "CORBELL_LLM_API_KEY")
        if env_var:
            return os.environ.get(env_var) or os.environ.get("CORBELL_LLM_API_KEY")
        return None


class WorkspaceInfo(BaseModel):
    """Top-level workspace metadata."""

    name: str = "my-platform"
    root: str = ".."

    model_config = {"extra": "ignore"}


class WorkspaceConfig(BaseModel):
    """Root workspace configuration model (parsed from workspace.yaml)."""

    version: str = "1"
    workspace: WorkspaceInfo = Field(default_factory=WorkspaceInfo)
    services: List[ServiceConfig] = Field(default_factory=list)
    existing_docs: ExistingDocsConfig = Field(default_factory=ExistingDocsConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    spec: SpecConfig = Field(default_factory=SpecConfig)
    integrations: IntegrationsConfig = Field(default_factory=IntegrationsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    # Internal: path this config was loaded from
    _config_path: Optional[Path] = None

    model_config = {"extra": "ignore"}

    def resolve_paths(self, config_dir: Path) -> "WorkspaceConfig":
        """Resolve relative repo paths to absolute paths under config_dir."""
        for svc in self.services:
            raw = svc.repo
            if raw.startswith("${"):
                var = raw[2:-1]
                raw = os.environ.get(var, raw)
            p = Path(raw)
            if not p.is_absolute():
                p = (config_dir / p).resolve()
            svc.resolved_path = p
        return self

    def db_path(self, config_dir: Path) -> Path:
        """Return absolute path to the SQLite DB file."""
        raw = self.storage.graph.path
        p = Path(raw)
        if not p.is_absolute():
            p = (config_dir / p).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def spec_output_dir(self, config_dir: Path) -> Path:
        """Return absolute path to the spec output directory."""
        p = Path(self.spec.output_dir)
        if not p.is_absolute():
            p = (config_dir / p).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p


def _expand_env(value: Any) -> Any:
    """Recursively expand ${VAR} references in dict/list/str values."""
    if isinstance(value, str):
        if value.startswith("${") and value.endswith("}"):
            var = value[2:-1]
            return os.environ.get(var, value)
        return value
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand_env(i) for i in value]
    return value


def load_workspace(path: Path | str) -> "WorkspaceConfig":
    """Load and parse a workspace.yaml file.

    Args:
        path: Path to ``workspace.yaml`` or the directory containing it.

    Returns:
        Parsed and path-resolved :class:`WorkspaceConfig`.

    Raises:
        FileNotFoundError: If the workspace file does not exist.
        ValueError: If the file is not valid YAML or fails schema validation.
    """
    path = Path(path)
    if path.is_dir():
        path = path / "workspace.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Workspace file not found: {path}")

    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    raw = _expand_env(raw)
    config = WorkspaceConfig.model_validate(raw)
    config._config_path = path
    config.resolve_paths(path.parent)
    return config


def find_workspace_root(start: Path | str | None = None) -> Optional[Path]:
    """Walk up directories looking for corbell-data/workspace.yaml.

    Args:
        start: Directory to start searching from (default: cwd).

    Returns:
        Path to the **directory** containing ``corbell-data/workspace.yaml``, or
        ``None`` if not found.
    """
    current = Path(start or Path.cwd()).resolve()
    for candidate in [current, *current.parents]:
        ws = candidate / "corbell-data" / "workspace.yaml"
        if ws.exists():
            return candidate
        ws2 = candidate / "workspace.yaml"
        if ws2.exists():
            return candidate
    return None


def init_workspace_yaml(target_dir: Path) -> Path:
    """Write a starter workspace.yaml into target_dir/corbell-data/workspace.yaml.

    Args:
        target_dir: Root directory for the new workspace.

    Returns:
        Path to the written file.
    """
    out_dir = target_dir / "corbell-data"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "workspace.yaml"
    template = """\
version: "1"

workspace:
  name: "my-platform"
  root: ".."

services:
  - id: my-service
    repo: ../my-service
    language: python
    tags: [core]

existing_docs:
  auto_scan: true
  paths: []
  patterns:
    - "*.design.md"
    - "*-spec.md"
    - "RFC-*.md"
    - "ADR-*.md"
    - "DESIGN.md"

storage:
  graph:
    backend: sqlite
    path: .corbell/workspace.db
  embeddings:
    backend: sqlite
    path: .corbell/workspace.db
  model: all-MiniLM-L6-v2

spec:
  output_dir: specs/
  template: default

integrations:
  notion:
    token: ${CORBELL_NOTION_TOKEN}
    parent_page_id: ${CORBELL_NOTION_PAGE_ID}
  linear:
    api_key: ${CORBELL_LINEAR_API_KEY}
    team_id: ${CORBELL_LINEAR_TEAM_ID}
    default_project_id: ${CORBELL_LINEAR_PROJECT_ID}

llm:
  # ---- Option 1: Anthropic (recommended) ----
  provider: anthropic
  model: claude-sonnet-4-5
  api_key: ${ANTHROPIC_API_KEY}

  # ---- Option 2: OpenAI ----
  # provider: openai
  # model: gpt-4o
  # api_key: ${OPENAI_API_KEY}

  # ---- Option 3: AWS Bedrock (Anthropic Claude) ----
  # Two auth options:
  #
  # A) Long-term API key (simplest — paste your Bedrock API key directly):
  # provider: aws
  # model: us.anthropic.claude-sonnet-4-20250514-v1:0
  # api_key: ${BEDROCK_API_KEY}    # get this from AWS Bedrock console
  # aws_region: us-east-1
  #
  # B) IAM credentials (boto3 credential chain):
  # provider: aws
  # model: us.anthropic.claude-sonnet-4-20250514-v1:0
  # aws_region: us-east-1
  # (set AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY or use: aws configure)

  # ---- Option 4: Azure OpenAI ----
  # provider: azure
  # model: gpt-4o
  # api_key: ${AZURE_OPENAI_API_KEY}
  # azure_endpoint: https://my-resource.openai.azure.com/
  # azure_deployment: my-gpt4o-deployment
  # azure_api_version: "2024-02-01"

  # ---- Option 5: GCP Vertex AI (Anthropic Claude) ----
  # Auth: gcloud auth application-default login
  # provider: gcp
  # model: claude-sonnet-4-5@20250514
  # gcp_project: my-gcp-project
  # gcp_region: us-central1

  # ---- Option 6: Ollama (local, no API key) ----
  # provider: ollama
  # model: llama3
"""
    out.write_text(template, encoding="utf-8")
    return out
