"""Design document generator — the heart of Corbell.

Builds context from the graph, embeddings, and learned doc patterns,
then calls an LLM (OpenAI/Anthropic/AWS/Azure/GCP) to produce a full technical
design document in Markdown.

Key features:
- **Auto service discovery**: PRDProcessor discovers relevant services automatically
  via embedding similarity — no --service flag needed.
- **Existing codebase mode**: Generate a design doc without any PRD.
- **Design doc context**: Existing .md design docs are extracted and fed to LLM.
- **Token tracking**: All LLM calls tracked and summarized.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from corbell.core.docs.learner import DocLearner
from corbell.core.docs.models import DocPattern
from corbell.core.docs.store import DocPatternStore
from corbell.core.graph.schema import GraphStore
from corbell.core.llm_client import LLMClient
from corbell.core.spec.schema import (
    ConstraintsBlock,
    DecompositionBlock,
    ReviewBlock,
    ServicesBlock,
    SpecFrontmatter,
    serialize_frontmatter,
)


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior staff engineer writing a technical design document for your team.

FORMAT AND STRUCTURE REQUIREMENTS — STRICT CONTENT RATIO (FOLLOW EXACTLY):
The document MUST be composed of three parts in roughly these proportions:

1. TEXT (~50%): Explanatory prose, trade-off analysis, architectural decisions, implementation guidance.

2. DIAGRAMS (~25%): Include 2-3 Mermaid.js diagrams.
   - Sequence diagrams for data flows (use standard sequenceDiagram syntax).
   - Component diagrams for service relationships.
   - Place diagrams where they best illustrate architecture.

3. CODE FILE REFERENCES AND SNIPPETS (~25%): MANDATORY.
   - Reference actual file paths from the code context (do NOT invent paths).
   - Show existing code (what happens today) and explain changes needed.
   - For EVERY file listed in instructions, show relevant existing code.
   - A design document without real file paths and existing code is UNACCEPTABLE.
   - If no code context was provided, explicitly state which files need to be created.

REQUIRED DOCUMENT STRUCTURE (all sections mandatory):

# {title}

## Context
WHY this feature is built, problem statement, success criteria.

## Current Architecture
<!-- CORBELL_GRAPH_START -->
{graph_block}
<!-- CORBELL_GRAPH_END -->
Describe current state using actual service names from the graph.

## Proposed Design

### Service Changes
For each affected service: new endpoints, models, workers, schema changes, code examples.

### Data Flow
```mermaid
sequenceDiagram
    ...
```

### API Contracts
New/changed endpoints with request/response shapes.

### Failure Modes and Mitigations
List every failure mode: timeouts, retries, circuit breakers, dead-letter queues.

## Reliability and Risk Constraints

<!-- CORBELL_CONSTRAINTS_START -->
{constraints_block}
<!-- CORBELL_CONSTRAINTS_END -->

State: latency SLOs, error-rate targets, capacity, security constraints.
CRITICAL: Do NOT violate any constraint from the constraints block above.

## Rollout Plan
Phases, feature flags, canary %, rollback procedure.

---
WRITING RULES:
1. Be specific — mention table names, function names, queue names, env vars.
2. Reference exact file paths from code context (never invent paths).
3. Do not mention timeline weeks (week 1-2 etc).
4. Keep tone senior-engineer-to-senior-engineer.
5. If the PRD doesn't specify something, say "TBD: <reason>" — do not invent.
"""

