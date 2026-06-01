"""Dependency-free HTTP server for the CastorOps local demo UI."""

from __future__ import annotations

import asyncio
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs
from urllib.parse import urlparse

from app.api.facade import CastorOpsApiFacade
from app.api.responses import ApiResponse
from app.api.responses import ResponseMeta
from app.core.errors import ValidationAppError


STATIC_DIR = Path(__file__).resolve().parent / "static"


class DemoWebApp:
    """Route local HTTP requests to the framework-independent API facade."""

    def __init__(self, facade: CastorOpsApiFacade, *, target_project_id: str) -> None:
        self._facade = facade
        self._target_project_id = target_project_id

    async def handle(
        self,
        *,
        method: str,
        raw_path: str,
        body: bytes = b"",
    ) -> tuple[int, str, bytes]:
        parsed_url = urlparse(raw_path)
        path_parts = tuple(part for part in parsed_url.path.strip("/").split("/") if part)
        query = parse_qs(parsed_url.query)
        if method == "GET" and not path_parts:
            return _static_response(STATIC_DIR / "index.html", "text/html; charset=utf-8")
        if method == "GET" and path_parts[:1] == ("assets",):
            return _asset_response(path_parts)
        if path_parts[:1] != ("api",):
            return _json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "route not found")

        request_body = _parse_json_body(body)
        if method == "GET" and path_parts == ("api", "health"):
            return _api_response(ApiResponse.ok({"status": "ok"}))
        if method == "POST" and path_parts == ("api", "projects"):
            payload = _require_object(request_body)
            response = await self._facade.create_project(
                name=_optional_string(payload, "name", "Local Demo"),
                idea=_required_string(payload, "idea"),
            )
            return _api_response(response)
        if len(path_parts) >= 3 and path_parts[:2] == ("api", "projects"):
            return await self._handle_project_route(
                method=method,
                path_parts=path_parts,
                query=query,
                request_body=request_body,
            )
        return _json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "route not found")

    async def _handle_project_route(
        self,
        *,
        method: str,
        path_parts: tuple[str, ...],
        query: dict[str, list[str]],
        request_body: Any,
    ) -> tuple[int, str, bytes]:
        project_id = path_parts[2]
        action = path_parts[3:] if len(path_parts) > 3 else ()
        payload = _require_object(request_body) if method == "POST" else {}
        if method == "GET" and not action:
            return _api_response(await self._facade.get_project(project_id=project_id))
        if method == "POST" and action == ("follow-up",):
            return _api_response(
                await self._facade.generate_follow_up_questions(
                    project_id=project_id,
                    form_responses=_optional_object(payload, "form_responses"),
                )
            )
        if method == "POST" and action == ("requirements",):
            return _api_response(await self._facade.generate_requirements(project_id=project_id))
        if method == "POST" and action == ("requirements", "image-artifact"):
            return _api_response(
                await self._facade.capture_image_requirement(
                    project_id=project_id,
                    file_name=_required_string(payload, "file_name"),
                    description=_required_string(payload, "description"),
                )
            )
        if method == "POST" and action == ("approve",):
            return _api_response(
                await self._facade.decide_approval(
                    project_id=project_id,
                    gate=_required_string(payload, "gate"),
                    decision=_required_string(payload, "decision"),
                    rationale=_optional_string(payload, "rationale", ""),
                    snapshot=_optional_object(payload, "snapshot"),
                )
            )
        if method == "POST" and action == ("designs",):
            return _api_response(await self._facade.generate_design_set(project_id=project_id))
        if method == "GET" and action == ("documents",):
            return _api_response(await self._facade.latest_documents(project_id=project_id))
        if method == "POST" and action == ("architecture",):
            return _api_response(
                await self._facade.propose_architecture(
                    project_id=project_id,
                    target_project_id=_optional_string(payload, "target_project_id", self._target_project_id),
                )
            )
        if method == "GET" and action == ("architecture", "latest"):
            return _api_response(await self._facade.latest_architecture(project_id=project_id))
        if method == "POST" and action == ("architecture", "preview-node"):
            return _api_response(
                await self._facade.preview_architecture_node_update(
                    project_id=project_id,
                    node_id=_required_string(payload, "node_id"),
                    parameter_patch=_optional_object(payload, "parameter_patch"),
                )
            )
        if method == "POST" and action == ("architecture", "update-node"):
            return _api_response(
                await self._facade.update_architecture_node(
                    project_id=project_id,
                    node_id=_required_string(payload, "node_id"),
                    parameter_patch=_optional_object(payload, "parameter_patch"),
                    change_reason=_optional_string(payload, "change_reason", "Updated from demo UI"),
                )
            )
        if method == "POST" and action == ("architecture", "chat-revise"):
            return _api_response(
                await self._facade.revise_architecture_from_chat(
                    project_id=project_id,
                    message=_required_string(payload, "message"),
                )
            )
        if method == "POST" and action == ("architecture", "delete-node"):
            return _api_response(
                await self._facade.delete_architecture_node(
                    project_id=project_id,
                    node_id=_required_string(payload, "node_id"),
                    confirmed=_optional_bool(payload, "confirmed", False),
                    change_reason=_optional_string(payload, "change_reason", "Deleted from demo UI"),
                )
            )
        if method == "POST" and action == ("architecture", "add-node"):
            return _api_response(
                await self._facade.add_architecture_node(
                    project_id=project_id,
                    node_id=_required_string(payload, "node_id"),
                    node_type=_required_string(payload, "node_type"),
                    name=_required_string(payload, "name"),
                    parameters=_optional_object(payload, "parameters"),
                    change_reason=_optional_string(payload, "change_reason", "Added from demo UI"),
                )
            )
        if method == "POST" and action == ("architecture", "add-edge"):
            return _api_response(
                await self._facade.add_architecture_edge(
                    project_id=project_id,
                    edge_id=_required_string(payload, "edge_id"),
                    from_node=_required_string(payload, "from_node"),
                    to_node=_required_string(payload, "to_node"),
                    edge_type=_required_string(payload, "edge_type"),
                    description=_required_string(payload, "description"),
                    change_reason=_optional_string(payload, "change_reason", "Added edge from demo UI"),
                )
            )
        if method == "POST" and action == ("architecture", "delete-edge"):
            return _api_response(
                await self._facade.delete_architecture_edge(
                    project_id=project_id,
                    edge_id=_required_string(payload, "edge_id"),
                    change_reason=_optional_string(payload, "change_reason", "Deleted edge from demo UI"),
                )
            )
        if method == "POST" and action == ("security",):
            return _api_response(await self._facade.evaluate_security(project_id=project_id))
        if method == "POST" and action == ("security", "loop"):
            return _api_response(
                await self._facade.evaluate_security_loop(
                    project_id=project_id,
                    rounds=_optional_int(payload, "rounds", 2),
                )
            )
        if method == "POST" and action == ("target-app",):
            fields = payload.get("fields", ["subject", "message", "email"])
            if not isinstance(fields, list) or not all(isinstance(item, str) for item in fields):
                raise ValidationAppError("fields must be a string list")
            env_vars = payload.get("env_vars", [])
            if not isinstance(env_vars, list) or not all(isinstance(item, str) for item in env_vars):
                raise ValidationAppError("env_vars must be a string list")
            return _api_response(
                await self._facade.generate_target_app(
                    project_id=project_id,
                    app_name=_optional_string(payload, "app_name", "Support Desk API"),
                    collection_name=_optional_string(payload, "collection_name", "support_tickets"),
                    fields=tuple(fields),
                    env_vars=tuple(env_vars),
                )
            )
        if method == "GET" and action == ("target-app", "latest"):
            return _api_response(await self._facade.latest_target_app(project_id=project_id))
        if method == "POST" and action == ("target-app", "review"):
            return _api_response(await self._facade.review_latest_target_app(project_id=project_id))
        if method == "POST" and action == ("apply",):
            return _api_response(await self._facade.apply_latest_architecture(project_id=project_id))
        if method == "POST" and action == ("apply", "failure-guidance"):
            return _api_response(
                await self._facade.apply_failure_guidance(
                    project_id=project_id,
                    error_text=_required_string(payload, "error_text"),
                )
            )
        if method == "POST" and action == ("apply", "failure-demo"):
            return _api_response(
                await self._facade.apply_failure_demo(
                    project_id=project_id,
                    error_text=_required_string(payload, "error_text"),
                )
            )
        if method == "GET" and action == ("terraform", "preview"):
            return _api_response(await self._facade.terraform_preview(project_id=project_id))
        if method == "POST" and action == ("github", "demo"):
            return _api_response(
                await self._facade.github_demo_flow(
                    project_id=project_id,
                    repo_url=_required_string(payload, "repo_url"),
                )
            )
        if method == "GET" and action == ("runtime", "cloud-run"):
            return _api_response(await self._facade.cloud_run_evidence(project_id=project_id))
        if method == "GET" and action == ("adapters",):
            return _api_response(await self._facade.adapter_inventory(project_id=project_id))
        if method == "GET" and action == ("submission", "brief"):
            return _api_response(await self._facade.submission_brief(project_id=project_id))
        if method == "GET" and action == ("ops",):
            return _api_response(await self._facade.ops_overview(project_id=project_id))
        if method == "GET" and action == ("timeline",):
            since = query.get("since", [None])[0]
            _ = since
            return _api_response(await self._facade.timeline(project_id=project_id))
        return _json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "route not found")


