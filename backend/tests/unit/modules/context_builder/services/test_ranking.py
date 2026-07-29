from __future__ import annotations

from datetime import timedelta

from aep.core.db import utcnow
from aep.modules.context_builder.domain.models import SourceDocumentType
from aep.modules.context_builder.services.ranking import (
    DOC_TYPE_PRIOR,
    SECTION_ORDER,
    recency_decay,
)


def test_recency_decay_is_one_for_now() -> None:
    # `recency_decay` calls `utcnow()` again internally, a fraction of a second after the
    # `utcnow()` passed in here, so age is a tiny positive number, not exactly zero.
    assert abs(recency_decay(utcnow()) - 1.0) < 1e-6


def test_recency_decay_is_half_at_one_half_life() -> None:
    thirty_days_ago = utcnow() - timedelta(days=30)

    score = recency_decay(thirty_days_ago, half_life_days=30.0)

    assert abs(score - 0.5) < 1e-9


def test_recency_decay_never_exceeds_one_for_future_timestamps() -> None:
    # Clock skew between processes could produce a "future" reference_time; age is clamped to 0.
    assert recency_decay(utcnow() + timedelta(days=5)) == 1.0


def test_doc_type_prior_covers_every_doc_type() -> None:
    assert set(DOC_TYPE_PRIOR) == set(SourceDocumentType)


def test_coding_standards_and_architecture_docs_have_the_highest_priors() -> None:
    # docs/architecture/06-context-builder.md §6: these two "are close to always relevant... this
    # is what keeps them from getting starved out."
    scored_types = sorted(DOC_TYPE_PRIOR, key=lambda t: DOC_TYPE_PRIOR[t], reverse=True)
    assert scored_types[0] == SourceDocumentType.CODING_STANDARD
    assert scored_types[1] == SourceDocumentType.ARCHITECTURE_DOC


def test_section_order_covers_every_doc_type_with_unique_positions() -> None:
    assert set(SECTION_ORDER) == set(SourceDocumentType)
    assert sorted(SECTION_ORDER.values()) == list(range(1, len(SourceDocumentType) + 1))


def test_prompt_template_is_always_last_in_section_order() -> None:
    # docs/architecture/06-context-builder.md §9: "Prompt template + task description (always
    # last)."
    assert SECTION_ORDER[SourceDocumentType.PROMPT_TEMPLATE] == max(SECTION_ORDER.values())
