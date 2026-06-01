import json
import unittest

from app.bootstrap import build_demo_facade
from app.core.errors import ValidationAppError
from app.web.demo_server import DemoWebApp


class DemoWebServerTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_returns_ok(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        status, content_type, body = await app.handle(method="GET", raw_path="/api/health")
        payload = json.loads(body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        self.assertEqual(payload["data"], {"status": "ok"})

    async def test_project_pipeline_routes_reach_facade(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        _, _, create_body = await app.handle(
            method="POST",
            raw_path="/api/projects",
            body=json.dumps({"name": "Support Desk", "idea": "support desk app"}).encode("utf-8"),
        )
        project_id = json.loads(create_body.decode("utf-8"))["data"]["id"]

        status, _, requirements_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/requirements",
            body=b"{}",
        )
        payload = json.loads(requirements_body.decode("utf-8"))

        self.assertEqual(status, 200)
        self.assertEqual(payload["data"]["run_status"], "SUCCEEDED")

    async def test_gui_edit_routes_support_preview_and_confirmed_delete(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        _, _, create_body = await app.handle(
            method="POST",
            raw_path="/api/projects",
            body=json.dumps({"name": "Support Desk", "idea": "support desk app"}).encode("utf-8"),
        )
        project_id = json.loads(create_body.decode("utf-8"))["data"]["id"]
        for action, body in (
            ("requirements", {}),
            ("approve", {"gate": "requirements", "decision": "approved"}),
            ("designs", {}),
            ("approve", {"gate": "design", "decision": "approved"}),
            ("architecture", {"target_project_id": "demo-gcp-project"}),
        ):
            await app.handle(
                method="POST",
                raw_path=f"/api/projects/{project_id}/{action}",
                body=json.dumps(body).encode("utf-8"),
            )

        preview_status, _, preview_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/architecture/preview-node",
            body=json.dumps({"node_id": "backend", "parameter_patch": {"memory": "1Gi"}}).encode("utf-8"),
        )
        delete_status, _, delete_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/architecture/delete-node",
            body=json.dumps(
                {
                    "node_id": "firestore",
                    "confirmed": True,
                    "change_reason": "Remove store in demo",
                }
            ).encode("utf-8"),
        )
        chat_status, _, chat_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/architecture/chat-revise",
            body=json.dumps({"message": "backendを公開し、メモリを1Giにしてください"}).encode("utf-8"),
        )
        add_node_status, _, add_node_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/architecture/add-node",
            body=json.dumps(
                {
                    "node_id": "secrets",
                    "node_type": "secret_manager",
                    "name": "Runtime Secrets",
                    "parameters": {"secret_names": ["GEMINI_API_KEY"]},
                }
            ).encode("utf-8"),
        )
        add_edge_status, _, add_edge_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/architecture/add-edge",
            body=json.dumps(
                {
                    "edge_id": "backend-secrets",
                    "from_node": "backend",
                    "to_node": "secrets",
                    "edge_type": "secret_read",
                    "description": "Backend reads runtime secrets.",
                }
            ).encode("utf-8"),
        )
        delete_edge_status, _, delete_edge_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/architecture/delete-edge",
            body=json.dumps({"edge_id": "backend-secrets"}).encode("utf-8"),
        )

        self.assertEqual(preview_status, 200)
        self.assertTrue(json.loads(preview_body.decode("utf-8"))["data"]["requires_reapply"])
        self.assertEqual(delete_status, 200)
        self.assertEqual(json.loads(delete_body.decode("utf-8"))["data"]["version"], 2)
        self.assertEqual(chat_status, 200)
        self.assertEqual(json.loads(chat_body.decode("utf-8"))["data"]["changes"]["memory"], "1Gi")
        self.assertTrue(json.loads(chat_body.decode("utf-8"))["data"]["changes"]["allow_unauthenticated"])
        self.assertEqual(add_node_status, 200)
        self.assertEqual(json.loads(add_node_body.decode("utf-8"))["data"]["node_id"], "secrets")
        self.assertEqual(add_edge_status, 200)
        self.assertEqual(json.loads(add_edge_body.decode("utf-8"))["data"]["edge_id"], "backend-secrets")
        self.assertEqual(delete_edge_status, 200)
        self.assertEqual(json.loads(delete_edge_body.decode("utf-8"))["data"]["edge_id"], "backend-secrets")

    async def test_optional_delivery_routes_return_demo_payloads(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        _, _, create_body = await app.handle(
            method="POST",
            raw_path="/api/projects",
            body=json.dumps({"name": "Support Desk", "idea": "support desk app"}).encode("utf-8"),
        )
        project_id = json.loads(create_body.decode("utf-8"))["data"]["id"]
        for action, body in (
            ("requirements", {}),
            ("approve", {"gate": "requirements", "decision": "approved"}),
            ("designs", {}),
            ("approve", {"gate": "design", "decision": "approved"}),
            ("architecture", {"target_project_id": "demo-gcp-project"}),
            ("target-app", {"fields": ["subject", "message"], "env_vars": ["GEMINI_API_KEY"]}),
        ):
            await app.handle(
                method="POST",
                raw_path=f"/api/projects/{project_id}/{action}",
                body=json.dumps(body).encode("utf-8"),
            )

        terraform_status, _, terraform_body = await app.handle(
            method="GET",
            raw_path=f"/api/projects/{project_id}/terraform/preview",
        )
        github_status, _, github_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/github/demo",
            body=json.dumps({"repo_url": "https://github.com/sh0g0-ikeda/CastorOps"}).encode("utf-8"),
        )
        review_status, _, review_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/target-app/review",
            body=b"{}",
        )
        image_status, _, image_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/requirements/image-artifact",
            body=json.dumps(
                {
                    "file_name": "sketch.png",
                    "description": "Cloud Run connected to Firestore",
                }
            ).encode("utf-8"),
        )
        adapter_status, _, adapter_body = await app.handle(
            method="GET",
            raw_path=f"/api/projects/{project_id}/adapters",
        )
        brief_status, _, brief_body = await app.handle(
            method="GET",
            raw_path=f"/api/projects/{project_id}/submission/brief",
        )
        cloud_run_status, _, cloud_run_body = await app.handle(
            method="GET",
            raw_path=f"/api/projects/{project_id}/runtime/cloud-run",
        )
        failure_demo_status, _, failure_demo_body = await app.handle(
            method="POST",
            raw_path=f"/api/projects/{project_id}/apply/failure-demo",
            body=json.dumps({"error_text": "Cloud Run deploy failed: permission denied"}).encode("utf-8"),
        )

        self.assertEqual(terraform_status, 200)
        self.assertEqual(json.loads(terraform_body.decode("utf-8"))["data"]["mode"], "preview_only")
        self.assertEqual(github_status, 200)
        self.assertTrue(json.loads(github_body.decode("utf-8"))["data"]["draft_pr"]["created"])
        self.assertEqual(review_status, 200)
        self.assertTrue(json.loads(review_body.decode("utf-8"))["data"]["passed"])
        self.assertEqual(image_status, 200)
        self.assertEqual(json.loads(image_body.decode("utf-8"))["data"]["mode"], "demo_image_artifact")
        self.assertEqual(adapter_status, 200)
        self.assertEqual(json.loads(adapter_body.decode("utf-8"))["data"]["cloud_build_apply"]["mode"], "demo_adapter")
        self.assertEqual(brief_status, 200)
        self.assertEqual(json.loads(brief_body.decode("utf-8"))["data"]["product"], "CastorOps")
        self.assertEqual(cloud_run_status, 200)
        self.assertEqual(json.loads(cloud_run_body.decode("utf-8"))["data"]["runtime_product"], "Cloud Run")
        self.assertEqual(failure_demo_status, 200)
        self.assertTrue(json.loads(failure_demo_body.decode("utf-8"))["data"]["recovery_demo"]["kept_previous_revision"])

    async def test_judging_demo_route_rebuilds_complete_workspace(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        status, _, body = await app.handle(
            method="POST",
            raw_path="/api/demo/run",
            body=json.dumps(
                {
                    "name": "",
                    "idea": " ",
                    "target_project_id": "",
                    "repo_url": "",
                }
            ).encode("utf-8"),
        )
        payload = json.loads(body.decode("utf-8"))["data"]

        self.assertEqual(status, 200)
        self.assertEqual(payload["project"]["phase"], "DEPLOYED")
        self.assertEqual(payload["readiness"]["cloud_run_evidence"]["runtime_product"], "Cloud Run")
        self.assertEqual(payload["readiness"]["adapter_inventory"]["cloud_build_apply"]["mode"], "demo_adapter")
        self.assertTrue(payload["target_app"]["files"])
        self.assertTrue(payload["timeline"])
        self.assertTrue(payload["optional_delivery"]["github_demo"]["draft_pr"]["created"])

    async def test_invalid_json_returns_validation_error(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        with self.assertRaisesRegex(ValidationAppError, "request body must be valid JSON"):
            await app.handle(method="POST", raw_path="/api/projects", body=b"{")


if __name__ == "__main__":
    unittest.main()
