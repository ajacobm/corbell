"""corbell init — create a new workspace.yaml from template."""

from __future__ import annotations

import os
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

    # ── LLM setup hints ────────────────────────────────────────────────────
    console.print("\n[bold cyan]LLM Configuration[/bold cyan] (set one of these env vars):")
    _hint("ANTHROPIC_API_KEY", "Anthropic Claude (recommended)")
    _hint("OPENAI_API_KEY", "OpenAI GPT-4o")
    _hint("BEDROCK_API_KEY", "AWS Bedrock — also set aws_region in workspace.yaml")

    # ── Jira setup hints ───────────────────────────────────────────────────
    console.print("\n[bold cyan]Jira Integration[/bold cyan] (optional — for exporting tasks):")
    _hint("CORBELL_JIRA_URL", "e.g. https://yourcompany.atlassian.net")
    _hint("CORBELL_JIRA_EMAIL", "Your Atlassian account email")
    _hint("CORBELL_JIRA_API_TOKEN", "Personal API token from id.atlassian.com/manage-profile/security/api-tokens")
    _hint("CORBELL_JIRA_PROJECT_KEY", "e.g. ENG, DEV, KAN")

    # ── Linear setup hints ─────────────────────────────────────────────────
    console.print("\n[bold cyan]Linear Integration[/bold cyan] (optional):")
    _hint("CORBELL_LINEAR_API_KEY", "Linear API key")
    _hint("CORBELL_LINEAR_TEAM_ID", "Linear team ID")

    # ── Next steps ─────────────────────────────────────────────────────────
    console.print("\n[bold]Next steps:[/bold]")
    console.print("  1. Edit [bold]corbell-data/workspace.yaml[/bold] — add your repo paths")
    console.print("  2. Run [bold]corbell graph build[/bold] to scan your repositories")
    console.print("  3. Run [bold]corbell embeddings build[/bold] to index code for search")
    console.print("  4. Run [bold]corbell spec new --feature \"My Feature\" --prd-file prd.md[/bold]")
    console.print("  5. Run [bold]corbell spec decompose <spec.md>[/bold] to generate tasks")
    console.print("  6. Run [bold]corbell export jira <tasks.yaml>[/bold] to push to Jira")


def _hint(env_var: str, description: str) -> None:
    """Print a coloured env-var hint, ticking if already set."""
    value = os.environ.get(env_var)
    if value:
        console.print(f"  [green]✓[/green] [bold]{env_var}[/bold] — {description} [dim](already set)[/dim]")
    else:
        console.print(f"  [dim]○[/dim] [bold]{env_var}[/bold] — {description}")