def create_demo_server(
    *,
    host: str,
    port: int,
    facade: CastorOpsApiFacade,
    target_project_id: str,
) -> ThreadingHTTPServer:
    """Create the local demo server."""

    app = DemoWebApp(facade, target_project_id=target_project_id)

    class DemoRequestHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self._handle()

        def do_POST(self) -> None:
            self._handle()

        def log_message(self, format: str, *args: object) -> None:
            return

        def _handle(self) -> None:
            content_length = int(self.headers.get("content-length", "0") or "0")
            body = self.rfile.read(content_length) if content_length else b""
            try:
                status, content_type, response_body = asyncio.run(
                    app.handle(method=self.command, raw_path=self.path, body=body)
                )
            except ValidationAppError as exc:
                status, content_type, response_body = _json_error(
                    HTTPStatus.UNPROCESSABLE_ENTITY,
                    exc.code,
                    exc.message,
                    exc.safe_details,
                )
            self.send_response(status)
            self.send_header("content-type", content_type)
            self.send_header("content-length", str(len(response_body)))
            self.end_headers()
            self.wfile.write(response_body)

    return ThreadingHTTPServer((host, port), DemoRequestHandler)


def _api_response(response: ApiResponse) -> tuple[int, str, bytes]:
    body = response.to_dict()
    status = HTTPStatus.OK if body["error"] is None else _status_for_error_code(body["error"]["code"])
    return int(status), "application/json; charset=utf-8", _json_bytes(body)


