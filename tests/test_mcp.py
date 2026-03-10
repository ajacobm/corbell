"""Test script to verify MCP server functionality."""

import pytest
import os
import sys
from pathlib import Path


@pytest.mark.asyncio
async def test_mcp_server_tools_registered():
    """Verify that the FastMCP server registers our built-in Corbell tools."""
    # We can inspect the mcp object directly before running transport
    from corbell.core.mcp.server import mcp
    
    # FastMCP holds the registered tools in mcp._tool_manager
    tool_names = [tool.name for tool in mcp._tool_manager.list_tools()]
    
    assert "graph_query" in tool_names
    assert "spec_generate" not in tool_names
    assert "get_architecture_context" in tool_names
    assert "spec_context" not in tool_names

@pytest.fixture
def temp_workspace_dir(tmp_path):
    """Create a temporary directory simulating a Corbell workspace."""
    workspace_dir = tmp_path / "my_project"
    workspace_dir.mkdir()
    corbell_dir = workspace_dir / "corbell"
    corbell_dir.mkdir()
    
    yaml_file = corbell_dir / "workspace.yaml"
    yaml_file.write_text("""workspace:
  name: test-workspace
services: []
llm:
  provider: ollama
  model: llama3
""")
    return workspace_dir

def test_workspace_discovery_with_env(temp_workspace_dir, monkeypatch):
    """Verify that _load_workspace respects the CORBELL_WORKSPACE environment variable."""
    from corbell.core.mcp.tools import _load_workspace
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_dir))
    
    cfg, config_dir = _load_workspace()
    assert cfg.workspace.name == "test-workspace"
    assert config_dir == temp_workspace_dir / "corbell"

def test_workspace_discovery_invalid_env(tmp_path, monkeypatch):
    """Verify that _load_workspace raises ValueError for invalid CORBELL_WORKSPACE."""
    from corbell.core.mcp.tools import _load_workspace
    
    invalid_dir = tmp_path / "invalid"
    invalid_dir.mkdir()
    monkeypatch.setenv("CORBELL_WORKSPACE", str(invalid_dir))
    
    with pytest.raises(ValueError, match="does not contain workspace.yaml"):
        _load_workspace()

@pytest.mark.asyncio
async def test_mcp_graph_query_tool_schema():
    """Verify the schema of graph_query matches our expectations."""
    from corbell.core.mcp.server import mcp
    
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    graph_tool = tools["graph_query"]
    
    assert "service_id" in graph_tool.parameters["properties"]
    assert "include_dependencies" in graph_tool.parameters["properties"]
    assert "include_methods" in graph_tool.parameters["properties"]

@pytest.mark.asyncio
async def test_mcp_get_architecture_context_tool_schema():
    """Verify the schema of get_architecture_context matches our expectations."""
    from corbell.core.mcp.server import mcp
    
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    context_tool = tools["get_architecture_context"]
    
    assert "feature_description" in context_tool.parameters["properties"]
    assert "top_k_services" in context_tool.parameters["properties"]
