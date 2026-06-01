"""Application composition root for demo mode."""

from __future__ import annotations

import os

from app.agents.gemini import DEFAULT_GEMINI_MODEL
from app.agents.gemini import GeminiApiConfig
from app.agents.gemini import GeminiArchitectGenerator
from app.agents.gemini import GeminiGcpPlannerGenerator
from app.agents.gemini import GeminiJsonClient
from app.agents.gemini import GeminiRequirementGenerator
from app.agents.gemini import GeminiSecurityEvaluator
from app.agents.runtime import AgentRuntime
from app.agents.runtime import InMemoryAgentStore
from app.agents.tool_guard import DEFAULT_TOOL_DEFINITIONS
from app.agents.tool_guard import ToolGuard
from app.api.facade import CastorOpsApiFacade
from app.approvals.repository import InMemoryApprovalRepository
from app.approvals.service import ApprovalService
from app.architectures.repository import InMemoryArchitectureRepository
from app.architectures.service import ArchitectureService
from app.codegen.repository import InMemoryCodeGenerationRepository
from app.codegen.service import TargetAppCodeService
from app.deployments.cloudbuild import LocalCloudBuildAdapter
from app.deployments.repository import InMemoryDeploymentRepository
from app.deployments.service import DeploymentService
from app.documents.repository import InMemoryDocumentRepository
from app.documents.service import DocumentService
from app.ops.service import OpsDashboardService
from app.projects.repository import InMemoryProjectRepository
from app.projects.service import ProjectService
from app.security.repository import InMemorySecurityFindingRepository
from app.security.service import SecurityFindingService
from app.timeline.repository import InMemoryTimelineRepository
from app.timeline.service import TimelineService
from app.workflows.apply import ApplyWorkflowService
from app.workflows.demo import DemoArchitectGenerator
from app.workflows.demo import DemoGcpPlannerGenerator
from app.workflows.demo import DemoRequirementGenerator
from app.workflows.demo import DemoSecurityEvaluator
from app.workflows.designs import DesignWorkflowService
from app.workflows.planning import PlanningWorkflowService
from app.workflows.requirements import RequirementWorkflowService
from app.workflows.security import SecurityEvaluationWorkflowService


def build_demo_facade() -> CastorOpsApiFacade:
    """Build a fully wired in-memory facade.

    By default this uses deterministic demo agents. Set
    CASTOROPS_AGENT_PROVIDER=gemini and GEMINI_API_KEY to use Gemini API-backed
    agents for requirements, design, planning, and security evaluation.
    """

    agent_provider_mode = _agent_provider_mode_from_env()
    generators = _build_agent_generators(agent_provider_mode)
    project_service = ProjectService(repository=InMemoryProjectRepository())
    document_service = DocumentService(InMemoryDocumentRepository())
    architecture_service = ArchitectureService(InMemoryArchitectureRepository())
    deployment_service = DeploymentService(InMemoryDeploymentRepository())
    finding_service = SecurityFindingService(InMemorySecurityFindingRepository())
    timeline_service = TimelineService(
        InMemoryTimelineRepository(),
        agent_adapter_mode="gemini_api" if agent_provider_mode == "gemini" else "demo_agent",
    )
    code_service = TargetAppCodeService(InMemoryCodeGenerationRepository())
    agent_runtime = AgentRuntime(
        store=InMemoryAgentStore(),
        tool_guard=ToolGuard(DEFAULT_TOOL_DEFINITIONS),
    )
    return CastorOpsApiFacade(
        project_service=project_service,
        requirement_workflow=RequirementWorkflowService(
            project_service=project_service,
            document_service=document_service,
            agent_runtime=agent_runtime,
            generator=generators.requirement,
        ),
        design_workflow=DesignWorkflowService(
            project_service=project_service,
            document_service=document_service,
            agent_runtime=agent_runtime,
            generator=generators.architect,
        ),
        planning_workflow=PlanningWorkflowService(
            project_service=project_service,
            document_service=document_service,
            architecture_service=architecture_service,
            agent_runtime=agent_runtime,
            generator=generators.planner,
        ),
        security_workflow=SecurityEvaluationWorkflowService(
            project_service=project_service,
            architecture_service=architecture_service,
            finding_service=finding_service,
            agent_runtime=agent_runtime,
            evaluator=generators.security,
        ),
        apply_workflow=ApplyWorkflowService(
            project_service=project_service,
            architecture_service=architecture_service,
            deployment_service=deployment_service,
            cloudbuild_adapter=LocalCloudBuildAdapter(),
        ),
        architecture_service=architecture_service,
        code_service=code_service,
        ops_service=OpsDashboardService(
            project_service=project_service,
            architecture_service=architecture_service,
            deployment_service=deployment_service,
            finding_service=finding_service,
            timeline_service=timeline_service,
        ),
        timeline_service=timeline_service,
        document_service=document_service,
        deployment_service=deployment_service,
        approval_service=ApprovalService(
            repository=InMemoryApprovalRepository(),
            project_service=project_service,
        ),
        agent_provider_mode=agent_provider_mode,
    )


class _AgentGenerators:
    def __init__(
        self,
        *,
        requirement: object,
        architect: object,
        planner: object,
        security: object,
    ) -> None:
        self.requirement = requirement
        self.architect = architect
        self.planner = planner
        self.security = security


def _agent_provider_mode_from_env() -> str:
    raw_mode = os.environ.get("CASTOROPS_AGENT_PROVIDER", "demo").strip().lower()
    if raw_mode not in {"demo", "gemini"}:
        raise RuntimeError("CASTOROPS_AGENT_PROVIDER must be either 'demo' or 'gemini'")
    return raw_mode


def _build_agent_generators(agent_provider_mode: str) -> _AgentGenerators:
    if agent_provider_mode == "gemini":
        client = GeminiJsonClient(
            GeminiApiConfig(
                api_key=os.environ.get("GEMINI_API_KEY", ""),
                model=os.environ.get("GEMINI_MODEL", DEFAULT_GEMINI_MODEL),
                endpoint=os.environ.get("GEMINI_API_ENDPOINT", "https://generativelanguage.googleapis.com/v1beta"),
                timeout_seconds=float(os.environ.get("GEMINI_TIMEOUT_SECONDS", "45")),
            )
        )
        return _AgentGenerators(
            requirement=GeminiRequirementGenerator(client),
            architect=GeminiArchitectGenerator(client),
            planner=GeminiGcpPlannerGenerator(client),
            security=GeminiSecurityEvaluator(client),
        )
    return _AgentGenerators(
        requirement=DemoRequirementGenerator(),
        architect=DemoArchitectGenerator(),
        planner=DemoGcpPlannerGenerator(),
        security=DemoSecurityEvaluator(),
    )
