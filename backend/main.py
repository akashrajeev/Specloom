import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.build import router as build_router
from backend.api.context import router as context_router
from backend.api.evaluation import router as evaluation_router
from backend.api.projects import router as projects_router
from backend.api.runtime import router as runtime_router
from backend.api.provenance import router as provenance_router
from backend.api.runs import router as runs_router
from backend.api.simulation import router as simulation_router
from backend.workflow.loader import load_workflow
from backend.workflow.validator import validate_workflow

app = FastAPI(title="Specloom API", version="0.1.0")

allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "SPECL00M_CORS_ORIGINS",
        "http://localhost:5173,http://127.0.0.1:5173",
    ).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context_router)
app.include_router(projects_router)
app.include_router(build_router)
app.include_router(simulation_router)
app.include_router(evaluation_router)
app.include_router(runtime_router)
app.include_router(provenance_router)
app.include_router(runs_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/workflow/example")
def example_workflow() -> dict:
    ir = load_workflow("examples/showcase-workflow.json")
    return {
        "workflow": ir.model_dump(mode="json"),
        "validation_errors": validate_workflow(ir),
    }
