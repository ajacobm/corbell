"""CLI command for the Corbell architecture graph UI."""

from __future__ import annotations

import typer
from rich.console import Console

app = typer.Typer(help="Architecture graph browser UI.")
console = Console()


@app.command("serve")
def ui_serve(
    port: int = typer.Option(7433, "--port", "-p", help="Port to listen on (default: 7433)."),
    no_browser: bool = typer.Option(False, "--no-browser", help="Skip auto-opening the browser."),
):
    """Start the Corbell architecture graph UI (local only).

    Reads from your workspace SQLite store — no cloud required.
    Stop with Ctrl+C.

    Example::

        corbell ui serve
        corbell ui serve --port 8080 --no-browser
    """
    from pathlib import Path

    from corbell.core.ui.server import _find_workspace, run_server

    ws_yaml = _find_workspace(Path.cwd())
    if ws_yaml is None:
        console.print(
            "[red]✗[/red] No workspace.yaml found.\n"
            "  Run [bold]corbell init[/bold] to create one, or set "
            "[bold]CORBELL_WORKSPACE=/path/to/workspace[/bold]."
        )
        raise typer.Exit(1)

    url = f"http://localhost:{port}"
    console.print(f"\n[bold green]🏗️  Corbell UI[/bold green]  →  [bold cyan]{url}[/bold cyan]")
    console.print(f"[dim]   Workspace: {ws_yaml.parent}[/dim]")
    console.print(f"[dim]   Stop with Ctrl+C[/dim]\n")

    if not no_browser:
        import webbrowser, threading, time
        def _open():
            time.sleep(0.6)  # let the server bind first
            webbrowser.open(url)
        threading.Thread(target=_open, daemon=True).start()

    server = run_server(port, ws_yaml)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        console.print("\n[dim]Corbell UI stopped.[/dim]")
