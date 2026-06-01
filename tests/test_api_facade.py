import unittest

from app.approvals.repository import InMemoryApprovalRepository
from app.approvals.service import ApprovalService
from app.agents.runtime import AgentRuntime
from app.agents.runtime import InMemoryAgentStore
from app.agents.tool_guard import DEFAULT_TOOL_DEFINITIONS
from app.agents.tool_guard import ToolGuard
from app.api.facade import CastorOpsApiFacade
from app.architectures.repository import InMemoryArchitectureRepository
from app.architectures.service import ArchitectureService
from app.codegen.repository import InMemoryCodeGenerationRepository
from app.codegen.service import TargetAppCodeService
from app.deployments.cloudbuild import LocalCloudBuildAdapter
from app.deployments.repository import InMemoryDeploymentRepository
from app.deployments.service import DeploymentService
from app.ops.service import OpsDashboardService
from app.documents.repository import InMemoryDocumentRepository
from app.documents.service import DocumentService
from app.projects.repository import InMemoryProjectRepository
from app.projects.service import ProjectService
from app.security.repository import InMemorySecurityFindingRepository
from app.security.service import SecurityFindingService
from app.timeline.repository import InMemoryTimelineRepository
from app.timeline.service import TimelineService
from app.workflows.demo import DemoArchitectGenerator
from app.workflows.demo import DemoGcpPlannerGenerator
from app.workflows.demo import DemoRequirementGenerator
from app.workflows.demo import DemoSecurityEvaluator
from app.workflows.apply import ApplyWorkflowService
from app.workflows.designs import DesignWorkflowService
from app.workflows.planning import PlanningWorkflowService
from app.workflows.requirements import RequirementWorkflowService
from app.workflows.security import SecurityEvaluationWorkflowService


def make_facade() -> CastorOpsApiFacade:
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


class CastorOpsApiFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_project_returns_api_response(self) -> None:
        facade = make_facade()

        response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
            request_id="request-1",
        )
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertEqual(body["data"]["owner_uid"], "demo-user")
        self.assertEqual(body["data"]["phase"], "DRAFT")
        self.assertEqual(body["meta"]["request_id"], "request-1")

    async def test_create_project_validation_error_uses_error_envelope(self) -> None:
        facade = make_facade()

        response = await facade.create_project(
            name=" ",
            idea="問い合わせ管理アプリ",
            request_id="request-1",
        )
        body = response.to_dict()

        self.assertIsNone(body["data"])
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(body["meta"]["request_id"], "request-1")

    async def test_transition_project_rejects_unknown_phase(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]

        response = await facade.transition_project(
            project_id=project_id,
            next_phase="UNKNOWN",
            request_id="request-2",
        )
        body = response.to_dict()

        self.assertIsNone(body["data"])
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")
        self.assertEqual(body["error"]["details"], {"next_phase": "UNKNOWN"})
        self.assertEqual(body["meta"]["request_id"], "request-2")

    async def test_generate_follow_up_questions_returns_max_three_questions(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]

        response = await facade.generate_follow_up_questions(
            project_id=project_id,
            form_responses={"users": "support"},
        )
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertEqual(body["data"]["run_status"], "SUCCEEDED")
        self.assertLessEqual(len(body["data"]["follow_up_questions"]), 3)

    async def test_api_facade_runs_full_generation_pipeline(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]

        requirements_response = await facade.generate_requirements(project_id=project_id)
        requirements_body = requirements_response.to_dict()
        self.assertIsNone(requirements_body["error"])
        self.assertEqual(requirements_body["data"]["run_status"], "SUCCEEDED")
        self.assertIsNotNone(requirements_body["data"]["document_id"])

        requirement_approval = await facade.transition_project(
            project_id=project_id,
            next_phase="REQUIREMENT_APPROVED",
        )
        self.assertIsNone(requirement_approval.to_dict()["error"])

        design_response = await facade.generate_basic_design(project_id=project_id)
        design_body = design_response.to_dict()
        self.assertIsNone(design_body["error"])
        self.assertEqual(design_body["data"]["run_status"], "SUCCEEDED")
        self.assertIsNotNone(design_body["data"]["document_id"])

        design_approval = await facade.transition_project(
            project_id=project_id,
            next_phase="DESIGN_APPROVED",
        )
        self.assertIsNone(design_approval.to_dict()["error"])

        planning_response = await facade.propose_architecture(
            project_id=project_id,
            target_project_id="demo-gcp-project",
        )
        planning_body = planning_response.to_dict()
        self.assertIsNone(planning_body["error"])
        self.assertEqual(planning_body["data"]["run_status"], "SUCCEEDED")
        self.assertIsNotNone(planning_body["data"]["architecture_id"])

        security_response = await facade.evaluate_security(project_id=project_id)
        security_body = security_response.to_dict()
        self.assertIsNone(security_body["error"])
        self.assertEqual(security_body["data"]["run_status"], "SUCCEEDED")
        self.assertEqual(security_body["data"]["findings"], 1)

    async def test_generate_design_set_creates_required_and_recommended_design_docs(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]
        await facade.generate_requirements(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="requirements",
            decision="approved",
        )

        response = await facade.generate_design_set(project_id=project_id)
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertEqual(
            [item["doc_type"] for item in body["data"]],
            [
                "basic_design",
                "api_design",
                "data_design",
                "adr",
                "tasks",
                "ops_design",
                "security_design",
            ],
        )
        self.assertTrue(all(item["run_status"] == "SUCCEEDED" for item in body["data"]))

        documents_response = await facade.latest_documents(project_id=project_id)
        self.assertEqual(len(documents_response.to_dict()["data"]), 8)

    async def test_generate_design_document_rejects_unknown_doc_type(self) -> None:
        facade = make_facade()

        response = await facade.generate_design_document(
            project_id="project-1",
            doc_type="unknown",
        )
        body = response.to_dict()

        self.assertIsNone(body["data"])
        self.assertEqual(body["error"]["code"], "VALIDATION_ERROR")

    async def test_architecture_node_edit_preview_and_update_are_exposed(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]
        await facade.generate_requirements(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="requirements",
            decision="approved",
        )
        await facade.generate_basic_design(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="design",
            decision="approved",
        )
        await facade.propose_architecture(
            project_id=project_id,
            target_project_id="demo-gcp-project",
        )

        editable_response = await facade.get_editable_architecture_node(
            project_id=project_id,
            node_id="backend",
        )
        preview_response = await facade.preview_architecture_node_update(
            project_id=project_id,
            node_id="backend",
            parameter_patch={"memory": "1Gi"},
        )
        update_response = await facade.update_architecture_node(
            project_id=project_id,
            node_id="backend",
            parameter_patch={"memory": "1Gi"},
            change_reason="デモ負荷に備える",
        )

        self.assertIn("memory", editable_response.to_dict()["data"]["editable_fields"])
        self.assertTrue(preview_response.to_dict()["data"]["requires_reapply"])
        self.assertEqual(update_response.to_dict()["data"]["version"], 2)

        delete_response = await facade.delete_architecture_node(
            project_id=project_id,
            node_id="firestore",
            confirmed=True,
            change_reason="Remove persistent store from the demo architecture",
        )
        self.assertEqual(delete_response.to_dict()["data"]["version"], 3)

        chat_response = await facade.revise_architecture_from_chat(
            project_id=project_id,
            message="make the backend public and use 2 cpu",
        )
        self.assertEqual(chat_response.to_dict()["data"]["changes"]["cpu"], "2")
        self.assertTrue(chat_response.to_dict()["data"]["requires_reapproval"])

        add_node_response = await facade.add_architecture_node(
            project_id=project_id,
            node_id="secrets",
            node_type="secret_manager",
            name="Runtime Secrets",
            parameters={"secret_names": ["GEMINI_API_KEY"]},
            change_reason="Add runtime secrets",
        )
        add_edge_response = await facade.add_architecture_edge(
            project_id=project_id,
            edge_id="backend-secrets",
            from_node="backend",
            to_node="secrets",
            edge_type="secret_read",
            description="Backend reads runtime secrets.",
            change_reason="Connect backend to secrets",
        )
        delete_edge_response = await facade.delete_architecture_edge(
            project_id=project_id,
            edge_id="backend-secrets",
            change_reason="Remove secret edge",
        )
        self.assertEqual(add_node_response.to_dict()["data"]["node_id"], "secrets")
        self.assertEqual(add_edge_response.to_dict()["data"]["edge_id"], "backend-secrets")
        self.assertEqual(delete_edge_response.to_dict()["data"]["edge_id"], "backend-secrets")

    async def test_apply_latest_architecture_deploys_after_architecture_approval(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]
        await facade.generate_requirements(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="requirements",
            decision="approved",
        )
        await facade.generate_basic_design(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="design",
            decision="approved",
        )
        await facade.propose_architecture(
            project_id=project_id,
            target_project_id="demo-gcp-project",
        )
        await facade.decide_approval(
            project_id=project_id,
            gate="architecture",
            decision="approved",
        )

        response = await facade.apply_latest_architecture(project_id=project_id)
        project_response = await facade.get_project(project_id=project_id)
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertEqual(body["data"]["status"], "succeeded")
        self.assertTrue(body["data"]["deployed_url"].startswith("https://"))
        self.assertEqual(project_response.to_dict()["data"]["phase"], "DEPLOYED")

    async def test_generate_target_app_creates_template_package(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]

        response = await facade.generate_target_app(
            project_id=project_id,
            app_name="Support Desk API",
            collection_name="support_tickets",
            fields=("subject", "message"),
            env_vars=("GEMINI_API_KEY",),
        )
        latest_response = await facade.latest_target_app(project_id=project_id)
        review_response = await facade.review_latest_target_app(project_id=project_id)

        self.assertIsNone(response.to_dict()["error"])
        self.assertIn(
            {"path": "app/main.py"},
            response.to_dict()["data"]["files"],
        )
        self.assertIn("cloudbuild.yaml", [item["path"] for item in latest_response.to_dict()["data"]["files"]])
        self.assertTrue(review_response.to_dict()["data"]["passed"])

    async def test_optional_delivery_addons_return_demo_payloads(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="support desk app",
        )
        project_id = create_response.to_dict()["data"]["id"]
        await facade.generate_requirements(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="requirements",
            decision="approved",
        )
        await facade.generate_basic_design(project_id=project_id)
        await facade.decide_approval(
            project_id=project_id,
            gate="design",
            decision="approved",
        )
        await facade.propose_architecture(
            project_id=project_id,
            target_project_id="demo-gcp-project",
        )
        await facade.generate_target_app(
            project_id=project_id,
            app_name="Support Desk API",
        )

        image_response = await facade.capture_image_requirement(
            project_id=project_id,
            file_name="sketch.png",
            description="Cloud Run connected to Firestore",
        )
        terraform_response = await facade.terraform_preview(project_id=project_id)
        github_response = await facade.github_demo_flow(
            project_id=project_id,
            repo_url="https://github.com/sh0g0-ikeda/CastorOps",
        )
        guidance_response = await facade.apply_failure_guidance(
            project_id=project_id,
            error_text="Cloud Run deploy failed: permission denied",
        )
        security_loop_response = await facade.evaluate_security_loop(project_id=project_id, rounds=2)

        self.assertEqual(image_response.to_dict()["data"]["mode"], "demo_image_artifact")
        self.assertEqual(terraform_response.to_dict()["data"]["mode"], "preview_only")
        self.assertTrue(github_response.to_dict()["data"]["draft_pr"]["created"])
        self.assertIn("IAM", guidance_response.to_dict()["data"]["likely_cause"])
        self.assertEqual(security_loop_response.to_dict()["data"]["stopped_reason"], "no_critical_findings")

    async def test_ops_overview_returns_dashboard_sections(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]

        response = await facade.ops_overview(project_id=project_id)
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertIn("system_overview", body["data"])
        self.assertIn("recommended_next_actions", body["data"])

    async def test_agent_workflow_records_timeline_event(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]

        await facade.generate_requirements(project_id=project_id)
        response = await facade.timeline(project_id=project_id)
        ops_response = await facade.ops_overview(project_id=project_id)

        self.assertEqual(response.to_dict()["data"][0]["action"], "generated_requirements")
        self.assertEqual(
            ops_response.to_dict()["data"]["agent_actions"][0]["action"],
            "generated_requirements",
        )

    async def test_decide_approval_advances_phase_and_records_history(self) -> None:
        facade = make_facade()
        create_response = await facade.create_project(
            name="Support Desk",
            idea="問い合わせ管理アプリ",
        )
        project_id = create_response.to_dict()["data"]["id"]
        await facade.generate_requirements(project_id=project_id)

        approval_response = await facade.decide_approval(
            project_id=project_id,
            gate="requirements",
            decision="approved",
            rationale="デモ用に承認",
        )
        approvals_response = await facade.list_approvals(project_id=project_id)
        project_response = await facade.get_project(project_id=project_id)

        self.assertIsNone(approval_response.to_dict()["error"])
        self.assertEqual(project_response.to_dict()["data"]["phase"], "REQUIREMENT_APPROVED")
        self.assertEqual(approvals_response.to_dict()["data"][0]["decided_by"], "demo-user")


if __name__ == "__main__":
    unittest.main()
