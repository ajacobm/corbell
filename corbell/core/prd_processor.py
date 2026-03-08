"""PRD processor — extract natural-language search queries + service hints for auto-discovery.

Adapted from specgen_local/src/prd_processor.py with OSS improvements:
- No Supabase dependency
- Returns service-relevance scores against the graph
- Also identifies relevant service IDs from graph without user specifying them
"""

from __future__ import annotations

import re
from typing import List, Optional


class PRDProcessor:
    """Process PRD text to produce search queries and auto-discover relevant services.

    When no ``--service`` flag is passed to ``corbell spec new``, this class:
    1. Uses the LLM (or fallback regex) to generate 3-4 natural-language code search queries
    2. Runs those queries against the embedding store to find matching code chunks
    3. Scores services by how many of their chunks match, and returns the top services

    This is the recommended mode — the user only needs to describe their feature,
    not map it to specific service IDs.
    """

    def __init__(self, llm_client=None):
        """Initialize the processor.

        Args:
            llm_client: Optional :class:`~corbell.core.llm_client.LLMClient`.
                Falls back to sentence-splitting without LLM.
        """
        self.llm = llm_client

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def create_search_queries(self, prd_text: str) -> List[str]:
        """Produce 3-4 natural-language queries describing *what code to look for*.

        These are sentence-form descriptions, not keyword lists — they embed far
        closer to actual source code than keyword soup.

        Adapted from specgen_local prd_processor.py ``create_search_queries``.

        Args:
            prd_text: Full PRD / feature description text.

        Returns:
            List of 1-4 sentence queries suitable for embedding similarity search.
        """
        if not self.llm or not self.llm.is_configured:
            return self._fallback_queries(prd_text)

        system_prompt = (
            "You are a code search expert helping find relevant source-code files in a codebase.\n\n"
            "Given a Product Requirements Document (PRD), produce exactly 3 short, natural-language search queries.\n"
            "Each query must describe a *specific piece of implementation code* that would need to be written "
            "or modified to fulfil the PRD.\n\n"
            "Rules:\n"
            "- Write each query as a plain English phrase describing what the code *does*, not what technology it uses.\n"
            "- Be specific about the functionality: mention what the function/class/module is responsible for.\n"
            "- Do NOT mention specific frameworks, folders, or infrastructure platforms — describe behaviour.\n"
            "- Respond with exactly 3 lines, one query per line, no numbering, no bullets.\n\n"
            "Example output for PRD 'Add rate limiting to the web API':\n"
            "function that intercepts incoming requests and enforces a per-user request rate limit\n"
            "class that tracks and increments request counts within a sliding time window\n"
            "handler that returns an error response when the rate limit is exceeded"
        )
        user_prompt = f"PRD:\n\n{prd_text[:1500]}\n\nGenerate 3 code search queries:"

        try:
            response = self.llm.call(system_prompt, user_prompt, max_tokens=300, temperature=0.0)
            lines = [ln.strip() for ln in response.strip().splitlines() if ln.strip()]
            queries = [re.sub(r'^[\d\.\-\*\)]+\s*', '', ln) for ln in lines if len(ln) > 10]
            if queries:
                return queries[:4]
        except Exception:
            pass

        return self._fallback_queries(prd_text)

    def discover_relevant_services(
        self,
        prd_text: str,
        embedding_store,
        all_service_ids: List[str],
        top_k: int = 3,
    ) -> List[str]:
        """Auto-discover the most relevant services for a PRD via embedding search.

        Uses ``create_search_queries`` to generate description queries, then scores
        each service by how many of its code chunks appear in the top results.

        Args:
            prd_text: Feature description / PRD text.
            embedding_store: :class:`~corbell.core.embeddings.sqlite_store.SQLiteEmbeddingStore`.
            all_service_ids: All known service IDs (from workspace config or graph).
            top_k: Number of services to return (default: 3).

        Returns:
            List of service IDs ordered by relevance (highest first).
        """
        queries = self.create_search_queries(prd_text)

        try:
            from corbell.core.embeddings.model import SentenceTransformerModel
            model = SentenceTransformerModel()
        except Exception:
            return all_service_ids[:top_k]

        service_scores: dict[str, float] = {svc: 0.0 for svc in all_service_ids}

        for query in queries:
            try:
                qvec = model.encode([query])[0]
                results = embedding_store.query(qvec, top_k=20)
                for i, rec in enumerate(results):
                    if rec.service_id in service_scores:
                        # Weight by position (higher rank = more weight)
                        service_scores[rec.service_id] += 1.0 / (i + 1)
            except Exception:
                continue

        ranked = sorted(service_scores.items(), key=lambda x: x[1], reverse=True)
        # Only return services with at least one match
        relevant = [svc for svc, score in ranked if score > 0]

        if not relevant:
            # Fall back to primary service (first in workspace config)
            return all_service_ids[:1]

        return relevant[:top_k]

    def extract_keywords(self, prd_text: str) -> List[str]:
        """Extract technical keywords for broad filtering (fallback / supplementary).

        Args:
            prd_text: PRD text to extract from.

        Returns:
            Up to 15 keywords/phrases.
        """
        if not self.llm or not self.llm.is_configured:
            return self._fallback_keywords(prd_text)

        system_prompt = (
            "Extract the most relevant technical keywords from this PRD that would help find related code "
            "in a vector search. Return only a comma-separated list of technical terms. "
            "Focus on: function names, API endpoints, data models, domain entities, business operations."
        )
        try:
            resp = self.llm.call(system_prompt, prd_text[:1500], max_tokens=200, temperature=0.0)
            resp = resp.strip()
            if ":" in resp and len(resp.split(":")[0]) < 50:
                resp = resp.split(":", 1)[1]
            keywords = [k.strip() for k in resp.split(",") if k.strip()]
            return keywords[:15]
        except Exception:
            return self._fallback_keywords(prd_text)

    # ------------------------------------------------------------------ #
    # Fallbacks                                                            #
    # ------------------------------------------------------------------ #

    def _fallback_queries(self, prd_text: str) -> List[str]:
        """Extract plain sentences from PRD as search queries."""
        sentences = [s.strip() for s in re.split(r'[.\n]', prd_text) if len(s.strip()) > 30]
        return sentences[:3] if sentences else [prd_text[:200]]

    def _fallback_keywords(self, prd_text: str) -> List[str]:
        words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9_-]{2,}\b', prd_text.lower())
        stop = {"with", "that", "this", "will", "from", "have", "been", "they", "their"}
        return list(dict.fromkeys(w for w in words if w not in stop))[:10]
