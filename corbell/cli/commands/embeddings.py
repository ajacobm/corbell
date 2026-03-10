"""embeddings: CLI commands — build and query the embedding index."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(help="Code embedding index commands.")
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


@app.command("build")
def embeddings_build(
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    service: Optional[str] = typer.Option(None, "--service", "-s", help="Build only for this service."),
    rebuild: bool = typer.Option(False, "--rebuild", help="Clear existing index for the service."),
):
    """Index code chunks from all (or one) service repo(s)."""
    from corbell.core.embeddings.extractor import CodeChunkExtractor
    from corbell.core.embeddings.factory import get_embedding_store
    from corbell.core.embeddings.model import SentenceTransformerModel

    cfg, config_dir = _load(workspace)
    db_path = cfg.db_path(config_dir)
    embedding_backend = cfg.storage.embeddings.backend
    store = get_embedding_store(embedding_backend, db_path)

    services = cfg.services
    if service:
        services = [s for s in services if s.id == service]
        if not services:
            console.print(f"[red]Service '{service}' not found in workspace.yaml.[/red]")
            raise typer.Exit(1)

    console.print(f"[bold cyan]Loading embedding model ({cfg.storage.model})...[/bold cyan]")
    model = SentenceTransformerModel(cfg.storage.model)
    extractor = CodeChunkExtractor()

    for svc in services:
        repo_path = svc.resolved_path or Path(svc.repo)
        if not repo_path.exists():
            console.print(f"[yellow]  ⚠️  Skipping {svc.id} — path not found: {repo_path}[/yellow]")
            continue

        if rebuild:
            store.clear(svc.id)

        console.print(f"  [cyan]Scanning[/cyan] {svc.id} at {repo_path} ...")
        records = extractor.extract_from_repo(repo_path, svc.id)
        if not records:
            console.print(f"    [yellow]No chunks found for {svc.id}[/yellow]")
            continue

        # Encode in batches
        batch_size = 64
        total = len(records)
        for i in range(0, total, batch_size):
            batch = records[i : i + batch_size]
            texts = [r.content for r in batch]
            vecs = model.encode(texts)
            for rec, vec in zip(batch, vecs):
                rec.embedding = vec
            store.upsert_batch(batch)
            console.print(f"    Embedded {min(i + batch_size, total)}/{total} chunks", end="\r")

        console.print(f"\n  [green]✓[/green] {svc.id}: indexed {total} chunks")

    summary = store.count()
    console.print(f"\n[green]✓ Total chunks in index: {summary}[/green]")


@app.command("query")
def embeddings_query(
    query_text: str = typer.Argument(..., help="Free-text query to search the embedding index."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    top_k: int = typer.Option(10, "--top", "-k"),
    service: Optional[str] = typer.Option(None, "--service", "-s"),
):
    """Search the embedding index with a text query."""
    from corbell.core.embeddings.factory import get_embedding_store
    from corbell.core.embeddings.model import SentenceTransformerModel

    cfg, config_dir = _load(workspace)
    store = get_embedding_store(cfg.storage.embeddings.backend, cfg.db_path(config_dir))

    if store.count() == 0:
        console.print("[yellow]Embedding index is empty — run `corbell embeddings:build` first.[/yellow]")
        raise typer.Exit(0)

    model = SentenceTransformerModel(cfg.storage.model)
    qvec = model.encode([query_text])[0]
    service_ids = [service] if service else None
    results = store.query(qvec, service_ids=service_ids, top_k=top_k)

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Top {top_k} results for: {query_text!r}")
    table.add_column("Service", style="cyan", no_wrap=True)
    table.add_column("File", style="dim")
    table.add_column("Symbol / Type")
    table.add_column("Lines", style="dim")
    table.add_column("Preview", no_wrap=False, max_width=60)

    for r in results:
        preview = r.content.replace("\n", " ")[:80]
        sym = r.symbol or r.chunk_type
        table.add_row(r.service_id, r.file_path, sym, f"{r.start_line}–{r.end_line}", preview)

    console.print(table)
