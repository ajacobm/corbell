"""Token usage tracker — local, no external dependencies.

Tracks per-call token usage (input + output) and estimated cost.
Accumulates usage across the entire CLI session and displays a rich summary.

Pricing constants are updated regularly; set CORBELL_COST_PER_1K_INPUT / OUTPUT
env vars to override.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Pricing tables (per 1K tokens, USD)
# update when providers change pricing
# ---------------------------------------------------------------------------

_MODEL_PRICING: Dict[str, Dict[str, float]] = {
    # Anthropic
    "claude-sonnet-4-5-20250929": {"input": 0.003, "output": 0.015},
    "claude-3-5-haiku-20241022":  {"input": 0.0008, "output": 0.004},
    "claude-3-haiku-20240307":    {"input": 0.00025, "output": 0.00125},
    "claude-3-opus-20240229":     {"input": 0.015, "output": 0.075},
    # OpenAI
    "gpt-4o":                     {"input": 0.005, "output": 0.015},
    "gpt-4o-mini":                {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo":                {"input": 0.01, "output": 0.03},
    # Ollama — free / local
    "llama3":                     {"input": 0.0, "output": 0.0},
    "mistral":                    {"input": 0.0, "output": 0.0},
}

_DEFAULT_INPUT_COST  = float(os.getenv("CORBELL_COST_PER_1K_INPUT",  "0.003"))
_DEFAULT_OUTPUT_COST = float(os.getenv("CORBELL_COST_PER_1K_OUTPUT", "0.015"))


def _cost_per_1k(model: str) -> tuple[float, float]:
    pricing = _MODEL_PRICING.get(model, {})
    return (
        pricing.get("input", _DEFAULT_INPUT_COST),
        pricing.get("output", _DEFAULT_OUTPUT_COST),
    )


@dataclass
class TokenUsageRecord:
    """A single LLM API call's token usage."""

    request_type: str
    model: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def estimated_cost_usd(self) -> float:
        cost_in, cost_out = _cost_per_1k(self.model)
        return round(
            (self.input_tokens / 1000) * cost_in
            + (self.output_tokens / 1000) * cost_out,
            6,
        )


