from __future__ import annotations

from uuid import uuid4

from aep.modules.dashboard_api.domain.models import DashboardOverview, TaskGraph


def test_dashboard_overview_defaults_to_empty_lists() -> None:
    overview = DashboardOverview(active_projects=1, running_agents=0, pending_approvals=0)

    assert overview.recent_evaluations == []
    assert overview.recent_audit_events == []


def test_task_graph_defaults_to_empty_nodes_and_edges() -> None:
    graph = TaskGraph(project_id=uuid4())

    assert graph.nodes == []
    assert graph.edges == []
