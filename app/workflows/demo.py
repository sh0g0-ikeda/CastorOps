"""Local demo helpers for exercising workflows without cloud dependencies."""

from __future__ import annotations

from typing import Any

from app.agents.architect import ArchitectGenerationRequest
from app.agents.gcp_planner import GcpPlannerRequest
from app.agents.requirement import RequirementGenerationRequest
from app.agents.runtime import AgentRuntime
from app.agents.runtime import InMemoryAgentStore
from app.agents.schemas import AgentRunStatus
from app.agents.security import SecurityEvaluationRequest
from app.agents.tool_guard import DEFAULT_TOOL_DEFINITIONS
from app.agents.tool_guard import ToolGuard
from app.api.responses import ApiResponse
from app.architectures.repository import InMemoryArchitectureRepository
from app.architectures.service import ArchitectureService
from app.documents.models import DocumentType
from app.documents.repository import InMemoryDocumentRepository
from app.documents.service import DocumentService
from app.projects.models import ProjectPhase
from app.projects.repository import InMemoryProjectRepository
from app.projects.service import ProjectService
from app.security.repository import InMemorySecurityFindingRepository
from app.security.service import SecurityFindingService
from app.workflows.designs import DesignWorkflowService
from app.workflows.planning import PlanningWorkflowService
from app.workflows.requirements import RequirementWorkflowService
from app.workflows.security import SecurityEvaluationWorkflowService


class DemoRequirementGenerator:
    """Deterministic requirement generator used for local smoke tests."""

    async def generate(self, request: RequirementGenerationRequest) -> dict[str, Any]:
        unresolved_items = []
        follow_up_questions = []
        if "auth" not in request.follow_up_answers:
            unresolved_items.append("Authentication policy")
            follow_up_questions.append(
                "Should this product require sign-in, or is a demo-only single user mode acceptable?"
            )
        if not request.form_responses.get("data_storage"):
            follow_up_questions.append(
                "What data should be persisted, and how long should it be retained?"
            )
        if not request.form_responses.get("public_scope"):
            follow_up_questions.append(
                "Should the deployed API be private, team-only, or publicly reachable?"
            )

        return {
            "follow_up_questions": follow_up_questions[:3],
            "requirements_doc_md": _build_requirements_doc(request, unresolved_items),
            "unresolved_items": unresolved_items,
        }


class DemoArchitectGenerator:
    """Deterministic architect generator used for local smoke tests."""

    async def generate(self, request: ArchitectGenerationRequest) -> dict[str, Any]:
        title_by_type = {
            DocumentType.BASIC_DESIGN: "Basic Design",
            DocumentType.API_DESIGN: "API Design",
            DocumentType.DATA_DESIGN: "Data Design",
            DocumentType.OPS_DESIGN: "Operations Design",
            DocumentType.SECURITY_DESIGN: "Security Design",
            DocumentType.ADR: "Architecture Decision Record",
            DocumentType.TASKS: "Implementation Tasks",
        }
        title = title_by_type[request.doc_type]
        return {
            "doc_md": (
                f"# {title}\n\n"
                "## Context\n"
                f"{request.requirements_doc_md[:240]}\n\n"
                "## CastorOps Decision\n"
                "Use a small Cloud Run service backed by Firestore so the demo can show "
                "design, approval, deployment, and operations in one path.\n"
            ),
            "references": ["requirements:latest"],
        }


class DemoGcpPlannerGenerator:
    """Deterministic GCP planner used for local smoke tests."""

    async def generate(self, request: GcpPlannerRequest) -> dict[str, Any]:
        return {
            "architecture_spec": {
                "project_id": request.target_project_id,
                "region": "asia-northeast1",
                "nodes": [
                    {
                        "id": "backend",
                        "type": "cloud_run",
                        "name": "CastorOps Backend",
                        "parameters": {"memory": "512Mi", "cpu": "1", "allow_unauthenticated": False},
                        "rationale": "Run the CastorOps API on Cloud Run for fast container deployment.",
                        "cost_band": "low",
                        "security_notes": [
                            "Require an approval gate before apply",
                            "Use a dedicated service account with least privilege",
                        ],
                    },
                    {
                        "id": "firestore",
                        "type": "firestore",
                        "name": "Project State Store",
                        "parameters": {"mode": "native"},
                        "rationale": "Persist project state, approvals, timelines, and generated documents.",
                        "cost_band": "low",
                    },
                ],
                "edges": [
                    {
                        "id": "backend-firestore",
                        "from_node": "backend",
                        "to_node": "firestore",
                        "type": "db_rw",
                        "description": "Backend reads and writes project state.",
                    }
                ],
            },
            "rationale_md": (
                "# Recommended GCP Architecture\n\n"
                "Cloud Run hosts the CastorOps backend. Firestore stores project state, "
                "approvals, generated artifacts, and timeline entries. This is the smallest "
                "MVP architecture that still demonstrates deploy and ops visibility."
            ),
            "cloudbuild_yaml": "steps: []",
            "gcloud_commands": ["gcloud run services list"],
        }