class TokenUsageTracker:
    """Accumulate token usage across multiple LLM calls and display a rich summary.

    Usage:
        tracker = TokenUsageTracker()
        # passed into LLMClient; automatically records each call
        tracker.record("spec_generation", "claude-sonnet-4-5-20250929", 4000, 3200)
        tracker.record("keyword_extraction", "claude-sonnet-4-5-20250929", 300, 100)
        tracker.print_summary()
    """

    def __init__(self):
        self._records: List[TokenUsageRecord] = []

    def record(
        self,
        request_type: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> None:
        """Record a single LLM API call.

        Args:
            request_type: Label (e.g. ``spec_generation``, ``keyword_extraction``).
            model: Model identifier (used for cost lookup).
            input_tokens: Number of input tokens consumed.
            output_tokens: Number of output tokens generated.
        """
        self._records.append(
            TokenUsageRecord(
                request_type=request_type,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
            )
        )

    @property
    def total_input_tokens(self) -> int:
        return sum(r.input_tokens for r in self._records)

    @property
    def total_output_tokens(self) -> int:
        return sum(r.output_tokens for r in self._records)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    @property
    def total_cost_usd(self) -> float:
        return round(sum(r.estimated_cost_usd for r in self._records), 6)

    @property
    def call_count(self) -> int:
        return len(self._records)

    def print_summary(self, console=None) -> None:
        """Print a token usage summary table to the console.

        Args:
            console: A ``rich.console.Console`` instance. If None, uses a new default console.
        """
        if not self._records:
            return

        if console is None:
            from rich.console import Console
            console = Console()

        from rich.table import Table
        from rich.panel import Panel

        table = Table(title="Token Usage — This Session", show_header=True, header_style="bold cyan")
        table.add_column("Step", style="dim")
        table.add_column("Model", style="dim")
        table.add_column("Input ↑", justify="right")
        table.add_column("Output ↓", justify="right")
        table.add_column("Total", justify="right", style="yellow")
        table.add_column("Est. Cost", justify="right", style="green")

        for rec in self._records:
            table.add_row(
                rec.request_type,
                rec.model,
                f"{rec.input_tokens:,}",
                f"{rec.output_tokens:,}",
                f"{rec.total_tokens:,}",
                f"${rec.estimated_cost_usd:.5f}",
            )

        # Totals row
        table.add_section()
        table.add_row(
            "[bold]TOTAL[/bold]",
            f"{self.call_count} call(s)",
            f"[bold]{self.total_input_tokens:,}[/bold]",
            f"[bold]{self.total_output_tokens:,}[/bold]",
            f"[bold]{self.total_tokens:,}[/bold]",
            f"[bold green]${self.total_cost_usd:.5f}[/bold green]",
        )

        console.print(table)

    def summary_dict(self) -> Dict[str, Any]:
        """Return usage stats as a plain dict for programmatic use."""
        return {
            "calls": self.call_count,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": self.total_cost_usd,
            "breakdown": [
                {
                    "request_type": r.request_type,
                    "model": r.model,
                    "input_tokens": r.input_tokens,
                    "output_tokens": r.output_tokens,
                    "cost_usd": r.estimated_cost_usd,
                }
                for r in self._records
            ],
        }


# ---------------------------------------------------------------------------
# Context Pruner — intelligent context budget management
# ---------------------------------------------------------------------------

# Approximate characters per token.  GPT / Claude tokenizers average ~3.5–4.5
# chars per token on mixed English + code.  We use 4.0 as a safe middle ground.
_CHARS_PER_TOKEN: float = 4.0

# Default total token budget for the *input* context window sent to the LLM.
# This leaves headroom for the system prompt (~2k tokens) and output (~8k tokens).
_DEFAULT_TOKEN_BUDGET: int = 100_000


def estimate_tokens(text: str) -> int:
    """Estimate the token count for a string using a character-ratio heuristic.

    This avoids pulling in a heavy tokenizer dependency.  The estimate is
    intentionally conservative (rounds up) so we stay within budget.

    Args:
        text: The raw text to estimate.

    Returns:
        Estimated token count (always >= 0).
    """
    if not text:
        return 0
    import math
    return math.ceil(len(text) / _CHARS_PER_TOKEN)


@dataclass
class ContextSection:
    """A named section of LLM context with a priority weight.

    Attributes:
        name: Human-readable label (e.g. ``code_context``, ``graph_context``).
        content: The raw text content for this section.
        priority: Higher values mean the section is more important and will be
            pruned *last*.  Suggested scale 1-10.
        max_share: Maximum fraction of the total budget this section may consume
            (0.0–1.0).  Defaults to 1.0 (no cap beyond the global budget).
    """

    name: str
    content: str
    priority: int = 5
    max_share: float = 1.0

    @property
    def estimated_tokens(self) -> int:
        return estimate_tokens(self.content)


@dataclass
class PruneResult:
    """The output of a pruning pass.

    Attributes:
        sections: Dict mapping section name → pruned content string.
        total_tokens_before: Estimated tokens before pruning.
        total_tokens_after: Estimated tokens after pruning.
        pruned_sections: List of section names that were trimmed.
        budget: The token budget that was targeted.
    """

    sections: Dict[str, str]
    total_tokens_before: int
    total_tokens_after: int
    pruned_sections: List[str]
    budget: int


class ContextPruner:
    """Intelligent context pruner that fits multi-section context within a token budget.

    Instead of blindly slicing strings at a character offset, the pruner:

    1. Estimates the token count of each :class:`ContextSection`.
    2. If the total is within budget, returns everything unchanged.
    3. If over budget, iteratively trims the *lowest-priority* sections first —
       either by truncating to a proportional share or by summarizing the
       section down to its first N lines as a fallback.

    Usage::

        pruner = ContextPruner(budget=100_000)
        result = pruner.prune([
            ContextSection("prd", prd_text, priority=9, max_share=0.15),
            ContextSection("code_context", code_ctx, priority=8, max_share=0.40),
            ContextSection("graph_context", graph_ctx, priority=7, max_share=0.15),
            ContextSection("patterns", patterns_ctx, priority=5, max_share=0.15),
            ContextSection("file_list", file_list, priority=6, max_share=0.10),
        ])
        code_context = result.sections["code_context"]
    """

    def __init__(self, budget: int = _DEFAULT_TOKEN_BUDGET):
        """Initialize the pruner.

        Args:
            budget: Maximum total tokens across all sections.
        """
        self.budget = budget

    def prune(self, sections: List[ContextSection]) -> PruneResult:
        """Prune sections to fit within the token budget.

        Sections are processed lowest-priority-first.  Each section is first
        capped to its ``max_share`` of the budget, then if the aggregate still
        exceeds the budget, the lowest-priority sections are progressively
        truncated further.

        Args:
            sections: The context sections to prune.

        Returns:
            A :class:`PruneResult` with the pruned content and metadata.
        """
        if not sections:
            return PruneResult(
                sections={}, total_tokens_before=0, total_tokens_after=0,
                pruned_sections=[], budget=self.budget,
            )

        total_before = sum(s.estimated_tokens for s in sections)

        # Phase 1: Cap each section to its max_share of the budget
        working: Dict[str, str] = {}
        for sec in sections:
            cap_tokens = int(self.budget * sec.max_share)
            if sec.estimated_tokens > cap_tokens:
                working[sec.name] = _truncate_to_tokens(sec.content, cap_tokens)
            else:
                working[sec.name] = sec.content

        # Check if we're within budget after phase 1
        current_total = sum(estimate_tokens(v) for v in working.values())
        if current_total <= self.budget:
            pruned_names = [
                s.name for s in sections if working[s.name] != s.content
            ]
            return PruneResult(
                sections=working,
                total_tokens_before=total_before,
                total_tokens_after=current_total,
                pruned_sections=pruned_names,
                budget=self.budget,
            )

        # Phase 2: Still over budget — trim lowest-priority sections further
        sorted_sections = sorted(sections, key=lambda s: s.priority)
        overshoot = current_total - self.budget
        pruned_names: List[str] = []

        for sec in sorted_sections:
            if overshoot <= 0:
                break
            current_tokens = estimate_tokens(working[sec.name])
            if current_tokens == 0:
                continue

            # How much to keep for this section
            desired_tokens = max(current_tokens - overshoot, 0)

            # Always keep at least a small header/summary (min 50 tokens)
            min_keep = min(50, current_tokens)
            desired_tokens = max(desired_tokens, min_keep)

            if desired_tokens < current_tokens:
                working[sec.name] = _truncate_to_tokens(
                    working[sec.name], desired_tokens
                )
                saved = current_tokens - estimate_tokens(working[sec.name])
                overshoot -= saved
                pruned_names.append(sec.name)

        total_after = sum(estimate_tokens(v) for v in working.values())

        # Collect all sections that were modified
        all_pruned = list(set(
            pruned_names + [
                s.name for s in sections if working[s.name] != s.content
            ]
        ))

        return PruneResult(
            sections=working,
            total_tokens_before=total_before,
            total_tokens_after=total_after,
            pruned_sections=all_pruned,
            budget=self.budget,
        )


def _truncate_to_tokens(text: str, target_tokens: int) -> str:
    """Truncate text to approximately *target_tokens*, breaking at line boundaries.

    Tries to cut at line boundaries so we don't leave half-written code
    lines in the context.  Appends a ``[… truncated …]`` marker when content
    is removed.

    Args:
        text: The original text.
        target_tokens: Desired token count.

    Returns:
        Truncated text ≤ target_tokens (approximately).
    """
    if estimate_tokens(text) <= target_tokens:
        return text

    import math
    target_chars = int(target_tokens * _CHARS_PER_TOKEN)
    # Reserve space for the truncation marker
    marker = "\n\n[… truncated — context pruned to fit token budget …]\n"
    usable = max(target_chars - len(marker), 0)

    if usable == 0:
        return marker.strip()

    # Find the last newline before the cutoff point
    cut = text[:usable].rfind("\n")
    if cut < 0:
        cut = usable

    return text[:cut] + marker
