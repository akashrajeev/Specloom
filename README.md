# Specloom

> **Give it a problem. Specloom architects the system.**

[![CI](https://github.com/akashrajeev/Specloom/actions/workflows/ci.yml/badge.svg)](https://github.com/akashrajeev/Specloom/actions/workflows/ci.yml)

Specloom is an **agentic system compiler**. A user provides a goal and the context available to the system; Specloom turns that intent into a structured, validated, executable workflow and the artifacts required to operate it.

**Goal + Context → Understand → Architect → Validate → Evaluate → Repair → Deploy → Run**

The **Workflow IR** is the execution-control source of truth. Model output is treated as a proposal; deterministic compiler, capability, and policy checks decide whether that proposal is admissible.

---

## What Specloom does

A system build can start with a problem such as:

> Create a support triage system that classifies customer requests, drafts helpful responses, and requires human review for urgent cases.

Specloom can then:

1. ingest context from text, URLs, PDFs, and repository sources;
2. extract requirements, constraints, entities, capabilities, examples, and provenance;
3. detect missing information that could change behavior, permissions, safety, or correctness;
4. decompose the problem into executable steps;
5. use the configured architect to produce Workflow IR;
6. bind workflow nodes to available or synthesized capabilities;
7. validate graph structure, requirements, constraints, tools, policies, loops, and outputs;
8. compile inspectable implementation, specification, and deployment artifacts;
9. generate requirement-oriented evaluation;
10. diagnose failures and apply bounded IR repairs;
11. deploy through the selected target;
12. execute the workflow and record an execution trace.

The key architectural boundary is:

**The model proposes architecture; the compiler and runtime control execution.**

---

# Architecture

## End-to-end system

The system is organized as four cooperating planes. The diagram keeps the data path left-to-right and the infrastructure dependencies separate so the architecture remains readable.

~~~mermaid
flowchart LR
    U((User)) --> UI[React / Vite Workspace]

    subgraph CONTROL["Specloom Control Plane"]
        direction LR
        API[FastAPI API]
        CTX[Context Graph]
        DEC[Decomposition]
        ARC[Architect]
        COMP[Universal Compiler]
        IR[Workflow IR]
        VAL[Validation + Policy]
        API --> CTX --> DEC --> ARC --> COMP --> IR --> VAL
    end

    UI --> API

    subgraph EXEC["Execution Plane"]
        direction TB
        RUN[Runtime]
        GATE[Policy-aware Tool Gateway]
        CAP[Web · URL · GitHub · OpenAPI · MCP]
        APP[Human Approval]
        TRACE[Execution Trace + Output]
        RUN --> GATE --> CAP
        GATE --> APP
        RUN --> TRACE
        APP --> TRACE
    end

    VAL --> RUN

    subgraph AWS["AWS Infrastructure"]
        direction TB
        EDGE[API Gateway]
        LAMBDA[Lambda + Mangum]
        BED[Amazon Bedrock]
        SFN[Standard Step Functions]
        DATA[(DynamoDB + S3)]
        ID[Cognito]
        EDGE --> LAMBDA
        LAMBDA --> BED
        LAMBDA --> SFN
        LAMBDA --> DATA
        ID -. authentication .-> EDGE
    end

    EDGE --> API
    RUN -. model execution .-> BED
    RUN -. durable execution .-> SFN
    API -. persistence .-> DATA
~~~

### Compiler lifecycle

~~~mermaid
flowchart LR
    GOAL[Goal + Context]
    GOAL --> UNDERSTAND[Understand]
    UNDERSTAND --> GAP{Blocking gap?}
    GAP -- yes --> CLARIFY[Clarify]
    CLARIFY --> UNDERSTAND
    GAP -- no --> DESIGN[Architect]
    DESIGN --> IR2[Workflow IR]
    IR2 --> CHECK[Deterministic validation]
    CHECK -- fail --> REPAIR[Bounded repair]
    REPAIR --> IR2
    CHECK -- pass --> EVAL[Evaluation]
    EVAL -- fail --> REPAIR
    EVAL -- pass --> BUILD[Compile artifacts]
    BUILD --> DEPLOY[Deploy]
    DEPLOY --> RUN2[Run]
    RUN2 --> OBS[Trace + output]
~~~

### Runtime safety boundary

~~~mermaid
flowchart LR
    IR3[Validated Workflow IR] --> EXEC2[Runtime]
    INPUT[Runtime input] --> EXEC2
    EXEC2 --> AGENT[Agent node]
    EXEC2 --> TOOL[Tool node]
    EXEC2 --> HUMAN[Human approval]
    EXEC2 --> OUT[Output]
    AGENT --> MODEL[Bedrock model]
    TOOL --> GATE2[Tool Gateway]
    GATE2 --> READ[Read capability]
    GATE2 --> WRITE[Write capability]
    WRITE --> POLICY[Policy + approval]
    HUMAN --> POLICY
    POLICY --> WRITE
~~~

### Architectural invariant

**Model-generated intent is not equivalent to permission.**

External effects are bounded by schema validation, graph validation, capability binding, tool permissions, policy references, approval gates, and bounded execution controls.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the implementation-level breakdown.

---

# Core concepts

### Context Graph

The Context Graph is Specloom's normalized representation of what the system knows about a project:

- sources;
- requirements;
- constraints;
- entities;
- capabilities;
- examples;
- provenance;
- problem decomposition.

Source material is ingested and normalized before architecture generation. Requirements and constraints retain provenance back to source material where available.

### Workflow IR

Workflow IR describes what the system will do.

| Node | Purpose |
|---|---|
| trigger | manual, scheduled, webhook, or event start |
| agent | bounded model reasoning with explicit tools/output |
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
│   ├── agents/          # Architects and reviewers
│   ├── api/             # FastAPI control-plane endpoints
│   ├── capabilities/    # Capability contracts and binding logic
│   ├── compiler/        # Universal software/compiler pipeline
│   ├── context/         # Ingestion, analysis, gaps, provenance
│   ├── evaluation/      # Test generation and evaluation
│   ├── runtime/         # Local, Bedrock, SageMaker, durable execution
│   ├── security/        # Authentication and workspace isolation
│   ├── storage/         # Memory and AWS persistence
│   ├── tools/           # Registry, gateway, adapters, APIs, MCP
│   └── workflow/        # Workflow IR, compilation, validation
├── frontend/
│   ├── src/App.tsx      # Main engineering workspace
│   ├── src/api.ts       # Typed API client
│   └── src/components/  # Build, context, run, deploy, provenance UI
├── schemas/             # Workflow IR, Context Graph, SoftwareSpec
├── examples/            # Workflow fixtures and reference systems
├── infra/
│   ├── aws/             # Canonical AWS SAM control plane
│   └── agentcore/       # AgentCore runtime entrypoint/scaffold
├── tests/               # Backend/compiler/runtime/security tests
├── docs/                # Architecture and operational documentation
├── requirements.txt     # Root Python dependency entrypoint
├── samconfig.toml       # SAM deployment defaults
└── Makefile             # Development helpers
~~~

---

# Quick start

## Prerequisites

Recommended versions:

- Python **3.11**;
- Node.js/npm (CI currently uses Node 24);
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

The frontend defaults to the backend at http://localhost:8000. Set VITE_API_BASE_URL to point at another API.

---

# Local development

For a fully local deterministic configuration:

~~~bash
export SPECL00M_ARCHITECT_MODE=showcase
export SPECL00M_CONTEXT_MODE=deterministic
export SPECL00M_RUNTIME_MODE=local
export SPECL00M_STORAGE_MODE=memory
~~~

PowerShell:

~~~powershell
$env:SPECL00M_ARCHITECT_MODE="showcase"
$env:SPECL00M_CONTEXT_MODE="deterministic"
$env:SPECL00M_RUNTIME_MODE="local"
$env:SPECL00M_STORAGE_MODE="memory"
~~~

These settings provide a repeatable local engineering path without AWS credentials.

The generic production architecture path is model-backed.

---

# Bedrock-backed mode

Install the AWS/model dependencies:

~~~bash
python -m pip install -r backend/requirements-aws.txt
~~~

Verify credentials:

~~~bash
aws sts get-caller-identity
~~~

Configure:

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

# API overview

The FastAPI control plane exposes the main lifecycle under /api/v1.

| Area | Endpoint |
|---|---|
| Health | GET /health |
| Config | GET /api/v1/config |
| Example workflow | GET /api/v1/workflow/example |
| Project | GET /api/v1/projects/{id} |
| Build | POST /api/v1/projects/{id}/build |
| Autonomous build | POST /api/v1/projects/{id}/autobuild |
| Context | GET /api/v1/projects/{id}/context |
| Add text context | POST /api/v1/projects/{id}/context/text |
| Add URL context | POST /api/v1/projects/{id}/context/url |
| Add file context | POST /api/v1/projects/{id}/context/file |
| Evaluate | POST /api/v1/projects/{id}/evaluate |
| Repair | POST /api/v1/projects/{id}/repair |
| Apply repair | POST /api/v1/projects/{id}/repair/apply |
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

The authoritative request/response contract is the FastAPI OpenAPI schema available at /docs.

See [docs/API.md](docs/API.md) for the endpoint-level reference.

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

The compatibility wrapper:

~~~bash
./scripts/deploy-aws.sh
~~~

delegates to the same canonical stack.

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

The application can create/update a Standard Step Functions state machine for a project at runtime. The state machine is derived from Workflow IR rather than being one fixed workflow.

Read deployment outputs:

~~~bash
aws cloudformation describe-stacks \
  --stack-name specloom \
  --query 'Stacks[0].Outputs' \
  --output table
~~~

Use the ApiUrl output as VITE_API_BASE_URL for the frontend.

See [docs/AWS.md](docs/AWS.md) for the deployment runbook.

> **Deployment note:** the repository is deployment-ready, but a successful deployment still depends on the target AWS account, credentials, region, IAM permissions, and enabled model/service access.

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

Backend CI uses Python 3.11 and deterministic local settings so the suite does not require an AWS account.

---

# Documentation

- [Architecture](docs/ARCHITECTURE.md)
- [Development](docs/DEVELOPMENT.md)
- [API Reference](docs/API.md)
- [AWS Deployment](docs/AWS.md)
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

### Production path first

The same compiler, policy boundary, runtime, persistence, and observability concepts are used from local development through AWS deployment.

---

# License

No open-source license is currently declared in the repository. Check the project owner's distribution terms before redistributing the source.
