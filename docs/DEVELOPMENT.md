# Specloom Development Guide

This guide explains how to run, extend, test, and deploy Specloom while preserving the canonical Workflow IR architecture.

## 1. Development model

Specloom separates four concerns:

~~~text
Experience
    ↓
FastAPI Control Plane
    ↓
Compiler + Validation
    ↓
Runtime + External Capabilities
~~~

The browser is a client of the control plane. Workflow IR is the single source of truth shared by build, validation, runtime, persistence, and the UI.

## 2. Prerequisites

Use:

- Python 3.11;
- Node.js/npm (CI uses Node 24);
- Git.

For AWS-backed development, also install:

- AWS CLI;
- AWS SAM CLI;
- credentials with the permissions required by the selected services.

## 3. Backend setup

From the repository root:

~~~bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
~~~

Windows PowerShell:

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
~~~

Start the API:

~~~bash
uvicorn backend.main:app --reload --port 8000
~~~

Open:

~~~text
http://localhost:8000/docs
~~~

## 4. Frontend setup

~~~bash
cd frontend
npm install
npm run dev
~~~

The development server normally runs at:

~~~text
http://localhost:5173
~~~

Set VITE_API_BASE_URL when the API is hosted elsewhere.

Production build:

~~~bash
npm run build
~~~

## 5. Local configuration

A deterministic local configuration can use:

~~~text
SPECL00M_ARCHITECT_MODE=showcase
SPECL00M_CONTEXT_MODE=deterministic
SPECL00M_RUNTIME_MODE=local
SPECL00M_STORAGE_MODE=memory
~~~

This keeps local compiler and runtime development independent of AWS credentials.

The model-backed path uses:

~~~text
SPECL00M_ARCHITECT_MODE=bedrock
SPECL00M_CONTEXT_MODE=bedrock
SPECL00M_RUNTIME_MODE=bedrock
SPECL00M_STORAGE_MODE=memory
SPECL00M_BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
SPECL00M_ALLOWED_BEDROCK_MODELS=amazon.nova-lite-v1:0
AWS_REGION=ap-south-1
~~~

Install AWS/model dependencies with:

~~~bash
python -m pip install -r backend/requirements-aws.txt
~~~

## 6. Code organization

~~~text
backend/api/          HTTP endpoints and request models
backend/context/      ingestion, analysis, gap detection, provenance
backend/agents/       architecture and review agents
backend/compiler/     decomposition, capability binding, compilation
backend/workflow/     Workflow IR models, loaders, validators
backend/capabilities/ capability contracts and binding
backend/tools/        registry, gateway, adapters, MCP/OpenAPI
backend/evaluation/   tests, evaluation, bounded repair
backend/runtime/      local, Bedrock, SageMaker, durable execution
backend/security/     authentication and workspace isolation
backend/storage/      repository abstractions and AWS persistence
frontend/src/         engineering workspace and typed API client
schemas/              canonical JSON schemas
infra/aws/            canonical SAM deployment
~~~

## 7. Build lifecycle

The build path should remain understandable as:

~~~text
goal + context
      ↓
Context Graph
      ↓
gap detection
      ↓
problem decomposition
      ↓
architecture proposal
      ↓
Workflow IR
      ↓
capability binding
      ↓
deterministic validation
      ↓
evaluation
      ↓
bounded repair when required
      ↓
artifacts + deployment plan
~~~

When changing compiler behavior, prefer updating the canonical representation and deterministic checks before adding UI-specific behavior.

## 8. Working with Workflow IR

Workflow IR is the canonical execution representation.

Top-level concepts include:

~~~text
metadata
trigger
nodes
edges
variables
policies
tests
~~~

The authoritative schema is schemas/workflow-ir.schema.json.

Use Workflow IR for:

- graph structure;
- node configuration;
- control-flow semantics;
- policies;
- tests;
- execution planning.

Do not put secrets, provider credentials, or deployment secrets into the IR.

## 9. Context development

Context sources become Context Graph entries through backend/context.

The flow is:

~~~text
source
  ↓
ingestion
  ↓
stored source
  ↓
analysis
  ↓
requirements / constraints / entities / capabilities / examples
  ↓
provenance
  ↓
Context Graph
~~~

When a missing requirement is resolved, preserve the source of that answer so later planning can explain why the workflow contains the resulting behavior.

## 10. Tool development

Register native capabilities in backend/tools/registry.py and keep execution behind backend/tools/gateway.py.

