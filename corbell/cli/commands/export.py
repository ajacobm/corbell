"""export: CLI commands — export to Notion and Linear."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console

app = typer.Typer(help="Export spec and tasks to Notion or Linear.")
console = Console()


def _load(ws_dir: Optional[Path]):
    from corbell.core.workspace import find_workspace_root, load_workspace
    root = find_workspace_root(ws_dir or Path.cwd())
    if root is None:
        console.print("[red]No workspace.yaml found. Run `corbell init` first.[/red]")
        raise typer.Exit(1)
    config_dir = root / "corbell-data" if (root / "corbell-data" / "workspace.yaml").exists() else root
    cfg = load_workspace(config_dir / "workspace.yaml")
    return cfg, config_dir


@app.command("notion")
def export_notion(
    spec_path: Path = typer.Argument(..., help="Path to the spec .md file."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    token: Optional[str] = typer.Option(None, "--token", envvar="CORBELL_NOTION_TOKEN"),
    parent_page_id: Optional[str] = typer.Option(None, "--page-id", envvar="CORBELL_NOTION_PAGE_ID"),
):
    """Export a spec to Notion as a page."""
    from corbell.core.export.notion import NotionExporter

    cfg, _ = _load(workspace)
    tok = token or cfg.integrations.notion.token
    page_id = parent_page_id or cfg.integrations.notion.parent_page_id

    exporter = NotionExporter(token=tok, parent_page_id=page_id)
    try:
        result = exporter.export(spec_path)
        console.print(f"[green]✓ Exported to Notion:[/green] {result.get('url', 'n/a')}")
    except (ImportError, ValueError) as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


@app.command("linear")
def export_linear(
    tasks_path: Path = typer.Argument(..., help="Path to the .tasks.yaml file."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    api_key: Optional[str] = typer.Option(None, "--api-key", envvar="CORBELL_LINEAR_API_KEY"),
    team_id: Optional[str] = typer.Option(None, "--team-id", envvar="CORBELL_LINEAR_TEAM_ID"),
    project_id: Optional[str] = typer.Option(None, "--project-id", envvar="CORBELL_LINEAR_PROJECT_ID"),
):
    """Create Linear issues from a .tasks.yaml file."""
    from corbell.core.export.linear import LinearExporter

    cfg, _ = _load(workspace)
    lin = cfg.integrations.linear
    exporter = LinearExporter(
        api_key=api_key or lin.api_key,
        team_id=team_id or lin.team_id,
        project_id=project_id or lin.default_project_id,
    )

    try:
        created = exporter.export_tasks(tasks_path)
        console.print(f"[green]✓ Created {len(created)} Linear issue(s):[/green]")
        for issue in created:
            console.print(f"  {issue.get('identifier', '')} — {issue.get('title', '')} ({issue.get('url', '')})")
    except (ImportError, ValueError) as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)
