# Specloom Development Guide

This document covers local development, testing, environment configuration, and common failure modes.

## 1. Development model

The repository has three useful local profiles:

| Profile | Architect | Context | Runtime | Storage | AWS |
|---|---|---|---|---|---|
| Local deterministic | showcase | deterministic | local | memory | not required |
| Bedrock local | bedrock | bedrock or deterministic | bedrock | memory | required |
| AWS control plane | bedrock | bedrock | stepfunctions/bedrock/sagemaker | aws | required |

The first profile is the fastest way to develop and run the UI. It also matches CI.

## 2. Backend setup

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

AWS/model support adds:

~~~bash
python -m pip install -r backend/requirements-aws.txt
~~~

## 3. Frontend setup

~~~bash
cd frontend
npm install
npm run dev
~~~

Production build:

~~~bash
npm run build
~~~

The build command is intentionally:

~~~text
tsc -b && vite build
~~~

so TypeScript errors fail the frontend build.

## 4. Start both services

Terminal 1:

~~~bash
uvicorn backend.main:app --reload --port 8000
~~~

Terminal 2:

~~~bash
cd frontend
npm run dev
~~~

The frontend uses VITE_API_BASE_URL when the API is not on localhost:8000.

## 5. Environment configuration

backend/.env.example contains the main configuration surface.

### Compiler / context

| Variable | Meaning | Local default |
|---|---|---|
| SPECL00M_ARCHITECT_MODE | showcase or bedrock architect | showcase |
| SPECL00M_CONTEXT_MODE | deterministic or bedrock context analysis | deterministic |
| SPECL00M_REVIEW_MODE | semantic review mode | none |
| SPECL00M_RUNTIME_MODE | local, bedrock, sagemaker, stepfunctions | local |
| SPECL00M_STORAGE_MODE | memory or aws | memory |

### Bedrock

~~~text
SPECL00M_BEDROCK_MODEL_ID
SPECL00M_ALLOWED_BEDROCK_MODELS
AWS_REGION
~~~

The architect and runtime validate model IDs against the configured allowlist.

### AWS persistence

~~~text
SPECL00M_DDB_TABLE
SPECL00M_S3_BUCKET
~~~

AWS storage uses DynamoDB for project metadata/state and S3 for source documents and artifacts.

### GitHub

~~~text
SPECL00M_GITHUB_TOKEN
SPECL00M_GITHUB_REPOSITORY
~~~

The token is only needed for live GitHub operations. Keep it in the process environment or secret manager; do not place it in prompts, Workflow IR, or committed files.

### Cognito

~~~text
SPECL00M_AUTH_MODE
SPECL00M_COGNITO_ISSUER
SPECL00M_COGNITO_CLIENT_ID
~~~

Local development normally leaves authentication off. The AWS SAM template defaults the deployed control plane to Cognito mode.

### Durable execution

~~~text
SPECL00M_STEP_FUNCTIONS_ROLE_ARN
SPECL00M_STEP_FUNCTIONS_WORKER_ARN
SPECL00M_STEP_FUNCTIONS_APPROVAL_ARN
SPECL00M_STEP_FUNCTIONS_NAME_PREFIX
~~~

These values point the durable workflow manager at the IAM role and Lambda handlers needed to execute and resume workflows.

## 6. Test suite

Run all backend tests:

~~~bash
python -m pytest -q
~~~

A focused test file can be run with:

~~~bash
python -m pytest -q tests/test_build.py
~~~

The test suite covers areas including:

- architecture and Workflow IR contracts;
- decomposition;
- capability discovery/binding;
- compiler behavior;
- context ingestion;
- simulation;
- runtime semantics;
- generated implementation artifacts;
- deployment planning;
- Lambda handling;
- security and policy;
- Step Functions;
- repair;
- universal compiler behavior.

## 7. CI

GitHub Actions is defined in .github/workflows/ci.yml.

Backend CI:

- Python 3.11;
- installs backend/requirements.txt;
- uses showcase/local/memory configuration;
- runs pytest.

Frontend CI:

- Node 24;
- npm install;
- npm run build.

This makes CI deterministic and independent of AWS account credentials.

## 8. Build lifecycle for contributors

When changing compiler behavior, prefer this order:

~~~text
1. update the canonical model/schema
2. update deterministic validation
3. update compiler/runtime behavior
4. add or update tests
5. update frontend rendering/API types
6. update documentation
7. run backend tests
8. run frontend build
~~~

Do not create a second workflow representation solely for a UI feature.

