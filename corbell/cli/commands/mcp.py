"""CLI command for running the Corbell MCP server."""

from __future__ import annotations

import sys
import typer

app = typer.Typer(help="Model Context Protocol (MCP) server integration.")


@app.command("serve")
def mcp_serve(
    transport: str = typer.Option("stdio", "--transport", "-t", help="Transport protocol: stdio or sse"),
    port: int = typer.Option(8000, "--port", "-p", help="Port for SSE transport (default: 8000)"),
):
    """Start the Corbell MCP server.

    Supports two transports:
      - stdio (default): for IDE integrations like Cursor and Claude Desktop
      - sse: HTTP server on the specified port for web-based MCP clients
    """
    try:
        from corbell.core.mcp.server import serve
        serve(transport=transport, port=port)
    except Exception as e:
        import traceback
        print(f"Error starting MCP server: {e}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        raise typer.Exit(1)
