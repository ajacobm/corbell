"""MCP Server implementation for Corbell."""

from mcp.server.fastmcp import FastMCP

from corbell.core.mcp.models import GraphQueryRequest, SpecGenerateRequest, SpecContextRequest
from corbell.core.mcp.tools import handle_graph_query, handle_spec_generate, handle_spec_context


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
def spec_generate(prd_text: str) -> str:
    """Generate a technical specification (design doc) from a PRD using Corbell's architecture graph.
    
    Args:
        prd_text: The complete PRD or feature description. Corbell will automatically 
                  discover relevant services and generate the spec.
    """
    req = SpecGenerateRequest(prd_text=prd_text)
    return handle_spec_generate(req)


@mcp.tool()
def spec_context(feature_description: str, top_k_services: int = 10) -> str:
    """Preview the architecture and code context Corbell would use for a given feature.
    
    Args:
        feature_description: The feature description to preview context for.
        top_k_services: Maximum number of relevant code chunks to preview.
    """
    req = SpecContextRequest(feature_description=feature_description, top_k_services=top_k_services)
    return handle_spec_context(req)


def serve() -> None:
    """Run the MCP stdio server."""
    mcp.run(transport='stdio')
