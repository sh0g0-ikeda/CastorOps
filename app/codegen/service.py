"""Template-based target application generator."""

from __future__ import annotations

from typing import Any

from app.codegen.models import CodeGenerationResult
from app.codegen.models import GeneratedFile
from app.codegen.repository import CodeGenerationRepository
from app.core.errors import ValidationAppError


class TargetAppCodeService:
    """Generate a small inquiry API package from the approved design context."""

    def __init__(self, repository: CodeGenerationRepository) -> None:
        self._repository = repository

    async def generate_inquiry_api(
        self,
        *,
        project_id: str,
        app_name: str,
        collection_name: str = "inquiries",
        fields: tuple[str, ...] = ("subject", "message", "email"),
    ) -> CodeGenerationResult:
        normalized_app_name = _safe_app_name(app_name)
        normalized_collection = _safe_identifier(collection_name, "collection_name")
        normalized_fields = tuple(_safe_identifier(field, "field") for field in fields)
        files = _render_files(
            app_name=normalized_app_name,
            collection_name=normalized_collection,
            fields=normalized_fields,
        )
        result = CodeGenerationResult.create(
            project_id=project_id,
            app_name=normalized_app_name,
            files=files,
            notes_md=(
                "# Generation Notes\n\n"
                "- Generated a small inquiry API template for Cloud Run.\n"
                "- The package includes tests, a Dockerfile, and a Cloud Build pipeline.\n"
            ),
        )
        await self._repository.create(result)
        return result

    async def latest_payload(self, project_id: str) -> dict[str, Any]:
        result = await self._repository.latest(project_id)
        return _result_payload(result)


def _render_files(
    *,
    app_name: str,
    collection_name: str,
    fields: tuple[str, ...],
) -> tuple[GeneratedFile, ...]:
    field_defaults = ", ".join(f'"{field}": ""' for field in fields)
    required_fields = ", ".join(f'"{field}"' for field in fields)
    return (
        GeneratedFile(
            path="README.md",
            content=f"# {app_name}\n\nA Cloud Run-ready inquiry management API.\n",
        ),
        GeneratedFile(
            path="requirements.txt",
            content="fastapi==0.115.6\nuvicorn[standard]==0.32.1\n",
        ),
        GeneratedFile(
            path="Dockerfile",
            content=(
                "FROM python:3.12-slim\n"
                "WORKDIR /app\n"
                "COPY requirements.txt .\n"
                "RUN pip install --no-cache-dir -r requirements.txt\n"
                "COPY app ./app\n"
                'CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]\n'
            ),
        ),
        GeneratedFile(
            path="app/main.py",
            content=(
                "from fastapi import FastAPI, HTTPException\n"
                "from pydantic import BaseModel\n\n"
                f'app = FastAPI(title="{app_name}")\n'
                f'COLLECTION_NAME = "{collection_name}"\n'
                f"REQUIRED_FIELDS = {{{required_fields}}}\n"
                "STORE = []\n\n"
                "class Inquiry(BaseModel):\n"
                "    payload: dict[str, str]\n\n"
                '@app.get("/healthz")\n'
                "def healthz() -> dict[str, str]:\n"
                '    return {"status": "ok"}\n\n'
                '@app.post("/inquiries")\n'
                "def create_inquiry(inquiry: Inquiry) -> dict[str, object]:\n"
                "    missing = REQUIRED_FIELDS - set(inquiry.payload)\n"
                "    if missing:\n"
                '        raise HTTPException(status_code=422, detail={"missing": sorted(missing)})\n'
                "    record = {\n"
                f"        {field_defaults},\n"
                "        **inquiry.payload,\n"
                '        "collection": COLLECTION_NAME,\n'
                "    }\n"
                "    STORE.append(record)\n"
                '    return {"id": len(STORE), "record": record}\n\n'
                '@app.get("/inquiries")\n'
                "def list_inquiries() -> dict[str, object]:\n"
                '    return {"items": STORE}\n'
            ),
        ),
        GeneratedFile(
            path="tests/test_health.py",
            content=(
                "from fastapi.testclient import TestClient\n"
                "from app.main import app\n\n"
                "def test_healthz() -> None:\n"
                "    response = TestClient(app).get('/healthz')\n"
                "    assert response.status_code == 200\n"
            ),
        ),
        GeneratedFile(
            path="cloudbuild.yaml",
            content=(
                "steps:\n"
                "  - id: test\n"
                "    name: python:3.12-slim\n"
                "    entrypoint: bash\n"
                "    args: ['-c', 'pip install -r requirements.txt pytest && pytest']\n"
                "  - id: build\n"
                "    name: gcr.io/cloud-builders/docker\n"
                "    args: ['build', '-t', '$_IMAGE', '.']\n"
                "  - id: push\n"
                "    name: gcr.io/cloud-builders/docker\n"
                "    args: ['push', '$_IMAGE']\n"
                "  - id: deploy\n"
                "    name: gcr.io/google.com/cloudsdktool/cloud-sdk\n"
                "    entrypoint: gcloud\n"
                "    args:\n"
                "      - run\n"
                "      - deploy\n"
                "      - $_SERVICE\n"
                "      - --image=$_IMAGE\n"
                "      - --region=$_REGION\n"
                "      - --platform=managed\n"
                "      - --allow-unauthenticated\n"
                "      - --quiet\n"
                "images:\n"
                "  - $_IMAGE\n"
            ),
        ),
    )


def _safe_app_name(value: str) -> str:
    if not value.strip():
        raise ValidationAppError("app_name must not be empty")
    return value.strip()[:80]


def _safe_identifier(value: str, field_name: str) -> str:
    if not value.strip():
        raise ValidationAppError(f"{field_name} must not be empty")
    normalized = value.strip().replace("-", "_")
    if not all(ch.islower() or ch.isdigit() or ch == "_" for ch in normalized):
        raise ValidationAppError(f"{field_name} must use lowercase letters, digits, or _")
    return normalized


def _result_payload(result: CodeGenerationResult) -> dict[str, Any]:
    return {
        "id": result.id,
        "project_id": result.project_id,
        "app_name": result.app_name,
        "files": [
            {"path": generated_file.path, "content": generated_file.content}
            for generated_file in result.files
        ],
        "notes_md": result.notes_md,
        "created_at": result.created_at.isoformat(),
    }
