from __future__ import annotations

import pytest

from aep.modules.context_builder.services.chunking import TextChunker, estimate_tokens


def test_empty_text_produces_no_chunks() -> None:
    chunker = TextChunker()

    assert chunker.chunk("") == []


def test_short_text_produces_a_single_chunk() -> None:
    chunker = TextChunker(lines_per_chunk=40, overlap_lines=5)
    text = "\n".join(f"line {i}" for i in range(10))

    chunks = chunker.chunk(text)

    assert len(chunks) == 1
    assert chunks[0].start_line == 0
    assert chunks[0].text == text


def test_long_text_produces_overlapping_chunks() -> None:
    chunker = TextChunker(lines_per_chunk=10, overlap_lines=2)
    lines = [f"line {i}" for i in range(25)]
    text = "\n".join(lines)

    chunks = chunker.chunk(text)

    assert len(chunks) > 1
    # Consecutive chunks share `overlap_lines` lines: the second chunk's start_line advances by
    # (lines_per_chunk - overlap_lines), not by lines_per_chunk.
    assert chunks[1].start_line == 8
    # Every line must be covered by at least one chunk.
    covered_last_line = chunks[-1].start_line + len(chunks[-1].text.splitlines()) - 1
    assert covered_last_line == len(lines) - 1


def test_estimate_tokens_is_a_positive_char_based_heuristic() -> None:
    assert estimate_tokens("") == 1
    assert estimate_tokens("a" * 40) == 10
    assert estimate_tokens("a") == 1


def test_chunker_rejects_invalid_overlap_configuration() -> None:
    with pytest.raises(ValueError):
        TextChunker(lines_per_chunk=10, overlap_lines=10)
    with pytest.raises(ValueError):
        TextChunker(lines_per_chunk=10, overlap_lines=-1)
    with pytest.raises(ValueError):
        TextChunker(lines_per_chunk=0)
