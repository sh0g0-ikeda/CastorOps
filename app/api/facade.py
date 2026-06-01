"""Framework-independent API facade.

FastAPI handlers can delegate to this facade without embedding workflow logic
inside transport code.
"""

from __future__ import annotations

from typing import Any

from app.approvals.service import ApprovalService
from app.approvals.service import parse_approval_decision
from app.approvals.service import parse_approval_gate
from app.auth.demo import DemoIdentityProvider
from app.api.responses import ApiResponse
from app.codegen.service import TargetAppCodeService
from app.core.errors import AppError
from app.core.errors import ValidationAppError
from app.deployments.service import DeploymentService
from app.documents.models import DocumentType
from app.documents.service import DocumentService
from app.ops.service import OpsDashboardService
from app.projects.models import ProjectPhase
from app.projects.service import ProjectService
from app.timeline.service import TimelineService
from app.workflows.apply import ApplyWorkflowService
from app.workflows.designs import DesignWorkflowService
from app.workflows.planning import PlanningWorkflowService
from app.workflows.requirements import RequirementWorkflowService
from app.workflows.security import SecurityEvaluationWorkflowService


class CastorOpsApiFacade:
    """Application-facing operations exposed by the backend API."""

    def __init__(
        self,
        *,
        project_service: ProjectService,
        requirement_workflow: RequirementWorkflowService,
        design_workflow: DesignWorkflowService,
        planning_workflow: PlanningWorkflowService,
        security_workflow: SecurityEvaluationWorkflowService,
        apply_workflow: ApplyWorkflowService | None = None,
        architecture_service: "ArchitectureService | None" = None,
        code_service: TargetAppCodeService | None = None,
        ops_service: OpsDashboardService | None = None,
        timeline_service: TimelineService | None = None,
        document_service: DocumentService | None = None,
        deployment_service: DeploymentService | None = None,
        identity_provider: DemoIdentityProvider | None = None,
        approval_service: ApprovalService | None = None,
    ) -> None:
        self._project_service = project_service
        self._requirement_workflow = requirement_workflow
        self._design_workflow = design_workflow
        self._planning_workflow = planning_workflow
        self._security_workflow = security_workflow
        self._apply_workflow = apply_workflow
        self._architecture_service = architecture_service
        self._code_service = code_service
        self._ops_service = ops_service
        self._timeline_service = timeline_service
        self._document_service = document_service
        self._deployment_service = deployment_service
        self._identity_provider = identity_provider or DemoIdentityProvider()
        self._approval_service = approval_service

    async def create_project(
        self,
        *,
        owner_uid: str | None = None,
        name: str,
        idea: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            current_user = await self._identity_provider.current_user()
            project = await self._project_service.create_project(
                owner_uid=owner_uid or current_user.uid,
                name=name,
                idea=idea,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "id": project.id,
                "owner_uid": project.owner_uid,
                "name": project.name,
                "idea": project.idea,
                "phase": project.phase.value,
            },
            request_id=request_id,
        )

    async def get_project(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        try:
            payload = await self._project_service.get_project_payload(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def transition_project(
        self,
        *,
        project_id: str,
        next_phase: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            parsed_next_phase = ProjectPhase(next_phase)
            project = await self._project_service.transition_project(
                project_id=project_id,
                next_phase=parsed_next_phase,
            )
        except ValueError:
            error = ValidationAppError("next_phase is not supported", {"next_phase": next_phase})
            return ApiResponse.failed(error, request_id=request_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "id": project.id,
                "phase": project.phase.value,
            },
            request_id=request_id,
        )

    async def list_approvals(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        if self._approval_service is None:
            return ApiResponse.ok([], request_id=request_id)
        try:
            approvals = await self._approval_service.list_payloads(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(approvals, request_id=request_id)

    async def decide_approval(
        self,
        *,
        project_id: str,
        gate: str,
        decision: str,
        rationale: str = "",
        snapshot: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._approval_service is None:
            error = ValidationAppError("approval service is not configured")
            return ApiResponse.failed(error, request_id=request_id)
        try:
            current_user = await self._identity_provider.current_user()
            approval = await self._approval_service.decide(
                project_id=project_id,
                gate=parse_approval_gate(gate),
                decision=parse_approval_decision(decision),
                decided_by=current_user.uid,
                rationale=rationale,
                snapshot=snapshot,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "id": approval.id,
                "gate": approval.gate.value,
                "decision": approval.decision.value,
                "decided_by": approval.decided_by,
            },
            request_id=request_id,
        )

    async def generate_requirements(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            result = await self._requirement_workflow.generate_requirements(project_id=project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        await self._record_agent_run(
            run=result.run,
            action="generated_requirements",
            target={"type": "document", "id": result.document.id} if result.document else None,
        )
        return ApiResponse.ok(
            {
                "run_id": result.run.id,
                "run_status": result.run.status.value,
                "document_id": result.document.id if result.document else None,
            },
            request_id=request_id,
        )

    async def capture_image_requirement(
        self,
        *,
        project_id: str,
        file_name: str,
        description: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if not file_name.strip():
            return ApiResponse.failed(
                ValidationAppError("file_name must be a non-empty string"),
                request_id=request_id,
            )
        if not description.strip():
            return ApiResponse.failed(
                ValidationAppError("description must be a non-empty string"),
                request_id=request_id,
            )
        return ApiResponse.ok(
            {
                "project_id": project_id,
                "file_name": file_name.strip(),
                "extracted_requirements": [
                    "Use the uploaded visual as architecture context.",
                    f"Captured note: {description.strip()}",
                ],
                "mode": "demo_image_artifact",
            },
            request_id=request_id,
        )

    async def generate_follow_up_questions(
        self,
        *,
        project_id: str,
        form_responses: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            result = await self._requirement_workflow.generate_follow_up_questions(
                project_id=project_id,
                form_responses=form_responses,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        await self._record_agent_run(
            run=result.run,
            action="generated_follow_up_questions",
        )
        return ApiResponse.ok(
            {
                "run_id": result.run.id,
                "run_status": result.run.status.value,
                "follow_up_questions": result.questions,
            },
            request_id=request_id,
        )

    async def generate_basic_design(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            result = await self._design_workflow.generate_design_document(
                project_id=project_id,
                doc_type=DocumentType.BASIC_DESIGN,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        await self._record_agent_run(
            run=result.run,
            action="generated_design_document",
            target={"type": "document", "id": result.document.id} if result.document else None,
        )
        return ApiResponse.ok(
            {
                "run_id": result.run.id,
                "run_status": result.run.status.value,
                "document_id": result.document.id if result.document else None,
            },
            request_id=request_id,
        )

    async def generate_design_document(
        self,
        *,
        project_id: str,
        doc_type: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            parsed_doc_type = DocumentType(doc_type)
            result = await self._design_workflow.generate_design_document(
                project_id=project_id,
                doc_type=parsed_doc_type,
            )
        except ValueError:
            error = ValidationAppError("doc_type is not supported", {"doc_type": doc_type})
            return ApiResponse.failed(error, request_id=request_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "run_id": result.run.id,
                "run_status": result.run.status.value,
                "doc_type": parsed_doc_type.value,
                "document_id": result.document.id if result.document else None,
            },
            request_id=request_id,
        )

    async def generate_design_set(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        design_doc_types = (
            DocumentType.BASIC_DESIGN,
            DocumentType.API_DESIGN,
            DocumentType.DATA_DESIGN,
            DocumentType.ADR,
            DocumentType.TASKS,
            DocumentType.OPS_DESIGN,
            DocumentType.SECURITY_DESIGN,
        )
        generated_documents = []
        try:
            for doc_type in design_doc_types:
                result = await self._design_workflow.generate_design_document(
                    project_id=project_id,
                    doc_type=doc_type,
                )
                await self._record_agent_run(
                    run=result.run,
                    action="generated_design_document",
                    target={"type": "document", "id": result.document.id} if result.document else None,
                )
                generated_documents.append(
                    {
                        "run_id": result.run.id,
                        "run_status": result.run.status.value,
                        "doc_type": doc_type.value,
                        "document_id": result.document.id if result.document else None,
                    }
                )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(generated_documents, request_id=request_id)

    async def latest_documents(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._document_service is None:
            return ApiResponse.ok([], request_id=request_id)
        documents = []
        try:
            for doc_type in DocumentType:
                try:
                    documents.append(await self._document_service.latest_payload(project_id, doc_type))
                except AppError:
                    continue
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(documents, request_id=request_id)

    async def propose_architecture(
        self,
        *,
        project_id: str,
        target_project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            result = await self._planning_workflow.propose_architecture(
                project_id=project_id,
                target_project_id=target_project_id,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        await self._record_agent_run(
            run=result.run,
            action="proposed_architecture",
            target={"type": "architecture", "id": result.proposal.id} if result.proposal else None,
        )
        return ApiResponse.ok(
            {
                "run_id": result.run.id,
                "run_status": result.run.status.value,
                "architecture_id": result.proposal.id if result.proposal else None,
            },
            request_id=request_id,
        )

    async def evaluate_security(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            result = await self._security_workflow.evaluate_latest_architecture(project_id=project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        await self._record_agent_run(
            run=result.run,
            action="evaluated_security",
        )
        return ApiResponse.ok(
            {
                "run_id": result.run.id,
                "run_status": result.run.status.value,
                "findings": len(result.findings),
                "critical_count": result.critical_count,
            },
            request_id=request_id,
        )

    async def get_editable_architecture_node(
        self,
        *,
        project_id: str,
        node_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            payload = await self._architecture_service.editable_node_parameters(
                project_id=project_id,
                node_id=node_id,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def latest_architecture(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            payload = await self._architecture_service.latest_payload(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def preview_architecture_node_update(
        self,
        *,
        project_id: str,
        node_id: str,
        parameter_patch: dict[str, Any],
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            payload = await self._architecture_service.preview_node_update(
                project_id=project_id,
                node_id=node_id,
                parameter_patch=parameter_patch,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def update_architecture_node(
        self,
        *,
        project_id: str,
        node_id: str,
        parameter_patch: dict[str, Any],
        change_reason: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            proposal = await self._architecture_service.create_updated_node_proposal(
                project_id=project_id,
                node_id=node_id,
                parameter_patch=parameter_patch,
                change_reason=change_reason,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "architecture_id": proposal.id,
                "version": proposal.version,
                "status": proposal.status.value,
            },
            request_id=request_id,
        )

    async def revise_architecture_from_chat(
        self,
        *,
        project_id: str,
        message: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            parameter_patch = _parameter_patch_from_change_request(message)
            preview = await self._architecture_service.preview_node_update(
                project_id=project_id,
                node_id="backend",
                parameter_patch=parameter_patch,
            )
            proposal = await self._architecture_service.create_updated_node_proposal(
                project_id=project_id,
                node_id="backend",
                parameter_patch=parameter_patch,
                change_reason=f"Chat change request: {message.strip()}",
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "architecture_id": proposal.id,
                "version": proposal.version,
                "status": proposal.status.value,
                "node_id": "backend",
                "changes": parameter_patch,
                "impact": preview["impact"],
                "requires_reapproval": True,
                "requires_reapply": True,
            },
            request_id=request_id,
        )

    async def delete_architecture_node(
        self,
        *,
        project_id: str,
        node_id: str,
        confirmed: bool,
        change_reason: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            proposal = await self._architecture_service.create_deleted_node_proposal(
                project_id=project_id,
                node_id=node_id,
                confirmed=confirmed,
                change_reason=change_reason,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "architecture_id": proposal.id,
                "version": proposal.version,
                "status": proposal.status.value,
            },
            request_id=request_id,
        )

    async def evaluate_security_loop(
        self,
        *,
        project_id: str,
        rounds: int = 2,
        request_id: str | None = None,
    ) -> ApiResponse:
        if rounds < 1 or rounds > 3:
            return ApiResponse.failed(
                ValidationAppError("rounds must be between 1 and 3"),
                request_id=request_id,
            )
        completed_rounds = []
        try:
            for round_index in range(rounds):
                result = await self._security_workflow.evaluate_latest_architecture(project_id=project_id)
                await self._record_agent_run(
                    run=result.run,
                    action="evaluated_security",
                )
                completed_rounds.append(
                    {
                        "round": round_index + 1,
                        "run_id": result.run.id,
                        "run_status": result.run.status.value,
                        "findings": len(result.findings),
                        "critical_count": result.critical_count,
                        "conditional_reproposal": result.critical_count > 0,
                    }
                )
                if result.critical_count == 0:
                    break
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "rounds": completed_rounds,
                "completed": True,
                "stopped_reason": "no_critical_findings"
                if completed_rounds and completed_rounds[-1]["critical_count"] == 0
                else "round_limit",
            },
            request_id=request_id,
        )

    async def add_architecture_node(
        self,
        *,
        project_id: str,
        node_id: str,
        node_type: str,
        name: str,
        parameters: dict[str, Any],
        change_reason: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            proposal = await self._architecture_service.create_added_node_proposal(
                project_id=project_id,
                node_id=node_id,
                node_type=node_type,
                name=name,
                parameters=parameters,
                change_reason=change_reason,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "architecture_id": proposal.id,
                "version": proposal.version,
                "status": proposal.status.value,
                "node_id": node_id,
            },
            request_id=request_id,
        )

    async def add_architecture_edge(
        self,
        *,
        project_id: str,
        edge_id: str,
        from_node: str,
        to_node: str,
        edge_type: str,
        description: str,
        change_reason: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            proposal = await self._architecture_service.create_added_edge_proposal(
                project_id=project_id,
                edge_id=edge_id,
                from_node=from_node,
                to_node=to_node,
                edge_type=edge_type,
                description=description,
                change_reason=change_reason,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "architecture_id": proposal.id,
                "version": proposal.version,
                "status": proposal.status.value,
                "edge_id": edge_id,
            },
            request_id=request_id,
        )

    async def delete_architecture_edge(
        self,
        *,
        project_id: str,
        edge_id: str,
        change_reason: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            proposal = await self._architecture_service.create_deleted_edge_proposal(
                project_id=project_id,
                edge_id=edge_id,
                change_reason=change_reason,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "architecture_id": proposal.id,
                "version": proposal.version,
                "status": proposal.status.value,
                "edge_id": edge_id,
            },
            request_id=request_id,
        )

    async def apply_latest_architecture(
        self,
        *,
        project_id: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._apply_workflow is None:
            return ApiResponse.failed(
                ValidationAppError("apply workflow is not configured"),
                request_id=request_id,
            )
        try:
            result = await self._apply_workflow.apply_latest_architecture(project_id=project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "deployment_id": result.deployment.id,
                "build_id": result.deployment.build_id,
                "status": result.deployment.status.value,
                "deployed_url": result.deployment.deployed_url,
            },
            request_id=request_id,
        )

    async def apply_failure_guidance(
        self,
        *,
        project_id: str,
        error_text: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        if not error_text.strip():
            return ApiResponse.failed(
                ValidationAppError("error_text must be a non-empty string"),
                request_id=request_id,
            )
        try:
            architecture = await self._architecture_service.latest_payload(project_id) if self._architecture_service else None
        except AppError:
            architecture = None
        return ApiResponse.ok(
            _apply_failure_guidance_payload(error_text=error_text, architecture=architecture),
            request_id=request_id,
        )

    async def apply_failure_demo(
        self,
        *,
        project_id: str,
        error_text: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        guidance_response = await self.apply_failure_guidance(
            project_id=project_id,
            error_text=error_text,
            request_id=request_id,
        )
        guidance_body = guidance_response.to_dict()
        if guidance_body["error"] is not None:
            return guidance_response
        return ApiResponse.ok(
            {
                "simulated_failure": {
                    "status": "failed",
                    "adapter_mode": "demo_adapter",
                    "error_text": error_text,
                },
                "diagnosis": guidance_body["data"],
                "recovery_demo": {
                    "kept_previous_revision": True,
                    "recommended_fix_applied_to_draft": True,
                    "next_command": "Approve architecture, then run Apply again.",
                },
            },
            request_id=request_id,
        )

    async def terraform_preview(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        if self._architecture_service is None:
            return ApiResponse.failed(
                ValidationAppError("architecture service is not configured"),
                request_id=request_id,
            )
        try:
            architecture = await self._architecture_service.latest_payload(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(_terraform_preview_payload(architecture), request_id=request_id)

    async def github_demo_flow(
        self,
        *,
        project_id: str,
        repo_url: str,
        request_id: str | None = None,
    ) -> ApiResponse:
        try:
            latest_package = await self._code_service.latest_payload(project_id) if self._code_service else None
        except AppError:
            latest_package = None
        try:
            latest_architecture = await self._architecture_service.latest_payload(project_id) if self._architecture_service else None
        except AppError:
            latest_architecture = None
        try:
            payload = _github_demo_payload(
                project_id=project_id,
                repo_url=repo_url,
                latest_package=latest_package,
                latest_architecture=latest_architecture,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def cloud_run_evidence(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        try:
            architecture = await self._architecture_service.latest_payload(project_id) if self._architecture_service else None
        except AppError:
            architecture = None
        try:
            deployment = await self._deployment_service.latest_payload(project_id) if self._deployment_service else None
        except AppError:
            deployment = None
        return ApiResponse.ok(
            _cloud_run_evidence_payload(architecture=architecture, deployment=deployment),
            request_id=request_id,
        )

    async def adapter_inventory(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        _ = project_id
        return ApiResponse.ok(
            {
                "runtime": {"product": "Cloud Run", "mode": "live_deploy_supported"},
                "ai_generation": {"provider": "Gemini/Vertex AI", "mode": "pending_final_live_credentials"},
                "requirements_agent": {"mode": "demo_agent", "live_target": "Gemini"},
                "architect_agent": {"mode": "demo_agent", "live_target": "Gemini"},
                "security_agent": {"mode": "demo_agent", "live_target": "Gemini"},
                "cloud_build_apply": {"mode": "demo_adapter", "live_target": "Cloud Build + Cloud Run"},
                "github_delivery": {"mode": "demo_adapter", "live_target": "GitHub API"},
                "terraform_preview": {"mode": "preview_only", "live_target": "future IaC adapter"},
            },
            request_id=request_id,
        )

    async def submission_brief(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        try:
            project = await self._project_service.get_project_payload(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "product": "CastorOps",
                "project_id": project["id"],
                "target_user": "Solo developers and small teams that can build an app but struggle to explain and operate GCP infrastructure.",
                "problem": "AI coding tools speed up implementation, but cloud design, approval, deployment, and operations remain hard to inspect.",
                "agent_value": "CastorOps turns an idea into requirements, design docs, a GCP architecture, approval-gated apply steps, and an Ops Dashboard with traceable decisions.",
                "before_after": {
                    "before": "The user has code or an idea but cannot confidently explain the GCP design or operate it.",
                    "after": "The user can inspect why Cloud Run and related services were selected, approve changes, and monitor deployment state.",
                },
                "google_cloud_usage": {
                    "required_runtime": "Cloud Run",
                    "required_ai": "Gemini/Vertex AI final live adapter planned for submission; current demo keeps deterministic agent adapters for repeatable judging.",
                    "supporting_services": ["Cloud Build", "Artifact Registry", "Firestore", "Cloud Logging", "Cloud Monitoring"],
                },
                "demo_scenes": [
                    "Create project and follow-up questions",
                    "Generate requirements and design documents",
                    "Propose and edit GCP architecture",
                    "Approve and apply architecture",
                    "Inspect Ops Dashboard and Execution Timeline",
                ],
            },
            request_id=request_id,
        )

    async def generate_target_app(
        self,
        *,
        project_id: str,
        app_name: str,
        collection_name: str = "inquiries",
        fields: tuple[str, ...] = ("subject", "message", "email"),
        env_vars: tuple[str, ...] = (),
        request_id: str | None = None,
    ) -> ApiResponse:
        if self._code_service is None:
            return ApiResponse.failed(
                ValidationAppError("code service is not configured"),
                request_id=request_id,
            )
        try:
            result = await self._code_service.generate_inquiry_api(
                project_id=project_id,
                app_name=app_name,
                collection_name=collection_name,
                fields=fields,
                env_vars=env_vars,
            )
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(
            {
                "id": result.id,
                "app_name": result.app_name,
                "files": [{"path": generated_file.path} for generated_file in result.files],
            },
            request_id=request_id,
        )

    async def latest_target_app(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        if self._code_service is None:
            return ApiResponse.failed(
                ValidationAppError("code service is not configured"),
                request_id=request_id,
            )
        try:
            payload = await self._code_service.latest_payload(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def review_latest_target_app(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        if self._code_service is None:
            return ApiResponse.failed(
                ValidationAppError("code service is not configured"),
                request_id=request_id,
            )
        try:
            payload = await self._code_service.review_latest(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def ops_overview(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        if self._ops_service is None:
            return ApiResponse.failed(
                ValidationAppError("ops service is not configured"),
                request_id=request_id,
            )
        try:
            payload = await self._ops_service.overview(project_id=project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def timeline(self, *, project_id: str, request_id: str | None = None) -> ApiResponse:
        if self._timeline_service is None:
            return ApiResponse.ok([], request_id=request_id)
        try:
            payload = await self._timeline_service.list_payloads(project_id)
        except AppError as exc:
            return ApiResponse.failed(exc, request_id=request_id)
        return ApiResponse.ok(payload, request_id=request_id)

    async def _record_agent_run(
        self,
        *,
        run: Any,
        action: str,
        target: dict[str, str] | None = None,
    ) -> None:
        if self._timeline_service is None:
            return
        await self._timeline_service.record_agent_run(
            run=run,
            action=action,
            target=target,
        )


def _parameter_patch_from_change_request(message: str) -> dict[str, Any]:
    normalized = message.strip().lower()
    if not normalized:
        raise ValidationAppError("message must be a non-empty string")
    patch: dict[str, Any] = {}
    if "1gi" in normalized or "1 gi" in normalized or "more memory" in normalized or "larger memory" in normalized:
        patch["memory"] = "1Gi"
    elif "512mi" in normalized or "512 mi" in normalized:
        patch["memory"] = "512Mi"
    elif "256mi" in normalized or "256 mi" in normalized or "cheaper" in normalized or "lower cost" in normalized:
        patch["memory"] = "256Mi"

    if "2 cpu" in normalized or "cpu 2" in normalized or "more cpu" in normalized:
        patch["cpu"] = "2"
    elif "1 cpu" in normalized or "cpu 1" in normalized or "cheaper" in normalized or "lower cost" in normalized:
        patch["cpu"] = "1"

    if "unauthenticated" in normalized or "public" in normalized:
        patch["allow_unauthenticated"] = True
    elif "private" in normalized or "authenticated" in normalized:
        patch["allow_unauthenticated"] = False

    if not patch:
        raise ValidationAppError(
            "chat request did not include a supported architecture change",
            {"supported_examples": ["make it public", "use 1Gi memory", "lower cost"]},
        )
    return patch


def _apply_failure_guidance_payload(
    *,
    error_text: str,
    architecture: dict[str, Any] | None,
) -> dict[str, Any]:
    normalized = error_text.lower()
    if "permission" in normalized or "iam" in normalized or "forbidden" in normalized:
        likely_cause = "Insufficient IAM permission for Cloud Build or Cloud Run deployment."
        repair_steps = [
            "Confirm the Cloud Build service account has deploy permission for Cloud Run.",
            "Confirm Artifact Registry push permission is granted.",
            "Re-run apply after approval.",
        ]
    elif "image" in normalized or "artifact" in normalized:
        likely_cause = "Container image build or push failed."
        repair_steps = [
            "Run the generated tests locally.",
            "Rebuild the container image.",
            "Check Artifact Registry repository and region.",
        ]
    else:
        likely_cause = "Cloud Build apply failed before deployment completed."
        repair_steps = [
            "Open the Cloud Build log for the failed step.",
            "Keep the previous deployed revision serving traffic.",
            "Apply the corrected architecture draft after approval.",
        ]
    rollback_candidates = []
    if architecture is not None:
        rollback_candidates.append(
            {
                "architecture_id": architecture["id"],
                "version": architecture["version"],
                "strategy": "Keep previous Cloud Run revision and re-apply this architecture after fixing the error.",
            }
        )
    return {
        "likely_cause": likely_cause,
        "repair_steps": repair_steps,
        "rollback_candidates": rollback_candidates,
    }


def _terraform_preview_payload(architecture: dict[str, Any]) -> dict[str, Any]:
    resources = []
    for node in architecture["spec"]["nodes"]:
        resource_name = node["id"].replace("-", "_")
        if node["type"] == "cloud_run":
            resources.append(
                "\n".join(
                    [
                        f'resource "google_cloud_run_v2_service" "{resource_name}" {{',
                        f'  name     = "{node["id"]}"',
                        f'  location = "{architecture["spec"]["region"]}"',
                        "}",
                    ]
                )
            )
        elif node["type"] == "firestore":
            resources.append(
                "\n".join(
                    [
                        f'resource "google_firestore_database" "{resource_name}" {{',
                        '  name        = "(default)"',
                        f'  location_id = "{architecture["spec"]["region"]}"',
                        '  type        = "FIRESTORE_NATIVE"',
                        "}",
                    ]
                )
            )
        else:
            resources.append(f'# {node["type"]} "{node["id"]}" is represented in the architecture map.')
    return {
        "mode": "preview_only",
        "hcl": "\n\n".join(resources),
        "plan_summary": {
            "add": len(architecture["spec"]["nodes"]),
            "change": 0,
            "destroy": 0,
        },
        "warning": "Terraform is a COULD-level preview in this demo. Cloud Build + gcloud remains the executable apply path.",
    }


def _github_demo_payload(
    *,
    project_id: str,
    repo_url: str,
    latest_package: dict[str, Any] | None,
    latest_architecture: dict[str, Any] | None,
) -> dict[str, Any]:
    if not repo_url.strip() or "github.com" not in repo_url:
        raise ValidationAppError("repo_url must be a GitHub repository URL")
    normalized_url = repo_url.strip().rstrip("/")
    branch = f"castorops/{project_id[:8]}-demo"
    files = latest_package["files"] if latest_package else []
    detected_paths = [file_payload["path"] for file_payload in files]
    return {
        "repository": {
            "url": normalized_url,
            "read": True,
            "detected_files": detected_paths or ["README.md", "Dockerfile", "cloudbuild.yaml"],
        },
        "branch": {
            "name": branch,
            "created": True,
        },
        "push": {
            "pushed": True,
            "files": detected_paths,
        },
        "draft_pr": {
            "created": True,
            "url": f"{normalized_url}/pull/castorops-demo",
            "title": "CastorOps generated deployment package",
        },
        "architecture_version": latest_architecture["version"] if latest_architecture else None,
        "mode": "demo_adapter",
    }


def _cloud_run_evidence_payload(
    *,
    architecture: dict[str, Any] | None,
    deployment: dict[str, Any] | None,
) -> dict[str, Any]:
    region = architecture["spec"]["region"] if architecture else "asia-northeast1"
    service_name = "backend"
    target_project = architecture["spec"]["project_id"] if architecture else "demo-gcp-project"
    if deployment is None:
        return {
            "runtime_product": "Cloud Run",
            "target_project": target_project,
            "region": region,
            "service_name": service_name,
            "status": "not_deployed",
            "adapter_mode": "demo_adapter",
            "evidence": ["Dockerfile present", "Cloud Build deploy pipeline present"],
        }
    return {
        "runtime_product": "Cloud Run",
        "target_project": target_project,
        "region": region,
        "service_name": service_name,
        "service_url": deployment["deployed_url"],
        "revision": f'{service_name}-{deployment["build_id"][-8:]}',
        "status": deployment["status"],
        "authentication": "private-by-default demo; public access requires explicit approval",
        "build_id": deployment["build_id"],
        "adapter_mode": "demo_adapter",
        "evidence": deployment["logs"],
    }
