"""Text similarity, used for both the `semantic_similarity` ranking signal and near-duplicate
dedup (docs/architecture/06-context-builder.md §5-6).

docs/architecture/06-context-builder.md §13 explicitly puts "the embedding model or vector store
used for `semantic_similarity`" out of scope for the design — no embedding provider is wired into
`backend/` yet (the reference `ClaudeProvider` in `examples/custom-provider-plugin` doesn't
implement `embed()`; Claude has no embeddings API). `JaccardSimilarityScorer` is a real,
deterministic, dependency-free stand-in — token-set overlap is a legitimate classic-IR baseline,
not a fake — behind a `TextSimilarityScorer` protocol so a real embedding-backed implementation
can be dropped in later (e.g. once a provider that supports `embed()` is registered) without
touching the ranking/dedup code that calls it.
"""

from __future__ import annotations

import re
from typing import Protocol

# No underscore: splitting `implement_password_reset` into `implement`/`password`/`reset` is
# what lets a snake_case source-code identifier overlap with natural-language task text at all —
# keeping the underscore would make every multi-word identifier one opaque token that can never
# match a task description's separate words.
_TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9]+")


class TextSimilarityScorer(Protocol):
    def score(self, text_a: str, text_b: str) -> float: ...


class JaccardSimilarityScorer:
    """Jaccard index over lowercased word-tokens: |A ∩ B| / |A ∪ B|. Symmetric, bounded to
    [0, 1], and 0.0 whenever either side has no tokens (an empty/unreadable document should never
    look identical to another empty one)."""

    def score(self, text_a: str, text_b: str) -> float:
        tokens_a = _tokenize(text_a)
        tokens_b = _tokenize(text_b)
        if not tokens_a or not tokens_b:
            return 0.0
        intersection = tokens_a & tokens_b
        union = tokens_a | tokens_b
        return len(intersection) / len(union)


def _tokenize(text: str) -> set[str]:
    return {match.lower() for match in _TOKEN_PATTERN.findall(text)}
