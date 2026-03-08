"""LLM client for Corbell OSS — with token usage tracking.

Supports OpenAI, Anthropic, and Ollama providers.
API keys are read from environment variables or workspace.yaml llm config.

No AWS Bedrock dependency — OSS-friendly provider options only.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from corbell.core.token_tracker import TokenUsageTracker


class LLMClient:
    """Provider-agnostic LLM client for Corbell.

    Supports:
    - ``openai``  — requires ``openai>=1.0`` and ``OPENAI_API_KEY``
    - ``anthropic`` — requires ``anthropic>=0.25`` and ``ANTHROPIC_API_KEY``
    - ``ollama``  — requires a running Ollama server (http://localhost:11434)

    Falls back to a structured template response when no API key is found.
    Token usage is automatically tracked in the provided ``TokenUsageTracker``.
    """

    def __init__(
        self,
        provider: str = "anthropic",
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        token_tracker: Optional["TokenUsageTracker"] = None,
    ):
        """Initialize the LLM client.

        Args:
            provider: One of ``openai``, ``anthropic``, ``ollama``.
            model: Model identifier. Defaults per provider:
                - anthropic: ``claude-3-5-sonnet-20241022``
                - openai: ``gpt-4o``
                - ollama: ``llama3``
            api_key: API key. If None, read from env vars
                (``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` / ``CORBELL_LLM_API_KEY``).
            token_tracker: Optional :class:`~corbell.core.token_tracker.TokenUsageTracker`
                instance. Each API call records its token usage here.
        """
        self.provider = provider.lower()
        self._api_key = api_key or self._resolve_key()
        self.token_tracker = token_tracker

        _defaults = {
            "anthropic": "claude-3-5-sonnet-20241022",
            "openai": "gpt-4o",
            "ollama": "llama3",
        }
        self.model = model or _defaults.get(self.provider, "claude-3-5-sonnet-20241022")

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def call(
        self,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int = 8000,
        temperature: float = 0.1,
        request_type: Optional[str] = None,
    ) -> str:
        """Call the configured LLM provider.

        Args:
            system_prompt: System / persona prompt.
            user_prompt: User message / context.
            max_tokens: Max tokens in the response.
            temperature: Sampling temperature.
            request_type: Label for token tracking (e.g. ``spec_generation``).

        Returns:
            Text response string. Falls back to structured template if no API key.
        """
        if not self._api_key and self.provider != "ollama":
            return self._fallback_response(system_prompt, user_prompt)

        try:
            if self.provider == "anthropic":
                return self._call_anthropic(
                    system_prompt, user_prompt, max_tokens, temperature,
                    request_type=request_type or "call",
                )
            if self.provider == "openai":
                return self._call_openai(
                    system_prompt, user_prompt, max_tokens, temperature,
                    request_type=request_type or "call",
                )
            if self.provider == "ollama":
                return self._call_ollama(system_prompt, user_prompt, max_tokens)
        except Exception as e:
            print(f"⚠️  LLM call failed ({self.provider}): {e}")
            return self._fallback_response(system_prompt, user_prompt)

        return self._fallback_response(system_prompt, user_prompt)

    @property
    def is_configured(self) -> bool:
        """True if an API key (or Ollama) is available."""
        return bool(self._api_key) or self.provider == "ollama"

    # ------------------------------------------------------------------ #
    # Provider implementations                                             #
    # ------------------------------------------------------------------ #

    def _call_anthropic(
        self, system: str, user: str, max_tokens: int, temperature: float,
        request_type: str = "call",
    ) -> str:
        try:
            import anthropic
        except ImportError:
            raise ImportError("Install corbell[anthropic] to use Anthropic: pip install corbell[anthropic]")

        client = anthropic.Anthropic(api_key=self._api_key)
        msg = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system,
            messages=[{"role": "user", "content": user}],
        )

        # Track token usage
        if self.token_tracker and hasattr(msg, "usage"):
            self.token_tracker.record(
                request_type=request_type,
                model=self.model,
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
            )

        return msg.content[0].text

    def _call_openai(
        self, system: str, user: str, max_tokens: int, temperature: float,
        request_type: str = "call",
    ) -> str:
        try:
            import openai
        except ImportError:
            raise ImportError("Install corbell[openai] to use OpenAI: pip install corbell[openai]")

        client = openai.OpenAI(api_key=self._api_key)
        resp = client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )

        # Track token usage
        if self.token_tracker and resp.usage:
            self.token_tracker.record(
                request_type=request_type,
                model=self.model,
                input_tokens=resp.usage.prompt_tokens,
                output_tokens=resp.usage.completion_tokens,
            )

        return resp.choices[0].message.content or ""

    def _call_ollama(self, system: str, user: str, max_tokens: int) -> str:
        """Call a local Ollama instance (no token tracking — local model)."""
        import urllib.request

        payload = json.dumps(
            {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "stream": False,
                "options": {"num_predict": max_tokens},
            }
        ).encode()

        req = urllib.request.Request(
            "http://localhost:11434/api/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
        return data.get("message", {}).get("content", "")

    # ------------------------------------------------------------------ #
    # Helpers                                                              #
    # ------------------------------------------------------------------ #

    def _resolve_key(self) -> Optional[str]:
        env_map = {
            "anthropic": ["ANTHROPIC_API_KEY", "CORBELL_LLM_API_KEY"],
            "openai": ["OPENAI_API_KEY", "CORBELL_LLM_API_KEY"],
            "ollama": [],
        }
        for var in env_map.get(self.provider, ["CORBELL_LLM_API_KEY"]):
            val = os.environ.get(var)
            if val:
                return val
        return None

    def _fallback_response(self, system: str, user: str) -> str:
        """Return a structured template when no LLM is available."""
        if "design document" in system.lower() or "technical design" in system.lower():
            return _MOCK_DESIGN_DOC
        if "design decisions" in system.lower() or "extract" in system.lower():
            return "[]"
        if "pattern" in system.lower():
            return "{}"
        if "search" in system.lower() or "keywords" in system.lower() or "queries" in system.lower():
            # Fallback: split user text into sentences
            import re
            sentences = [s.strip() for s in re.split(r'[.\n]', user) if len(s.strip()) > 30]
            return "\n".join(sentences[:3]) if sentences else user[:200]
        return (
            "⚠️  No LLM API key configured. Set ANTHROPIC_API_KEY or OPENAI_API_KEY "
            "and re-run, or pass --no-llm to use template mode."
        )


_MOCK_DESIGN_DOC = """\
# Technical Design Document

> ⚠️ **Template mode**: LLM provider not configured.
> Set `ANTHROPIC_API_KEY` (Anthropic) or `OPENAI_API_KEY` (OpenAI) and re-run.

## Context

<!-- Describe WHY this feature is being built. -->

## Current Architecture

<!-- CORBELL_GRAPH_START -->
<!-- Current service graph will be inserted here by corbell. -->
<!-- CORBELL_GRAPH_END -->

## Proposed Design

### Service Changes

<!-- What changes in each service. -->

### Data Flow

<!-- Sequence or description of how data moves. -->

### Failure Modes

<!-- What can go wrong, how each is handled. -->

## Reliability and Risk Constraints

<!-- CORBELL_CONSTRAINTS_START -->
<!-- Constraints go here. -->
<!-- CORBELL_CONSTRAINTS_END -->

## Rollout Plan

<!-- Phases, feature flags, rollback plan. -->

## Open Questions

<!-- Things not yet decided. -->
"""
