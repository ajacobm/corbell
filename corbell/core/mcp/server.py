"""MCP Server implementation for Corbell."""

from mcp.server.fastmcp import FastMCP

from corbell.core.mcp.models import GraphQueryRequest, SpecContextRequest
from corbell.core.mcp.tools import handle_graph_query, handle_get_architecture_context


# Create the FastMCP Server
mcp = FastMCP("corbell", dependencies=["corbell"])


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


@mcp.tool()
def get_architecture_context(feature_description: str, top_k_services: int = 10) -> str:
    """Get architecture and code context for a feature without LLM generation.
    
    Args:
        feature_description: The feature description to get context for.
        top_k_services: Maximum number of relevant code chunks to return.
    """
    req = SpecContextRequest(feature_description=feature_description, top_k_services=top_k_services)
    return handle_get_architecture_context(req)


def serve() -> None:
    """Run the MCP stdio server."""
    mcp.run(transport='stdio')
