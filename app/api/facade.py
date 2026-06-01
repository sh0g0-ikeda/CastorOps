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

    async def generate_target_app(
        self,
        *,
        project_id: str,
        app_name: str,
        collection_name: str = "inquiries",
        fields: tuple[str, ...] = ("subject", "message", "email"),
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