_EXISTING_CODEBASE_SYSTEM_PROMPT = """\
You are a senior engineer writing a design document that describes an EXISTING codebase.

You have these inputs:
- System architecture context: service topology, databases, queues, inter-service relationships.
- Relevant code chunks from the codebase (entry points, API routes, workers, key flows).
- Repository folder structure.

Your job is to write a design document that:
- Describes the EXISTING architecture and key flows.
- Focuses on key entry points (main(), API routers, workers) and 2-4 representative flows.
- Uses the service graph to describe components, boundaries, and data flow.
- References actual file paths and includes short code snippets from the provided chunks.
- Includes 1-2 Mermaid diagrams for the main architecture.
- Is approximately 4-6 pages. Do NOT try to cover everything — prioritize main services and flows.

STRUCTURE (keep concise):
1. **Overview** — what this system does, tech stack, languages used.
2. **Architecture** — services, databases, queues; one Mermaid component diagram.
3. **Key Flow(s)** — pick 1-2 important request flows with sequence diagram.
4. **Code Map** — important files/modules and their roles (from real chunks provided).
5. **Scaling Characteristics** — what will stress the system as load grows.

Do not invent file paths or code; use only the provided context.
"""

_USER_PROMPT_TEMPLATE = """\
## Feature Request / PRD
{prd}

---
## Relevant Code Context (from repositories — {code_chunks_count} chunks)
{code_context}

---
## Service Graph (current architecture)
{graph_context}

---
## Established Design Patterns From Your Team's Docs
{patterns_context}

---
## Files That MUST Be Referenced in the Design
{file_list}

---
Produce the complete technical design document following the system prompt structure.
Use exact filenames and service names from the code context above.
"""


