"""MCP tool handlers that interface with Corbell's internal components."""

from pathlib import Path
from typing import Dict, Any, List

from corbell.core.mcp.models import GraphQueryRequest, SpecGenerateRequest, SpecContextRequest


def _load_workspace():
    from corbell.core.workspace import find_workspace_root, load_workspace
    import os
    
    workspace_env = os.environ.get("CORBELL_WORKSPACE")
    if workspace_env:
        root = Path(workspace_env).resolve()
        if not (root / "corbell" / "workspace.yaml").exists() and not (root / "workspace.yaml").exists():
            raise ValueError(f"CORBELL_WORKSPACE={workspace_env} does not contain workspace.yaml")
    else:
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





def handle_get_architecture_context(request: SpecContextRequest) -> str:
    """Handle architecture context requests without internal LLM calls."""
    try:
        from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore
        from corbell.core.prd_processor import PRDProcessor
        
        cfg, config_dir = _load_workspace()
        db_path = cfg.db_path(config_dir)
        emb_store = SQLiteEmbeddingStore(db_path)
        
        # Force PRDProcessor to use regex fallback by passing llm_client=None
        proc = PRDProcessor(workspace_config=cfg, config_dir=config_dir, llm_client=None)
        all_ids = [s.id for s in cfg.services]
        
        # Rest of implementation remains similar but streamlined for no LLM calls
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
        
    except Exception as e:
        return f"Error getting architecture context: {str(e)}"
