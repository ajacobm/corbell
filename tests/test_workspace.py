"""Tests for core/workspace.py"""

from pathlib import Path

import pytest
import yaml

from corbell.core.workspace import (
    WorkspaceConfig,
    find_workspace_root,
    init_workspace_yaml,
    load_workspace,
)


def test_load_workspace_basic(sample_workspace_yaml, sample_repo):
    cfg = load_workspace(sample_workspace_yaml)
    assert cfg.workspace.name == "test-platform"
    assert len(cfg.services) == 1
    assert cfg.services[0].id == "sample-service"
    assert cfg.services[0].resolved_path == sample_repo


def test_load_workspace_from_dir(sample_workspace_yaml):
    cfg = load_workspace(sample_workspace_yaml.parent)
    assert cfg.workspace.name == "test-platform"


def test_load_workspace_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_workspace(tmp_path / "nonexistent" / "workspace.yaml")


def test_init_workspace_yaml(tmp_path):
    out = init_workspace_yaml(tmp_path)
    assert out.exists()
    raw = yaml.safe_load(out.read_text())
    assert "services" in raw
    assert raw["workspace"]["name"] == "my-platform"


def test_init_workspace_yaml_overwrite(tmp_path):
    out1 = init_workspace_yaml(tmp_path)
    out2 = init_workspace_yaml(tmp_path)
    assert out1 == out2


def test_find_workspace_root(tmp_path, sample_workspace_yaml):
    # Should find from inside the workspace dir
    root = find_workspace_root(sample_workspace_yaml.parent)
    assert root is not None


def test_find_workspace_root_not_found(tmp_path):
    isolated = tmp_path / "isolated"
    isolated.mkdir()
    assert find_workspace_root(isolated) is None


def test_llm_config_resolved_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test-123")
    config_dir = tmp_path / "corbell"
    config_dir.mkdir()
    ws = config_dir / "workspace.yaml"
    ws.write_text("""
version: "1"
workspace:
  name: test
services: []
llm:
  provider: anthropic
  model: claude-sonnet-4-5-20250929
""")
    cfg = load_workspace(ws)
    assert cfg.llm.resolved_api_key() == "sk-test-123"


def test_db_path_creates_parent(sample_workspace_yaml, tmp_path):
    cfg = load_workspace(sample_workspace_yaml)
    db = cfg.db_path(sample_workspace_yaml.parent)
    assert db.parent.exists()