class SpecGenerator:
    """Generate a full technical design document for a feature.

    Three modes:
    1. **PRD mode** (default): Generate a design doc from a PRD. Services are
       auto-discovered by semantic search — no ``--service`` flag needed.
    2. **Existing codebase mode**: Generate a design doc for the current
       codebase without any PRD (describe what exists).
    3. **Template mode** (no LLM): Fills skeleton with graph + code context only.
    """

    def __init__(
        self,
        graph_store: GraphStore,
        embedding_store,
        doc_pattern_store: DocPatternStore,
        llm_client: Optional[LLMClient] = None,
        token_tracker=None,
    ):
        """Initialize the generator.

        Args:
            graph_store: For querying service/dependency graph context.
            embedding_store: For finding relevant code chunks.
            doc_pattern_store: For loading learned design patterns.
            llm_client: Optional LLM client for rich generation.
            token_tracker: Optional :class:`~corbell.core.token_tracker.TokenUsageTracker`.
        """
        self.graph = graph_store
        self.embeddings = embedding_store
        self.patterns = doc_pattern_store
        self.llm = llm_client
        self.token_tracker = token_tracker

    def generate(
        self,
        feature: str,
        prd: str,
        services: Optional[List[str]] = None,
        output_dir: Path = Path("."),
        spec_id: Optional[str] = None,
        author: Optional[str] = None,
        max_code_chunks: int = 15,
        all_service_ids: Optional[List[str]] = None,
        design_doc_paths: Optional[List[Path]] = None,
        full_graph: bool = False,
    ) -> Path:
        """Generate a technical design document.

        Services are automatically discovered from the PRD when ``services``
        is not provided (recommended).

        Args:
            feature: Short feature name (used for filename and title).
            prd: Full PRD / feature description text.
            services: Optional explicit list of service IDs. When None,
                services are auto-discovered from the embedding index.
            output_dir: Directory to write the ``.md`` file.
            spec_id: Optional explicit spec ID (default: slugified feature name).
            author: Optional author name.
            max_code_chunks: Max code snippets to include in LLM context.
            all_service_ids: All known service IDs (for auto-discovery fallback).
            design_doc_paths: Optional existing design doc paths to extract
                patterns from (supplements doc_pattern_store).

        Returns:
            Path to the generated spec Markdown file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        slug = spec_id or self._slugify(feature)
        out_path = output_dir / f"{slug}.md"

        # Auto-discover services from PRD if not supplied
        if not services and all_service_ids:
            services = self._auto_discover_services(prd, all_service_ids)
            print(f"   Auto-discovered services: {services}")

        services = services or []

        # Inject infrastructure services automatically
        all_svcs = self.graph.get_all_services()
        for svc in all_svcs:
            if getattr(svc, "service_type", "service") == "infrastructure" and svc.id not in services:
                services.append(svc.id)
                print(f"   Added infrastructure service to context: {svc.id}")

        # Build front-matter
        fm = SpecFrontmatter(
            id=slug,
            title=feature,
            services=ServicesBlock(
                primary=services[0] if services else "",
                related=services[1:] if len(services) > 1 else [],
            ),
            status="draft",
            author=author or "",
            created_at=str(date.today()),
            updated_at=str(date.today()),
        )

        # Load additional patterns from design doc paths
        extra_patterns = self._load_design_doc_patterns(design_doc_paths or [])

        # Build graph context
        graph_context = self._build_graph_context(services, full_graph=full_graph)

        # Build code context (embedding search)
        code_context, file_list = self._build_code_context_with_filelist(
            prd, services, max_code_chunks, full_graph=full_graph
        )
        patterns_context = self._build_patterns_context(prd, extra_patterns)

        # Generate body
        if self.llm and self.llm.is_configured:
            body = self._generate_with_llm(
                feature, prd, graph_context, code_context, patterns_context, file_list, services, full_graph=full_graph
            )
        else:
            body = self._generate_template(feature, prd, graph_context, code_context)

        # Write file
        full_content = serialize_frontmatter(fm) + body
        out_path.write_text(full_content, encoding="utf-8")
        return out_path

    def generate_existing_codebase(
        self,
        output_dir: Path,
        services: Optional[List[str]] = None,
        spec_id: Optional[str] = None,
        author: Optional[str] = None,
        max_code_chunks: int = 20,
    ) -> Path:
        """Generate a design document that describes the EXISTING codebase.

        Use this when you have no new PRD — just want to capture what the
        current system does, how it’s structured, and key flows.

        Args:
            output_dir: Directory to write the doc.
            services: Service IDs to focus on (None = all known services).
            spec_id: Filename slug. Defaults to ``existing-codebase-design``.
            author: Optional author name.
            max_code_chunks: Max code snippets (higher for codebase docs).

        Returns:
            Path to the generated Markdown file.
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        slug = spec_id or "existing-codebase-design"
        out_path = output_dir / f"{slug}.md"

        all_svcs = self.graph.get_all_services()
        focus = services or [s.id for s in all_svcs]

        graph_context = self._build_graph_context(focus)
        code_chunks = self._get_existing_codebase_chunks(focus, max_code_chunks)
        code_context = self._format_chunks(code_chunks)
        repo_index = self._build_repo_index(focus)

        if self.llm and self.llm.is_configured:
            body = self._generate_existing_with_llm(graph_context, code_context, repo_index)
        else:
            body = self._generate_existing_template(graph_context, code_context, repo_index)

        # Minimal front-matter for existing codebase docs
        fm = SpecFrontmatter(
            id=slug,
            title=f"Codebase Design: {', '.join(focus[:3])}",
            services=ServicesBlock(primary=focus[0] if focus else ""),
            status="draft",
            author=author or "",
            created_at=str(date.today()),
        )

        full_content = serialize_frontmatter(fm) + body
        out_path.write_text(full_content, encoding="utf-8")
        return out_path

    # ------------------------------------------------------------------ #
    # Auto-discovery                                                        #
    # ------------------------------------------------------------------ #

    def _auto_discover_services(self, prd: str, all_service_ids: List[str]) -> List[str]:
        """Use PRDProcessor to find services relevant to this PRD."""
        try:
            from corbell.core.prd_processor import PRDProcessor
            proc = PRDProcessor(llm_client=self.llm)
            return proc.discover_relevant_services(prd, self.embeddings, all_service_ids, top_k=3)
        except Exception:
            return all_service_ids[:2]

    # ------------------------------------------------------------------ #
    # LLM generation — new PRD mode                                        #
    # ------------------------------------------------------------------ #

    def _generate_with_llm(
        self,
        feature: str,
        prd: str,
        graph_context: str,
        code_context: str,
        patterns_context: str,
        file_list: str,
        services: List[str],
        full_graph: bool = False,
    ) -> str:
        assert self.llm

        constraints_placeholder = (
            "<!-- Add constraints manually. -->\n\n"
            "**Manual constraints example** (add your team's real constraints here):\n"
            "- Only deploy to Azure (no AWS services)\n"
            "- All PII must be encrypted at rest and in transit\n"
            "- p99 latency must be < 200ms for all synchronous API calls\n"
            "- No single points of failure; must survive AZ failure\n"
            "- Rate limit all external API calls to prevent cascade failures"
        )

        full_graph_instructions = ""
        if full_graph:
            full_graph_instructions = (
                "\nIMPORTANT: You have been provided with the FULL method graph skeletal context for these services. "
                "Analyze the full graph to identify relevant cross-service boundaries and method chains. "
                "For infrastructure services, use the context to deeply understand the deployed infrastructure and cloud resources. "
                "Do NOT include the whole skeletal graph in your final design output. Keep the 'Current Architecture' "
                "section relevant to the feature request and concise. Use the graph context to ensure your proposed changes "
                "respect the existing call paths and service boundaries."
            )

        system = _SYSTEM_PROMPT.format(
            title=feature,
            graph_block=graph_context,
            constraints_block=constraints_placeholder,
        )
        if full_graph:
            system += full_graph_instructions

        code_chunks_count = code_context.count("### ")
        user = _USER_PROMPT_TEMPLATE.format(
            prd=prd[:6000],
            code_context=code_context[:8000],
            graph_context=graph_context[:2000],
            patterns_context=patterns_context[:3000],
            file_list=file_list,
            code_chunks_count=code_chunks_count,
        )

        raw = self.llm.call(
            system_prompt=system,
            user_prompt=user,
            max_tokens=8000,
            temperature=0.1,
            request_type="spec_generation",
        )

        return self._postprocess(raw, feature, graph_context)

    # ------------------------------------------------------------------ #
    # LLM generation — existing codebase mode                              #
    # ------------------------------------------------------------------ #

    def _generate_existing_with_llm(
        self, graph_context: str, code_context: str, repo_index: str
    ) -> str:
        assert self.llm

        user = (
            f"**Service Graph:**\n{graph_context}\n\n"
            f"**Repository folder structure:**\n{repo_index}\n\n"
            f"**Relevant code chunks:**\n{code_context[:8000]}\n\n"
            "Produce a single markdown design document describing this existing codebase (4-6 pages max)."
        )

        return self.llm.call(
            system_prompt=_EXISTING_CODEBASE_SYSTEM_PROMPT,
            user_prompt=user,
            max_tokens=6000,
            temperature=0.1,
            request_type="existing_codebase_design",
        )

    def _generate_existing_template(
        self, graph_context: str, code_context: str, repo_index: str
    ) -> str:
        return f"""## Overview

> ⚠️ Template mode — configure an LLM key for auto-generated content.

{graph_context}

## Key Code Context

{code_context[:3000]}

## Repository Structure

{repo_index}
"""

    # ------------------------------------------------------------------ #
    # Template mode (no LLM)                                              #
    # ------------------------------------------------------------------ #

    def _generate_template(
        self, feature: str, prd: str, graph_context: str, code_context: str
    ) -> str:
        return f"""# {feature}

> ⚠️ **Template mode** — no LLM configured. Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` for full generation.

## Context

{prd}

## Current Architecture

<!-- CORBELL_GRAPH_START -->
{graph_context}
<!-- CORBELL_GRAPH_END -->

## Proposed Design

### Service Changes

<!-- Describe changes per service. -->

### Data Flow

<!-- Add a Mermaid sequence diagram. -->

### Failure Modes and Mitigations

<!-- Document failure modes and mitigations. -->

## Reliability and Risk Constraints

<!-- CORBELL_CONSTRAINTS_START -->
<!-- Add your team's infrastructure and reliability constraints here.
     Examples:
     - Cloud provider restrictions: "Only Azure, no AWS services"
     - Scaling limits: "Max 500 req/s per instance, horizontal scaling only"
     - Security: "All PII encrypted at rest (AES-256) and in transit (TLS 1.2+)"
     - Latency SLOs: "p99 API response < 200ms"
     - Availability: "Must survive AZ failure (2 of 3 region AZs)"
     These constraints are surfaced in spec:review and enforced in spec:lint. -->
<!-- CORBELL_CONSTRAINTS_END -->

## Rollout Plan

<!-- Describe phased rollout, feature flags, rollback plan. -->

---

## Relevant Code Context

```
{code_context[:3000]}
```
"""

    # ------------------------------------------------------------------ #
    # Context builders                                                     #
    # ------------------------------------------------------------------ #

    def _build_graph_context(self, services: List[str], full_graph: bool = False) -> str:
        lines = ["### Service Graph\n"]
        for svc_id in services:
            svc = self.graph.get_service(svc_id)
            if svc:
                lines.append(f"**{svc.name}** (`{svc.id}`, {svc.language}, type: {svc.service_type})")
                if getattr(svc, "service_type", "service") == "infrastructure":
                    lines.append("  *(Infrastructure Configuration / CDK Repository)*")
            else:
                lines.append(f"**{svc_id}** (not yet scanned)")
            deps = self.graph.get_dependencies(svc_id)
            for dep in deps:
                lines.append(f"  → {dep.target_id} [{dep.kind}]")
            
            if full_graph:
                # Include ALL methods and their relationships for this service
                methods = self.graph.get_methods_for_service(svc_id)
                if methods:
                    lines.append("  \n  **Methods & Call Graph:**")
                    for m in methods:
                        # Skip test/mock methods even in full graph unless user really wants them
                        # But for now, let's keep the filter to keep it production-focused
                        m_name = m.method_name.lower()
                        if m_name.startswith("test_") or "mock" in m_name:
                            continue
                            
                        lines.append(f"  - `{m.method_name}`: {m.signature}")
                        # Who calls this method?
                        callers = self.graph.get_callers_of_method(m.id)
                        if callers:
                            caller_names = [f"`{c.method_name}`" for c in callers[:5]]
                            lines.append(f"    (Called by: {', '.join(caller_names)})")

            lines.append("")

        all_svcs = self.graph.get_all_services()
        if all_svcs:
            lines.append("### All Known Services")
            for s in all_svcs:
                lines.append(f"- `{s.id}` ({s.language}) tags: {s.tags}")

        return "\n".join(lines)

    def _build_code_context_with_filelist(
        self, prd: str, services: List[str], max_chunks: int, full_graph: bool = False
    ) -> Tuple[str, str]:
        """Return (code_context_str, file_list_str)."""
        chunks = self._query_code_chunks(prd, services, max_chunks, full_graph=full_graph)
        if not chunks:
            return "(no code context found — run `corbell embeddings:build` first)", "(none found)"

        seen_files: dict[str, str] = {}
        context_parts: List[str] = []

        for rec in chunks:
            key = f"{rec.file_path}::{rec.symbol or rec.chunk_type}"
            label = f"[{rec.service_id}] {rec.file_path}"
            if rec.symbol:
                label += f" :: {rec.symbol}"
            context_parts.append(
                f"### {label} (lines {rec.start_line}–{rec.end_line})\n"
                f"```{rec.language}\n{rec.content[:500]}\n```"
            )
            fp = f"[{rec.service_id}] {rec.file_path}"
            if fp not in seen_files:
                seen_files[fp] = rec.symbol or rec.chunk_type

        file_list = "\n".join(
            f"- `{fp}`" + (f" (contains: `{sym}`)" if sym else "")
            for fp, sym in seen_files.items()
        )

        return "\n\n".join(context_parts), file_list

    def _query_code_chunks(
        self, prd: str, services: List[str], max_chunks: int, full_graph: bool = False
    ) -> List[Any]:
        """Query code chunks using PRDProcessor queries with .md retry logic.

        Steps:
        1. Generate 3-4 natural-language search queries from PRD
        2. For each query, search the embedding store
        3. If >60% results are .md files, retry with code-specific suffix
        4. Merge: code chunks first, .md chunks as supplemental fallback only
        5. Filter out test/logging files
        6. Deduplicate by file path, cap to max_chunks
        """
        # Suffixes appended on retry when results are dominated by .md files
        _CODE_SUFFIXES = [
            " implementation source code",
            " function class module",
        ]
        # Path fragments to skip (test files, logging config)
        _SKIP_FRAGMENTS = (
            "/tests/", "/test_", "_test.", "test_", "__tests__", "/mocks/", "/mock_",
            "logging_config", "log_config", "/fixtures/",
        )

        def _is_md(rec) -> bool:
            return getattr(rec, "language", "") == "markdown" or rec.file_path.lower().endswith(".md")

        def _mostly_md(recs, threshold=0.6) -> bool:
            if not recs:
                return False
            return sum(1 for r in recs if _is_md(r)) / len(recs) >= threshold

        def _should_skip(rec) -> bool:
            return any(frag in rec.file_path for frag in _SKIP_FRAGMENTS)

        try:
            from corbell.core.embeddings.model import SentenceTransformerModel
            from corbell.core.prd_processor import PRDProcessor
            from rich.console import Console
            console = Console()

            proc = PRDProcessor(llm_client=self.llm)
            
            # Step 1: LLM Semantic Queries
            queries = proc.create_search_queries(prd)
            
            console.print(f"\n[bold cyan]1. LLM Semantic Search Queries[/bold cyan] (generated from PRD):")
            for q in queries:
                console.print(f"  [dim]→[/dim] {q}")

            # Step 2: Extract keywords and query Graph store for relevant Method names
            keywords = proc.extract_keywords(prd)
            
            relevant_methods = []
            if self.graph:
                all_methods = []
                # Fetch methods from relevant services (or all if None)
                target_services = services if services else [s.id for s in self.graph.get_all_services()]
                for svc in target_services:
                    all_methods.extend(self.graph.get_methods_for_service(svc))
                
                if full_graph:
                    # In full_graph mode, we consider everything (except raw test/mock)
                    console.print(f"\n[bold green]2. Full Graph Context Enabled[/bold green], no relevant methods)")
                else:
                    console.print(f"\n[bold cyan]2. Graph Store Method Lookup[/bold cyan] (using keywords: {', '.join(keywords[:5])}...)")
                    # Filter methods by keyword match
                    lower_keywords = [k.lower() for k in keywords]
                    for m in all_methods:
                        m_name = m.method_name.lower()
                        # Final safety: skip test/mock methods
                        if m_name.startswith("test_") or "mock" in m_name:
                            continue
                        if any(k in m_name for k in lower_keywords):
                            relevant_methods.append(m)
            
            # Rank and pick unique method names
            method_names = list(set(m.method_name for m in relevant_methods))
            
            # Use a larger set for full_graph to broaden the embedding search
            method_cap = 400 if full_graph else 10
            method_names = method_names[:method_cap]
            
            if method_names:
                console.print(f"  [dim]Found {len(relevant_methods)} matching methods in graph. Top targets:[/dim]")
                for mn in method_names[:8]:
                     console.print(f"  [yellow]ƒ[/yellow] {mn}")
                
                # Append method names as specific code queries
                method_queries = [f"function {mn} implementation source code" for mn in method_names]
                
                # Only use method-derived queries for retrieval if we are NOT in full_graph mode.
                # In full_graph mode, we already have the structural map and don't want to 
                # spam the vector store with 400+ specific method lookups.
                if not full_graph:
                    queries.extend(method_queries)
            else:
                console.print("  [dim]No specific method names found in graph matching PRD keywords.[/dim]")

            # Step 3: Execute Embedding Store search
            console.print(f"\n[bold cyan]3. Embedding Store Retrieval[/bold cyan] (executing {len(queries)} queries)")
            model = SentenceTransformerModel()
            seen_ids: set = set()
            all_code_chunks: list = []
            all_md_chunks: list = []

            per_query_k = max(5, max_chunks // max(len(queries), 1) + 2)

            for i, query in enumerate(queries):
                query_code: list = []
                query_md: list = []

                for attempt in range(3):  # 0 = original, 1 = retry 1, 2 = retry 2
                    current_q = query if attempt == 0 else query + _CODE_SUFFIXES[attempt - 1]
                    qvec = model.encode([current_q])[0]
                    hits = self.embeddings.query(
                        qvec,
                        service_ids=services or None,
                        top_k=per_query_k,
                    )
                    
                    if attempt == 0:
                        # Log every original query hit to ensure transparency
                        console.print(f"  [dim]Query {i+1} hits: {len(hits)} raw chunks retrieved[/dim] - [dim italic]'{current_q}'[/dim]")

                    # Partition into code vs .md
                    for r in hits:
                        if r.id in seen_ids or _should_skip(r):
                            continue
                        if _is_md(r):
                            query_md.append(r)
                        else:
                            query_code.append(r)

                    if query_code:
                        break  # Got real code chunks, no need to retry

                    if attempt < 2:
                        print(
                            f"   Query {i+1}: results mostly .md, retrying with code suffix"
                            f" (attempt {attempt + 1}/2)…"
                        )

                # Mark seen
                for r in query_code + query_md:
                    seen_ids.add(r.id)

                all_code_chunks.extend(query_code)
                if not query_code:
                    # Only use .md chunks as supplemental when no code found
                    all_md_chunks.extend(query_md)

            # Code-first ordering, .md chunks appended only as fallback
            combined = all_code_chunks + all_md_chunks

            # Deduplicate by file path (keep highest-ranked per file)
            seen_files: dict = {}
            deduped: list = []
            for r in combined:
                fkey = f"{r.service_id}:{r.file_path}"
                if fkey not in seen_files:
                    seen_files[fkey] = True
                    deduped.append(r)

            final_chunks = deduped[:max_chunks]
            console.print(f"\n[bold green]✓ Embeddings search complete: Selected {len(final_chunks)} exact code chunks for LLM context[/bold green]")
            for c in final_chunks:
                console.print(f"  [dim]- {c.file_path} (lines {c.start_line}-{c.end_line}) {':: ' + c.symbol if c.symbol else ''}[/dim]")
                
            return final_chunks

        except Exception as e:
            print(f"⚠️  Code chunk query failed: {e}")
            return []

    def _get_existing_codebase_chunks(self, services: List[str], max_chunks: int) -> list:
        """Retrieve chunks representative of the entire codebase (no PRD)."""
        priority_queries = [
            "main entry point server startup",
            "API route handler request response",
            "database connection query model",
            "background worker task queue consumer",
            "configuration environment settings",
        ]
        try:
            from corbell.core.embeddings.model import SentenceTransformerModel
            model = SentenceTransformerModel()
            seen: set = set()
            results = []
            for q in priority_queries:
                qvec = model.encode([q])[0]
                hits = self.embeddings.query(
                    qvec, service_ids=services or None, top_k=5
                )
                for r in hits:
                    if r.id not in seen:
                        seen.add(r.id)
                        results.append(r)
        except Exception:
            results = []

        # Sort: prefer entry points and API files
        def priority(r):
            fname = r.file_path.lower()
            if any(kw in fname for kw in ("main", "app", "server", "router", "api")):
                return 0
            if r.chunk_type in ("function", "method"):
                return 1
            return 2

        results.sort(key=priority)
        return results[:max_chunks]

    def _format_chunks(self, chunks: list) -> str:
        if not chunks:
            return "(no code chunks found — run `corbell embeddings:build`)"
        parts = []
        for r in chunks:
            label = f"[{r.service_id}] {r.file_path}"
            if r.symbol:
                label += f" :: {r.symbol}"
            parts.append(
                f"**File: {label}** (lines {r.start_line}–{r.end_line})\n"
                f"```{r.language}\n{r.content[:600]}\n```"
            )
        return "\n\n".join(parts)

    def _build_repo_index(self, services: List[str]) -> str:
        """Build a folder-to-purpose index for existing codebase docs."""
        lines = []
        for svc_id in services:
            svc = self.graph.get_service(svc_id)
            if not svc or not svc.repo:
                continue
            repo = Path(svc.repo)
            if not repo.exists():
                continue
            lines.append(f"\n**{svc_id}** ({svc.language}):")
            # Top-level folders
            for entry in sorted(repo.iterdir()):
                if entry.is_dir() and not entry.name.startswith("."):
                    lines.append(f"  - `{entry.name}/`")
        return "\n".join(lines) if lines else "(repo paths not available)"

    def _build_patterns_context(self, prd: str, extra_patterns: List[DocPattern]) -> str:
        """Combine stored patterns + extra patterns from design doc paths."""
        stored = self.patterns.load()
        all_patterns = stored + extra_patterns

        if not all_patterns:
            return "No doc patterns found. Run `corbell docs:scan && corbell docs:learn` first."

        learner = DocLearner()
        relevant = self._filter_relevant_patterns(prd, all_patterns)
        return learner.format_patterns_for_prompt(relevant[:5])

    def _load_design_doc_patterns(self, paths: List[Path]) -> List[DocPattern]:
        """Extract patterns from explicit design doc paths (supplement to stored patterns)."""
        if not paths:
            return []
        from corbell.core.docs.models import CandidateDoc
        from corbell.core.docs.learner import DocLearner
        candidates = [
            CandidateDoc(
                path=str(p),
                detected_type="design_doc",
                title=p.stem,
                confirmed=True,
            )
            for p in paths if p.exists()
        ]
        learner = DocLearner(llm_client=self.llm)
        return learner.learn_from_docs(candidates)

    def _filter_relevant_patterns(self, prd: str, patterns: List[DocPattern]) -> List[DocPattern]:
        prd_lower = prd.lower()
        scored = []
        for pat in patterns:
            score = sum(1 for t in list(pat.terminology.keys())[:10] if t.lower() in prd_lower)
            score += sum(1 for d in pat.decisions[:3] if d.summary and any(w in prd_lower for w in d.summary.lower().split()))
            scored.append((score, pat))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [p for _, p in scored]

    def _postprocess(self, content: str, feature: str, graph_context: str) -> str:
        """Ensure markers present, clean temp file paths."""
        if "<!-- CORBELL_GRAPH_START -->" not in content:
            content = content.replace(
                "## Current Architecture",
                f"## Current Architecture\n\n<!-- CORBELL_GRAPH_START -->\n{graph_context}\n<!-- CORBELL_GRAPH_END -->",
                1,
            )
        if "<!-- CORBELL_CONSTRAINTS_START -->" not in content:
            content = content.replace(
                "## Reliability and Risk Constraints",
                "## Reliability and Risk Constraints\n\n<!-- CORBELL_CONSTRAINTS_START -->\n<!-- CORBELL_CONSTRAINTS_END -->",
                1,
            )
        # Clean internal temp paths
        content = re.sub(r"/tmp/[^\s/]+/", "[repo]/", content)
        content = re.sub(r"/Users/[^/]+/[^/]+/([^/]+)/", r"[\1]/", content)
        return content

    @staticmethod
    def _slugify(text: str) -> str:
        slug = text.lower().strip()
        slug = re.sub(r"[^\w\s-]", "", slug)
        slug = re.sub(r"[\s_-]+", "-", slug)
        return slug[:60].strip("-")