A side-effecting capability should explicitly define:

- permissions;
- side_effecting=true;
- policy requirements;
- an execution mode;
- a safe live adapter.

Agent nodes must not receive an unrestricted side-effecting path.

For external APIs, prefer a declared API/OpenAPI capability or a read-only MCP boundary when an explicit contract exists.

## 11. Runtime development

Local graph execution is implemented in backend/runtime/executor.py.

Bedrock agent execution is implemented in backend/runtime/bedrock_runner.py.

Durable Workflow IR compilation and execution are implemented in backend/runtime/durable.py and backend/workflow/stepfunctions.py.

Runtime changes should preserve:

- Workflow IR validation before execution;
- event ordering;
- approval semantics;
- bounded loops;
- terminal outputs;
- error propagation.

## 12. Generated artifacts

The compiler can generate an inspectable artifact bundle containing:

- system specification;
- Workflow IR;
- implementation files;
- tests;
- container files;
- deployment metadata;
- documentation;
- capability adapters.

Artifacts are content-addressed and can be persisted in S3 in AWS mode.

Generated source should be reviewed before it is promoted to an external environment.

## 13. Testing

Run the backend suite:

~~~bash
python -m pytest -q
~~~

Run the frontend build:

~~~bash
cd frontend
npm run build
~~~

CI runs both the backend test suite and frontend build for pull requests and pushes to main.

Keep tests deterministic and avoid requiring a live AWS account for the default CI path.

## 14. Adding an API endpoint

Add the route under backend/api and include its router from backend/main.py.

Keep:

- request validation in Pydantic models;
- persistence behind the repository/context store;
- external effects behind ToolGateway;
- workflow changes validated before acceptance.

Add a regression test under tests.

## 15. Persistence

The storage facade is selected by backend/storage/factory.py.

Local development uses MemoryRepository.

AWS mode uses AwsProjectRepository:

~~~text
DynamoDB
  → project metadata, Workflow IR, versions, context metadata, runs

S3
  → source documents, artifacts, immutable snapshots
~~~

Do not bypass this abstraction for project-state access.

## 16. Authentication

Authentication is implemented in backend/security/auth.py.

Cognito mode verifies:

- bearer token presence;
- issuer;
- client/audience when configured;
- Specloom workspace identity.

Workspace identity is propagated into project storage so one workspace cannot access another workspace's project state.

## 17. AWS deployment development path

The canonical infrastructure lives at:

~~~text
infra/aws/template.yaml
~~~

Use:

~~~bash
./infra/aws/deploy.sh
~~~

The script builds the SAM template and deploys using samconfig.toml.

After deployment, inspect outputs:

~~~bash
aws cloudformation describe-stacks \
  --stack-name specloom \
  --query 'Stacks[0].Outputs' \
  --output table
~~~

The root template.yaml is a legacy smaller stack and should not be used for the canonical production deployment path.

## 18. Troubleshooting

### Frontend cannot reach the backend

Check port 8000 and VITE_API_BASE_URL. Also verify CORS includes the frontend origin.

### Bedrock import or credential errors

Install backend/requirements-aws.txt and verify:

~~~bash
aws sts get-caller-identity
~~~

### Model allowlist errors

Ensure the requested model is included in SPECL00M_ALLOWED_BEDROCK_MODELS.

### Cognito 401/403 responses

Verify issuer/client configuration and the workspace claim or group used by the authenticated identity.

### Durable execution errors

Verify the Step Functions role, Lambda worker/approval configuration, IAM pass-role permission, and the generated state machine definition.

### GitHub write failures

Check SPECL00M_GITHUB_TOKEN and SPECL00M_GITHUB_REPOSITORY. GitHub write operations remain policy-gated.

## 19. Contributor workflow

Use this sequence for a behavior change:

~~~text
1. update the canonical model or schema
2. update deterministic validation
3. update compiler/runtime behavior
4. add regression tests
5. update frontend API types/rendering
6. update documentation
7. run pytest
8. run the frontend build
~~~

Do not introduce a second workflow representation merely to simplify one surface.

## 20. Documentation conventions

Documentation should answer:

1. what Specloom is;
2. how the architecture works;
3. how to run it;
4. how to configure model-backed execution;
5. how to deploy to AWS;
6. where the authoritative schemas and API contracts live.

Keep implementation details in docs rather than duplicating them across multiple READMEs.
