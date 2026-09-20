# Specloom Architecture

This document describes the architecture implemented in the repository, not only the intended future design.

## 1. Architectural model

Specloom is divided into four logical planes:

1. **Experience plane** — React/Vite engineering workspace.
2. **Control plane** — FastAPI APIs plus context, compiler, validation, evaluation, repair, and deployment orchestration.
3. **Execution plane** — Workflow IR runtime executors, Strands/Bedrock, tool gateway, and durable Step Functions execution.
4. **Infrastructure plane** — local memory or AWS persistence plus API Gateway, Lambda, Cognito, S3, DynamoDB, EventBridge, and AWS IAM.

The Workflow IR is the canonical execution graph.

## 2. End-to-end architecture

~~~mermaid
flowchart TB
    USER[User]
    UI[React + Vite]
    API[FastAPI Control Plane]

    subgraph BUILD[Build pipeline]
        INGEST[Context ingestion]
        GRAPH[Context Graph]
        GAP[Gap detector]
        DECOMP[Problem decomposition]
        ARCH[Architect]
        COMP[Universal Compiler]
        VALID[Workflow + policy validation]
        EVAL[Tests + evaluation]
        REPAIR[Bounded repair]
        ART[Artifacts + deployment plan]

        INGEST --> GRAPH --> GAP --> DECOMP --> ARCH --> COMP --> VALID
        VALID --> EVAL
        EVAL --> REPAIR
        REPAIR --> VALID
        EVAL --> ART
    end

    subgraph RUN[Execution]
        LOCAL[Runtime Executor]
        BEDA[Bedrock Agent Runner]
        SAGE[SageMaker Runner]
        DUR[Durable Workflow Manager]
        TOOL[Tool Gateway]
        HUMAN[Human approval]
    end

    subgraph CAP[Capabilities]
        WEB[Web search]
        URL[URL fetch]
        GH[GitHub]
        APIOPS[Configured API / OpenAPI]
        MCP[Read-only MCP]
    end

    subgraph AWS[AWS]
        APIGW[API Gateway]
        LAMBDA[Lambda + Mangum]
        COG[Cognito]
        DDB[(DynamoDB)]
        S3[(S3)]
        EB[EventBridge]
        SFN[Standard Step Functions]
        BED[Bedrock]
    end

    USER --> UI --> API
    API --> BUILD
    API --> RUN
    API --> DDB
    API --> S3

    LOCAL --> TOOL
    BEDA --> BED
    BEDA --> TOOL
    TOOL --> WEB
    TOOL --> URL
    TOOL --> GH
    TOOL --> APIOPS
    TOOL --> MCP
    TOOL --> HUMAN

    DUR --> SFN
    SFN --> LAMBDA
    DUR --> HUMAN

    APIGW --> LAMBDA --> API
    COG -. JWT authentication .-> APIGW
    EB --> LAMBDA
~~~

## 3. Experience plane

The frontend is deliberately an engineering workspace instead of a chat-first client.

Main surfaces include:

- Build / New system;
- Context;
- System graph;
- Tests;
- Deploy;
- Run history;
- Node inspection;
- Provenance;
- Human approval actions.

The UI consumes the canonical Workflow IR returned by the API and converts it to a React Flow canvas representation only for rendering.

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
- simulation;
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
    SRC[Text / PDF / URL / GitHub] --> INGEST[Ingestion]
    INGEST --> RAW[Stored source content]
    INGEST --> ANALYZE[Context analysis]
    ANALYZE --> REQ[Requirements]
    ANALYZE --> CON[Constraints]
    ANALYZE --> ENT[Entities]
    ANALYZE --> TOOL[Tools / capabilities]
    ANALYZE --> EX[Examples]
    ANALYZE --> PROV[Provenance]
    REQ --> GRAPH[Context Graph]
    CON --> GRAPH
    ENT --> GRAPH
    TOOL --> GRAPH
    EX --> GRAPH
    PROV --> GRAPH
~~~

The implementation supports both deterministic analysis and a Bedrock-backed context analyzer.

Gap detection runs against the current graph. Build answers are ingested as context with provenance instead of being held only in frontend state.

## 6. Architecture generation

ConfiguredArchitect selects:

- **showcase** — deterministic local fallback;
- **bedrock** — Strands + Amazon Bedrock architect.

