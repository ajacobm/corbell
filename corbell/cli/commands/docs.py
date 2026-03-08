"""docs: CLI commands — scan, learn, and list design doc patterns."""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Design document scanning and pattern learning.")
console = Console()


def _load(ws_dir: Optional[Path]):
    from corbell.core.workspace import find_workspace_root, load_workspace
    root = find_workspace_root(ws_dir or Path.cwd())
    if root is None:
        console.print("[red]No workspace.yaml found. Run `corbell init` first.[/red]")
        raise typer.Exit(1)
    config_dir = root / "corbell" if (root / "corbell" / "workspace.yaml").exists() else root
    cfg = load_workspace(config_dir / "workspace.yaml")
    return cfg, config_dir


@app.command("scan")
def docs_scan(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    path: Optional[List[Path]] = typer.Option(None, "--path", "-p", help="Extra directories to scan."),
):
    """Scan repos for design docs (ADRs, RFCs, design docs)."""
    from corbell.core.docs.scanner import DocScanner
    from corbell.core.docs.store import DocPatternStore

    cfg, config_dir = _load(workspace)

    scan_paths: List[Path] = list(path or [])
    # Add repo paths
    for svc in cfg.services:
        p = svc.resolved_path or Path(svc.repo)
        if p.exists():
            scan_paths.append(p)
    # Add extra explicit doc paths
    for ep in cfg.existing_docs.paths:
        ep_path = Path(ep)
        if not ep_path.is_absolute():
            ep_path = (config_dir / ep_path).resolve()
        if ep_path.exists():
            scan_paths.append(ep_path)

    scanner = DocScanner(patterns=cfg.existing_docs.patterns)
    candidates = scanner.scan(scan_paths)

    if not candidates:
        console.print("[yellow]No design documents found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Found {len(candidates)} candidate design docs")
    table.add_column("Type", style="cyan", no_wrap=True)
    table.add_column("Title")
    table.add_column("Path", style="dim")
    for c in candidates:
        table.add_row(c.detected_type, c.title[:60], c.path)
    console.print(table)

    # Save candidate list
    store = DocPatternStore(config_dir / ".corbell" / "doc_patterns.json")
    # Mark all as confirmed if auto_scan is enabled
    if cfg.existing_docs.auto_scan:
        for c in candidates:
            c.confirmed = True
    store.save_candidates(candidates)
    console.print(f"\n[green]✓ Saved {len(candidates)} candidates.[/green] Run [bold]docs:learn[/bold] to extract patterns.")


@app.command("learn")
def docs_learn(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use regex-only extraction (no LLM)."),
):
    """Extract design patterns from scanned docs."""
    from corbell.core.docs.learner import DocLearner
    from corbell.core.docs.store import DocPatternStore
    from corbell.core.llm_client import LLMClient

    cfg, config_dir = _load(workspace)
    store = DocPatternStore(config_dir / ".corbell" / "doc_patterns.json")
    candidates = store.load_candidates()
    confirmed = [c for c in candidates if c.confirmed]

    if not confirmed:
        console.print("[yellow]No confirmed docs. Run `docs:scan` first.[/yellow]")
        raise typer.Exit(0)

    llm = None
    if not no_llm:
        llm_cfg = cfg.llm
        key = llm_cfg.resolved_api_key()
        if key:
            llm = LLMClient(provider=llm_cfg.provider, model=llm_cfg.model, api_key=key)
            console.print(f"[cyan]Using LLM: {llm_cfg.provider}/{llm_cfg.model}[/cyan]")
        else:
            console.print("[yellow]No LLM key found — using regex-only extraction.[/yellow]")

    learner = DocLearner(llm_client=llm)
    patterns = learner.learn_from_docs(confirmed)
    store.save(patterns)

    console.print(f"[green]✓ Learned {len(patterns)} doc patterns from {len(confirmed)} docs.[/green]")


@app.command("patterns")
def docs_patterns(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
):
    """Show learned design patterns from your team's docs."""
    from corbell.core.docs.store import DocPatternStore

    cfg, config_dir = _load(workspace)
    store = DocPatternStore(config_dir / ".corbell" / "doc_patterns.json")
    patterns = store.load()

    if not patterns:
        console.print("[yellow]No patterns learned yet. Run `docs:scan` then `docs:learn`.[/yellow]")
        raise typer.Exit(0)

    for pat in patterns:
        console.print(f"\n[bold cyan]{pat.source_file}[/bold cyan] ({pat.detected_type})")
        if pat.section_headings:
            console.print(f"  Sections: {', '.join(pat.section_headings[:5])}")
        for dec in pat.decisions[:3]:
            console.print(f"  • {dec.summary}")
