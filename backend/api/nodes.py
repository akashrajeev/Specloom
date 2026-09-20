from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.context.store import store
from backend.workflow.models import Node, NodeType, WorkflowIR
from backend.workflow.validator import validate_workflow

router = APIRouter(prefix="/api/v1/projects", tags=["nodes"])


class NodeModeUpdate(BaseModel):
    mode: Literal["mock", "sandbox", "live"]


class NodeUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    description: str | None = None
    config: dict | None = None
    policy_ref: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)


class NodeCreate(BaseModel):
    type: NodeType
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    config: dict = Field(default_factory=dict)
    policy_ref: str | None = None
    timeout_seconds: int | None = Field(default=None, ge=1)
    before_node_id: str | None = None


class WorkflowUpdate(BaseModel):
    workflow: WorkflowIR


def _save_validated(project_id: str, workflow: WorkflowIR) -> dict:
    errors = validate_workflow(workflow)
    if errors:
        raise HTTPException(status_code=422, detail={"validation_errors": errors})
    saved = store.save_workflow(project_id, workflow)
    return {
        "project_id": project_id,
        "version": len(saved.workflow_versions),
        "workflow": workflow.model_dump(mode="json"),
    }


def _default_node_config(node_type: str) -> dict:
    if node_type == "agent":
        return {"role": "Task agent"}
    if node_type == "tool":
        return {"mode": "mock"}
    if node_type == "condition":
        return {"expression": "true"}
    if node_type == "parallel":
        return {"branches": []}
    if node_type == "loop":
        return {"body": "", "max_iterations": 3}
    return {}


@router.patch("/{project_id}/nodes/{node_id}/mode")
def update_node_mode(project_id: str, node_id: str, request: NodeModeUpdate) -> dict:
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no workflow")

    patched = WorkflowIR.model_validate(project.workflow.model_dump(mode="json"))
    node = next((item for item in patched.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    if node.type != "tool":
        raise HTTPException(status_code=400, detail="only tool node modes can be changed")

    node.config["mode"] = request.mode
    return _save_validated(project_id, patched)


@router.patch("/{project_id}/nodes/{node_id}")
def update_node(project_id: str, node_id: str, request: NodeUpdate) -> dict:
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no workflow")

    patched = WorkflowIR.model_validate(project.workflow.model_dump(mode="json"))
    node = next((item for item in patched.nodes if item.id == node_id), None)
    if node is None:
        raise HTTPException(status_code=404, detail="node not found")
    if request.name is not None:
        node.name = request.name
    if request.description is not None:
        node.description = request.description
    if request.config is not None:
        node.config = request.config
    if request.policy_ref is not None:
        node.policy_ref = request.policy_ref
    if request.timeout_seconds is not None:
        node.timeout_seconds = request.timeout_seconds
    return _save_validated(project_id, patched)


@router.post("/{project_id}/nodes")
def add_node(project_id: str, request: NodeCreate) -> dict:
    project = store.get(project_id)
    if project.workflow is None:
        raise HTTPException(status_code=404, detail="project has no workflow")

    workflow = WorkflowIR.model_validate(project.workflow.model_dump(mode="json"))
    existing_ids = {workflow.trigger.id, *(item.id for item in workflow.nodes)}
    base_id = "".join(char.lower() if char.isalnum() else "_" for char in request.name).strip("_") or "node"
    node_id = base_id
    suffix = 2
    while node_id in existing_ids:
        node_id = f"{base_id}_{suffix}"
        suffix += 1

    config = {**_default_node_config(request.type), **request.config}
    new_node = Node(
        id=node_id,
        type=request.type,
        name=request.name,
        description=request.description,
        config=config,
        policy_ref=request.policy_ref,
        timeout_seconds=request.timeout_seconds,
    )

    target_id = request.before_node_id
    if not target_id:
        outputs = [item.id for item in workflow.nodes if item.type == "output"]
        if not outputs:
            raise HTTPException(status_code=422, detail="workflow has no output node to insert before")
        target_id = outputs[0]

    if target_id == workflow.trigger.id:
        outgoing = [edge for edge in workflow.edges if edge.get("from") == target_id]
        if len(outgoing) != 1:
            raise HTTPException(status_code=422, detail="trigger must have exactly one successor before insertion")
        replacement = []
        old_target = outgoing[0]["to"]
        for edge in workflow.edges:
            if edge is outgoing[0]:
                replacement.extend([
                    {"from": workflow.trigger.id, "to": node_id},
                    {"from": node_id, "to": old_target},
                ])
            else:
                replacement.append(edge)
        workflow.edges = replacement
    else:
        incoming = [edge for edge in workflow.edges if edge.get("to") == target_id]
        if not incoming:
            raise HTTPException(status_code=422, detail="selected node cannot be inserted before")
        replacement = []
        inserted = False
        for edge in workflow.edges:
            if edge in incoming:
                replacement.append({"from": edge.get("from"), "to": node_id, "label": edge.get("label")})
                if not inserted:
                    replacement.append({"from": node_id, "to": target_id})
                    inserted = True
            else:
                replacement.append(edge)
        workflow.edges = replacement

    workflow.nodes.append(new_node)
    return _save_validated(project_id, workflow)


@router.put("/{project_id}/workflow")
def update_workflow(project_id: str, request: WorkflowUpdate) -> dict:
    project = store.get(project_id)
    _ = project
    return _save_validated(project_id, request.workflow)
