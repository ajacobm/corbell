"""CLI command for running the Corbell MCP server."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(help="Model Context Protocol (MCP) server integration.")
console = Console()


@app.command("serve")
def mcp_serve():
    """Start the Corbell MCP server over stdio.
    
    This command is intended to be run by MCP clients (like Claude Desktop or Cursor),
    not directly by human operators. It provides Corbell's architecture graph and
    spec generation capabilities as tools to external AI assistants.
    """
    try:
        from corbell.core.mcp.server import serve
        serve()
    except Exception as e:
        console.print(f"[red]Error starting MCP server: {e}[/red]", err=True)
        raise typer.Exit(1)
