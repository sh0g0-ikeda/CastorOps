"""Application service for architecture proposals."""

from __future__ import annotations

from typing import Any

from app.architectures.models import ArchitectureEdge
from app.architectures.models import ArchitectureNode
from app.architectures.models import ArchitectureNodeType
from app.architectures.models import ArchitectureProposal
from app.architectures.models import parse_architecture_spec
from app.architectures.repository import ArchitectureRepository
from app.core.errors import NotFoundAppError
from app.core.errors import ValidationAppError


class ArchitectureService:
    """Create and read architecture proposal versions."""

    def __init__(self, repository: ArchitectureRepository) -> None:
        self._repository = repository

    async def create_next_proposal(
        self,
        *,
        project_id: str,
        spec_payload: dict[str, Any],
        rationale_md: str,
        cloudbuild_yaml: str,
        gcloud_commands: tuple[str, ...],
    ) -> ArchitectureProposal:
        existing_proposals = await self._repository.list_by_project(project_id)
        spec = parse_architecture_spec(spec_payload)
        proposal = ArchitectureProposal.create(
            project_id=project_id,
            version=len(existing_proposals) + 1,
            spec=spec,
            rationale_md=rationale_md,
            cloudbuild_yaml=cloudbuild_yaml,
            gcloud_commands=gcloud_commands,
        )
        await self._repository.create(proposal)
        return proposal

    async def latest_payload(self, project_id: str) -> dict[str, Any]:
        proposal = await self._repository.latest(project_id)
        return {
            "id": proposal.id,
            "project_id": proposal.project_id,
            "version": proposal.version,
            "status": proposal.status.value,
            "spec": {
                "project_id": proposal.spec.project_id,
                "region": proposal.spec.region,
                "nodes": [_node_payload(node) for node in proposal.spec.nodes],
                "edges": [_edge_payload(edge) for edge in proposal.spec.edges],
            },
            "rationale_md": proposal.rationale_md,
            "cloudbuild_yaml": proposal.cloudbuild_yaml,
            "gcloud_commands": list(proposal.gcloud_commands),
            "created_at": proposal.created_at.isoformat(),
        }

    async def editable_node_parameters(self, *, project_id: str, node_id: str) -> dict[str, Any]:
        proposal = await self._repository.latest(project_id)
        node = _find_node(proposal, node_id)
        editable_fields = _editable_fields_for_node(node.type)
        return {
            "architecture_id": proposal.id,
            "node_id": node.id,
            "node_type": node.type.value,
            "editable_fields": editable_fields,
            "current_parameters": {
                field_name: node.parameters.get(field_name)
                for field_name in editable_fields
            },
        }

    async def preview_node_update(
        self,
        *,
        project_id: str,
        node_id: str,
        parameter_patch: dict[str, Any],
    ) -> dict[str, Any]:
        proposal = await self._repository.latest(project_id)
        node = _find_node(proposal, node_id)
        normalized_patch = _validate_parameter_patch(node, parameter_patch)
        return {
            "architecture_id": proposal.id,
            "node_id": node.id,
            "changes": normalized_patch,
            "impact": _impact_summary(node, normalized_patch),
            "requires_reapply": True,
            "requires_confirmation": _patch_requires_confirmation(normalized_patch),
        }

    async def create_updated_node_proposal(
        self,
        *,
        project_id: str,
        node_id: str,
        parameter_patch: dict[str, Any],
        change_reason: str,
    ) -> ArchitectureProposal:
        proposal = await self._repository.latest(project_id)
        node = _find_node(proposal, node_id)
        normalized_patch = _validate_parameter_patch(node, parameter_patch)
        updated_spec = _proposal_spec_payload(proposal)
        for raw_node in updated_spec["nodes"]:
            if raw_node["id"] == node.id:
                raw_node["parameters"] = {
                    **raw_node["parameters"],
                    **normalized_patch,
                }
                raw_node["rationale"] = _append_change_reason(
                    raw_node["rationale"],
                    change_reason,
                )
                break
        return await self.create_next_proposal(
            project_id=project_id,
            spec_payload=updated_spec,
            rationale_md=_append_change_reason(proposal.rationale_md, change_reason),
            cloudbuild_yaml=proposal.cloudbuild_yaml,
            gcloud_commands=proposal.gcloud_commands,
        )

    async def create_deleted_node_proposal(
        self,
        *,
        project_id: str,
        node_id: str,
        confirmed: bool,
        change_reason: str,
    ) -> ArchitectureProposal:
        if not confirmed:
            raise ValidationAppError(
                "node deletion requires explicit confirmation",
                {"node_id": node_id},
            )
        proposal = await self._repository.latest(project_id)
        _find_node(proposal, node_id)
        updated_spec = _proposal_spec_payload(proposal)
        updated_spec["nodes"] = [
            node
            for node in updated_spec["nodes"]
            if node["id"] != node_id
        ]
        updated_spec["edges"] = [
            edge
            for edge in updated_spec["edges"]
            if edge["from_node"] != node_id and edge["to_node"] != node_id
        ]
        return await self.create_next_proposal(
            project_id=project_id,
            spec_payload=updated_spec,
            rationale_md=_append_change_reason(proposal.rationale_md, change_reason),
            cloudbuild_yaml=proposal.cloudbuild_yaml,
            gcloud_commands=proposal.gcloud_commands,
        )

    async def create_added_node_proposal(
        self,
        *,
        project_id: str,
        node_id: str,
        node_type: str,
        name: str,
        parameters: dict[str, Any],
        change_reason: str,
    ) -> ArchitectureProposal:
        proposal = await self._repository.latest(project_id)
        updated_spec = _proposal_spec_payload(proposal)
        if any(node["id"] == node_id for node in updated_spec["nodes"]):
            raise ValidationAppError("architecture node id already exists", {"node_id": node_id})
        node_payload = _new_node_payload(
            node_id=node_id,
            node_type=node_type,
            name=name,
            parameters=parameters,
        )
        updated_spec["nodes"].append(node_payload)
        return await self.create_next_proposal(
            project_id=project_id,
            spec_payload=updated_spec,
            rationale_md=_append_change_reason(proposal.rationale_md, change_reason),
            cloudbuild_yaml=proposal.cloudbuild_yaml,
            gcloud_commands=proposal.gcloud_commands,
        )

    async def create_added_edge_proposal(
        self,
        *,
        project_id: str,
        edge_id: str,
        from_node: str,
        to_node: str,
        edge_type: str,
        description: str,
        change_reason: str,
    ) -> ArchitectureProposal:
        proposal = await self._repository.latest(project_id)
        updated_spec = _proposal_spec_payload(proposal)
        if any(edge["id"] == edge_id for edge in updated_spec["edges"]):
            raise ValidationAppError("architecture edge id already exists", {"edge_id": edge_id})
        updated_spec["edges"].append(
            {
                "id": edge_id,
                "from_node": from_node,
                "to_node": to_node,
                "type": edge_type,
                "description": description,
            }
        )
        return await self.create_next_proposal(
            project_id=project_id,
            spec_payload=updated_spec,
            rationale_md=_append_change_reason(proposal.rationale_md, change_reason),
            cloudbuild_yaml=proposal.cloudbuild_yaml,
            gcloud_commands=proposal.gcloud_commands,
        )

    async def create_deleted_edge_proposal(
        self,
        *,
        project_id: str,
        edge_id: str,
        change_reason: str,
    ) -> ArchitectureProposal:
        proposal = await self._repository.latest(project_id)
        updated_spec = _proposal_spec_payload(proposal)
        if not any(edge["id"] == edge_id for edge in updated_spec["edges"]):
            raise NotFoundAppError("architecture_edge", f"{proposal.id}:{edge_id}")
        updated_spec["edges"] = [
            edge
            for edge in updated_spec["edges"]
            if edge["id"] != edge_id
        ]
        return await self.create_next_proposal(
            project_id=project_id,
            spec_payload=updated_spec,
            rationale_md=_append_change_reason(proposal.rationale_md, change_reason),
            cloudbuild_yaml=proposal.cloudbuild_yaml,
            gcloud_commands=proposal.gcloud_commands,
        )


