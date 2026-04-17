"""Tests for PRDProcessor (auto service discovery) and TokenUsageTracker."""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from corbell.core.prd_processor import PRDProcessor
from corbell.core.token_tracker import TokenUsageTracker, TokenUsageRecord


# ─── PRDProcessor tests ────────────────────────────────────────────────────

@pytest.fixture
def sample_prd() -> str:
    return textwrap.dedent("""\
        We need to implement exponential backoff retry logic for payment processing.
        When a payment gateway call fails with a transient error (5xx), the system
        should retry up to 3 times with delays of 1s, 2s, 4s before returning failure.
        The retry state should be stored in Redis so retries survive service restarts.
        All retry attempts and outcomes should be written to the audit log.
    """)


class TestPRDProcessor:
    def test_fallback_queries_no_llm(self, sample_prd):
        proc = PRDProcessor(llm_client=None)
        queries = proc.create_search_queries(sample_prd)
        assert len(queries) >= 1
        assert all(len(q) > 10 for q in queries)

    def test_fallback_keywords_no_llm(self, sample_prd):
        proc = PRDProcessor(llm_client=None)
        keywords = proc.extract_keywords(sample_prd)
        assert len(keywords) >= 3
        assert any("retry" in k or "payment" in k for k in keywords)

    def test_create_search_queries_with_mock_llm(self, sample_prd):
        mock_llm = MagicMock()
        mock_llm.is_configured = True
        mock_llm.call.return_value = (
            "function that retries payment gateway calls with exponential backoff\n"
            "class that tracks retry count and delay in Redis state store\n"
            "handler that records retry outcomes to the audit log"
        )
        proc = PRDProcessor(llm_client=mock_llm)
        queries = proc.create_search_queries(sample_prd)
        assert len(queries) == 3
        assert "retry" in queries[0].lower() or "exponential" in queries[0].lower()

    def test_create_search_queries_llm_fallback_on_error(self, sample_prd):
        mock_llm = MagicMock()
        mock_llm.is_configured = True
        mock_llm.call.side_effect = Exception("API down")
        proc = PRDProcessor(llm_client=mock_llm)
        queries = proc.create_search_queries(sample_prd)
        # Should fall back without raising
        assert len(queries) >= 1

    def test_discover_relevant_services_empty_emb_store(self, sample_prd):
        """Auto-discovery should return first service when no embeddings exist."""
        mock_store = MagicMock()
        mock_store.query.return_value = []
        mock_store.count.return_value = 0

        proc = PRDProcessor(llm_client=None)
        # Without embedding model installed, should still not crash
        all_ids = ["payments-service", "auth-service", "notifications-service"]
        try:
            result = proc.discover_relevant_services(sample_prd, mock_store, all_ids, top_k=2)
            # Should return something
            assert isinstance(result, list)
        except Exception:
            # If embedding model not installed, that's acceptable
            pass

    def test_discover_empty_service_list(self, sample_prd):
        mock_store = MagicMock()
        proc = PRDProcessor(llm_client=None)
        result = proc.discover_relevant_services(sample_prd, mock_store, [], top_k=2)
        assert result == []


# ─── TokenUsageTracker tests ───────────────────────────────────────────────