The Bedrock architect returns Workflow IR v0.1. Before acceptance, the control plane validates:

1. Workflow IR structure;
2. architecture coverage;
3. capability bindings.

The Bedrock architect also supports bounded repair/revision attempts when model output fails validation.

## 7. Universal compiler

The compiler is the project-wide synthesis layer under backend/compiler.

Major responsibilities include:

~~~text
decomposition.py       problem decomposition
architecture_search.py architecture hypothesis search
capability_discovery.py open-world capability discovery
capability_autobind.py  capability binding
contracts.py            capability contracts
universal.py            SoftwareSpec + workflow compilation
implementation.py       implementation planning/materialization
codegen.py              generated artifacts
deployment.py           deployment planning
infrastructure.py       infrastructure planning
acceptance.py           acceptance criteria
benchmark.py            benchmarking
recovery.py             recovery planning
repair.py               bounded IR repair
repository.py           generated repository artifacts
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

## 9. Execution plane

There are two related but distinct execution paths.

### Local RuntimeExecutor

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
- passes Workflow IR payload into the agent role.

### DurableWorkflowManager

backend/runtime/durable.py compiles a Workflow IR into a Standard Step Functions state machine definition.

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
- executes mock/sandbox mode without external writes;
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
flowchart TB
    USER[Browser]
    COG[Cognito]
    API[API Gateway]
    LAMBDA[Lambda / Mangum]
    DDB[(DynamoDB)]
    S3[(S3)]
    EB[EventBridge]
    SFN[Step Functions]
    BED[Bedrock]

    USER --> API
    COG -. JWT .-> API
    API --> LAMBDA
    EB --> LAMBDA
    LAMBDA --> DDB
    LAMBDA --> S3
    LAMBDA --> BED
    LAMBDA --> SFN
    SFN --> LAMBDA
~~~

The template currently provisions:

- API Gateway;
- Lambda;
- Cognito User Pool + client;
- project DynamoDB table;
- durable approval DynamoDB table;
- S3 bucket;
- EventBridge schedule;
- IAM roles/policies.

It does **not** pre-create a state machine for every project. DurableWorkflowManager creates/updates the required Standard state machine dynamically.

## 13. Security model

The security architecture follows a simple rule:

**Model-generated intent is not equivalent to permission.**

Permission is established through:

- registered/allowlisted capabilities;
- capability bindings;
- tool side-effect classification;
- policy references;
- human approval;
- Cognito authentication;
- workspace identity;
- bounded execution.

Production credentials are not placed in the model prompt or Workflow IR.

## 14. Demo architecture

The Demo Gallery follows the same product flow as an ordinary build.

~~~mermaid
flowchart LR
    D[Demo problem starter] --> B[Normal Build dialog]
    B --> A[Architect]
    A --> V[Workflow IR + validation]
    V --> T[Tests]
    T --> R[Run now]
    R --> X[Normal runtime]
    X --> H[Approval when required]
    H --> O[Output + trace]
~~~

Demo inputs are synthetic for repeatability. They are not prerecorded outputs or a separate demo execution engine.

## 15. Important implementation boundaries

### Production-ready infrastructure vs deployed infrastructure

The repository contains a production-oriented SAM control plane, but infrastructure is only actually deployed when an AWS account executes the deployment.

### AgentCore

infra/agentcore contains an AgentCore runtime entrypoint/scaffold. The canonical SAM deployment currently uses the FastAPI/Lambda control plane and the application's durable/runtime adapters.

### Simulation

Simulation is intentionally distinct from live runtime execution. It is the safe path for testing Workflow IR and policy behavior before external side effects are enabled.

### Generated source

The compiler can materialize implementation artifacts, but generated source is not implicitly executed merely because it was generated. Runtime execution remains controlled by Workflow IR and the configured runtime.

---

## Architectural summary

~~~text
User goal/context
       ↓
Context Graph
       ↓
Problem decomposition + gap resolution
       ↓
Architect / compiler
       ↓
Workflow IR
       ↓
Deterministic validation + policy
       ↓
Tests / evaluation / repair
       ↓
Artifacts / deployment plan
       ↓
Runtime
  ├── local
  ├── Bedrock
  ├── SageMaker
  └── durable Step Functions
       ↓
Policy-aware tools + approvals
       ↓
Execution trace + output
~~~