class DemoSecurityEvaluator:
    """Deterministic security evaluator used for local smoke tests."""

    async def evaluate(self, request: SecurityEvaluationRequest) -> dict[str, Any]:
        return {
            "findings": [
                {
                    "severity": "warning",
                    "category": "iam",
                    "message": "Service account permissions must be reviewed before the real deploy.",
                    "suggestion": "Separate the Cloud Build service account from the backend runtime service account.",
                }
            ]
        }


async def build_requirement_demo_response(*, idea: str, owner_uid: str) -> ApiResponse:
    """Run the requirement workflow locally and return the API response envelope."""

    project_repository = InMemoryProjectRepository()
    project_service = ProjectService(repository=project_repository)
    document_service = DocumentService(InMemoryDocumentRepository())
    workflow = RequirementWorkflowService(
        project_service=project_service,
        document_service=document_service,
        agent_runtime=AgentRuntime(
            store=InMemoryAgentStore(),
            tool_guard=ToolGuard(DEFAULT_TOOL_DEFINITIONS),
        ),
        generator=DemoRequirementGenerator(),
    )

    project = await project_service.create_project(
        owner_uid=owner_uid,
        name="Local Requirement Demo",
        idea=idea,
    )
    result = await workflow.generate_requirements(project_id=project.id)

    return ApiResponse.ok(
        {
            "project_id": project.id,
            "run_status": result.run.status.value,
            "document_id": result.document.id if result.document else None,
            "document_version": result.document.version if result.document else None,
            "unresolved_items": result.run.output.get("unresolved_items", [])
            if result.run.output
            else [],
        }
    )


async def build_full_demo_response(
    *,
    idea: str,
    owner_uid: str,
    target_project_id: str,
) -> ApiResponse:
    """Run the local end-to-end workflow and return the API response envelope."""

    project_repository = InMemoryProjectRepository()
    project_service = ProjectService(repository=project_repository)
    document_repository = InMemoryDocumentRepository()
    document_service = DocumentService(document_repository)
    architecture_service = ArchitectureService(InMemoryArchitectureRepository())
    finding_service = SecurityFindingService(InMemorySecurityFindingRepository())
    agent_runtime = AgentRuntime(
        store=InMemoryAgentStore(),
        tool_guard=ToolGuard(DEFAULT_TOOL_DEFINITIONS),
    )

    project = await project_service.create_project(
        owner_uid=owner_uid,
        name="Local E2E Demo",
        idea=idea,
    )
    requirement_result = await RequirementWorkflowService(
        project_service=project_service,
        document_service=document_service,
        agent_runtime=agent_runtime,
        generator=DemoRequirementGenerator(),
    ).generate_requirements(project_id=project.id)
    _require_success(requirement_result.run.status, "requirement workflow")
    await project_service.transition_project(
        project_id=project.id,
        next_phase=ProjectPhase.REQUIREMENT_APPROVED,
    )
    design_result = await DesignWorkflowService(
        project_service=project_service,
        document_service=document_service,
        agent_runtime=agent_runtime,
        generator=DemoArchitectGenerator(),
    ).generate_design_document(
        project_id=project.id,
        doc_type=DocumentType.BASIC_DESIGN,
    )
    _require_success(design_result.run.status, "design workflow")
    await project_service.transition_project(
        project_id=project.id,
        next_phase=ProjectPhase.DESIGN_APPROVED,
    )
    planning_result = await PlanningWorkflowService(
        project_service=project_service,
        document_service=document_service,
        architecture_service=architecture_service,
        agent_runtime=agent_runtime,
        generator=DemoGcpPlannerGenerator(),
    ).propose_architecture(
        project_id=project.id,
        target_project_id=target_project_id,
    )
    _require_success(planning_result.run.status, "planning workflow")
    security_result = await SecurityEvaluationWorkflowService(
        project_service=project_service,
        architecture_service=architecture_service,
        finding_service=finding_service,
        agent_runtime=agent_runtime,
        evaluator=DemoSecurityEvaluator(),
    ).evaluate_latest_architecture(project_id=project.id)

    return ApiResponse.ok(
        {
            "project_id": project.id,
            "requirements_document_id": requirement_result.document.id
            if requirement_result.document
            else None,
            "basic_design_document_id": design_result.document.id if design_result.document else None,
            "architecture_id": planning_result.proposal.id if planning_result.proposal else None,
            "security_findings": len(security_result.findings),
            "security_critical_count": security_result.critical_count,
        }
    )


def _require_success(status: AgentRunStatus, operation_name: str) -> None:
    if status is not AgentRunStatus.SUCCEEDED:
        raise RuntimeError(f"{operation_name} failed: {status.value}")


def _build_requirements_doc(
    request: RequirementGenerationRequest,
    unresolved_items: list[str],
) -> str:
    unresolved_section = "\n".join(f"- {item}" for item in unresolved_items) or "- None"
    return "\n".join(
        [
            "# Requirements",
            "",
            "## 1. Idea",
            request.idea,
            "",
            "## 2. Submitted Form",
            f"- Answer count: {len(request.form_responses)}",
            "",
            "## 3. Open Items",
            unresolved_section,
        ]
    )
