"""Gemini API-backed generators for CastorOps agents."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from app.agents.architect import ArchitectGenerationRequest
from app.agents.gcp_planner import GcpPlannerRequest
from app.agents.requirement import RequirementGenerationRequest
from app.agents.security import SecurityEvaluationRequest
from app.core.errors import ValidationAppError
from app.documents.models import DocumentType


DEFAULT_GEMINI_MODEL = "gemini-3-flash-preview"
DEFAULT_GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta"


@dataclass(frozen=True)
class GeminiApiConfig:
    """Configuration for direct Gemini API calls."""

    api_key: str
    model: str = DEFAULT_GEMINI_MODEL
    endpoint: str = DEFAULT_GEMINI_ENDPOINT
    timeout_seconds: float = 45.0

    def __post_init__(self) -> None:
        if not self.api_key.strip():
            raise ValidationAppError("GEMINI_API_KEY is required when CASTOROPS_AGENT_PROVIDER=gemini")
        if not self.model.strip():
            raise ValidationAppError("GEMINI_MODEL must be a non-empty string")
        if not self.endpoint.strip():
            raise ValidationAppError("GEMINI_API_ENDPOINT must be a non-empty string")


HttpPostJson = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]


class GeminiJsonClient:
    """Small dependency-free Gemini REST client for structured JSON outputs."""

    def __init__(self, config: GeminiApiConfig, http_post_json: HttpPostJson | None = None) -> None:
        self._config = config
        self._http_post_json = http_post_json or _default_http_post_json

    async def generate_json(
        self,
        *,
        prompt: str,
        response_schema: dict[str, Any],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._generate_json_sync,
            prompt,
            response_schema,
        )

    def _generate_json_sync(self, prompt: str, response_schema: dict[str, Any]) -> dict[str, Any]:
        url = (
            f"{self._config.endpoint.rstrip('/')}/models/"
            f"{self._config.model}:generateContent"
        )
        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": prompt}],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
                "responseMimeType": "application/json",
                "responseJsonSchema": response_schema,
            },
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._config.api_key,
        }
        payload = self._http_post_json(url, body, headers, self._config.timeout_seconds)

        text = _extract_text(payload)
        try:
            output = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationAppError(
                "Gemini response text was not valid JSON",
                {"text": _truncate(text, 1200)},
            ) from exc
        if not isinstance(output, dict):
            raise ValidationAppError("Gemini structured output must be an object")
        return output


def _default_http_post_json(
    url: str,
    body: dict[str, Any],
    headers: dict[str, str],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url=url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        error_body = exc.read().decode("utf-8", errors="replace")
        raise ValidationAppError(
            "Gemini API request failed",
            {"status": exc.code, "body": _truncate(error_body, 1200)},
        ) from exc
    except urllib.error.URLError as exc:
        raise ValidationAppError(
            "Gemini API request could not be completed",
            {"reason": str(exc.reason)},
        ) from exc
    except json.JSONDecodeError as exc:
        raise ValidationAppError("Gemini API returned invalid JSON") from exc
    if not isinstance(payload, dict):
        raise ValidationAppError("Gemini API response must be an object")
    return payload


class GeminiRequirementGenerator:
    """Generate requirements and follow-up questions with Gemini API."""

    def __init__(self, client: GeminiJsonClient) -> None:
        self._client = client

    async def generate(self, request: RequirementGenerationRequest) -> dict[str, Any]:
        return await self._client.generate_json(
            prompt="\n".join(
                [
                    "You are the CastorOps requirement agent.",
                    "Create a concise but useful Markdown requirements document for a GCP/Cloud Run app.",
                    "Also identify at most three follow-up questions and unresolved items.",
                    "Keep the output suitable for a hackathon demo and implementation review.",
                    "",
                    "Project idea:",
                    request.idea,
                    "",
                    "Form responses JSON:",
                    json.dumps(dict(request.form_responses), ensure_ascii=False, indent=2),
                    "",
                    "Follow-up answers JSON:",
                    json.dumps(dict(request.follow_up_answers), ensure_ascii=False, indent=2),
                ]
            ),
            response_schema=_requirement_schema(),
        )


class GeminiArchitectGenerator:
    """Generate design documents with Gemini API."""

    def __init__(self, client: GeminiJsonClient) -> None:
        self._client = client

    async def generate(self, request: ArchitectGenerationRequest) -> dict[str, Any]:
        return await self._client.generate_json(
            prompt="\n".join(
                [
                    "You are the CastorOps architect agent.",
                    f"Generate the {request.doc_type.value} document in Markdown.",
                    "Base the design on the approved requirements. Be concrete about Cloud Run, APIs, data, operations, and risks when relevant.",
                    "Return references to the requirements or relevant generated documents.",
                    "",
                    "Approved requirements Markdown:",
                    request.requirements_doc_md,
                ]
            ),
            response_schema=_architect_schema(),
        )


class GeminiGcpPlannerGenerator:
    """Generate GCP architecture proposals with Gemini API."""

    def __init__(self, client: GeminiJsonClient) -> None:
        self._client = client

    async def generate(self, request: GcpPlannerRequest) -> dict[str, Any]:
        return await self._client.generate_json(
            prompt="\n".join(
                [
                    "You are the CastorOps GCP planner agent.",
                    "Generate a minimal valid GCP architecture for the app. The architecture_spec must pass the CastorOps schema.",
                    "Use Cloud Run for the backend and Firestore for persisted app/project state unless the documents strongly justify otherwise.",
                    "Allowed node types include cloud_run, firestore, secret_manager, cloud_storage, cloud_logging, cloud_monitoring, artifact_registry, iam_sa, and external.",
                    "Use low-cost defaults and private-by-default Cloud Run unless the requirements say public access is needed.",
                    "",
                    f"Target GCP project id: {request.target_project_id}",
                    "",
                    "Requirements Markdown:",
                    request.requirements_doc_md,
                    "",
                    "Basic design Markdown:",
                    request.basic_design_md,
                ]
            ),
            response_schema=_planner_schema(),
        )


class GeminiSecurityEvaluator:
    """Evaluate architecture security with Gemini API."""

    def __init__(self, client: GeminiJsonClient) -> None:
        self._client = client

    async def evaluate(self, request: SecurityEvaluationRequest) -> dict[str, Any]:
        return await self._client.generate_json(
            prompt="\n".join(
                [
                    "You are the CastorOps security agent.",
                    "Evaluate the architecture and return zero or more actionable security findings.",
                    "Prefer practical Cloud Run, IAM, Secret Manager, logging, and public access findings.",
                    "Severity must be one of info, warning, critical.",
                    "",
                    f"Target type: {request.target_type}",
                    f"Target id: {request.target_id}",
                    "",
                    "Architecture spec JSON:",
                    json.dumps(request.architecture_spec, ensure_ascii=False, indent=2),
                ]
            ),
            response_schema=_security_schema(),
        )


def _extract_text(payload: Mapping[str, Any]) -> str:
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValidationAppError("Gemini API response did not include candidates", {"response": dict(payload)})
    candidate = candidates[0]
    if not isinstance(candidate, Mapping):
        raise ValidationAppError("Gemini candidate must be an object")
    content = candidate.get("content")
    if not isinstance(content, Mapping):
        raise ValidationAppError("Gemini candidate content must be an object")
    parts = content.get("parts")
    if not isinstance(parts, list) or not parts:
        raise ValidationAppError("Gemini candidate content did not include parts")
    texts = []
    for part in parts:
        if isinstance(part, Mapping) and isinstance(part.get("text"), str):
            texts.append(part["text"])
    text = "".join(texts).strip()
    if not text:
        raise ValidationAppError("Gemini response text was empty")
    return text


def _requirement_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "follow_up_questions": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
            "requirements_doc_md": {"type": "string"},
            "unresolved_items": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["follow_up_questions", "requirements_doc_md", "unresolved_items"],
        "additionalProperties": False,
    }


def _architect_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "doc_md": {"type": "string"},
            "references": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["doc_md", "references"],
        "additionalProperties": False,
    }


def _planner_schema() -> dict[str, Any]:
    node_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "type": {"type": "string"},
            "name": {"type": "string"},
            "parameters": {"type": "object", "additionalProperties": True},
            "rationale": {"type": "string"},
            "cost_band": {"type": "string", "enum": ["low", "medium", "high"]},
            "security_notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["id", "type", "name", "parameters", "rationale", "cost_band"],
        "additionalProperties": False,
    }
    edge_schema = {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "from_node": {"type": "string"},
            "to_node": {"type": "string"},
            "type": {"type": "string"},
            "description": {"type": "string"},
        },
        "required": ["id", "from_node", "to_node", "type", "description"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "architecture_spec": {
                "type": "object",
                "properties": {
                    "project_id": {"type": "string"},
                    "region": {"type": "string"},
                    "nodes": {"type": "array", "items": node_schema, "minItems": 1},
                    "edges": {"type": "array", "items": edge_schema},
                },
                "required": ["project_id", "region", "nodes", "edges"],
                "additionalProperties": False,
            },
            "rationale_md": {"type": "string"},
            "cloudbuild_yaml": {"type": "string"},
            "gcloud_commands": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        },
        "required": ["architecture_spec", "rationale_md", "cloudbuild_yaml", "gcloud_commands"],
        "additionalProperties": False,
    }


def _security_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "findings": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "severity": {"type": "string", "enum": ["info", "warning", "critical"]},
                        "category": {"type": "string"},
                        "message": {"type": "string"},
                        "suggestion": {"type": "string"},
                    },
                    "required": ["severity", "category", "message", "suggestion"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["findings"],
        "additionalProperties": False,
    }


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit] + "...(truncated)"
