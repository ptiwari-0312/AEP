"""Normalize & Chunk (docs/architecture/06-context-builder.md §4, ADR-CB2).

The design doc calls for structural chunk boundaries where they exist (function/class for source
files, section headers for docs, hunk for PR diffs) and a fixed-size sliding-window fallback
otherwise. This reference implementation only builds the fallback — a per-language structural
splitter is real additional work (parsing each language's function/class boundaries) that isn't
implementable generically without per-language tooling this module doesn't have — so every
document is chunked with the same sliding window regardless of `doc_type`. Flagged in this
module's README, not silently narrowed.
"""

from __future__ import annotations

from dataclasses import dataclass


def estimate_tokens(text: str) -> int:
    """A fast approximate tokenizer (~4 chars/token), same heuristic and same justification as
    `examples/custom-provider-plugin`'s `ClaudeProvider.count_tokens()`: no real tokenizer
    dependency is wired into `backend/` yet, and docs/architecture/06-context-builder.md §13
    explicitly defers "the specific tokenizer integration per provider" to the Model Provider SDK,
    to be re-counted exactly once a provider is selected for a run (§8) — out of scope here."""
    return max(1, len(text) // 4)


@dataclass(frozen=True)
class TextChunk:
    text: str
    start_line: int
    token_count: int


class TextChunker:
    def __init__(self, *, lines_per_chunk: int = 40, overlap_lines: int = 5) -> None:
        if lines_per_chunk <= 0:
            raise ValueError("lines_per_chunk must be positive")
        if overlap_lines < 0 or overlap_lines >= lines_per_chunk:
            raise ValueError("overlap_lines must be non-negative and smaller than lines_per_chunk")
        self._lines_per_chunk = lines_per_chunk
        self._step = lines_per_chunk - overlap_lines

    def chunk(self, text: str) -> list[TextChunk]:
        lines = text.splitlines()
        if not lines:
            return []

        chunks: list[TextChunk] = []
        start = 0
        while start < len(lines):
            end = min(start + self._lines_per_chunk, len(lines))
            chunk_text = "\n".join(lines[start:end])
            chunks.append(
                TextChunk(text=chunk_text, start_line=start, token_count=estimate_tokens(chunk_text))
            )
            if end == len(lines):
                break
            start += self._step
        return chunks