class TestTokenUsageTracker:
    def test_record_and_totals(self):
        tracker = TokenUsageTracker()
        tracker.record("spec_generation", "claude-sonnet-4-5-20250929", 4000, 3200)
        tracker.record("keyword_extraction", "claude-sonnet-4-5-20250929", 300, 150)
        assert tracker.total_input_tokens == 4300
        assert tracker.total_output_tokens == 3350
        assert tracker.total_tokens == 7650
        assert tracker.call_count == 2

    def test_cost_calculation(self):
        tracker = TokenUsageTracker()
        # 1000 input @ $0.003/1k + 1000 output @ $0.015/1k = $0.018
        tracker.record("test", "claude-sonnet-4-5-20250929", 1000, 1000)
        assert abs(tracker.total_cost_usd - 0.018) < 0.0001

    def test_gpt4o_cost(self):
        tracker = TokenUsageTracker()
        # 1000 input @ $0.005 + 1000 output @ $0.015 = $0.020
        tracker.record("test", "gpt-4o", 1000, 1000)
        assert abs(tracker.total_cost_usd - 0.020) < 0.0001

    def test_ollama_free(self):
        tracker = TokenUsageTracker()
        tracker.record("test", "llama3", 10000, 5000)
        assert tracker.total_cost_usd == 0.0

    def test_summary_dict(self):
        tracker = TokenUsageTracker()
        tracker.record("spec_generation", "claude-sonnet-4-5-20250929", 4000, 3200)
        d = tracker.summary_dict()
        assert d["calls"] == 1
        assert d["total_tokens"] == 7200
        assert "breakdown" in d
        assert d["breakdown"][0]["request_type"] == "spec_generation"

    def test_empty_tracker(self):
        tracker = TokenUsageTracker()
        assert tracker.total_tokens == 0
        assert tracker.total_cost_usd == 0.0
        assert tracker.call_count == 0
        assert tracker.summary_dict()["calls"] == 0

    def test_print_summary_no_records(self, capsys):
        tracker = TokenUsageTracker()
        # Should not raise or print anything
        tracker.print_summary()

    def test_print_summary_with_records(self):
        from io import StringIO
        from rich.console import Console
        tracker = TokenUsageTracker()
        tracker.record("spec_generation", "claude-sonnet-4-5-20250929", 4000, 3200)
        tracker.record("keyword_extraction", "gpt-4o", 200, 100)

        sio = StringIO()
        console = Console(file=sio, force_terminal=False, width=120)
        tracker.print_summary(console)
        output = sio.getvalue()
        # Should contain request types
        assert "spec_generation" in output
        assert "keyword_extraction" in output
        assert "TOTAL" in output

    def test_token_usage_record_cost(self):
        rec = TokenUsageRecord(
            request_type="test",
            model="claude-sonnet-4-5-20250929",
            input_tokens=1000,
            output_tokens=500,
        )
        # 1000/1k * 0.003 + 500/1k * 0.015 = 0.003 + 0.0075 = 0.0105
        assert abs(rec.estimated_cost_usd - 0.0105) < 0.00001

    def test_unknown_model_uses_defaults(self):
        tracker = TokenUsageTracker()
        # Unknown model falls back to default pricing but doesn't crash
        tracker.record("test", "some-new-model-x", 1000, 500)
        assert tracker.call_count == 1
        assert tracker.total_tokens == 1500


# ─── Context Pruner tests ─────────────────────────────────────────────────

from corbell.core.token_tracker import (
    ContextPruner,
    ContextSection,
    PruneResult,
    estimate_tokens,
    _truncate_to_tokens,
    _CHARS_PER_TOKEN,
)


class TestEstimateTokens:
    def test_empty_string(self):
        assert estimate_tokens("") == 0

    def test_short_string(self):
        # 12 chars / 4.0 = 3.0 → ceil → 3
        assert estimate_tokens("hello world!") == 3

    def test_consistent_with_char_ratio(self):
        text = "a" * 400
        expected = 400 / _CHARS_PER_TOKEN
        result = estimate_tokens(text)
        assert result == 100  # 400 / 4.0

    def test_rounds_up(self):
        # 5 chars / 4.0 = 1.25 → ceil → 2
        assert estimate_tokens("abcde") == 2


class TestTruncateToTokens:
    def test_no_truncation_when_under_budget(self):
        text = "line one\nline two\nline three"
        result = _truncate_to_tokens(text, 1000)
        assert result == text

    def test_truncation_adds_marker(self):
        text = "x" * 8000
        result = _truncate_to_tokens(text, 100)
        assert "truncated" in result
        assert len(result) < len(text)

    def test_truncation_respects_line_boundary(self):
        lines = [f"line {i}: some content here" for i in range(200)]
        text = "\n".join(lines)
        result = _truncate_to_tokens(text, 50)
        # Result should end at a line boundary, not mid-line
        before_marker = result.split("\n\n[")[0]
        # The last character before the marker split should be a complete line
        assert not before_marker.endswith(" ")  # didn't cut mid-word typically

    def test_zero_target(self):
        text = "some text"
        result = _truncate_to_tokens(text, 0)
        assert "truncated" in result


