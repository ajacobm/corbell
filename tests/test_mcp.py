"""Test script to verify MCP server functionality."""

import pytest
import os
import sys
import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def temp_workspace_dir(tmp_path):
    """Create a temporary directory simulating a Corbell workspace with corbell/ layout."""
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


@pytest.fixture
def temp_workspace_dir_corbell_data(tmp_path):
    """Create a temporary directory simulating a workspace with corbell-data/ layout."""
    workspace_dir = tmp_path / "my_project"
    workspace_dir.mkdir()
    data_dir = workspace_dir / "corbell-data"
    data_dir.mkdir()
    
    yaml_file = data_dir / "workspace.yaml"
    yaml_file.write_text("""workspace:
  name: test-workspace-data
services: []
llm:
  provider: ollama
  model: llama3
""")
    return workspace_dir


@pytest.fixture
def temp_workspace_with_db(tmp_path):
    """Create a workspace with a real SQLite graph DB for tool handler tests."""
    workspace_dir = tmp_path / "my_project"
    workspace_dir.mkdir()
    corbell_dir = workspace_dir / "corbell"
    corbell_dir.mkdir()

    yaml_file = corbell_dir / "workspace.yaml"
    yaml_file.write_text("""workspace:
  name: handler-test
services:
  - id: test-service
    repo: ./test-repo
    language: python
    service_type: api
llm:
  provider: ollama
  model: llama3
""")

    # Load the config to find the actual db_path it will use
    from corbell.core.workspace import load_workspace
    cfg = load_workspace(corbell_dir / "workspace.yaml")
    db_path = cfg.db_path(corbell_dir)

    # Create a graph DB at that exact path
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    from corbell.core.graph.schema import ServiceNode, DependencyEdge

    store = SQLiteGraphStore(db_path)
    store.upsert_node(ServiceNode(
        id="test-service",
        name="Test Service",
        repo="./test-repo",
        language="python",
        service_type="api",
        tags=["test", "demo"],
    ))
    store.upsert_edge(DependencyEdge(
        source_id="test-service",
        target_id="external:some-api",
        kind="http_call",
    ))

    return workspace_dir


# ---------------------------------------------------------------------------
# Tool Registration Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_server_tools_registered():
    """Verify that the FastMCP server registers all 4 Corbell tools."""
    from corbell.core.mcp.server import mcp
    
    tool_names = [tool.name for tool in mcp._tool_manager.list_tools()]
    
    assert "graph_query" in tool_names
    assert "get_architecture_context" in tool_names
    assert "code_search" in tool_names
    assert "list_services" in tool_names


@pytest.mark.asyncio
async def test_mcp_server_has_exactly_four_tools():
    """Verify no unexpected tools are registered."""
    from corbell.core.mcp.server import mcp
    
    tool_names = [tool.name for tool in mcp._tool_manager.list_tools()]
    assert len(tool_names) == 4


# ---------------------------------------------------------------------------
# Tool Schema Tests
# ---------------------------------------------------------------------------

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


@pytest.mark.asyncio
async def test_mcp_code_search_tool_schema():
    """Verify the schema of code_search matches our expectations."""
    from corbell.core.mcp.server import mcp
    
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    search_tool = tools["code_search"]
    
    assert "query" in search_tool.parameters["properties"]
    assert "service_id" in search_tool.parameters["properties"]
    assert "top_k" in search_tool.parameters["properties"]


@pytest.mark.asyncio
async def test_mcp_list_services_tool_schema():
    """Verify list_services takes no required arguments."""
    from corbell.core.mcp.server import mcp
    
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    list_tool = tools["list_services"]
    
    # list_services has no required parameters
    required = list_tool.parameters.get("required", [])
    assert len(required) == 0


# ---------------------------------------------------------------------------
# Workspace Discovery Tests
# ---------------------------------------------------------------------------

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


def test_workspace_discovery_corbell_data_path(temp_workspace_dir_corbell_data, monkeypatch):
    """Verify that _load_workspace finds workspace.yaml in corbell-data/ directory."""
    from corbell.core.mcp.tools import _load_workspace
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_dir_corbell_data))
    
    cfg, config_dir = _load_workspace()
    assert cfg.workspace.name == "test-workspace-data"
    assert config_dir == temp_workspace_dir_corbell_data / "corbell-data"


