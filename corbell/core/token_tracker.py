"""Token usage tracker — local, no Supabase required.

Adapted from specgen_local/src/token_tracker.py.
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
    "claude-3-5-sonnet-20241022": {"input": 0.003, "output": 0.015},
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
        tracker.record("spec_generation", "claude-3-5-sonnet-20241022", 4000, 3200)
        tracker.record("keyword_extraction", "claude-3-5-sonnet-20241022", 300, 100)
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
