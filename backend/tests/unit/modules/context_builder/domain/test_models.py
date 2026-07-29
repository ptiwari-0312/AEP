from __future__ import annotations

from uuid import uuid4

from aep.modules.context_builder.domain.models import (
    ContextPackage,
    ContextPackageSource,
    RankingWeights,
    SourceDocument,
    SourceDocumentType,
)


def test_source_document_defaults() -> None:
    document = SourceDocument(
        id=uuid4(),
        project_id=uuid4(),
        doc_type=SourceDocumentType.SOURCE_FILE,
        uri="/repo/src/module.py",
        content_hash="a" * 64,
    )

    assert document.last_indexed_at is None
    assert document.created_at is None


def test_context_package_source_defaults() -> None:
    source = ContextPackageSource(
        id=uuid4(),
        context_package_id=uuid4(),
        source_document_id=uuid4(),
        relevance_score=0.75,
        rank=1,
    )

    assert source.included is True
    assert source.token_count == 0


def test_context_package_carries_ranking_algorithm_version() -> None:
    package = ContextPackage(
        id=uuid4(), task_id=uuid4(), token_count=1000, ranking_algorithm_version="v1"
    )

    assert package.ranking_algorithm_version == "v1"


def test_ranking_weights_defaults_are_present() -> None:
    weights = RankingWeights()

    assert weights.semantic > 0
    assert weights.doc_type > 0


def test_source_document_type_matches_db_check_constraint_values() -> None:
    # docs/architecture/03-db-design.md §13's CHECK IN (...) list, verbatim.
    expected = {
        "source_file",
        "architecture_doc",
        "coding_standard",
        "api_spec",
        "pull_request",
        "dependency_graph",
        "evaluation_history",
        "prompt_template",
    }
    assert {member.value for member in SourceDocumentType} == expected