# ---------------------------------------------------------------------------
# FilteredStdin Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_filtered_stdin_drops_empty_lines():
    """Verify FilteredStdin silently drops empty/whitespace lines."""
    from corbell.core.mcp.server import _FilteredStdin
    import io
    
    test_input = '\n\n  \n{"valid":"json"}\n\n\t\n{"second":"line"}\n'
    fake_stdin = io.StringIO(test_input)
    
    with patch.object(sys, 'stdin', fake_stdin):
        filtered = _FilteredStdin()
        results = []
        async for line in filtered:
            results.append(line)
        
        # Only the two valid JSON lines should come through
        assert len(results) == 2
        assert '{"valid":"json"}\n' in results
        assert '{"second":"line"}\n' in results


@pytest.mark.asyncio
async def test_filtered_stdin_handles_eof():
    """Verify FilteredStdin raises StopAsyncIteration on EOF."""
    from corbell.core.mcp.server import _FilteredStdin
    
    with patch('sys.stdin') as mock_stdin:
        mock_stdin.readline = lambda: ''  # Immediate EOF
        
        filtered = _FilteredStdin()
        results = []
        async for line in filtered:
            results.append(line)
        
        assert results == []


# ---------------------------------------------------------------------------
# Tool Handler Execution Tests
# ---------------------------------------------------------------------------

def test_handle_graph_query_success(temp_workspace_with_db, monkeypatch):
    """Verify handle_graph_query returns service data from the graph DB."""
    from corbell.core.mcp.tools import handle_graph_query
    from corbell.core.mcp.models import GraphQueryRequest
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_with_db))
    
    req = GraphQueryRequest(service_id="test-service", include_dependencies=True, include_methods=False)
    result = handle_graph_query(req)
    
    assert "Test Service" in result
    assert "python" in result
    assert "external:some-api" in result
    assert "http_call" in result


def test_handle_graph_query_not_found(temp_workspace_with_db, monkeypatch):
    """Verify handle_graph_query returns error string for missing service."""
    from corbell.core.mcp.tools import handle_graph_query
    from corbell.core.mcp.models import GraphQueryRequest
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_with_db))
    
    req = GraphQueryRequest(service_id="nonexistent-service")
    result = handle_graph_query(req)
    
    assert "Error" in result
    assert "nonexistent-service" in result
    assert "not found" in result


def test_handle_list_services_success(temp_workspace_with_db, monkeypatch):
    """Verify handle_list_services returns formatted service list."""
    from corbell.core.mcp.tools import handle_list_services
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_with_db))
    
    result = handle_list_services()
    
    assert "test-service" in result
    assert "python" in result
    assert "1 total" in result


def test_handle_list_services_empty_graph(temp_workspace_dir, monkeypatch):
    """Verify handle_list_services returns helpful message when no services exist."""
    from corbell.core.mcp.tools import handle_list_services
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    
    # Create an empty DB
    db_path = temp_workspace_dir / "corbell" / "corbell.db"
    SQLiteGraphStore(db_path)
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_dir))
    
    result = handle_list_services()
    assert "No services found" in result


def test_handle_code_search_no_embeddings(temp_workspace_with_db, monkeypatch):
    """Verify handle_code_search returns helpful message when no embeddings exist."""
    from corbell.core.mcp.tools import handle_code_search
    
    monkeypatch.setenv("CORBELL_WORKSPACE", str(temp_workspace_with_db))
    
    result = handle_code_search("test query")
    assert "No code embeddings found" in result or "No code matches" in result


# ---------------------------------------------------------------------------
# Error Handling Tests
# ---------------------------------------------------------------------------

def test_handle_graph_query_returns_error_string_not_exception():
    """Verify tool handlers return error strings instead of raising exceptions."""
    from corbell.core.mcp.tools import handle_graph_query
    from corbell.core.mcp.models import GraphQueryRequest
    
    # Without CORBELL_WORKSPACE set and no workspace.yaml, it should return an error string
    req = GraphQueryRequest(service_id="anything")
    result = handle_graph_query(req)
    
    # Should be a string, not an exception
    assert isinstance(result, str)
    assert "Error" in result or "error" in result


def test_handle_list_services_returns_error_string_not_exception(monkeypatch):
    """Verify list_services returns error string instead of raising."""
    from corbell.core.mcp.tools import handle_list_services
    
    monkeypatch.setenv("CORBELL_WORKSPACE", "/invalid/path")
    result = handle_list_services()
    assert isinstance(result, str)
    assert "Error" in result or "error" in result


def test_handle_code_search_returns_error_string_not_exception():
    """Verify code_search returns error string instead of raising."""
    from corbell.core.mcp.tools import handle_code_search
    
    result = handle_code_search("anything")
    assert isinstance(result, str)
    assert "Error" in result or "error" in result
