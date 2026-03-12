"""spec: CLI commands — generate, lint, review, approve, and decompose specs.

Key improvements in this version:
- spec new: No --service flag needed — services auto-discovered from PRD
- spec new: --existing mode for generating codebase design docs without any PRD
- spec new: --design-docs flag to feed existing design docs into LLM context
- All LLM commands: token usage tracked and displayed in a summary table
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.panel import Panel

app = typer.Typer(help="Design spec lifecycle commands.")
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


def _get_llm(cfg, no_llm: bool = False, tracker=None):
    """Return an LLMClient with token tracker if configured, else None."""
    if no_llm:
        return None
    from corbell.core.llm_client import LLMClient
    key = cfg.llm.resolved_api_key()
    if not key and cfg.llm.provider != "ollama":
        console.print(
            f"[yellow]⚠️  No LLM API key found for provider '{cfg.llm.provider}'.[/yellow]\n"
            f"  Set [bold]ANTHROPIC_API_KEY[/bold] or [bold]OPENAI_API_KEY[/bold].\n"
            f"  Using template mode."
        )
        return None
    return LLMClient(
        provider=cfg.llm.provider,
        model=cfg.llm.model,
        api_key=key,
        token_tracker=tracker,
    )


@app.command("new")
def spec_new(
    feature: str = typer.Option(
        None, "--feature", "-f",
        help="Short feature name (used as title and filename).",
    ),
    prd: Optional[str] = typer.Option(None, "--prd", help="PRD text (inline)."),
    prd_file: Optional[Path] = typer.Option(None, "--prd-file", help="Path to PRD .md or .txt file."),
    design_docs: Optional[List[Path]] = typer.Option(
        None, "--design-doc", "-d",
        help=(
            "Path to an existing technical design doc (.md) to learn patterns from. "
            "Repeatable: --design-doc docs/auth-design.md --design-doc docs/payment-design.md"
        ),
    ),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    author: Optional[str] = typer.Option(None, "--author"),
    no_llm: bool = typer.Option(False, "--no-llm", help="Use template mode only (no LLM)."),
    spec_id: Optional[str] = typer.Option(None, "--id", help="Override spec ID (slug)."),
    existing: bool = typer.Option(
        False, "--existing",
        help=(
            "Generate a design doc for the EXISTING codebase instead of a new feature. "
            "No PRD required. Describes what exists: architecture, key flows, code map."
        ),
    ),
    full_graph: bool = typer.Option(
        False, "--full-graph",
        help=(
            "Include the FULL method call graph skeletal context in the prompt, "
            "bypassing keyword filters for graph lookups."
        ),
    ),
):
    """Generate a technical design document.

    Corbell automatically discovers which services are relevant to your PRD —
    no --service flag needed.

    \b
    Modes:
      Spec for new feature:
        corbell spec new --feature "Payment Retry" --prd-file prd.md

      Spec with full call graph context (no keyword filtering):
        corbell spec new --feature "Auth Flow" --prd-file prd.md --full-graph

      Spec for existing codebase (no PRD needed):
        corbell spec new --existing

      With existing design docs for pattern context:
        corbell spec new --feature "Auth Revamp" --prd-file prd.md \
          --design-doc docs/auth-design.md --design-doc docs/payment-design.md

    \\b
    About constraints:
      The \\`## Reliability and Risk Constraints\\` section in every spec is where
      you document infrastructure and scaling constraints your team must follow:
        • Cloud provider: "Only Azure — no AWS services permitted"
        • Latency SLOs: "p99 < 200ms for all sync API calls"
        • Security: "All PII encrypted (AES-256 at rest, TLS 1.2+ in transit)"
        • Scaling: "Horizontal scaling only; max 1000 DB connections per replica"
        • Redundancy: "Must survive single AZ failure"
      These constraints are enforced during spec:review.
    """
    from corbell.core.docs.store import DocPatternStore
    from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    from corbell.core.spec.generator import SpecGenerator
    from corbell.core.token_tracker import TokenUsageTracker

    cfg, config_dir = _load(workspace)
    tracker = TokenUsageTracker()
    llm = _get_llm(cfg, no_llm, tracker=tracker)
    mode_label = f"{cfg.llm.provider}/{cfg.llm.model}" if llm else "template (no LLM)"

    db_path = cfg.db_path(config_dir)
    graph_store = SQLiteGraphStore(db_path)
    emb_store = SQLiteEmbeddingStore(db_path)
    doc_store = DocPatternStore(config_dir / ".corbell" / "doc_patterns.json")

    gen = SpecGenerator(graph_store, emb_store, doc_store, llm_client=llm, token_tracker=tracker)

    # --- Existing codebase mode ---
    if existing:
        console.print("\n[bold cyan]Existing Codebase Design Mode[/bold cyan]")
        console.print("  Generating design doc from your scanned repos (no PRD required).")
        console.print(f"  Mode: {mode_label}\n")

        out_path = gen.generate_existing_codebase(
            output_dir=cfg.spec_output_dir(config_dir),
            spec_id=spec_id,
            author=author,
        )
        console.print(Panel(
            f"[green]✓[/green] Codebase design doc: [bold]{out_path}[/bold]",
            title="Design Doc Generated",
            border_style="green",
        ))
        tracker.print_summary(console)
        return

    # --- New feature mode ---
    if not feature:
        feature = typer.prompt("Feature name")

    prd_text = prd or ""
    if prd_file:
        pf = Path(prd_file)
        if not pf.exists():
            console.print(f"[red]PRD file not found: {pf}[/red]")
            raise typer.Exit(1)
        prd_text = pf.read_text(encoding="utf-8")
    if not prd_text.strip():
        prd_text = typer.prompt(
            "Paste your PRD / feature description",
            default="",
        )
    if not prd_text.strip():
        console.print("[red]PRD is required. Use --prd or --prd-file.[/red]")
        raise typer.Exit(1)

    all_service_ids = [s.id for s in cfg.services]

    console.print(f"\n[bold cyan]Generating specification for:[/bold cyan] {feature}")
    console.print(f"  Mode: {mode_label}")
    if all_service_ids:
        console.print(f"  Auto-discovering relevant services from {len(all_service_ids)} configured service(s)...")
    if design_docs:
        console.print(f"  Loading {len(design_docs)} existing design doc(s) for pattern context...")
    console.print(f"  PRD preview: {prd_text[:100].strip()}...")

    out_path = gen.generate(
        feature=feature,
        prd=prd_text,
        services=None,  # auto-discover
        output_dir=cfg.spec_output_dir(config_dir),
        spec_id=spec_id,
        author=author,
        all_service_ids=all_service_ids,
        design_doc_paths=list(design_docs or []),
        full_graph=full_graph,
    )

    console.print(Panel(
        f"[green]✓[/green] Spec: [bold]{out_path}[/bold]\n\n"
        f"Next steps:\n"
        f"  corbell spec lint {out_path}\n"
        f"  corbell spec review {out_path}\n"
        f"  corbell spec approve {out_path}",
        title="Spec Created",
        border_style="green",
    ))

    # Always show token usage summary
    tracker.print_summary(console)


@app.command("lint")
def spec_lint(
    spec_path: Path = typer.Argument(..., help="Path to spec .md file."),
    ci: bool = typer.Option(False, "--ci", help="Exit with code 1 if lint fails (for CI)."),
):
    """Lint a spec for required sections, markers, and front-matter."""
    from corbell.core.spec.linter import SpecLinter

    linter = SpecLinter()
    errors = linter.lint(spec_path)

    if not errors:
        console.print(f"[green]✓ Spec is valid:[/green] {spec_path}")
        raise typer.Exit(0)

    console.print(f"[red]✗ Spec has {len(errors)} issue(s):[/red]")
    for err in errors:
        prefix = "[bold red][CRITICAL][/bold red]" if "MISSING" in err.kind else "[yellow][WARNING][/yellow]"
        console.print(f"  {prefix} [{err.kind}] {err.message}")

    if ci:
        raise typer.Exit(1)


@app.command("review")
def spec_review(
    spec_path: Path = typer.Argument(..., help="Path to spec .md file."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    reviewer_name: str = typer.Option("", "--reviewer", help="Reviewer name (for front-matter)."),
    no_llm: bool = typer.Option(False, "--no-llm"),
):
    """Review a spec against the architecture graph. Writes a .review.md sidecar."""
    from corbell.core.docs.store import DocPatternStore
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    from corbell.core.spec.reviewer import SpecReviewer
    from corbell.core.token_tracker import TokenUsageTracker

    cfg, config_dir = _load(workspace)
    tracker = TokenUsageTracker()
    llm = _get_llm(cfg, no_llm, tracker=tracker)

    graph_store = SQLiteGraphStore(cfg.db_path(config_dir))
    doc_store = DocPatternStore(config_dir / ".corbell" / "doc_patterns.json")
    patterns = doc_store.load()

    reviewer = SpecReviewer(graph_store=graph_store, doc_patterns=patterns, llm_client=llm)
    review_path = reviewer.review(spec_path, reviewer=reviewer_name)

    console.print(f"[green]✓ Review written:[/green] {review_path}")
    console.print(f"[green]✓ Spec front-matter updated with review block.[/green]")
    tracker.print_summary(console)


@app.command("approve")
def spec_approve(
    spec_path: Path = typer.Argument(..., help="Path to spec .md file."),
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation prompt."),
):
    """Mark a spec as approved."""
    from corbell.core.spec.schema import parse_frontmatter, update_frontmatter

    content = spec_path.read_text(encoding="utf-8")
    fm, _ = parse_frontmatter(content)

    if fm.status == "approved":
        console.print(f"[yellow]Spec is already approved.[/yellow]")
        raise typer.Exit(0)

    if not yes:
        confirm = typer.confirm(
            f"Approve spec '{fm.id}' ({fm.title})? This will enable spec:decompose.",
            default=False,
        )
        if not confirm:
            console.print("[yellow]Cancelled.[/yellow]")
            raise typer.Exit(0)

    update_frontmatter(spec_path, status="approved")
    console.print(f"[green]✓ Spec approved:[/green] {spec_path}")
    console.print(f"  Run [bold]corbell spec decompose {spec_path}[/bold] to generate tasks.")


@app.command("decompose")
def spec_decompose(
    spec_path: Path = typer.Argument(..., help="Path to an approved spec .md file."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    no_llm: bool = typer.Option(False, "--no-llm"),
):
    """Decompose an approved spec into parallel task tracks (generates .tasks.yaml)."""
    from corbell.core.spec.decomposer import SpecDecomposer
    from corbell.core.token_tracker import TokenUsageTracker

    cfg, config_dir = _load(workspace)
    tracker = TokenUsageTracker()
    llm = _get_llm(cfg, no_llm, tracker=tracker)

    decomposer = SpecDecomposer(llm_client=llm)
    try:
        tasks_path = decomposer.decompose(spec_path)
    except ValueError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)

    console.print(f"[green]✓ Tasks YAML written:[/green] {tasks_path}")
    console.print(f"  Run [bold]corbell export linear {tasks_path}[/bold] to create Linear issues.")
    tracker.print_summary(console)


@app.command("context")
def spec_context(
    feature: str = typer.Argument(..., help="Feature / PRD description to preview context for."),
    workspace: Optional[Path] = typer.Option(None, "--workspace", "-w"),
    top_k: int = typer.Option(10, "--top", "-k"),
    no_llm: bool = typer.Option(False, "--no-llm"),
):
    """Preview auto-discovered services and code context for a potential spec.

    Use this before spec:new to see what graph + code context would be injected.
    Shows which services Corbell would discover automatically.
    """
    from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    from corbell.core.prd_processor import PRDProcessor

    cfg, config_dir = _load(workspace)
    db_path = cfg.db_path(config_dir)
    graph_store = SQLiteGraphStore(db_path)
    emb_store = SQLiteEmbeddingStore(db_path)

    llm = _get_llm(cfg, no_llm)
    proc = PRDProcessor(llm_client=llm)

    all_ids = [s.id for s in cfg.services]
    console.rule("[bold cyan]Auto-discovered Services[/bold cyan]")
    if emb_store.count() > 0 and all_ids:
        relevant = proc.discover_relevant_services(feature, emb_store, all_ids, top_k=3)
        for r in relevant:
            console.print(f"  [green]✓[/green] {r}")
        console.print(f"\n  (From {len(all_ids)} configured service(s))")
    else:
        console.print("[yellow]Run `corbell embeddings build` first to enable auto-discovery.[/yellow]")
        relevant = all_ids[:3]

    console.rule("[bold cyan]Search Queries Generated from PRD[/bold cyan]")
    queries = proc.create_search_queries(feature)
    for q in queries:
        console.print(f"  → {q}")

    console.rule("[bold cyan]Code Context (top matches)[/bold cyan]")
    from corbell.core.embeddings.model import SentenceTransformerModel
    model = SentenceTransformerModel()
    for q in queries[:2]:
        qvec = model.encode([q])[0]
        results = emb_store.query(qvec, service_ids=relevant or None, top_k=top_k // 2)
        for r in results:
            svc_label = f"[cyan]{r.service_id}[/cyan]"
            console.print(f"  {svc_label} {r.file_path}::{r.symbol or r.chunk_type}")
