"""Design document generator — the heart of Corbell OSS.

Builds context from the graph, embeddings, and learned docs patterns,
then calls an LLM (OpenAI/Anthropic) to produce a full technical design
document in Markdown.

Key improvements over v1:
- **Auto service discovery**: No --service flag needed; PRDProcessor discovers
  relevant services automatically using embedding similarity.
- **Existing codebase mode**: Generate a design doc for the current codebase
  without any PRD (pass ``mode="existing"``).
- **Design doc context**: Existing .md design docs are extracted + fed to LLM.
- **Token tracking**: All LLM calls tracked and summarized.

Adapted from specgen_local/src/design_generator.py.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

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
# System prompts (adapted from specgen_local design_generator.py)
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

        # Build context blocks
        graph_context = self._build_graph_context(services)
        code_context, file_list = self._build_code_context_with_filelist(prd, services, max_code_chunks)
        patterns_context = self._build_patterns_context(prd, extra_patterns)

        # Generate body
        if self.llm and self.llm.is_configured:
            body = self._generate_with_llm(
                feature, prd, graph_context, code_context, patterns_context, file_list, services
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
        current system does, how it's structured, and key flows.

        Adapted from specgen_local ``generate_existing_codebase_design``.

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
    ) -> str:
        assert self.llm

        constraints_placeholder = (
            "<!-- Add constraints manually or let Corbell SaaS populate incident_derived. -->\n\n"
            "**Manual constraints example** (add your team's real constraints here):\n"
            "- Only deploy to Azure (no AWS services)\n"
            "- All PII must be encrypted at rest and in transit\n"
            "- p99 latency must be < 200ms for all synchronous API calls\n"
            "- No single points of failure; must survive AZ failure\n"
            "- Rate limit all external API calls to prevent cascade failures"
        )

        system = _SYSTEM_PROMPT.format(
            title=feature,
            graph_block=graph_context,
            constraints_block=constraints_placeholder,
        )
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
     These constraints are surfaced in spec:review and enforced in spec:lint.
     Corbell SaaS adds incident_derived constraints automatically. -->
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

    def _build_graph_context(self, services: List[str]) -> str:
        lines = ["### Service Graph\n"]
        for svc_id in services:
            svc = self.graph.get_service(svc_id)
            if svc:
                lines.append(f"**{svc.name}** (`{svc.id}`, {svc.language}, type: {svc.service_type})")
            else:
                lines.append(f"**{svc_id}** (not yet scanned)")
            deps = self.graph.get_dependencies(svc_id)
            for dep in deps:
                lines.append(f"  → {dep.target_id} [{dep.kind}]")
            lines.append("")

        all_svcs = self.graph.get_all_services()
        if all_svcs:
            lines.append("### All Known Services")
            for s in all_svcs:
                lines.append(f"- `{s.id}` ({s.language}) tags: {s.tags}")

        return "\n".join(lines)

    def _build_code_context_with_filelist(
        self, prd: str, services: List[str], max_chunks: int
    ) -> tuple[str, str]:
        """Return (code_context_str, file_list_str)."""
        chunks = self._query_code_chunks(prd, services, max_chunks)
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

    def _query_code_chunks(self, prd: str, services: List[str], max_chunks: int) -> list:
        """Use PRDProcessor queries for smarter code retrieval."""
        try:
            from corbell.core.embeddings.model import SentenceTransformerModel
            from corbell.core.prd_processor import PRDProcessor

            proc = PRDProcessor(llm_client=self.llm)
            queries = proc.create_search_queries(prd)

            model = SentenceTransformerModel()
            seen_ids: set = set()
            results = []

            for query in queries:
                qvec = model.encode([query])[0]
                hits = self.embeddings.query(
                    qvec,
                    service_ids=services or None,
                    top_k=max(5, max_chunks // len(queries)),
                )
                for r in hits:
                    if r.id not in seen_ids:
                        seen_ids.add(r.id)
                        results.append(r)

            # De-prioritize markdown files if we have code chunks
            code_chunks = [r for r in results if r.language != "markdown"]
            md_chunks = [r for r in results if r.language == "markdown"]
            ordered = code_chunks + md_chunks
            return ordered[:max_chunks]

        except Exception:
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
