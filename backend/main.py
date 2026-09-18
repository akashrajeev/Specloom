from fastapi import FastAPI
from backend.workflow.loader import load_workflow
from backend.workflow.validator import validate_workflow

app = FastAPI(title="Specloom API", version="0.1.0")

@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}

@app.get("/api/v1/workflow/example")
def example_workflow() -> dict:
    ir = load_workflow("examples/showcase-workflow.json")
    return {"workflow": ir.model_dump(mode="json"), "validation_errors": validate_workflow(ir)}
