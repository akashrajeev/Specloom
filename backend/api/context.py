from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field, HttpUrl

from backend.capabilities.openapi import OpenAPICompileError, compile_openapi
from backend.context.gaps import detect_gaps
from backend.context.ingestion import IngestionError, ingest_api_spec, ingest_github, ingest_pdf, ingest_text, ingest_url
from backend.context.service import analyze_sources
from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["context"])


class TextContextRequest(BaseModel):
    name: str = Field(min_length=1)
    content: str = Field(min_length=1)


class URLContextRequest(BaseModel):
    url: HttpUrl
    name: str | None = None


class GitHubContextRequest(BaseModel):
    url: HttpUrl
    name: str | None = None


class OpenAPIContextRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    spec: str | dict = Field(min_length=2)
    base_url: HttpUrl | None = None
    auth_env: str | None = Field(default=None, pattern=r"^[A-Z][A-Z0-9_]{0,127}$")
    auth_header: str = Field(default="Authorization", min_length=1, max_length=100)
    auth_prefix: str = Field(default="Bearer ", max_length=100)


@router.post("/{project_id}/context/text")
def add_text(project_id: str, request: TextContextRequest) -> dict:
    source = ingest_text(request.name, request.content)
    project = store.add_source(project_id, source)
    project.graph = analyze_sources(project.graph, project.documents)
    store.persist(project_id)
    return {"source": source.source.model_dump(mode="json"), "graph": project.graph.model_dump(mode="json")}


@router.post("/{project_id}/context/url")
async def add_url(project_id: str, request: URLContextRequest) -> dict:
    try:
        source = await ingest_url(str(request.url), request.name)
    except (OSError, IngestionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = store.add_source(project_id, source)
    project.graph = analyze_sources(project.graph, project.documents)
    store.persist(project_id)
    return {"source": source.source.model_dump(mode="json"), "graph": project.graph.model_dump(mode="json")}


@router.post("/{project_id}/context/github")
async def add_github(project_id: str, request: GitHubContextRequest) -> dict:
    try:
        source = await ingest_github(str(request.url), request.name)
    except (OSError, IngestionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    project = store.add_source(project_id, source)
    project.graph = analyze_sources(project.graph, project.documents)
    store.persist(project_id)
    return {"source": source.source.model_dump(mode="json"), "graph": project.graph.model_dump(mode="json")}


@router.post("/{project_id}/context/openapi")
def add_openapi(project_id: str, request: OpenAPIContextRequest) -> dict:
    import json

    spec_text = json.dumps(request.spec) if isinstance(request.spec, dict) else request.spec
    try:
        source = ingest_api_spec(request.name, spec_text)
        capabilities = compile_openapi(
            spec_text,
            source_id=source.source.id,
            source_name=source.source.name,
            base_url_override=str(request.base_url) if request.base_url else None,
            auth_env=request.auth_env,
            auth_header=request.auth_header,
            auth_prefix=request.auth_prefix,
        )
    except (IngestionError, OpenAPICompileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project = store.add_source(project_id, source)
    existing = {item.id for item in project.graph.capabilities}
    project.graph.capabilities.extend(item for item in capabilities if item.id not in existing)
    project.graph.tools = [tool for tool in project.graph.tools if not tool.id.startswith("apiop:")]
    from backend.context.models import ContextTool
    project.graph.tools.extend(ContextTool.model_validate(item.to_context_tool()) for item in project.graph.capabilities)
    project.graph = analyze_sources(project.graph, project.documents)
    store.persist(project_id)
    return {
        "source": source.source.model_dump(mode="json"),
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        "graph": project.graph.model_dump(mode="json"),
    }


@router.post("/{project_id}/context/openapi/url")
async def add_openapi_url(
    project_id: str,
    url: HttpUrl,
    name: str | None = None,
    base_url: HttpUrl | None = None,
    auth_env: str | None = None,
) -> dict:
    try:
        source = await ingest_url(str(url), name or str(url))
        capabilities = compile_openapi(
            source.text,
            source_id=source.source.id,
            source_name=source.source.name,
            base_url_override=str(base_url) if base_url else None,
            auth_env=auth_env,
        )
    except (OSError, IngestionError, OpenAPICompileError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    project = store.add_source(project_id, source)
    existing = {item.id for item in project.graph.capabilities}
    project.graph.capabilities.extend(item for item in capabilities if item.id not in existing)
    project.graph.tools = [tool for tool in project.graph.tools if not tool.id.startswith("apiop:")]
    project.graph.tools.extend(ContextTool.model_validate(item.to_context_tool()) for item in project.graph.capabilities)
    store.persist(project_id)
    return {
        "source": source.source.model_dump(mode="json"),
        "capabilities": [item.model_dump(mode="json") for item in capabilities],
        "graph": project.graph.model_dump(mode="json"),
    }


@router.post("/{project_id}/context/file")
async def add_file(project_id: str, file: UploadFile = File(...)) -> dict:
    if file.filename is None:
        raise HTTPException(status_code=400, detail="filename is required")
    content_type = file.content_type or ""
    if content_type != "application/pdf" and not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=415, detail="MVP file ingestion supports PDF only")

    import tempfile
    from pathlib import Path
    suffix = Path(file.filename).suffix or ".pdf"
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
            temp.write(await file.read())
            temp_path = Path(temp.name)
        source = ingest_pdf(temp_path, file.filename)
    except (OSError, IngestionError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except UnboundLocalError:
            pass

    project = store.add_source(project_id, source)
    project.graph = analyze_sources(project.graph, project.documents)
    store.persist(project_id)
    return {"source": source.source.model_dump(mode="json"), "graph": project.graph.model_dump(mode="json")}


@router.get("/{project_id}/context")
def get_context(project_id: str) -> dict:
    project = store.get(project_id)
    return {"project_id": project_id, "graph": project.graph.model_dump(mode="json")}


@router.get("/{project_id}/capabilities")
def list_capabilities(project_id: str) -> dict:
    project = store.get(project_id)
    return {
        "project_id": project_id,
        "capabilities": [item.model_dump(mode="json") for item in project.graph.capabilities],
        "tools": [item.model_dump(mode="json") for item in project.graph.tools],
    }


@router.get("/{project_id}/gaps")
def get_gaps(project_id: str, goal: str) -> dict:
    project = store.get(project_id)
    project.graph = analyze_sources(project.graph, project.documents)
    gaps = detect_gaps(goal, project.graph)
    return {"project_id": project_id, "ready": not any(gap.severity == "blocking" for gap in gaps), "gaps": [gap.__dict__ for gap in gaps]}
