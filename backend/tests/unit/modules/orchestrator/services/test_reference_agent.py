from __future__ import annotations

import asyncio
from uuid import uuid4

from aep_agent_sdk import AgentRunStatus, AgentType, NullEventPublisher, TaskContext

from aep.core.events import InMemoryEventPublisher
from aep.modules.orchestrator.services.reference_agent import (
    EchoAgent,
    make_echo_agent_class,
)


def _make_agent(agent_type: AgentType = AgentType.CODING, **config) -> EchoAgent:
    agent_class = make_echo_agent_class(agent_type)
    return agent_class(
        agent_id=uuid4(),
        version="1.0.0",
        config=config,
        event_publisher=InMemoryEventPublisher(),
    )


async def test_echo_agent_completes_and_echoes_content() -> None:
    agent = _make_agent()
    context = TaskContext(task_id=uuid4(), content="hello world")

    report = await agent.run(context)

    assert report.agent_run_status == AgentRunStatus.COMPLETED
    assert report.execution_result is not None
    assert report.execution_result.artifacts[0].content == "hello world"
    assert report.self_evaluation is not None
    assert report.self_evaluation.passed is True


async def test_echo_agent_configured_to_fail_reports_failed_without_internal_retries() -> None:
    agent = _make_agent(fail=True)
    context = TaskContext(task_id=uuid4(), content="hello")

    report = await agent.run(context)

    assert report.agent_run_status == AgentRunStatus.FAILED
    assert report.error is not None
    # TerminalAgentError isn't in RetryPolicy's default retryable set, so run() shouldn't have
    # looped internally — a single attempt.
    assert report.attempt_number == 1


async def test_echo_agent_respects_cooperative_cancellation() -> None:
    agent = _make_agent(execution_delay_seconds=2.0, poll_interval_seconds=0.02)
    context = TaskContext(task_id=uuid4(), content="hello")

    run_task = asyncio.create_task(agent.run(context))
    await asyncio.sleep(0.05)
    await agent.cancel()
    report = await run_task

    assert report.agent_run_status == AgentRunStatus.CANCELLED


def test_make_echo_agent_class_sets_a_real_class_level_agent_type() -> None:
    planner_class = make_echo_agent_class(AgentType.PLANNER)
    reviewer_class = make_echo_agent_class(AgentType.REVIEW)

    assert planner_class.agent_type == AgentType.PLANNER
    assert reviewer_class.agent_type == AgentType.REVIEW

    planner = planner_class(agent_id=uuid4(), version="1.0.0", event_publisher=NullEventPublisher())
    assert planner.agent_type == AgentType.PLANNER


def test_echo_agent_itself_has_no_agent_type_and_cannot_be_instantiated_directly() -> None:
    try:
        EchoAgent(agent_id=uuid4(), version="1.0.0", event_publisher=NullEventPublisher())
    except TypeError as exc:
        assert "agent_type" in str(exc)
    else:
        raise AssertionError("expected TypeError: EchoAgent itself declares no agent_type")
