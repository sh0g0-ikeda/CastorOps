"""Application composition root for demo mode."""

from __future__ import annotations

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
    """Build a fully wired in-memory facade for hackathon demo mode."""

    project_service = ProjectService(repository=InMemoryProjectRepository())
    document_service = DocumentService(InMemoryDocumentRepository())
    architecture_service = ArchitectureService(InMemoryArchitectureRepository())
    deployment_service = DeploymentService(InMemoryDeploymentRepository())
    finding_service = SecurityFindingService(InMemorySecurityFindingRepository())
    timeline_service = TimelineService(InMemoryTimelineRepository())
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
            generator=DemoRequirementGenerator(),
        ),
        design_workflow=DesignWorkflowService(
            project_service=project_service,
            document_service=document_service,
            agent_runtime=agent_runtime,
            generator=DemoArchitectGenerator(),
        ),
        planning_workflow=PlanningWorkflowService(
            project_service=project_service,
            document_service=document_service,
            architecture_service=architecture_service,
            agent_runtime=agent_runtime,
            generator=DemoGcpPlannerGenerator(),
        ),
        security_workflow=SecurityEvaluationWorkflowService(
            project_service=project_service,
            architecture_service=architecture_service,
            finding_service=finding_service,
            agent_runtime=agent_runtime,
            evaluator=DemoSecurityEvaluator(),
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
        approval_service=ApprovalService(
            repository=InMemoryApprovalRepository(),
            project_service=project_service,
        ),
    )
