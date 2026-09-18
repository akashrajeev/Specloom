from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field, HttpUrl

from backend.context.ingestion import ingest_text, ingest_url
from backend.context.service import analyze_sources
from backend.context.store import store

router = APIRouter(prefix="/api/v1/projects", tags=["context"])

class TextContextRequest(BaseModel):
    name: str = Field(min_length=1)
    content: str = Field(min_length=1)

class URLContextRequest(BaseModel):
    url: HttpUrl
    name: str | None = None

@router.post("/{project_id}/context/text")
def add_text(project_id: str, request: TextContextRequest) -> dict:
    source = ingest_text(request.name, request.content)
    project = store.add_source(project_id, source)
    project.graph = analyze_sources(project.graph, project.documents)
    return {"source": source.source.model_dump(mode="json"), "graph": project.graph.model_dump(mode="json")}

@router.post("/{project_id}/context/url")
async def add_url(project_id: str, request: URLContextRequest) -> dict:
    source = await ingest_url(str(request.url), request.name)
    project = store.add_source(project_id, source)
    project.graph = analyze_sources(project.graph, project.documents)
    return {"source": source.source.model_dump(mode="json"), "graph": project.graph.model_dump(mode="json")}

@router.get("/{project_id}/context")
def get_context(project_id: str) -> dict:
    project = store.get(project_id)
    return {"project_id": project_id, "graph": project.graph.model_dump(mode="json")}