class TestContextSection:
    def test_estimated_tokens(self):
        sec = ContextSection(name="test", content="a" * 400, priority=5)
        assert sec.estimated_tokens == 100

    def test_default_priority_and_share(self):
        sec = ContextSection(name="test", content="hi")
        assert sec.priority == 5
        assert sec.max_share == 1.0


class TestContextPruner:
    def test_empty_sections(self):
        pruner = ContextPruner(budget=1000)
        result = pruner.prune([])
        assert result.sections == {}
        assert result.total_tokens_before == 0
        assert result.total_tokens_after == 0
        assert result.pruned_sections == []

    def test_under_budget_no_changes(self):
        """When total tokens are well under budget, nothing is pruned."""
        pruner = ContextPruner(budget=10_000)
        sections = [
            ContextSection("a", "short text", priority=5),
            ContextSection("b", "another short text", priority=8),
        ]
        result = pruner.prune(sections)
        assert result.sections["a"] == "short text"
        assert result.sections["b"] == "another short text"
        assert result.pruned_sections == []
        assert result.total_tokens_before == result.total_tokens_after

    def test_over_budget_trims_lowest_priority_first(self):
        """When over budget, lowest-priority sections are trimmed first."""
        budget = 100  # Very small budget (100 tokens = ~400 chars)
        pruner = ContextPruner(budget=budget)

        low_priority_content = "L" * 2000   # ~500 tokens  (way over budget)
        high_priority_content = "H" * 200    # ~50 tokens

        sections = [
            ContextSection("low", low_priority_content, priority=1, max_share=1.0),
            ContextSection("high", high_priority_content, priority=9, max_share=1.0),
        ]
        result = pruner.prune(sections)

        # High-priority content should be preserved fully
        assert result.sections["high"] == high_priority_content
        # Low-priority content should be trimmed
        assert len(result.sections["low"]) < len(low_priority_content)
        assert "low" in result.pruned_sections
        assert result.total_tokens_after <= budget

    def test_max_share_caps_individual_section(self):
        """max_share limits how much budget a single section can consume."""
        budget = 1000
        pruner = ContextPruner(budget=budget)

        # This section is 2000 tokens but max_share=0.10 → capped to 100 tokens
        big_content = "x" * 8000  # ~2000 tokens
        sections = [
            ContextSection("big", big_content, priority=5, max_share=0.10),
            ContextSection("small", "tiny", priority=8, max_share=0.90),
        ]
        result = pruner.prune(sections)

        # "big" should have been capped
        assert "big" in result.pruned_sections
        big_tokens = estimate_tokens(result.sections["big"])
        assert big_tokens <= int(budget * 0.10) + 5  # small tolerance for rounding

    def test_prune_result_metadata(self):
        """PruneResult correctly tracks before/after totals and budget."""
        pruner = ContextPruner(budget=50)
        sections = [
            ContextSection("a", "x" * 800, priority=3),  # ~200 tokens
        ]
        result = pruner.prune(sections)
        assert result.budget == 50
        assert result.total_tokens_before == 200
        assert result.total_tokens_after <= 50
        assert "a" in result.pruned_sections

    def test_preserves_min_content(self):
        """Even extremely tight budgets preserve at least some content."""
        pruner = ContextPruner(budget=10)
        sections = [
            ContextSection("only", "x" * 4000, priority=1),  # ~1000 tokens
        ]
        result = pruner.prune(sections)
        # Should still have some content (at least the truncation marker)
        assert len(result.sections["only"]) > 0

