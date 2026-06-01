"""Timeline application service."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from app.agents.schemas import AgentRun
from app.agents.schemas import AgentRunStatus
from app.timeline.models import TimelineCategory
from app.timeline.models import TimelineEvent
from app.timeline.models import TimelineResult
from app.timeline.repository import TimelineRepository


class TimelineService:
    """Create user-facing timeline events."""

    def __init__(self, repository: TimelineRepository) -> None:
        self._repository = repository

    async def record_agent_run(
        self,
        *,
        run: AgentRun,
        action: str,
        target: dict[str, str] | None = None,
    ) -> TimelineEvent:
        event = TimelineEvent.create(
            project_id=run.project_id,
            category=TimelineCategory.AGENT_ACTION,
            action=action,
            result=_result_from_run_status(run.status),
            agent_name=run.agent_name,
            target=target,
            rationale_md=_run_rationale(run, action, target),
            duration_ms=_duration_ms(run),
            metadata={
                "run_id": run.id,
                "progress_percent": run.progress_percent,
                "error_code": run.error_code,
                "decision": _decision_summary(action),
                "tool_boundary": _tool_boundary(action),
                "adapter_mode": _adapter_mode(action),
                "next_expected_action": _next_expected_action(action),
            },
        )
        await self._repository.create(event)
        return event

    async def list_payloads(self, project_id: str) -> list[dict[str, Any]]:
        events = await self._repository.list_by_project(project_id)
        return [_event_payload(event) for event in events]


def _result_from_run_status(status: AgentRunStatus) -> TimelineResult:
    if status is AgentRunStatus.SUCCEEDED:
        return TimelineResult.SUCCESS
    if status in {AgentRunStatus.FAILED, AgentRunStatus.CANCELLED}:
        return TimelineResult.FAILURE
    return TimelineResult.IN_PROGRESS


def _duration_ms(run: AgentRun) -> int | None:
    if run.started_at is None or run.finished_at is None:
        return None
    return int((run.finished_at - run.started_at).total_seconds() * 1000)


def _run_rationale(run: AgentRun, action: str, target: dict[str, str] | None) -> str:
    target_text = "the current project"
    if target:
        target_text = f"{target.get('type', 'target')} {target.get('id', '')}".strip()
    return (
        f"{run.agent_name} executed {action} for {target_text}. "
        "The step is recorded so the user can inspect why the pipeline advanced."
    )


def _decision_summary(action: str) -> str:
    decisions = {
        "generated_follow_up_questions": "Identify missing requirements before committing to design.",
        "generated_requirements": "Convert the idea into an auditable requirements document.",
        "generated_design_document": "Generate versioned design material before infrastructure planning.",
        "proposed_architecture": "Prefer a small Cloud Run and Firestore architecture for demo reliability.",
        "evaluated_security": "Run the required security pass before approval and apply.",
    }
    return decisions.get(action, "Record the agent operation for traceability.")


def _tool_boundary(action: str) -> str:
    tools = {
        "proposed_architecture": "architecture_repository",
        "evaluated_security": "security_finding_repository",
        "generated_design_document": "document_repository",
        "generated_requirements": "document_repository",
        "generated_follow_up_questions": "agent_runtime",
    }
    return tools.get(action, "agent_runtime")


def _adapter_mode(action: str) -> str:
    if action in {"proposed_architecture", "evaluated_security", "generated_design_document", "generated_requirements"}:
        return "demo_agent"
    return "demo_adapter"


def _next_expected_action(action: str) -> str:
    next_actions = {
        "generated_follow_up_questions": "Generate requirements",
        "generated_requirements": "Approve requirements",
        "generated_design_document": "Approve design or continue design set",
        "proposed_architecture": "Run security evaluation",
        "evaluated_security": "Approve architecture",
    }
    return next_actions.get(action, "Continue pipeline")


def _event_payload(event: TimelineEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["category"] = event.category.value
    payload["result"] = event.result.value
    payload["occurred_at"] = event.occurred_at.isoformat()
    payload["links"] = list(event.links)
    return payload
