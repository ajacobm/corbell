"""Method-call AST graph builder.

Adapted from specgen-repo-scanner/service_graph/method_flow_analyzer.py.
Extracts function/method nodes from Python (using ast) and JS/Java/Go (using regex).
"""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from corbell.core.graph.schema import DependencyEdge, GraphStore, MethodNode

_SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", "venv", "env", ".venv",
    ".pytest_cache", "dist", "build", "coverage",
}
_EXT_LANG = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".jsx": "javascript",
    ".go": "go",
    ".java": "java",
}


class MethodGraphBuilder:
    """Extract method nodes and call edges, store in GraphStore."""

    def __init__(self, graph_store: GraphStore):
        self.store = graph_store

    def build_for_service(self, service_id: str, repo_path: Path) -> Dict[str, Any]:
        """Scan all files in *repo_path* and populate method nodes + call edges.

        Args:
            service_id: Identifier for the owning service (e.g. ``checkout-service``).
            repo_path: Directory of the repository to scan.

        Returns:
            Summary with ``methods`` and ``calls`` counts.
        """
        all_methods: Dict[str, Dict] = {}
        all_calls: List[Dict] = []

        for fp in Path(repo_path).rglob("*"):
            if not fp.is_file():
                continue
            if any(part in _SKIP_DIRS for part in fp.parts):
                continue
            lang = _EXT_LANG.get(fp.suffix)
            if not lang:
                continue
            result = self._analyze_file(fp, service_id, lang)
            for m in result["methods"]:
                all_methods[m["id"]] = m
            all_calls.extend(result["calls"])

        # Upsert method nodes
        for method_id, info in all_methods.items():
            node = MethodNode(
                id=method_id,
                repo=str(repo_path),
                file_path=info["file_path"],
                class_name=info.get("class_name"),
                method_name=info["name"],
                signature=info.get("signature", info["name"]),
                docstring=info.get("docstring"),
                line_start=info.get("line_number", 0),
                line_end=info.get("line_end", info.get("line_number", 0)),
                service_id=service_id,
            )
            self.store.upsert_node(node)

        # Build call graph edges
        call_graph = self._build_call_graph(all_methods, all_calls)
        for caller_id, callee_id, meta in call_graph:
            self.store.upsert_edge(
                DependencyEdge(
                    source_id=caller_id,
                    target_id=callee_id,
                    kind="method_call",
                    metadata=meta,
                )
            )

        return {"methods": len(all_methods), "calls": len(call_graph)}

    # ------------------------------------------------------------------ #
    # Per-language analyzers                                               #
    # ------------------------------------------------------------------ #

    def _analyze_file(self, fp: Path, service_id: str, lang: str) -> Dict:
        try:
            content = fp.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            return {"methods": [], "calls": []}

        if lang == "python":
            return self._analyze_python(fp, content, service_id)
        if lang in ("javascript", "typescript"):
            return self._analyze_js(fp, content, service_id)
        if lang == "go":
            return self._analyze_go(fp, content, service_id)
        if lang == "java":
            return self._analyze_java(fp, content, service_id)
        return {"methods": [], "calls": []}

    def _make_method_id(self, service_id: str, fp: Path, full_name: str) -> str:
        return f"{service_id}::{fp.name}::{full_name}"

    def _analyze_python(self, fp: Path, content: str, service_id: str) -> Dict:
        """Use Python's ast module for accurate extraction."""
        methods: List[Dict] = []
        calls: List[Dict] = []

        try:
            tree = ast.parse(content, filename=str(fp))
        except SyntaxError:
            return {"methods": [], "calls": []}

        lines = content.splitlines()

        class _Visitor(ast.NodeVisitor):
            def __init__(self_inner):
                self_inner.current_class: Optional[str] = None
                self_inner.current_method_id: Optional[str] = None

            def visit_ClassDef(self_inner, node):
                old = self_inner.current_class
                self_inner.current_class = node.name
                self_inner.generic_visit(node)
                self_inner.current_class = old

            def _visit_func(self_inner, node):
                mname = node.name
                full = f"{self_inner.current_class}.{mname}" if self_inner.current_class else mname
                mid = self._make_method_id(service_id, fp, full)

                # Build signature line
                sig_parts = [a.arg for a in node.args.args]
                sig = f"def {mname}({', '.join(sig_parts)})"

                docstring = ast.get_docstring(node)

                # Line end: last node in body
                if node.body:
                    line_end = max(
                        getattr(n, "end_lineno", node.end_lineno or node.lineno)
                        for n in ast.walk(node)
                    )
                else:
                    line_end = node.lineno

                methods.append(
                    {
                        "id": mid,
                        "name": mname,
                        "full_name": full,
                        "class_name": self_inner.current_class,
                        "file_path": str(fp),
                        "line_number": node.lineno,
                        "line_end": line_end,
                        "is_async": isinstance(node, ast.AsyncFunctionDef),
                        "signature": sig,
                        "docstring": docstring,
                        "service_id": service_id,
                    }
                )

                old_mid = self_inner.current_method_id
                self_inner.current_method_id = mid
                self_inner.generic_visit(node)
                self_inner.current_method_id = old_mid

            visit_FunctionDef = _visit_func
            visit_AsyncFunctionDef = _visit_func

            def visit_Call(self_inner, node):
                if not self_inner.current_method_id:
                    self_inner.generic_visit(node)
                    return
                if isinstance(node.func, ast.Name):
                    callee = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    callee = node.func.attr
                else:
                    self_inner.generic_visit(node)
                    return
                calls.append(
                    {
                        "caller_id": self_inner.current_method_id,
                        "callee_name": callee,
                        "line_number": node.lineno,
                    }
                )
                self_inner.generic_visit(node)

        _Visitor().visit(tree)
        return {"methods": methods, "calls": calls}

    def _analyze_js(self, fp: Path, content: str, service_id: str) -> Dict:
        methods: List[Dict] = []
        calls: List[Dict] = []
        lines = content.splitlines()
        current_class = None

        func_pats = [
            re.compile(r"function\s+(\w+)\s*\("),
            re.compile(r"const\s+(\w+)\s*=\s*(?:async\s+)?(?:function|\([^)]*\)\s*=>)"),
            re.compile(r"(?:async\s+)?(\w+)\s*\([^)]*\)\s*\{"),
        ]
        class_pat = re.compile(r"class\s+(\w+)")

        for lnum, line in enumerate(lines, 1):
            cm = class_pat.search(line)
            if cm:
                current_class = cm.group(1)
                continue
            for pat in func_pats:
                m = pat.search(line)
                if m:
                    mname = m.group(1)
                    if mname in ("if", "for", "while", "return", "switch"):
                        continue
                    full = f"{current_class}.{mname}" if current_class else mname
                    mid = self._make_method_id(service_id, fp, full)
                    methods.append(
                        {
                            "id": mid,
                            "name": mname,
                            "full_name": full,
                            "class_name": current_class,
                            "file_path": str(fp),
                            "line_number": lnum,
                            "line_end": lnum,
                            "signature": mname,
                            "docstring": None,
                            "service_id": service_id,
                        }
                    )
                    break

        return {"methods": methods, "calls": calls}

    def _analyze_go(self, fp: Path, content: str, service_id: str) -> Dict:
        methods: List[Dict] = []
        lines = content.splitlines()
        pat = re.compile(r"^func\s+(?:\([^)]+\)\s+)?(\w+)\s*\(")
        for lnum, line in enumerate(lines, 1):
            m = pat.match(line)
            if m:
                mname = m.group(1)
                mid = self._make_method_id(service_id, fp, mname)
                methods.append(
                    {
                        "id": mid,
                        "name": mname,
                        "full_name": mname,
                        "class_name": None,
                        "file_path": str(fp),
                        "line_number": lnum,
                        "line_end": lnum,
                        "signature": mname,
                        "docstring": None,
                        "service_id": service_id,
                    }
                )
        return {"methods": methods, "calls": []}

    def _analyze_java(self, fp: Path, content: str, service_id: str) -> Dict:
        methods: List[Dict] = []
        lines = content.splitlines()
        pat = re.compile(
            r"(?:public|private|protected|static|\s)+[\w<>\[\]]+\s+(\w+)\s*\([^)]*\)\s*\{?"
        )
        skip = {"if", "for", "while", "switch", "catch", "class"}
        for lnum, line in enumerate(lines, 1):
            m = pat.search(line)
            if m and m.group(1) not in skip and "class " not in line:
                mname = m.group(1)
                mid = self._make_method_id(service_id, fp, mname)
                methods.append(
                    {
                        "id": mid,
                        "name": mname,
                        "full_name": mname,
                        "class_name": None,
                        "file_path": str(fp),
                        "line_number": lnum,
                        "line_end": lnum,
                        "signature": mname,
                        "docstring": None,
                        "service_id": service_id,
                    }
                )
        return {"methods": methods, "calls": []}

    # ------------------------------------------------------------------ #
    # Call graph resolution                                                #
    # ------------------------------------------------------------------ #

    def _build_call_graph(
        self, all_methods: Dict[str, Dict], all_calls: List[Dict]
    ) -> List[Tuple[str, str, Dict]]:
        """Match call names to method IDs and return (caller, callee, meta) triples."""
        name_to_ids: Dict[str, Set[str]] = defaultdict(set)
        for mid, info in all_methods.items():
            name_to_ids[info["name"]].add(mid)
            if info.get("full_name") and info["full_name"] != info["name"]:
                name_to_ids[info["full_name"]].add(mid)

        seen: Set[Tuple[str, str]] = set()
        result = []
        skip = {"if", "for", "while", "return", "try", "except", "catch", "with", "else", "elif"}
        for call in all_calls:
            caller_id = call["caller_id"]
            callee_name = call.get("callee_name", "")
            if callee_name in skip:
                continue
            for callee_id in name_to_ids.get(callee_name, set()):
                if caller_id == callee_id:
                    continue
                key = (caller_id, callee_id)
                if key not in seen:
                    seen.add(key)
                    result.append(
                        (caller_id, callee_id, {"line": call.get("line_number")})
                    )
        return result
