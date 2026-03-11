"""MCP Server implementation for Corbell.

Exposes Corbell's architecture graph, code embeddings, and spec tools
as MCP tools for external AI platforms (Cursor, Claude Desktop, Antigravity).
"""

import sys
import asyncio

from mcp.server.fastmcp import FastMCP

from corbell.core.mcp.models import GraphQueryRequest, SpecContextRequest
from corbell.core.mcp.tools import (
    handle_graph_query,
    handle_get_architecture_context,
    handle_code_search,
    handle_list_services,
)


# Create the FastMCP Server
mcp = FastMCP("corbell", dependencies=["corbell"])


@mcp.custom_route("/", methods=["GET"])
async def _root(request):
    from starlette.responses import JSONResponse
    return JSONResponse({
        "name": "Corbell MCP Server",
        "status": "running",
        "sse_endpoint": "/sse",
        "docs": "Connect your MCP client to /sse",
    })


# ---------------------------------------------------------------------------
# Tool 1: graph_query (existing)
# ---------------------------------------------------------------------------

@mcp.tool()
def graph_query(service_id: str, include_dependencies: bool = True, include_methods: bool = False) -> str:
    """Query Corbell's architecture graph for service dependencies and details.
    
    Args:
        service_id: The ID of the service to query.
        include_dependencies: Whether to include upstream/downstream dependencies.
        include_methods: Whether to include code-level extracted methods.
    """
    req = GraphQueryRequest(
        service_id=service_id, 
        include_dependencies=include_dependencies, 
        include_methods=include_methods
    )
    return handle_graph_query(req)


# ---------------------------------------------------------------------------
# Tool 2: get_architecture_context (existing)
# ---------------------------------------------------------------------------

@mcp.tool()
def get_architecture_context(feature_description: str, top_k_services: int = 10) -> str:
    """Get architecture and code context for a feature without LLM generation.
    
    Args:
        feature_description: The feature description to get context for.
        top_k_services: Maximum number of relevant code chunks to return.
    """
    req = SpecContextRequest(feature_description=feature_description, top_k_services=top_k_services)
    return handle_get_architecture_context(req)


# ---------------------------------------------------------------------------
# Tool 3: code_search (new)
# ---------------------------------------------------------------------------

@mcp.tool()
def code_search(query: str, service_id: str = "", top_k: int = 10) -> str:
    """Semantic search across Corbell's code embedding index.
    
    Returns the most relevant code chunks matching the query, ranked by
    cosine similarity. Useful for finding implementations, patterns, and
    code examples across the workspace.
    
    Args:
        query: Natural language search query (e.g. "database connection pooling").
        service_id: Optional service ID to restrict search to a single service.
        top_k: Maximum number of results to return (default 10).
    """
    return handle_code_search(query, service_id=service_id or None, top_k=top_k)


# ---------------------------------------------------------------------------
# Tool 4: list_services (new)
# ---------------------------------------------------------------------------

@mcp.tool()
def list_services() -> str:
    """List all services in the current Corbell workspace graph.
    
    Returns a summary of every service discovered by `corbell graph build`,
    including language, type, tags, and dependency count.
    """
    return handle_list_services()


# ---------------------------------------------------------------------------
# Filtered stdin wrapper — prevents empty-line crashes in MCP SDK
# ---------------------------------------------------------------------------

class _FilteredStdin:
    """Async iterator over stdin that silently drops empty/whitespace lines.
    
    The MCP SDK's stdio transport passes every raw line from sys.stdin to
    Pydantic's JSONRPCMessage.model_validate_json(). Empty newlines ('\\n')
    fail validation and crash the server. This wrapper filters them out.
    """

    def __init__(self):
        self._reader = None

    def __aiter__(self):
        return self

    async def __anext__(self) -> str:
        loop = asyncio.get_event_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:  # EOF
                raise StopAsyncIteration
            if line.strip():  # Only forward non-empty lines
                return line
            # Empty/whitespace lines are silently dropped


# ---------------------------------------------------------------------------
# Server entry point
# ---------------------------------------------------------------------------

def serve(transport: str = "stdio", port: int = 8000) -> None:
    """Run the MCP server.
    
    Args:
        transport: 'stdio' for pipe-based IDE integration, 'sse' for HTTP server.
        port: Port number for SSE transport (ignored for stdio).
    """
    if transport == "sse":
        print(f"Corbell MCP server starting on http://localhost:{port}/sse ...", file=sys.stderr)
        mcp.settings.port = port
        mcp.run(transport="sse")
    else:
        print("Corbell MCP server starting on stdio...", file=sys.stderr)

        async def _run():
            from mcp.server.stdio import stdio_server

            filtered = _FilteredStdin()
            async with stdio_server(stdin=filtered) as (read_stream, write_stream):
                await mcp._mcp_server.run(
                    read_stream,
                    write_stream,
                    mcp._mcp_server.create_initialization_options(),
                )

        asyncio.run(_run())
