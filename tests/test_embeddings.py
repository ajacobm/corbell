"""Tests for code chunk extractor and embedding store."""

import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from corbell.core.embeddings.extractor import CodeChunkExtractor, EmbeddingRecord
from corbell.core.embeddings.sqlite_store import SQLiteEmbeddingStore


# ─── Extractor tests ────────────────────────────────────────────────────────

def test_extract_python_functions(sample_repo):
    extractor = CodeChunkExtractor()
    records = extractor.extract_from_repo(sample_repo, "sample-service")
    assert len(records) > 0
    func_types = [r.chunk_type for r in records]
    assert any(t in ("function", "method", "class") for t in func_types)


def test_extract_python_symbols_named(sample_repo):
    extractor = CodeChunkExtractor()
    records = extractor.extract_from_repo(sample_repo, "sample-service")
    symbols = [r.symbol for r in records if r.symbol]
    assert any("get_token" in s or "AuthClient" in s for s in symbols)


def test_extract_generic_markdown(tmp_path):
    f = tmp_path / "DESIGN.md"
    f.write_text("# Title\n\n## Section\n\nsome content\n" * 30)
    extractor = CodeChunkExtractor(chunk_size=20, overlap=5)
    records = extractor.extract_from_repo(tmp_path, "docs")
    assert len(records) > 0
    assert records[0].language == "markdown"


def test_skip_large_files(tmp_path):
    large = tmp_path / "big.py"
    large.write_bytes(b"x" * (2 * 1024 * 1024))  # 2MB
    extractor = CodeChunkExtractor()
    records = extractor.extract_from_repo(tmp_path, "svc", max_file_bytes=1024 * 1024)
    assert len(records) == 0


# ─── SQLiteEmbeddingStore tests ──────────────────────────────────────────────

@pytest.fixture
def emb_store(tmp_db):
    return SQLiteEmbeddingStore(tmp_db)


def _make_record(i: int, svc: str = "svc") -> EmbeddingRecord:
    return EmbeddingRecord(
        id=f"{svc}::f{i}.py::func_{i}",
        service_id=svc,
        repo="/r",
        file_path=f"f{i}.py",
        start_line=1,
        end_line=10,
        content=f"def func_{i}(): pass",
        language="python",
        chunk_type="function",
        symbol=f"func_{i}",
        embedding=[float(i) * 0.1] * 384,
    )


def test_upsert_and_count(emb_store):
    for i in range(5):
        emb_store.upsert(_make_record(i))
    assert emb_store.count() == 5


def test_upsert_batch(emb_store):
    records = [_make_record(i) for i in range(10)]
    emb_store.upsert_batch(records)
    assert emb_store.count() == 10


def test_query_returns_results(emb_store):
    import numpy as np
    records = [_make_record(i) for i in range(5)]
    emb_store.upsert_batch(records)

    # Query with embedding close to record 2
    qvec = [0.2] * 384
    results = emb_store.query(qvec, top_k=3)
    assert len(results) <= 3
    assert all(isinstance(r, EmbeddingRecord) for r in results)


def test_query_service_filter(emb_store):
    for i in range(3):
        emb_store.upsert(_make_record(i, "svc-a"))
    for i in range(3):
        emb_store.upsert(_make_record(i, "svc-b"))

    qvec = [0.1] * 384
    results = emb_store.query(qvec, service_ids=["svc-a"], top_k=10)
    assert all(r.service_id == "svc-a" for r in results)


def test_clear_all(emb_store):
    emb_store.upsert_batch([_make_record(i) for i in range(5)])
    emb_store.clear()
    assert emb_store.count() == 0


def test_clear_service(emb_store):
    for i in range(3):
        emb_store.upsert(_make_record(i, "svc-a"))
    for i in range(3):
        emb_store.upsert(_make_record(i, "svc-b"))
    emb_store.clear(service_id="svc-a")
    assert emb_store.count() == 3
    assert emb_store.count("svc-b") == 3
