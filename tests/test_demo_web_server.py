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
            body=json.dumps({"message": "use 1Gi memory"}).encode("utf-8"),
        )

        self.assertEqual(preview_status, 200)
        self.assertTrue(json.loads(preview_body.decode("utf-8"))["data"]["requires_reapply"])
        self.assertEqual(delete_status, 200)
        self.assertEqual(json.loads(delete_body.decode("utf-8"))["data"]["version"], 2)
        self.assertEqual(chat_status, 200)
        self.assertEqual(json.loads(chat_body.decode("utf-8"))["data"]["changes"]["memory"], "1Gi")

    async def test_invalid_json_returns_validation_error(self) -> None:
        app = DemoWebApp(build_demo_facade(), target_project_id="demo-gcp-project")

        with self.assertRaisesRegex(ValidationAppError, "request body must be valid JSON"):
            await app.handle(method="POST", raw_path="/api/projects", body=b"{")


if __name__ == "__main__":
    unittest.main()
