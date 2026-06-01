import unittest

from app.codegen.repository import InMemoryCodeGenerationRepository
from app.codegen.service import TargetAppCodeService
from app.core.errors import ValidationAppError


class TargetAppCodeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_generate_inquiry_api_creates_expected_files(self) -> None:
        service = TargetAppCodeService(InMemoryCodeGenerationRepository())

        result = await service.generate_inquiry_api(
            project_id="project-1",
            app_name="Support Desk API",
            collection_name="support_tickets",
            fields=("subject", "message"),
            env_vars=("GEMINI_API_KEY",),
        )
        paths = {generated_file.path for generated_file in result.files}
        payload = await service.latest_payload("project-1")
        cloudbuild_yaml = next(
            generated_file.content
            for generated_file in result.files
            if generated_file.path == "cloudbuild.yaml"
        )
        dockerfile = next(
            generated_file.content
            for generated_file in result.files
            if generated_file.path == "Dockerfile"
        )

        self.assertIn("app/main.py", paths)
        self.assertIn("Dockerfile", paths)
        self.assertIn("cloudbuild.yaml", paths)
        self.assertIn("id: deploy", cloudbuild_yaml)
        self.assertIn("gcloud", cloudbuild_yaml)
        self.assertIn("${PORT:-8080}", dockerfile)
        self.assertEqual(payload["app_name"], "Support Desk API")
        self.assertIn("GEMINI_API_KEY", payload["files"][0]["content"])
        review = await service.review_latest("project-1")
        self.assertTrue(review["passed"])

    async def test_generate_inquiry_api_rejects_unsafe_field_name(self) -> None:
        service = TargetAppCodeService(InMemoryCodeGenerationRepository())

        with self.assertRaises(ValidationAppError):
            await service.generate_inquiry_api(
                project_id="project-1",
                app_name="Support Desk API",
                fields=("Subject",),
            )


if __name__ == "__main__":
    unittest.main()