def _node_payload(node: ArchitectureNode) -> dict[str, Any]:
    return {
        "id": node.id,
        "type": node.type.value,
        "name": node.name,
        "parameters": dict(node.parameters),
        "rationale": node.rationale,
        "cost_band": node.cost_band,
        "security_notes": list(node.security_notes),
    }


def _edge_payload(edge: ArchitectureEdge) -> dict[str, Any]:
    return {
        "id": edge.id,
        "from_node": edge.from_node,
        "to_node": edge.to_node,
        "type": edge.type.value,
        "description": edge.description,
    }


def _find_node(proposal: ArchitectureProposal, node_id: str) -> ArchitectureNode:
    for node in proposal.spec.nodes:
        if node.id == node_id:
            return node
    raise NotFoundAppError("architecture_node", f"{proposal.id}:{node_id}")


def _editable_fields_for_node(node_type: ArchitectureNodeType) -> tuple[str, ...]:
    editable_by_type = {
        ArchitectureNodeType.CLOUD_RUN: (
            "memory",
            "cpu",
            "min_instances",
            "max_instances",
            "allow_unauthenticated",
        ),
        ArchitectureNodeType.FIRESTORE: ("mode",),
        ArchitectureNodeType.CLOUD_STORAGE: ("lifecycle_days",),
        ArchitectureNodeType.SECRET_MANAGER: ("secret_names",),
    }
    return editable_by_type.get(node_type, ())


