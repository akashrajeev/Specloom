# Specloom Architecture

This document describes the architecture implemented in the repository, including the boundaries between context, compilation, policy, execution, and infrastructure.

## 1. Architectural model

Specloom is divided into four logical planes:

1. **Experience plane** — React/Vite engineering workspace.
2. **Control plane** — FastAPI APIs plus context, compiler, validation, evaluation, repair, and deployment orchestration.
3. **Execution plane** — Workflow IR runtime executors, Strands/Bedrock, tool gateway, and durable Step Functions execution.
4. **Infrastructure plane** — local memory or AWS persistence plus API Gateway, Lambda, Cognito, S3, DynamoDB, EventBridge, and IAM.

The Workflow IR is the canonical execution graph. The browser renders that graph; it does not create a second workflow model.

## 2. End-to-end architecture

The main architecture is intentionally laid out as a left-to-right pipeline. Cross-plane dependencies are dotted so the primary control flow stays visually distinct from infrastructure wiring.

~~~mermaid
flowchart LR
    USER((User)) --> UI[React / Vite Workspace]

    subgraph CONTROL["Control Plane"]
        direction LR
        API[FastAPI API]
        CTX[Context Graph]
        GAP[Gap Detection]
        DEC[Problem Decomposition]
        ARC[Architect]
        COMP[Universal Compiler]
        IR[Workflow IR]
        VAL[Validation + Policy]

        API --> CTX --> GAP --> DEC --> ARC --> COMP --> IR --> VAL
    end

    UI --> API

    subgraph EXEC["Execution Plane"]
        direction TB
        RUN[Runtime]
        GATE[Policy-aware Tool Gateway]
        CAP[Web / URL / GitHub / OpenAPI / MCP]
        HUMAN[Human Approval]
        TRACE[Execution Trace + Output]

        RUN --> GATE
        GATE --> CAP
        GATE --> HUMAN
        RUN --> TRACE
        HUMAN --> TRACE
    end

    VAL --> RUN

    subgraph INFRA["AWS Infrastructure"]
        direction TB
        EDGE[API Gateway]
        LAMBDA[Lambda + Mangum]
        AUTH[Cognito]
        MODEL[Amazon Bedrock]
        SFN[Standard Step Functions]
        DATA[(DynamoDB + S3)]

        EDGE --> LAMBDA
        LAMBDA --> MODEL
        LAMBDA --> SFN
        LAMBDA --> DATA
        AUTH -.-> EDGE
    end

    EDGE -. ingress .-> API
    RUN -. model calls .-> MODEL
    RUN -. durable execution .-> SFN
    API -. persistence .-> DATA
~~~

### Primary request flow

~~~text
User
  ↓
React workspace
  ↓
FastAPI control plane
  ↓
Context Graph
  ↓
Problem decomposition
  ↓
Architect
  ↓
Universal Compiler
  ↓
Workflow IR
  ↓
Deterministic validation + policy
  ↓
Runtime
  ↓
Execution trace + output
~~~

## 3. Experience plane

The frontend is an engineering workspace rather than a chat-first client.

Main surfaces include:

- Build / New System;
- Context;
- System graph;
- Tests;
- Deploy;
- Run history;
- Node inspection;
- Provenance;
- Human approval actions.

The UI consumes the canonical Workflow IR returned by the API and converts it to a React Flow representation only for rendering.

Important source files:

~~~text
frontend/src/App.tsx
frontend/src/api.ts
frontend/src/components/BuildDialog.tsx
frontend/src/components/ContextDialog.tsx
frontend/src/components/RunDetailDialog.tsx
frontend/src/components/RunHistory.tsx
frontend/src/components/ProvenancePanel.tsx
frontend/src/components/DeployView.tsx
frontend/src/styles.css
~~~

## 4. Control plane

The FastAPI application is created in backend/main.py.

It wires together:

- context APIs;
- artifact APIs;
- deployment APIs;
- project APIs;
- build/compiler APIs;
- evaluation;
- runtime;
- provenance;
- run history;
- node configuration;
- workflow versioning.

The main build path lives in backend/api/build.py. It coordinates context analysis, gaps, decomposition, capability discovery, architecture, compilation, verification, repair, and deployment planning.

## 5. Context Graph

