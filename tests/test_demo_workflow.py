import unittest

from app.workflows.demo import build_full_demo_response
from app.workflows.demo import build_requirement_demo_response


class DemoWorkflowTests(unittest.IsolatedAsyncioTestCase):
    async def test_requirement_demo_response_uses_api_envelope(self) -> None:
        response = await build_requirement_demo_response(
            idea="support desk app",
            owner_uid="local-user",
        )
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertEqual(body["data"]["run_status"], "SUCCEEDED")
        self.assertEqual(body["data"]["document_version"], 1)
        self.assertEqual(body["data"]["unresolved_items"], ["Authentication policy"])

    async def test_full_demo_response_runs_end_to_end(self) -> None:
        response = await build_full_demo_response(
            idea="support desk app",
            owner_uid="local-user",
            target_project_id="demo-gcp-project",
        )
        body = response.to_dict()

        self.assertIsNone(body["error"])
        self.assertIsNotNone(body["data"]["requirements_document_id"])
        self.assertIsNotNone(body["data"]["basic_design_document_id"])
        self.assertIsNotNone(body["data"]["architecture_id"])
        self.assertEqual(body["data"]["security_findings"], 1)
        self.assertEqual(body["data"]["security_critical_count"], 0)


if __name__ == "__main__":
    unittest.main()
