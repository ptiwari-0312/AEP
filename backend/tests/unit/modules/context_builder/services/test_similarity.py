from __future__ import annotations

from aep.modules.context_builder.services.similarity import JaccardSimilarityScorer


def test_identical_text_scores_one() -> None:
    scorer = JaccardSimilarityScorer()

    assert scorer.score("hello world", "hello world") == 1.0


def test_disjoint_text_scores_zero() -> None:
    scorer = JaccardSimilarityScorer()

    assert scorer.score("apple banana", "car truck") == 0.0


def test_partial_overlap_is_between_zero_and_one() -> None:
    scorer = JaccardSimilarityScorer()

    score = scorer.score("the quick brown fox", "the quick red fox")
    assert 0.0 < score < 1.0


def test_empty_text_never_scores_as_similar() -> None:
    scorer = JaccardSimilarityScorer()

    assert scorer.score("", "") == 0.0
    assert scorer.score("something", "") == 0.0


def test_score_is_symmetric() -> None:
    scorer = JaccardSimilarityScorer()

    assert scorer.score("alpha beta", "beta gamma") == scorer.score("beta gamma", "alpha beta")


def test_score_is_case_insensitive() -> None:
    scorer = JaccardSimilarityScorer()

    assert scorer.score("Hello World", "hello world") == 1.0
