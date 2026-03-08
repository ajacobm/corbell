"""MCP tool handlers that interface with Corbell's internal components."""

from pathlib import Path
from typing import Dict, Any, List

from corbell.core.mcp.models import GraphQueryRequest, SpecGenerateRequest, SpecContextRequest


def _load_workspace():
    from corbell.core.workspace import find_workspace_root, load_workspace
    root = find_workspace_root(Path.cwd())
    if root is None:
        raise ValueError("No workspace.yaml found (run `corbell init` in a terminal first)")
    config_dir = root / "corbell" if (root / "corbell" / "workspace.yaml").exists() else root
    cfg = load_workspace(config_dir / "workspace.yaml")
    return cfg, config_dir


def handle_graph_query(request: GraphQueryRequest) -> str:
    """Handle querying the service architecture graph."""
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    
    cfg, config_dir = _load_workspace()
    store = SQLiteGraphStore(cfg.db_path(config_dir))
    
    service = store.get_service(request.service_id)
    if not service:
        return f"Error: Service '{request.service_id}' not found in the architecture graph."
        
    lines = [
        f"Service: {service.name} ({service.id})",
        f"Language: {service.language}",
        f"Type: {service.service_type}",
        f"Repository: {service.repo}",
        f"Tags: {', '.join(service.tags) if service.tags else 'None'}",
    ]
    
    if request.include_dependencies:
        deps = store.get_dependencies(request.service_id)
        if deps:
            lines.append("\nDependencies:")
            for d in deps:
                lines.append(f"  → {d.target_id} [{d.kind}]")
        else:
            lines.append("\nDependencies: None")
            
    if request.include_methods:
        methods = store.get_methods_for_service(request.service_id)
        if methods:
            lines.append(f"\nMethods ({len(methods)} total):")
            for m in methods[:30]:  # Cap at 30 to avoid huge payloads
                name = f"{m.class_name}.{m.method_name}" if m.class_name else m.method_name
                lines.append(f"  - {name} ({m.file_path}:{m.line_start})")
            if len(methods) > 30:
                lines.append(f"  ... and {len(methods) - 30} more")
                
    return "\n".join(lines)


def handle_spec_generate(request: SpecGenerateRequest) -> str:
    """Handle generating a technical specification from a PRD."""
    from corbell.core.docs.store import DocPatternStore
    from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore
    from corbell.core.graph.sqlite_store import SQLiteGraphStore
    from corbell.core.spec.generator import SpecGenerator
    from corbell.core.llm_client import LLMClient
    from corbell.core.token_tracker import TokenUsageTracker
    
    cfg, config_dir = _load_workspace()
    tracker = TokenUsageTracker()
    
    key = cfg.llm.resolved_api_key()
    if not key and cfg.llm.provider != "ollama":
        llm = None
    else:
        llm = LLMClient(
            provider=cfg.llm.provider,
            model=cfg.llm.model,
            api_key=key,
            token_tracker=tracker,
        )
        
    db_path = cfg.db_path(config_dir)
    graph_store = SQLiteGraphStore(db_path)
    emb_store = SQLiteEmbeddingStore(db_path)
    doc_store = DocPatternStore(config_dir / ".corbell" / "doc_patterns.json")
    
    gen = SpecGenerator(graph_store, emb_store, doc_store, llm_client=llm, token_tracker=tracker)
    
    all_service_ids = [s.id for s in cfg.services]
    
    # Generate the spec text in memory (we use a temp file and read it, as generator writes to disk)
    import tempfile
    import uuid
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_id = f"mcp-spec-{uuid.uuid4().hex[:8]}"
        out_path = gen.generate(
            feature="MCP Generated Spec",
            prd=request.prd_text,
            services=None,
            output_dir=Path(tmpdir),
            spec_id=tmp_id,
            author="MCP Tool",
            all_service_ids=all_service_ids,
        )
        
        content = out_path.read_text(encoding="utf-8")
        
    # Append token usage if LLM was used
    if llm:
        summary = tracker.get_summary() # Not defined natively in Tracker, we'll format a basic string
        content += "\n\n---\n*Spec generated via Corbell MCP*"
        
    return content


def handle_spec_context(request: SpecContextRequest) -> str:
    """Handle previewing context without full generation."""
    from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore
    from corbell.core.prd_processor import PRDProcessor
    from corbell.core.llm_client import LLMClient
    
    cfg, config_dir = _load_workspace()
    db_path = cfg.db_path(config_dir)
    emb_store = SQLiteEmbeddingStore(db_path)
    
    key = cfg.llm.resolved_api_key()
    llm = LLMClient(
        provider=cfg.llm.provider,
        model=cfg.llm.model,
        api_key=key,
    ) if (key or cfg.llm.provider == "ollama") else None
    
    proc = PRDProcessor(llm_client=llm)
    all_ids = [s.id for s in cfg.services]
    
    lines = ["# Architecture Context Preview", ""]
    
    if emb_store.count() > 0 and all_ids:
        relevant = proc.discover_relevant_services(request.feature_description, emb_store, all_ids, top_k=3)
        lines.append("## Auto-discovered Services")
        for r in relevant:
            lines.append(f"- {r}")
        lines.append(f"*(From {len(all_ids)} configured services)*\n")
    else:
        lines.append("*No embedding store available. Run `corbell embeddings build` first.*\n")
        relevant = all_ids[:3]
        
    queries = proc.create_search_queries(request.feature_description)
    lines.append("## Search Queries Generated")
    for q in queries:
        lines.append(f"- {q}")
    lines.append("")
        
    if emb_store.count() > 0:
        lines.append("## Top Code Context")
        from corbell.core.embeddings.model import SentenceTransformerModel
        model = SentenceTransformerModel()
        for q in queries[:2]:
            qvec = model.encode([q])[0]
            results = emb_store.query(qvec, service_ids=relevant or None, top_k=request.top_k_services // 2)
            for r in results:
                lines.append(f"- [{r.service_id}] {r.file_path}::{r.symbol or r.chunk_type}")
                
    return "\n".join(lines)