The context layer separates raw source content from normalized facts.

~~~mermaid
flowchart LR
    S[Text / PDF / URL / GitHub] --> I[Ingestion]
    I --> R[Stored source]
    I --> A[Context analysis]

    A --> REQ[Requirements]
    A --> CON[Constraints]
    A --> ENT[Entities]
    A --> CAP2[Capabilities]
    A --> EX[Examples]
    A --> PROV[Provenance]

    REQ --> G[Context Graph]
    CON --> G
    ENT --> G
    CAP2 --> G
    EX --> G
    PROV --> G
~~~

The implementation supports deterministic analysis and a Bedrock-backed context analyzer.

Gap detection runs against the current graph. Answers to detected gaps are ingested as contextual evidence with provenance so they can affect subsequent planning.

## 6. Architecture generation

ConfiguredArchitect selects:

- **showcase** — deterministic local fallback;
- **bedrock** — Strands + Amazon Bedrock architect.

The Bedrock architect returns Workflow IR v0.1. Before acceptance, the control plane validates:

1. Workflow IR structure;
2. architecture coverage;
3. capability bindings.

Bounded repair/revision attempts can be made when model output fails validation.

## 7. Universal compiler

The universal compiler is the project-wide synthesis layer under backend/compiler.

Major responsibilities include:

~~~text
decomposition.py        problem decomposition
architecture_search.py  architecture hypothesis search
capability_discovery.py open-world capability discovery
capability_autobind.py  capability binding
contracts.py             capability contracts
universal.py             SoftwareSpec + workflow compilation
implementation.py        implementation planning/materialization
codegen.py               generated artifacts
deployment.py            deployment planning
infrastructure.py        infrastructure planning
acceptance.py            acceptance criteria
benchmark.py             benchmarking
recovery.py              recovery planning
repair.py                bounded IR repair
repository.py            generated repository artifacts
~~~

The compiler can represent missing external capabilities as synthesized capabilities with explicit contracts and provisioning requirements instead of silently inventing credentials or undocumented behavior.

## 8. Workflow IR

Workflow IR contains:

~~~text
metadata
trigger
nodes
edges
variables
policies
tests
~~~

The validator enforces:

- unique IDs;
- valid node types;
- valid references;
- valid graph edges;
- terminal output requirements;
- bounded loops;
- allowed models;
- allowed MCP servers;
- policy references;
- tool permission boundaries;
- requirement coverage;
- constraint coverage;
- decomposition coverage;
- capability availability.

See schemas/workflow-ir.schema.json.

### Compiler lifecycle

~~~mermaid
flowchart LR
    START[Goal + Context] --> UNDERSTAND[Understand]
    UNDERSTAND --> GAP{Blocking gap?}
    GAP -- yes --> CLARIFY[Clarify]
    CLARIFY --> UNDERSTAND
    GAP -- no --> ARCH2[Architect]
    ARCH2 --> IR2[Workflow IR]
    IR2 --> CHECK[Validate]
    CHECK -- fail --> FIX[Bounded repair]
    FIX --> IR2
    CHECK -- pass --> TEST[Evaluate]
    TEST -- fail --> FIX
    TEST -- pass --> ART[Compile artifacts]
    ART --> DEP[Deploy]
    DEP --> EXEC2[Run]
~~~

## 9. Execution plane

### Runtime Executor

backend/runtime/executor.py interprets the graph directly.

It implements:

- trigger handling;
- agent execution;
- tool execution;
- human approval;
- conditions;
- bounded loops;
- parallel fan-out/fan-in;
- terminal output;
- execution events.

### BedrockAgentRunner

backend/runtime/bedrock_runner.py creates a Strands Agent backed by Amazon Bedrock.

It:

- validates requested models against an allowlist;
- prevents agent nodes from directly using side-effecting tools;
- attaches only explicitly requested read-capable tools;
- supports read-only MCP clients;
- passes Workflow IR context into the agent role.

### DurableWorkflowManager

backend/runtime/durable.py compiles Workflow IR into a Standard Step Functions state machine definition.

It can:

- validate the generated state machine definition through AWS;
- create or update a state machine;
- start executions;
- inspect execution history;
- persist approval callback tokens;
- resume work after human approval.

