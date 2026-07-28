from __future__ import annotations

from uuid import uuid4

from aep.modules.projects.domain.models import (
    Feature,
    FeatureStatus,
    Project,
    ProjectStatus,
    is_legal_feature_transition,
)


def test_project_defaults_to_active_status() -> None:
    project = Project(id=uuid4(), name="AEP", slug="aep", owner_user_id=uuid4())

    assert project.status == ProjectStatus.ACTIVE
    assert project.description is None
    assert project.git_repository_id is None


def test_feature_defaults_to_draft_status() -> None:
    feature = Feature(id=uuid4(), project_id=uuid4(), title="New screen", created_by=uuid4())

    assert feature.status == FeatureStatus.DRAFT


def test_legal_transitions_from_draft() -> None:
    assert is_legal_feature_transition(FeatureStatus.DRAFT, FeatureStatus.IN_PROGRESS)
    assert is_legal_feature_transition(FeatureStatus.DRAFT, FeatureStatus.CANCELLED)
    assert not is_legal_feature_transition(FeatureStatus.DRAFT, FeatureStatus.DONE)
    assert not is_legal_feature_transition(FeatureStatus.DRAFT, FeatureStatus.IN_REVIEW)


def test_legal_transitions_from_in_review_allow_bouncing_back_to_in_progress() -> None:
    assert is_legal_feature_transition(FeatureStatus.IN_REVIEW, FeatureStatus.DONE)
    assert is_legal_feature_transition(FeatureStatus.IN_REVIEW, FeatureStatus.IN_PROGRESS)
    assert is_legal_feature_transition(FeatureStatus.IN_REVIEW, FeatureStatus.CANCELLED)


def test_terminal_statuses_have_no_legal_outgoing_transitions() -> None:
    for target in FeatureStatus:
        assert not is_legal_feature_transition(FeatureStatus.DONE, target)
        assert not is_legal_feature_transition(FeatureStatus.CANCELLED, target)
