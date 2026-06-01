import os
import unittest

from app.agents.gemini import GeminiApiConfig
from app.agents.gemini import GeminiJsonClient
from app.bootstrap import build_demo_facade


class GeminiProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_gemini_json_client_sends_api_key_and_parses_structured_output(self) -> None:
        captured = {}

        def fake_post_json(url, body, headers, timeout_seconds):
            captured["url"] = url
            captured["body"] = body
            captured["headers"] = headers
            captured["timeout_seconds"] = timeout_seconds
            return {
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": '{"requirements_doc_md":"# Requirements","follow_up_questions":[],"unresolved_items":[]}'
                                }
                            ]
                        }
                    }
                ]
            }

        client = GeminiJsonClient(
            GeminiApiConfig(api_key="test-key", model="gemini-test", endpoint="https://example.test/v1beta"),
            http_post_json=fake_post_json,
        )
        result = await client.generate_json(
            prompt="Generate requirements.",
            response_schema={
                "type": "object",
                "properties": {"requirements_doc_md": {"type": "string"}},
                "required": ["requirements_doc_md"],
            },
        )

        self.assertEqual(result["requirements_doc_md"], "# Requirements")
        self.assertEqual(captured["url"], "https://example.test/v1beta/models/gemini-test:generateContent")
        self.assertEqual(captured["headers"]["x-goog-api-key"], "test-key")
        self.assertEqual(captured["body"]["generationConfig"]["responseMimeType"], "application/json")
        self.assertIn("responseJsonSchema", captured["body"]["generationConfig"])

    async def test_bootstrap_can_switch_adapter_inventory_to_gemini_mode(self) -> None:
        original_provider = os.environ.get("CASTOROPS_AGENT_PROVIDER")
        original_key = os.environ.get("GEMINI_API_KEY")
        try:
            os.environ["CASTOROPS_AGENT_PROVIDER"] = "gemini"
            os.environ["GEMINI_API_KEY"] = "test-key"
            facade = build_demo_facade()
            create_response = await facade.create_project(name="Gemini Mode", idea="support desk app")
            project_id = create_response.to_dict()["data"]["id"]

            response = await facade.adapter_inventory(project_id=project_id)
            payload = response.to_dict()["data"]

            self.assertEqual(payload["ai_generation"]["mode"], "live_api_key")
            self.assertEqual(payload["requirements_agent"]["mode"], "gemini_api")
            self.assertEqual(payload["planner_agent"]["mode"], "gemini_api")
        finally:
            if original_provider is None:
                os.environ.pop("CASTOROPS_AGENT_PROVIDER", None)
            else:
                os.environ["CASTOROPS_AGENT_PROVIDER"] = original_provider
            if original_key is None:
                os.environ.pop("GEMINI_API_KEY", None)
            else:
                os.environ["GEMINI_API_KEY"] = original_key


if __name__ == "__main__":
    unittest.main()