def _validate_parameter_patch(
    node: ArchitectureNode,
    parameter_patch: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(parameter_patch, dict) or not parameter_patch:
        raise ValidationAppError("parameter_patch must be a non-empty object")
    editable_fields = set(_editable_fields_for_node(node.type))
    if not editable_fields:
        raise ValidationAppError(
            "node type has no editable parameters",
            {"node_type": node.type.value},
        )

    normalized_patch: dict[str, Any] = {}
    for field_name, value in parameter_patch.items():
        if field_name not in editable_fields:
            raise ValidationAppError(
                "parameter is not editable for this node type",
                {"node_type": node.type.value, "field_name": field_name},
            )
        normalized_patch[field_name] = _validate_parameter_value(field_name, value)
    return normalized_patch


def _validate_parameter_value(field_name: str, value: Any) -> Any:
    if field_name in {"memory", "cpu", "mode"}:
        if not isinstance(value, str) or not value.strip():
            raise ValidationAppError(f"{field_name} must be a non-empty string")
        return value.strip()
    if field_name in {"min_instances", "max_instances", "lifecycle_days"}:
        if not isinstance(value, int) or value < 0:
            raise ValidationAppError(f"{field_name} must be a non-negative integer")
        return value
    if field_name == "allow_unauthenticated":
        if not isinstance(value, bool):
            raise ValidationAppError("allow_unauthenticated must be a boolean")
        return value
    if field_name == "secret_names":
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            raise ValidationAppError("secret_names must be a string list")
        return [item.strip() for item in value if item.strip()]
    raise ValidationAppError("unsupported editable parameter", {"field_name": field_name})


def _patch_requires_confirmation(parameter_patch: dict[str, Any]) -> bool:
    return parameter_patch.get("allow_unauthenticated") is True


def _new_node_payload(
    *,
    node_id: str,
    node_type: str,
    name: str,
    parameters: dict[str, Any],
) -> dict[str, Any]:
    try:
        normalized_type = ArchitectureNodeType(node_type).value
    except ValueError as exc:
        raise ValidationAppError("architecture node type is not supported", {"type": node_type}) from exc
    defaults = {
        ArchitectureNodeType.SECRET_MANAGER.value: {
            "rationale": "Store runtime secrets outside source code.",
            "cost_band": "low",
            "security_notes": ["Restrict secret access to the runtime service account."],
        },
        ArchitectureNodeType.CLOUD_STORAGE.value: {
            "rationale": "Store generated artifacts and larger snapshots.",
            "cost_band": "low",
            "security_notes": ["Use uniform bucket-level access."],
        },
        ArchitectureNodeType.CLOUD_LOGGING.value: {
            "rationale": "Collect application logs for the Ops Dashboard.",
            "cost_band": "low",
            "security_notes": ["Mask secrets before writing logs."],
        },
        ArchitectureNodeType.CLOUD_MONITORING.value: {
            "rationale": "Track service health, latency, and error rates.",
            "cost_band": "low",
            "security_notes": ["Keep alert channels scoped to the project team."],
        },
        ArchitectureNodeType.ARTIFACT_REGISTRY.value: {
            "rationale": "Store deployable container images.",
            "cost_band": "low",
            "security_notes": ["Limit image push permissions to Cloud Build."],
        },
        ArchitectureNodeType.IAM_SERVICE_ACCOUNT.value: {
            "rationale": "Isolate runtime permissions with a dedicated service account.",
            "cost_band": "none",
            "security_notes": ["Grant only the minimum roles required by the runtime."],
        },
        ArchitectureNodeType.EXTERNAL.value: {
            "rationale": "Represent an external dependency in the architecture map.",
            "cost_band": "external",
            "security_notes": ["Review external trust boundaries before apply."],
        },
        ArchitectureNodeType.CLOUD_RUN.value: {
            "rationale": "Run a containerized HTTP service.",
            "cost_band": "low",
            "security_notes": ["Require explicit approval before public access."],
        },
        ArchitectureNodeType.FIRESTORE.value: {
            "rationale": "Persist structured application state.",
            "cost_band": "low",
            "security_notes": ["Use server-side access through the backend."],
        },
    }
    template = defaults[normalized_type]
    return {
        "id": node_id,
        "type": normalized_type,
        "name": name,
        "parameters": parameters,
        "rationale": template["rationale"],
        "cost_band": template["cost_band"],
        "security_notes": template["security_notes"],
    }


def _impact_summary(node: ArchitectureNode, parameter_patch: dict[str, Any]) -> dict[str, str]:
    if _patch_requires_confirmation(parameter_patch):
        security = (
            "Public access will be enabled. Confirm the endpoint is intended to be public "
            "and that authentication or rate limiting is handled appropriately."
        )
    else:
        security = "No direct weakening of the current security boundary was detected."

    performance = "Performance impact is expected to be minor."
    if "memory" in parameter_patch or "cpu" in parameter_patch:
        performance = (
            "Cloud Run resource allocation changes can affect response latency, cold starts, "
            "and concurrency behavior."
        )

    cost = "Monthly cost impact is expected to be small."
    if any(field in parameter_patch for field in ("memory", "cpu", "min_instances", "max_instances")):
        cost = (
            "Cloud Run cost may increase or decrease depending on memory, CPU, traffic, "
            "and minimum instance settings."
        )

    return {
        "summary": f"{node.name} parameter changes will take effect after the next approved apply.",
        "cost": cost,
        "security": security,
        "performance": performance,
    }


def _proposal_spec_payload(proposal: ArchitectureProposal) -> dict[str, Any]:
    return {
        "project_id": proposal.spec.project_id,
        "region": proposal.spec.region,
        "nodes": [_node_payload(node) for node in proposal.spec.nodes],
        "edges": [_edge_payload(edge) for edge in proposal.spec.edges],
    }


def _append_change_reason(current_text: str, change_reason: str) -> str:
    if not change_reason.strip():
        return current_text
    return f"{current_text.strip()}\n\nChange reason: {change_reason.strip()}"
