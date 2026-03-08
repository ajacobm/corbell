"""graph: CLI commands — build graph, show services, deps, methods, call-path."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Service graph commands.")
console = Console()


def _load(ws_dir: Optional[Path]):
    """Load workspace config and return (config, config_dir)."""
    from corbell.core.workspace import find_workspace_root, load_workspace

    search_from = ws_dir or Path.cwd()
    root = find_workspace_root(search_from)
    if root is None:
        console.print("[red]No workspace.yaml found. Run `corbell init` first.[/red]")
        raise typer.Exit(1)
    config_dir = root / "corbell" if (root / "corbell" / "workspace.yaml").exists() else root
    cfg = load_workspace(config_dir / "workspace.yaml")
    return cfg, config_dir


def _get_store(cfg, config_dir: Path):
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    return SQLiteGraphStore(cfg.db_path(config_dir))


@app.command("build")
def graph_build(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w", help="Workspace directory."),
    method_level: bool = typer.Option(True, "--methods", help="Also build method-call graph."),
    rebuild: bool = typer.Option(True, "--rebuild/--no-rebuild", help="Clear and rebuild from scratch."),
):
    """Scan repos and build the service dependency graph."""
    cfg, config_dir = _load(workspace)
    store = _get_store(cfg, config_dir)
    from corbell.core.graph.builder import ServiceGraphBuilder

    builder = ServiceGraphBuilder(store)
    svcs = [
        {
            "id": s.id,
            "repo": s.repo,
            "resolved_path": s.resolved_path,
            "language": s.language,
            "tags": s.tags,
        }
        for s in cfg.services
    ]

    console.print(f"[bold cyan]Building graph for {len(svcs)} service(s)...[/bold cyan]")
    for s in cfg.services:
        path = s.resolved_path or Path(s.repo)
        exists = "✓" if path.exists() else "✗ NOT FOUND"
        console.print(f"  {exists} [bold]{s.id}[/bold]  →  {path}")

    summary = builder.build_from_workspace(svcs, clear_existing=rebuild, method_level=method_level)
    console.print(f"\n[green]✓ Graph built:[/green] {summary}")


@app.command("services")
def graph_services(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
):
    """List all discovered services."""
    cfg, config_dir = _load(workspace)
    store = _get_store(cfg, config_dir)
    svcs = store.get_all_services()

    if not svcs:
        console.print("[yellow]No services found — run `corbell graph:build` first.[/yellow]")
        raise typer.Exit(0)

    table = Table(title="Services", show_header=True, header_style="bold magenta")
    table.add_column("ID", style="cyan")
    table.add_column("Language")
    table.add_column("Type")
    table.add_column("Tags")
    for s in svcs:
        table.add_row(s.id, s.language, s.service_type, ", ".join(s.tags))
    console.print(table)


@app.command("deps")
def graph_deps(
    service: str = typer.Argument(..., help="Service ID to show dependencies for."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
):
    """Show dependencies of a specific service."""
    cfg, config_dir = _load(workspace)
    store = _get_store(cfg, config_dir)
    deps = store.get_dependencies(service)

    if not deps:
        console.print(f"[yellow]No dependencies found for {service}.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Dependencies of {service}")
    table.add_column("Target", style="cyan")
    table.add_column("Kind", style="yellow")
    table.add_column("Metadata")
    for d in deps:
        table.add_row(d.target_id, d.kind, str(d.metadata))
    console.print(table)


@app.command("methods")
def graph_methods(
    service: str = typer.Argument(..., help="Service ID to show methods for."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    limit: int = typer.Option(30, "--limit", "-n"),
):
    """List extracted methods for a service."""
    cfg, config_dir = _load(workspace)
    store = _get_store(cfg, config_dir)
    methods = store.get_methods_for_service(service)

    if not methods:
        console.print(f"[yellow]No methods found for {service}. Build with --methods flag.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Methods in {service}", show_header=True)
    table.add_column("Method", style="cyan")
    table.add_column("File", style="dim")
    table.add_column("Line", style="dim")
    for m in methods[:limit]:
        name = f"{m.class_name}.{m.method_name}" if m.class_name else m.method_name
        table.add_row(name, m.file_path, str(m.line_start))
    console.print(table)


@app.command("callpath")
def graph_callpath(
    from_method: str = typer.Argument(..., help="Source method ID."),
    to_method: str = typer.Argument(..., help="Target method ID."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    max_depth: int = typer.Option(5, "--depth", "-d"),
):
    """Find call paths between two methods in the graph."""
    cfg, config_dir = _load(workspace)
    store = _get_store(cfg, config_dir)
    paths = store.get_call_path(from_method, to_method, max_depth=max_depth)

    if not paths:
        console.print(f"[yellow]No call path found from {from_method} → {to_method}.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[green]Found {len(paths)} path(s):[/green]")
    for i, path in enumerate(paths, 1):
        console.print(f"\n  Path {i}: {' → '.join(path)}")
