# Backend

The backend is Specloom's control and execution service.

## Responsibilities

- expose the FastAPI control plane;
- ingest and analyze context;
- build and validate Workflow IR;
- compile SoftwareSpec and implementation artifacts;
- evaluate and repair workflows;
- execute workflows through local, Bedrock, SageMaker, or durable Step Functions runtimes;
- enforce capability and policy boundaries;
- persist project state and artifacts;
- provide provenance, run history, approvals, and deployment APIs.

## Main packages

~~~text
backend/api/            FastAPI routes
backend/context/        Context ingestion, analysis, gaps, provenance
backend/agents/         Architects and reviewers
backend/compiler/       Universal compiler and artifact generation
backend/workflow/       Workflow IR, compilation, validation
backend/capabilities/   Capability contracts and binding
backend/tools/          Tool registry, gateway, adapters, MCP/OpenAPI
backend/evaluation/     Test generation, evaluation, repair
backend/runtime/        Execution engines and durable orchestration
backend/security/       Authentication and workspace isolation
backend/storage/        Memory and AWS persistence
~~~

## Local development

Install backend requirements from the repository root:

~~~bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r backend/requirements.txt
uvicorn backend.main:app --reload --port 8000
~~~

Run tests with:

~~~bash
python -m pytest -q
~~~

For AWS-backed capabilities, install backend/requirements-aws.txt and configure the required AWS credentials and environment variables.

The detailed implementation guide is in [docs/DEVELOPMENT.md](../docs/DEVELOPMENT.md).
