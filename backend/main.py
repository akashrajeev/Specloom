import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.artifacts import router as artifacts_router
from backend.api.build import router as build_router
from backend.api.context import router as context_router
from backend.api.deploy import router as deploy_router
from backend.api.evaluation import router as evaluation_router
from backend.api.projects import router as projects_router
from backend.api.runtime import router as runtime_router
from backend.api.versions import router as versions_router
from backend.api.provenance import router as provenance_router
from backend.api.runs import router as runs_router
from backend.api.nodes import router as nodes_router
from backend.api.simulation import router as simulation_router
from backend.api.telegram import router as telegram_router
from backend.api.demo import router as demo_router
from backend.workflow.loader import load_workflow
from backend.workflow.validator import validate_workflow
from backend.security.auth import AuthenticationMiddleware

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
    AuthenticationMiddleware,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=os.getenv("SPECL00M_ALLOW_CREDENTIALS", "false").lower() == "true",
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(context_router)
app.include_router(artifacts_router)
app.include_router(deploy_router)
app.include_router(projects_router)
app.include_router(build_router)
app.include_router(simulation_router)
app.include_router(evaluation_router)
app.include_router(runtime_router)
app.include_router(provenance_router)
app.include_router(runs_router)
app.include_router(nodes_router)
app.include_router(versions_router)
app.include_router(telegram_router)
app.include_router(demo_router)


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


@app.get("/api/v1/demos")
def demo_workflows() -> dict:
    demos = [
        {
            "id": "research-hunter",
            "name": "ResearchHunter",
            "description": "Find recent AI developments, check relevance, require approval, and create GitHub issues.",
            "goal": "Build a research system that finds recent AI developments from configured sources, checks relevance, requires human approval, and creates GitHub issues only after approval.",
            "input_data": {
                "topic": "AI agent systems and workflow compilers",
                "time_window": "recent developments",
                "candidate_limit": 3,
            },
        },
        {
            "id": "support-triage",
            "name": "Support Triage",
            "description": "Classify customer requests, draft responses, and require review for urgent cases.",
            "goal": "Build a support triage system that receives customer requests, classifies the issue, drafts a helpful response, and requires human approval before handling urgent cases.",
            "input_data": {
                "channel": "email",
                "customer_id": "demo-customer-1042",
                "customer_request": "I believe my account was compromised and I see an unauthorized charge. Please freeze the account immediately and help me secure it.",
            },
        },
        {
            "id": "document-brief",
            "name": "Document Brief",
            "description": "Extract facts, verify important claims, and produce an executive brief.",
            "goal": "Build a document briefing system that accepts a supplied business document, extracts key facts and decisions, verifies important claims, and produces a concise executive brief with risks and next actions.",
            "input_data": {
                "document_name": "Q3 Operating Review — synthetic demo",
                "document_text": "Q3 revenue was ₹48.2M, up 12% quarter over quarter. Gross margin improved from 61% to 64%. The enterprise segment contributed ₹19.6M, while self-serve contributed ₹28.6M. Two enterprise renewals slipped into Q4, creating a stated revenue risk of ₹1.8M. Management approved hiring four support engineers and requested a December review of retention.",
            },
        },
    ]
    return {"demos": demos}


@app.get("/api/v1/config")
def config() -> dict[str, str]:
    from backend.llm import provider_chain, provider_status

    return {
        # Secret names only; the provider is chosen from each key's format at runtime.
        "fallback_secret_names": ",".join(
            name.split(":", 1)[-1]
            for name in os.getenv("SPECL00M_FALLBACK_SECRET_NAMES", "none").split(",")
            if name
        ) or "none",
        "fallback_providers": ",".join(p.key for p in provider_chain() if p.kind == "openai") or "none",
        **{f"llm_last_{k}": v for k, v in provider_status().items()},
        "architect_mode": os.getenv("SPECL00M_ARCHITECT_MODE", "bedrock").lower(),
        "review_mode": os.getenv("SPECL00M_REVIEW_MODE", "none").lower(),
        "allowed_bedrock_models": os.getenv(
            "SPECL00M_ALLOWED_BEDROCK_MODELS",
            os.getenv("SPECL00M_BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0"),
        ),
        "context_mode": os.getenv("SPECL00M_CONTEXT_MODE", "deterministic").lower(),
        "runtime_mode": os.getenv("SPECL00M_RUNTIME_MODE", "local").lower(),
        "storage_mode": os.getenv("SPECL00M_STORAGE_MODE", "memory").lower(),
        "auth_mode": os.getenv("SPECL00M_AUTH_MODE", "off").lower(),
    }


@app.get("/api/v1/deploy/status")
def deploy_status() -> dict[str, object]:
    runtime_mode = os.getenv("SPECL00M_RUNTIME_MODE", "local").lower()
    storage_mode = os.getenv("SPECL00M_STORAGE_MODE", "memory").lower()
    public_url = os.getenv("SPECL00M_PUBLIC_URL", "").strip() or None
    persistence_ready = (
        storage_mode == "aws"
        and bool(os.getenv("SPECL00M_DDB_TABLE"))
        and bool(os.getenv("SPECL00M_S3_BUCKET"))
    )
    runtime_ready = runtime_mode in {"local", "bedrock"} or (
        runtime_mode == "sagemaker"
        and bool(os.getenv("SPECL00M_SAGEMAKER_ENDPOINT_NAME"))
    ) or (
        runtime_mode == "stepfunctions"
        and bool(os.getenv("SPECL00M_STEP_FUNCTIONS_ROLE_ARN"))
        and bool(os.getenv("SPECL00M_STEP_FUNCTIONS_WORKER_ARN"))
        and bool(os.getenv("SPECL00M_STEP_FUNCTIONS_APPROVAL_ARN"))
    )
    return {
        "deployment": "live" if public_url else "ready" if persistence_ready or runtime_ready else "local",
        "public_url": public_url,
        "persistence_ready": persistence_ready,
        "runtime_ready": runtime_ready,
        "agentcore_runtime_arn": os.getenv("SPECL00M_AGENTCORE_RUNTIME_ARN") or None,
        "runtime_mode": runtime_mode,
        "storage_mode": storage_mode,
        "region": os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or None,
    }
