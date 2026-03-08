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
    assert "spec_generate" in tool_names
    assert "spec_context" in tool_names

@pytest.mark.asyncio
async def test_mcp_graph_query_tool_schema():
    """Verify the schema of graph_query matches our expectations."""
    from corbell.core.mcp.server import mcp
    
    tools = {tool.name: tool for tool in mcp._tool_manager.list_tools()}
    graph_tool = tools["graph_query"]
    
    assert "service_id" in graph_tool.parameters["properties"]
    assert "include_dependencies" in graph_tool.parameters["properties"]
    assert "include_methods" in graph_tool.parameters["properties"]
