import sys, re
from pathlib import Path
sys.path.insert(0, str(Path.cwd()))
from corbell.core.graph.builder import ServiceGraphBuilder
class MockStore:
    def upsert_edge(self, e):
        print(f"STORE EDGE: {e.source_id} -> {e.target_id} [{e.kind}] {e.metadata}")
b = ServiceGraphBuilder(MockStore())
svc = {"id": "specgen_local", "files": [Path("/Users/himmi/github/corbel/specgen_local/src/supabase_orchestrator.py")]}
b._detect_http_calls(svc, {"specgen_repo_scanner", "specgen_incident_backend", "specgen_local", "frontend_and_supabase"})
