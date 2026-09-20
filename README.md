# Specloom

> **Give it a problem. Specloom architects the system.**

[![CI](https://github.com/akashrajeev/Specloom/actions/workflows/ci.yml/badge.svg)](https://github.com/akashrajeev/Specloom/actions/workflows/ci.yml)

Specloom is an **agentic system compiler**. A user provides a goal plus context, and Specloom turns that intent into a structured, validated, executable workflow.

**Goal + Context → Understand → Architect → Validate → Test → Repair → Deploy → Run**

The **Workflow IR** is the execution-control source of truth. Model output is treated as a proposal; deterministic compiler, capability, and policy checks decide whether that proposal is admissible.

---

## What Specloom does

A normal build can start with a problem such as:

> Create a support triage system that classifies customer requests, drafts helpful responses, and requires human review for urgent cases.

Specloom can then:

1. ingest context from text, URLs, PDFs, and repository sources;
2. extract requirements, constraints, entities, tools, examples, and provenance;
3. detect missing information that could change behavior, permissions, safety, or correctness;
4. decompose the problem into executable steps;
5. use the configured architect to produce Workflow IR;
6. bind workflow nodes to available or synthesized capabilities;
7. validate graph structure, requirements, constraints, tools, policies, loops, and outputs;
8. compile inspectable implementation/specification/deployment artifacts;
9. generate and run requirement-oriented evaluation;
10. simulate safely;
11. diagnose failures and apply bounded IR repairs;
12. deploy through the selected target;
13. execute the workflow and record an execution trace.

The important boundary is:

**The model proposes architecture; the compiler and runtime control execution.**

---

# Architecture

## End-to-end system

~~~mermaid
flowchart TB
    USER[User / Browser]

    subgraph EXPERIENCE[Experience Layer]
        UI[React + Vite Workspace]
        GRAPH[Workflow Canvas]
        INSPECT[Context / Provenance / Run Inspector]
        UI --> GRAPH
        UI --> INSPECT
    end

    subgraph CONTROL[Specloom Control Plane]
        API[FastAPI API]
        CONTEXT[Context ingestion + Context Graph]
        GAPS[Gap Detection]
        DECOMP[Problem Decomposition]
        ARCH[Architect]
        COMP[Universal Compiler]
        VALIDATE[Deterministic Validation + Policy]
        EVAL[Evaluation + Test Generation]
        REPAIR[Bounded IR Repair]
        ARTIFACTS[Artifacts + Deployment Plan]
        API --> CONTEXT
        CONTEXT --> GAPS
        GAPS --> DECOMP
        DECOMP --> ARCH
        ARCH --> COMP
        COMP --> VALIDATE
        VALIDATE --> EVAL
        EVAL --> REPAIR
        REPAIR --> ARTIFACTS
    end

    subgraph EXECUTION[Execution Layer]
        LOCAL[Runtime Executor]
        BEDROCK[Strands + Bedrock Runner]
        DURABLE[Durable Step Functions Manager]
        GATEWAY[Policy-aware Tool Gateway]
        TOOLS[Web / URL / GitHub / API / OpenAPI / MCP]
        APPROVAL[Human Approval]
    end

    subgraph AWS[AWS Foundation]
        APIGW[API Gateway]
        LAMBDA[Lambda + Mangum]
        COGNITO[Cognito]
        DDB[(DynamoDB)]
        S3[(S3)]
        EVENTS[EventBridge]
        SFN[Standard Step Functions]
        BR[Amazon Bedrock]
    end

    USER --> UI
    UI --> API

    APIGW --> LAMBDA
    LAMBDA --> API
    COGNITO -. authenticates .-> APIGW

    API --> DDB
    API --> S3

    API --> LOCAL
    API --> BEDROCK
    API --> DURABLE

    LOCAL --> GATEWAY
    BEDROCK --> BR
    BEDROCK --> GATEWAY
    DURABLE --> SFN
    SFN --> LAMBDA

    GATEWAY --> TOOLS
    GATEWAY --> APPROVAL
    DURABLE --> APPROVAL

    EVENTS --> LAMBDA
~~~

## Compiler lifecycle

~~~mermaid
flowchart LR
    GOAL[Goal] --> CONTEXT[Context Graph]
    CONTEXT --> GAP{Blocking gap?}
    GAP -- yes --> ANSWER[User clarification / more context]
    ANSWER --> CONTEXT
    GAP -- no --> DECOMP[Problem decomposition]
    DECOMP --> ARCH[Architecture proposal]
    ARCH --> IR[Workflow IR]
    IR --> VALIDATE[Deterministic validation]
    VALIDATE -- fail --> REVISE[Bounded revision / repair]
    REVISE --> IR
    VALIDATE -- pass --> TESTS[Generated tests + evaluation]
    TESTS -- fail --> REVISE
    TESTS -- pass --> BUILD[Artifacts + deployment plan]
    BUILD --> DEPLOY[Provision / Deploy]
    DEPLOY --> RUN[Run]
    RUN --> TRACE[Execution trace + output]
~~~

## Runtime safety boundary

~~~mermaid
flowchart LR
    IR[Validated Workflow IR] --> EXEC[Runtime Executor]
    INPUT[Runtime input] --> EXEC

    EXEC --> AGENT[Agent node]
    EXEC --> TOOL[Tool node]
    EXEC --> HUMAN[Human approval node]
    EXEC --> OUTPUT[Terminal output]

    AGENT --> BED[Strands + Bedrock]
    AGENT --> TOOL

    TOOL --> GATE[Tool Gateway]
    GATE --> READ[Read capability]
    GATE --> WRITE[Write capability]
    WRITE --> POLICY[Policy + approval]
    HUMAN --> POLICY
    POLICY --> WRITE
~~~

### Architectural invariant

**Models do not receive an unrestricted production side-effect path.**

Execution is bounded by schema validation, graph validation, capability binding, tool permissions, policy references, approval gates, and bounded loops/retries/timeouts.

---

# Core concepts

### Context Graph

The Context Graph describes what Specloom knows about a project:

- sources;
- requirements;
- constraints;
- entities;
- tools/capabilities;
- examples;
- provenance;
- problem decomposition.

Text, PDF, URL, and repository inputs are normalized into this graph. Requirements and constraints keep provenance back to source material when available.

### Workflow IR

Workflow IR describes what the system will do.

| Node | Purpose |
|---|---|
| trigger | manual, scheduled, webhook, or event start |
| agent | bounded LLM reasoning with explicit tools/output |
| tool | deterministic external capability |
| condition | deterministic branch |
| parallel | fan-out/fan-in |
| loop | bounded iteration |
| human_approval | explicit human decision point |
| output | terminal result, artifact, notification, or webhook |

Schema: [schemas/workflow-ir.schema.json](schemas/workflow-ir.schema.json)

### SoftwareSpec

SoftwareSpec is a provider-neutral software architecture representation produced by the universal compiler. It describes services, required capabilities, synthesized capabilities, data, environment, implementation information, and deployment targets.

Schema: [schemas/software-spec.schema.json](schemas/software-spec.schema.json)

### Capability binding

Capabilities can come from:

- registered native tools;
- configured APIs;
- OpenAPI definitions;
- read-only MCP servers;
- synthesized external-service contracts.

Credentials and provider-specific provisioning values stay outside model prompts and generated source.

---

# Repository structure

~~~text
Specloom/
├── backend/
│   ├── agents/          # Model-backed/deterministic architects and reviewers
│   ├── api/             # FastAPI control-plane endpoints
│   ├── capabilities/    # Capability contracts and binding logic
│   ├── compiler/        # Universal software/compiler pipeline
│   ├── context/         # Ingestion, analysis, gaps, provenance, storage facade
│   ├── evaluation/      # Test generation and evaluation
│   ├── runtime/         # Local, Bedrock, SageMaker, durable execution
│   ├── security/        # Optional Cognito/workspace authentication
│   ├── simulation/      # Side-effect-safe simulator
│   ├── storage/         # Memory and AWS repositories
│   ├── tools/           # Registry, gateway, adapters, APIs, MCP
│   └── workflow/        # Workflow IR, compilation, validation
├── frontend/
│   ├── src/App.tsx      # Main engineering workspace
│   ├── src/api.ts       # Typed API client
│   └── src/components/  # Build, context, run, deploy, provenance UI
├── schemas/             # Workflow IR, Context Graph, SoftwareSpec schemas
├── examples/            # Regression/showcase workflow fixtures
├── infra/
│   ├── aws/             # Canonical AWS SAM control plane
│   └── agentcore/       # AgentCore runtime entrypoint/scaffold
├── tests/               # Backend/compiler/runtime/security tests
├── docs/                # Architecture and operational documentation
├── requirements.txt     # Root Python dependency entrypoint
├── samconfig.toml       # SAM deployment defaults
└── Makefile             # Backend install/test/run helpers
~~~

---

# Quick start

## Prerequisites

Recommended versions:

- Python **3.11**;
- Node.js/npm; CI currently uses Node 24;
- Git.

AWS is **not required** for deterministic local development.

## 1. Clone

~~~bash
git clone https://github.com/akashrajeev/Specloom.git
cd Specloom
~~~

## 2. Create a Python environment

### Linux / macOS / WSL

~~~bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
~~~

### Windows PowerShell

~~~powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r backend/requirements.txt
~~~

## 3. Run the backend

From the repository root:

~~~bash
uvicorn backend.main:app --reload --port 8000
~~~

Health check:

~~~bash
curl http://localhost:8000/health
~~~

Expected:

~~~json
{"status":"ok"}
~~~

API documentation:

- http://localhost:8000/docs
- http://localhost:8000/redoc

## 4. Run the frontend

Open a second terminal:

~~~bash
cd frontend
npm install
npm run dev
~~~

Open the Vite URL printed by the dev server, normally:

~~~text
http://localhost:5173
~~~

The frontend defaults to the backend at http://localhost:8000. To point it at another API, set VITE_API_BASE_URL.

---

# Local development modes

For a fully local deterministic setup:

~~~bash
export SPECL00M_ARCHITECT_MODE=showcase
export SPECL00M_CONTEXT_MODE=deterministic
export SPECL00M_RUNTIME_MODE=local
export SPECL00M_STORAGE_MODE=memory
~~~

On PowerShell:

~~~powershell
$env:SPECL00M_ARCHITECT_MODE="showcase"
$env:SPECL00M_CONTEXT_MODE="deterministic"
$env:SPECL00M_RUNTIME_MODE="local"
$env:SPECL00M_STORAGE_MODE="memory"
~~~

The values also appear in backend/.env.example.

The deterministic architect is a local fallback and testing path. The generic production architecture path is model-backed.

---

# Bedrock-backed mode

Install the AWS/model dependencies:

~~~bash
python -m pip install -r backend/requirements-aws.txt
~~~

Verify your AWS credentials:

~~~bash
aws sts get-caller-identity
~~~

Then configure:

~~~bash
export SPECL00M_ARCHITECT_MODE=bedrock
export SPECL00M_CONTEXT_MODE=bedrock
export SPECL00M_RUNTIME_MODE=bedrock
export SPECL00M_STORAGE_MODE=memory
export SPECL00M_BEDROCK_MODEL_ID=amazon.nova-lite-v1:0
export SPECL00M_ALLOWED_BEDROCK_MODELS=amazon.nova-lite-v1:0
export AWS_REGION=ap-south-1
~~~

The Bedrock architect produces Workflow IR through the Strands SDK. Specloom then applies deterministic workflow validation, architecture coverage validation, and capability-binding validation.

---

# Running the demo

The Demo Gallery is a **problem starter**, not a prerecorded result.

~~~text
Demo Gallery
    ↓
Choose a real problem
    ↓
Normal Build / New System flow
    ↓
Specloom generates Workflow IR
    ↓
Validation + tests
    ↓
Run now
    ↓
Normal runtime execution
    ↓
Human approval when required
    ↓
Execution trace + result
~~~

Bundled starters:

### ResearchHunter
Research recent AI developments, judge relevance, require approval, and prepare a GitHub issue.

### Support Triage
Classify a customer request, draft a response, and route an explicitly urgent case through approval.

### Document Brief
Process supplied document content, extract key facts and decisions, verify important claims, and produce an executive brief.

The demo payloads are **synthetic but concrete**. The build and runtime calls are the same product APIs used outside the gallery.

---

# Simulation vs runtime

### Simulation

~~~text
POST /api/v1/projects/{project_id}/simulate
~~~

The simulator executes Workflow IR with mock/sandbox tool behavior and records a simulation run.

### Runtime

~~~text
POST /api/v1/projects/{project_id}/run
~~~

The runtime executes Workflow IR through the configured execution path:

- local RuntimeExecutor;
- Strands + Amazon Bedrock;
- SageMaker adapter;
- durable Step Functions execution.

Side-effecting tools remain policy-gated.

---

# API overview

| Area | Endpoint |
|---|---|
| Health | GET /health |
| Demo starters | GET /api/v1/demos |
| Example workflow | GET /api/v1/workflow/example |
| Project | GET /api/v1/projects/{id} |
| Build | POST /api/v1/projects/{id}/build |
| Autonomous build | POST /api/v1/projects/{id}/autobuild |
| Context | GET /api/v1/projects/{id}/context |
| Add text context | POST /api/v1/projects/{id}/context/text |
| Add URL context | POST /api/v1/projects/{id}/context/url |
| Add file context | POST /api/v1/projects/{id}/context/file |
| Evaluate | POST /api/v1/projects/{id}/evaluate |
| Simulate | POST /api/v1/projects/{id}/simulate |
| Runtime | POST /api/v1/projects/{id}/run |
| Trigger | POST /api/v1/projects/{id}/trigger |
| Run history | GET /api/v1/projects/{id}/runs |
| Run detail | GET /api/v1/projects/{id}/runs/{run_id} |
| Durable approvals | GET /api/v1/projects/{id}/durable/approvals |
| Workflow versions | GET /api/v1/projects/{id}/versions |
| Node mode | PATCH /api/v1/projects/{id}/nodes/{node_id}/mode |
| Provenance | GET /api/v1/projects/{id}/provenance |
| Artifacts | GET /api/v1/projects/{id}/artifacts |
| Deployment plan | GET /api/v1/projects/{id}/deploy/plan |

The authoritative request/response contract is the generated OpenAPI schema at /docs.

---

# AWS deployment

The **canonical production SAM stack** is:

~~~text
infra/aws/template.yaml
~~~

Deploy it with:

~~~bash
./infra/aws/deploy.sh
~~~

The compatibility wrapper is:

~~~bash
./scripts/deploy-aws.sh
~~~

and delegates to the same canonical stack.

The SAM stack provisions:

- API Gateway;
- Lambda + Mangum;
- Cognito User Pool and client;
- DynamoDB project state;
- DynamoDB durable approvals;
- S3 source/artifact storage;
- EventBridge scheduling;
- IAM permissions for Bedrock, SageMaker, Step Functions, DynamoDB, and S3;
- the durable Step Functions execution role.

The application can create/update a Standard Step Functions state machine for a project at runtime. The state machine is generated from Workflow IR rather than being one fixed workflow.

### Read deployment outputs

~~~bash
aws cloudformation describe-stacks \
  --stack-name specloom \
  --query 'Stacks[0].Outputs' \
  --output table
~~~

Use the ApiUrl output to configure the frontend as VITE_API_BASE_URL.

Then:

~~~bash
cd frontend
npm install
npm run build
~~~

The repository also contains infra/aws/amplify.yml for an Amplify static frontend build.

> **Deployment note:** the repository is deployment-ready, but an actual AWS deployment still depends on your AWS account, credentials, region, permissions, and enabled model/service access.

See [docs/AWS.md](docs/AWS.md) for the detailed deployment runbook.

---

# Security and execution policy

Specloom treats external capabilities as an explicit boundary.

- Tools are registered and allowlisted.
- Side-effecting tools are explicitly marked.
- Write-capable tool nodes require policy references.
- Human approval nodes can pause workflows before writes.
- Agent nodes cannot directly use side-effecting capabilities.
- Loops have explicit maximum iterations.
- Credentials are loaded from environment/configuration rather than generated into prompts.
- Cognito/workspace authentication is available and enabled by default in the AWS SAM template.
- Workflow repair is bounded to IR/configuration changes.
- Live HTTP adapters reject URLs resolving to non-public address ranges.

---

# Testing

Backend:

~~~bash
python -m pytest -q
~~~

Frontend:

~~~bash
cd frontend
npm run build
~~~

CI runs both on pull requests and pushes to main.

The backend CI uses Python 3.11 and deterministic local runtime/storage settings so the test suite does not require AWS credentials.

---

# Documentation map

- [Architecture](docs/ARCHITECTURE.md)
- [Development](docs/DEVELOPMENT.md)
- [AWS](docs/AWS.md)
- [Product](docs/PRODUCT.md)
- [Workflow IR schema](schemas/workflow-ir.schema.json)
- [SoftwareSpec schema](schemas/software-spec.schema.json)
- [Context Graph schema](schemas/context-graph.schema.json)

---

# Implementation status

### Implemented

- Workflow IR v0.1 + JSON Schema;
- Context Graph + provenance;
- text, URL, PDF, and GitHub repository context paths;
- deterministic and Bedrock-backed context analysis;
- context gap detection;
- problem decomposition;
- capability discovery, binding, and synthesis;
- deterministic workflow and architecture validation;
- simulation and runtime execution;
- Strands + Bedrock architecture path;
- Strands + Bedrock runtime runner;
- live web, URL, and GitHub adapters;
- configured API/OpenAPI capability paths;
- read-only MCP capability boundary;
- requirement-oriented test generation/evaluation;
- bounded IR repair;
- generated implementation/specification/deployment artifacts;
- artifact retrieval and immutable snapshots;
- memory and AWS persistence adapters;
- durable Step Functions execution manager;
- durable approval persistence;
- optional Cognito/workspace authentication;
- React/Vite engineering workspace;
- system graph, context, tests, deploy, provenance, versions, run history, and approvals UI;
- AWS SAM control plane;
- Amplify frontend configuration;
- GitHub Actions CI.

### Environment-dependent

- real Bedrock architecture/runtime requires AWS credentials and model access;
- Cognito mode requires a valid User Pool issuer/client;
- durable Step Functions execution needs the configured IAM roles/functions;
- live GitHub writes need a GitHub token and repository configuration;
- configured third-party APIs require their own endpoint/authentication values.

---

# Design principles

### One canonical graph
Workflow IR is the execution graph. The frontend does not maintain a second workflow schema.

### Probability at the edge, determinism at the boundary
Models handle ambiguous language and architecture proposals. Validators, capability binding, and policy logic control admissible execution.

### Provenance is first-class
Requirements, constraints, and generated nodes can be traced back to contextual evidence.

### Repair the representation
The repair loop prefers constrained IR/configuration changes and creates new workflow versions instead of unrestricted self-modifying source.

### Synthetic data, real product path
The demos use synthetic inputs for repeatability, but use the same build, validation, runtime, approval, and trace surfaces as ordinary systems.

---

# License

No open-source license is currently declared in the repository. Check the project owner's distribution terms before redistributing the code.