def _status_for_error_code(error_code: str) -> HTTPStatus:
    return {
        "VALIDATION_ERROR": HTTPStatus.UNPROCESSABLE_ENTITY,
        "NOT_FOUND": HTTPStatus.NOT_FOUND,
        "PHASE_CONFLICT": HTTPStatus.CONFLICT,
    }.get(error_code, HTTPStatus.INTERNAL_SERVER_ERROR)


def _json_error(
    status: HTTPStatus,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> tuple[int, str, bytes]:
    meta = ResponseMeta.create()
    response = {
        "data": None,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "meta": {
            "request_id": meta.request_id,
            "trace_id": None,
            "timestamp": meta.timestamp.isoformat(),
        },
    }
    return int(status), "application/json; charset=utf-8", _json_bytes(response)


def _parse_json_body(body: bytes) -> Any:
    if not body:
        return {}
    try:
        return json.loads(body.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise ValidationAppError("request body must be UTF-8 JSON") from exc
    except json.JSONDecodeError as exc:
        raise ValidationAppError("request body must be valid JSON") from exc


def _require_object(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationAppError("request body must be a JSON object")
    return payload


def _optional_object(payload: dict[str, Any], field_name: str) -> dict[str, Any]:
    value = payload.get(field_name, {})
    if not isinstance(value, dict):
        raise ValidationAppError(f"{field_name} must be an object")
    return value


def _required_string(payload: dict[str, Any], field_name: str) -> str:
    value = payload.get(field_name)
    if not isinstance(value, str) or not value.strip():
        raise ValidationAppError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_string(payload: dict[str, Any], field_name: str, default: str) -> str:
    if field_name not in payload:
        return default
    value = payload[field_name]
    if not isinstance(value, str) or not value.strip():
        raise ValidationAppError(f"{field_name} must be a non-empty string")
    return value.strip()


def _optional_bool(payload: dict[str, Any], field_name: str, default: bool) -> bool:
    value = payload.get(field_name, default)
    if not isinstance(value, bool):
        raise ValidationAppError(f"{field_name} must be a boolean")
    return value


def _optional_int(payload: dict[str, Any], field_name: str, default: int) -> int:
    value = payload.get(field_name, default)
    if not isinstance(value, int):
        raise ValidationAppError(f"{field_name} must be an integer")
    return value


def _static_response(path: Path, content_type: str) -> tuple[int, str, bytes]:
    if not _is_safe_static_path(path):
        return _json_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", "asset not found")
    return int(HTTPStatus.OK), content_type, path.read_bytes()


def _asset_response(path_parts: tuple[str, ...]) -> tuple[int, str, bytes]:
    relative_path = Path(*path_parts[1:])
    path = STATIC_DIR / relative_path
    suffix_to_type = {
        ".css": "text/css; charset=utf-8",
        ".js": "application/javascript; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }
    return _static_response(path, suffix_to_type.get(path.suffix, "application/octet-stream"))


def _is_safe_static_path(path: Path) -> bool:
    try:
        resolved_static_dir = STATIC_DIR.resolve()
        resolved_path = path.resolve()
    except FileNotFoundError:
        return False
    return resolved_path.is_file() and resolved_static_dir in resolved_path.parents


def _json_bytes(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