The SAM template supplies the IAM role and function permissions; project-specific state machines are managed by the application.

## 10. Tool boundary

backend/tools/gateway.py is the policy-aware boundary between Workflow IR and external effects.

The gateway:

- checks whether a capability is side-effecting;
- blocks writes without approval;
- executes mock or sandbox modes without external writes;
- dispatches live calls to registered adapters;
- supports native tools, OpenAPI capabilities, and synthesized capabilities.

Registered native adapters currently include:

~~~text
web_search
url_fetch
github.get_repo
github.list_issues
github.search_code
github.create_issue
~~~

The live HTTP adapter also rejects URLs resolving to private or otherwise non-public address ranges.

## 11. Persistence

The repository abstraction is selected by backend/storage/factory.py.

### Local

MemoryRepository keeps project state in process for fast deterministic development.

### AWS

AwsProjectRepository stores:

- project metadata;
- current Workflow IR;
- workflow versions;
- normalized Context Graph;
- run history

in DynamoDB, while source documents and generated artifacts are stored in S3.

Artifact snapshots are stored as immutable S3 manifests.

## 12. AWS control plane

The canonical infrastructure is infra/aws/template.yaml.

~~~mermaid
flowchart LR
    CLIENT[Browser / Client] --> EDGE[API Gateway]
    AUTH[Cognito] -. JWT .-> EDGE
    EDGE --> LAMBDA[Lambda + Mangum]

    LAMBDA --> DB[(DynamoDB)]
    LAMBDA --> STORAGE[(S3)]
    LAMBDA --> BEDROCK[Bedrock]
    LAMBDA --> SFS[Step Functions]
    SCHEDULE[EventBridge] --> LAMBDA
~~~

The template provisions:

- API Gateway;
- Lambda;
- Cognito User Pool + client;
- project DynamoDB table;
- durable approval DynamoDB table;
- S3 bucket;
- EventBridge schedule;
- IAM roles/policies.

It does **not** pre-create a state machine for every project. DurableWorkflowManager creates or updates the required Standard state machine dynamically.

## 13. Security model

The security architecture follows a simple rule:

**Model-generated intent is not equivalent to permission.**

Permission is established through:

- registered and allowlisted capabilities;
- capability bindings;
- tool side-effect classification;
- policy references;
- human approval;
- Cognito authentication;
- workspace identity;
- bounded execution.

Production credentials are not placed in the model prompt or Workflow IR.

## 14. Runtime boundary

~~~mermaid
flowchart LR
    IR3[Validated Workflow IR] --> EXEC3[Runtime]
    INPUT[Runtime input] --> EXEC3

    EXEC3 --> AGENT[Agent node]
    EXEC3 --> TOOL[Tool node]
    EXEC3 --> HUMAN3[Human approval]
    EXEC3 --> OUT[Terminal output]

    AGENT --> MODEL3[Bedrock model]
    TOOL --> GATE3[Tool Gateway]

    GATE3 --> READ[Read capability]
    GATE3 --> WRITE[Write capability]
    WRITE --> POLICY[Policy + approval]
    HUMAN3 --> POLICY
~~~

The runtime never treats a model-generated tool choice as an authorization by itself.

## 15. Implementation boundaries

### Production infrastructure vs deployed infrastructure

The repository contains a production-oriented SAM control plane, but infrastructure is only deployed when an AWS account executes the deployment.

### AgentCore

infra/agentcore contains an AgentCore runtime entrypoint/scaffold. The canonical SAM deployment uses the FastAPI/Lambda control plane and the application's runtime adapters.

### Generated source

The compiler can materialize implementation artifacts, but generated source is not implicitly executed merely because it was generated. Runtime execution remains controlled by Workflow IR and the configured runtime.

---

## Architectural summary

~~~text
Goal + context
     ↓
Context Graph
     ↓
Gap resolution + decomposition
     ↓
Architect
     ↓
Universal Compiler
     ↓
Workflow IR
     ↓
Deterministic validation + policy
     ↓
Evaluation + bounded repair
     ↓
Artifacts + deployment plan
     ↓
Runtime
  ├── local
  ├── Bedrock
  ├── SageMaker
  └── Standard Step Functions
     ↓
Policy-aware capabilities + approvals
     ↓
Execution trace + output
~~~