## 9. Working with Workflow IR

Workflow IR is stored and exchanged as a structured document.

Typical top-level shape:

~~~json
{
  "ir_version": "0.1",
  "id": "system-example",
  "name": "Example",
  "trigger": {},
  "nodes": [],
  "edges": [],
  "variables": [],
  "policies": [],
  "tests": []
}
~~~

The exact schema is authoritative in schemas/workflow-ir.schema.json.

Use Workflow IR for:

- graph structure;
- node configuration;
- control-flow semantics;
- policies;
- tests;
- execution planning.

Do not encode secrets or deployment credentials into the IR.

## 10. Context development

Context sources become Context Graph entries through backend/context.

The important distinction is:

~~~text
source content
     ↓
ingestion
     ↓
analysis
     ↓
requirements / constraints / entities / tools / examples
     ↓
provenance
     ↓
Context Graph
~~~

Build answers are also ingested as contextual evidence so a resolved gap can affect subsequent planning.

## 11. Tool development

Register a native capability in backend/tools/registry.py and keep execution behind backend/tools/gateway.py.

A new side-effecting tool should specify:

- permissions;
- side_effecting=true;
- an explicit policy requirement;
- an execution mode;
- a live adapter that is safe to call only after approval.

Agents are prevented from directly using side-effecting tools.

For external APIs, prefer a configured API/OpenAPI capability or MCP boundary when an explicit contract exists.

## 12. Runtime development

Local runtime logic is in backend/runtime/executor.py.

Bedrock agent-node execution is in backend/runtime/bedrock_runner.py.

Durable workflow generation/execution is in backend/runtime/durable.py and backend/workflow/stepfunctions.py.

A runtime change should preserve:

- deterministic Workflow IR validation;
- event ordering;
- approval semantics;
- bounded loops;
- terminal outputs;
- error propagation.

## 13. Simulation

Use simulation to test graph semantics without performing production writes.

The simulator intentionally treats mock/sandbox tool operations as non-mutating and records them as simulated side effects.

A useful development pattern is:

~~~text
build
 ↓
validate
 ↓
evaluate
 ↓
simulate
 ↓
inspect failure
 ↓
repair
 ↓
re-evaluate
 ↓
run live only when ready
~~~

## 14. Generated artifacts

The compiler can generate an inspectable artifact bundle containing items such as:

- system specification;
- Workflow IR;
- implementation files;
- tests;
- container files;
- deployment metadata;
- documentation;
- capability adapters.

Artifacts are hashed and exposed through the project artifact API. AWS storage can persist artifact snapshots in S3.

Generated source should be inspected before being promoted or executed.

## 15. Troubleshooting

### Frontend cannot reach the backend

Check that the API is running on port 8000 or set:

~~~text
VITE_API_BASE_URL=http://localhost:8000
~~~

Also confirm the backend CORS setting includes the frontend origin.

### Bedrock import errors

Install:

~~~bash
python -m pip install -r backend/requirements-aws.txt
~~~

Then verify AWS credentials:

~~~bash
aws sts get-caller-identity
~~~

### Model allowlist failures

Make sure the requested model appears in SPECL00M_ALLOWED_BEDROCK_MODELS.

### Cognito returns 401/403

Verify the issuer/client variables and make sure the authenticated identity carries a Specloom workspace claim/group.

### Durable runtime configuration errors

Verify all required Step Functions/Lambda role environment values are present and that the AWS execution role can create/update/start state machines and pass the configured role.

### Live GitHub write failures

Check SPECL00M_GITHUB_TOKEN and SPECL00M_GITHUB_REPOSITORY. Remember that GitHub write nodes are policy-gated and require approval.

### Simulation succeeds but runtime fails

Simulation uses mock/sandbox tool behavior. Runtime may expose real credential, network, model, or permission problems. Inspect the run trace and switch one tool at a time from sandbox to live.

## 16. Adding a new API endpoint

Add the route under backend/api and include its router in backend/main.py.

Keep:

- request validation in Pydantic models;
- storage access through ContextStore/ProjectRepository;
- external effects behind ToolGateway;
- Workflow IR validation before accepting workflow changes.

Add a regression test under tests.

## 17. Documentation conventions

README.md should answer:

1. what Specloom is;
2. how the architecture works;
3. how to run it;
4. how to run the demo;
5. how to configure Bedrock/AWS;
6. where the deeper documentation lives.

Detailed operational information belongs under docs.

When behavior changes, update documentation in the same change so the README does not describe an earlier architecture.
