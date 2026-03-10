"""corbell init — create a new workspace.yaml from template."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(help="Initialize a Corbell workspace.")
console = Console()


def init_cmd(
    directory: Optional[Path] = typer.Option(
        None, "--dir", "-d", help="Target directory (default: current directory)."
    ),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing workspace.yaml."),
):
    """Initialize a Corbell workspace. Creates corbell-data/workspace.yaml."""
    from corbell.core.workspace import init_workspace_yaml

    target = (directory or Path.cwd()).resolve()
    ws_file = target / "corbell-data" / "workspace.yaml"

    if ws_file.exists() and not force:
        console.print(
            f"[yellow]⚠️  workspace.yaml already exists at {ws_file}[/yellow]\n"
            "Use --force to overwrite."
        )
        raise typer.Exit(0)

    out = init_workspace_yaml(target)
    console.print(f"[green]✓[/green] Created [bold]{out}[/bold]")
    console.print("\nNext steps:")
    console.print("  1. Edit [bold]corbell-data/workspace.yaml[/bold] to add your repos")
    console.print("  2. Set [bold]ANTHROPIC_API_KEY[/bold] or [bold]OPENAI_API_KEY[/bold] for LLM generation")
    console.print("  3. Run [bold]corbell graph:build[/bold] to scan your repositories")
    console.print("  4. Run [bold]corbell embeddings:build[/bold] to index code")
    console.print("  5. Run [bold]corbell spec:new[/bold] to generate your first design doc")
