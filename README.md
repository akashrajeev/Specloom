# Specloom

> Give it the context. It builds the system.

Specloom is an agentic system compiler. A user provides a goal plus context (documents, URLs, APIs, code, rules, examples, and constraints). Specloom analyzes that context, identifies requirements and gaps, synthesizes a workflow, generates tests, simulates the workflow, repairs failures, and deploys a runnable agentic system.

## Core loop

Goal + Context → Context Analysis → Requirements → Capability Synthesis → SoftwareSpec + Workflow IR → Artifact Compilation → Validation → Tests → Simulation → Repair → Provision → Deploy → Run.

The workflow graph is the source of truth. The Context Graph describes what the system knows; the Workflow IR describes what it will do.

## Product goal

**Give Specloom a problem; it autonomously architects the production agent system.**

Specloom is intentionally split into a probabilistic planning layer and deterministic control plane:

```
Goal + Context
      ↓
Context Analyst
      ↓
Gap / capability check
      ↓
Bedrock Architect
      ↓
Workflow IR
      ↓
Validator + policy analysis
      ↓
Simulation + tests
      ↓
Repair
      ↓
Runtime + tools
```

The model is allowed to propose architecture, but it is not allowed to bypass the compiler's graph, tool, approval, loop, and terminal-output invariants.

## MVP

Supported context: PDF, URL, plain text, GitHub repository.

Generated node types:
1. trigger
2. agent
3. tool
4. condition
5. parallel
6. loop
7. human_approval
8. output

Generated implementation source is produced as inspectable artifacts, statically verified, and kept behind an explicit provisioning/promotion boundary; Specloom does not execute untrusted generated source implicitly.

## Node semantics

- **trigger**: manual, schedule, webhook, or event start.
- **agent**: bounded LLM reasoning with explicit tools and output contract.
- **tool**: deterministic external capability such as web search, HTTP, GitHub, database, or Lambda.
- **condition**: deterministic branch.
- **parallel**: fan-out/fan-in.
- **loop**: bounded iteration with explicit termination.
- **human_approval**: pause for explicit human decision.
- **output**: terminal result, notification, artifact, or webhook.

## Canonical IR

Workflow IR remains the execution-control graph; see `schemas/workflow-ir.schema.json`.

A workflow contains metadata, trigger, nodes, edges, variables, policies, and tests.

`SoftwareSpec` is the provider-neutral software architecture IR; see `schemas/software-spec.schema.json`. It describes services, capability requirements, synthesized capabilities, data models, environment, and deployment targets.

The compiler rejects malformed graphs, dangling references, duplicate IDs, unbounded loops, invalid tool bindings, and policy violations.

## Context Graph

Raw inputs are stored separately from normalized context:

```
Raw context
  ↓
Extraction
  ↓
Context Graph
  ├── requirements
  ├── constraints
  ├── entities
  ├── tools
  ├── examples
  └── provenance
```

Every extracted requirement or constraint retains provenance to its source.

## Logical agents

- **Context Analyst** — extracts requirements, constraints, tools, entities, examples, and provenance.
- **Architect** — generates the executable Workflow IR.
- **Universal Compiler** — synthesizes missing capability contracts and the surrounding SoftwareSpec.
- **Artifact Builder** — emits source, tests, container, deployment, specification, and documentation artifacts.
- **Evaluator / Repairer** — proves the candidate and drives bounded repair.

These are logical roles; they do not need to be separate model instances.

## Context gaps

Specloom asks for missing information instead of inventing it when the gap could change behavior, permissions, safety, or correctness.

A resolved gap creates a new context/spec version and triggers targeted replanning.

## Validation and simulation

Tests are generated from requirements and node contracts. They cover happy paths, invalid inputs, tool failures, permission boundaries, approvals, and loop termination.

Simulation defaults to mock/sandbox tools. Side-effecting production tools require explicit live mode.

A failed simulation records the failing node, expected vs actual, likely cause, and the proposed IR patch.

## Repair loop

FAIL → Diagnose → Propose IR patch → Validate → Re-run failed tests → PASS → deploy candidate.

Repairs are constrained to the generated IR/configuration; the MVP does not permit unrestricted self-modifying source code.

## Runtime and AWS

Target architecture:

```
React/Vite
  ↓
API Gateway
  ↓
FastAPI control plane
  ↓
Specloom compiler
  ↓
Strands / AgentCore runtime
  ↓
Bedrock
```

Supporting services:
- S3 — raw context and artifacts
- DynamoDB — projects, specs, and execution state
- EventBridge — scheduled runs
- Lambda — deterministic tools
- Step Functions — durable orchestration where useful
- OpenSearch — contextual retrieval when justified
- CloudWatch — logs and metrics

AWS services are used for actual product capabilities, not decoration.

## UI

The UI is a modern engineering workspace, not a generic AI chat app.

Primary views:
- Build
- Context
- System
- Test
- Deploy
- Run
- Tools
- Permissions

The System view uses a visual workflow canvas. The frontend consumes canonical Workflow IR and must not invent a second graph schema.

Important interactions:
- inspect context learned
- resolve context gaps
- inspect generated nodes
- show provenance / “why this exists”
- simulate
- see failures and repair
- deploy
- observe live execution

## Showcase and generic use cases

ResearchHunter is the first concrete showcase, not the architecture itself. The same compiler is designed to synthesize different workflows such as:

- Monitor a software project and open a ticket when a breaking change is detected.
- Read a policy or contract, extract obligations, flag exceptions, and route high-risk items for approval.
- Inspect a repository, investigate a defect, gather evidence, and produce a repair plan.
- Monitor public data, classify events, and trigger a bounded notification or escalation workflow.

The exact graph depends on the goal, available context, registered tools, and required safety controls.

## Repository layout

```
specloom/
├── frontend/
├── backend/
│   ├── api/
│   ├── context/
│   ├── agents/
│   ├── workflow/
│   ├── simulation/
│   ├── deployment/
│   └── tools/
├── schemas/
├── examples/
├── infra/
├── tests/
└── docs/
```

## Build order

1. Workflow IR models + validator
2. Minimal FastAPI API
3. Context ingestion + provenance
4. Context Analyst
5. Architect
6. Workflow compiler
7. Simulator
8. Evaluator + Repairer
9. React Flow UI
10. AWS runtime/deployment
11. Showcase workflow
12. Polish, documentation, and demo

## Security

Tool credentials live outside prompts and persisted context. Write-capable tools are allowlisted and can require human approval. Loops, retries, and timeouts are bounded. A deployed workflow is immutable by default; repairs create a new version.

## Definition of done

A user can enter a goal, add context, see requirements, resolve a missing rule, receive a workflow graph, inspect nodes, run simulation, observe a failure, accept a repair, re-run successfully, deploy, trigger a real run, and inspect the live result.


## Current implementation status

### Product state
Specloom is now structured around the generic compiler path:

Goal + Context → Model-backed Context Analysis → Gap Check → Bedrock Architect → Workflow IR → Deterministic Validation → Simulation/Evaluation → Repair → Runtime → Observation.

The deterministic ResearchHunter architect remains only as an explicit local test/demo fallback.

### Working
- Canonical Workflow IR v0.1 + JSON Schema
- Context Graph v0.1 + provenance model
- Text, URL, and PDF context ingestion
- Deterministic context requirement/constraint extraction
- Context gap detection
- Allowlisted tool registry + permission topology validation
- Workflow validator + compiler
- Semantic runtime for conditions, bounded loops, and parallel fan-out/fan-in
- Deterministic simulator
- Requirement test evaluator
- Bounded IR repairer
- FastAPI APIs for context, projects, build, simulation, evaluation, repair, and runtime
- React/Vite workspace with system canvas, context view, tests/evaluation view, live provenance inspector, run history + execution trace, inline gap resolution, version control, deployment checks, and API-backed execution
- Bedrock/Strands Architect with structured Workflow IR output and validator-driven repair
- Bedrock/Strands Context Analyst with structured requirements, constraints, entities, examples, and provenance
- Deterministic compiler checks for requirement/constraint coverage and MCP server trust
- Live web, URL, and GitHub read/write tool adapters behind the Tool Gateway
- Explicit read-only MCP server capability boundary for Bedrock agents
- Bounded GitHub repository source ingestion and a stored-workflow trigger endpoint
- Optional Bedrock/Strands runtime runner
- AgentCore runtime entrypoint scaffold
- SageMaker AI agent runtime adapter
- Deployable AWS SAM control plane: API Gateway, Lambda, DynamoDB, S3, EventBridge
- Amplify frontend build configuration
- GitHub Actions CI for backend tests and frontend build

### Next
- Deploy and verify the AWS stack with real credentials.
- Expand the capability catalog with additional authenticated API and MCP adapters.
- Move long-running graph execution to durable orchestration while preserving the same Workflow IR.
- Stream build, validation, simulation, approval, and runtime events into the workspace.
- Add provenance graph visualization and richer IR repair diffs.
- Add Cognito authentication and workspace-level permissions.
- Persist resumable approvals outside the process boundary.


## Universal software compilation

When the requested capability is not already configured, Specloom no longer treats that as an immediate dead end. The compiler creates a first-class synthesized capability with an explicit contract, implementation path, provisioning variables, risk classification, and generated verification test.

For example:

```
"Send the daily status to our internal notification system"
                    ↓
        Synthesized external-service capability
                    ↓
      SoftwareSpec + Workflow IR binding
                    ↓
 generated/capabilities/external-service.py
 generated/tests/test_external-service.py
 generated/backend/app.py
 generated/Dockerfile
 generated/deploy/cloudformation.yaml
```

Provider-specific URLs, credentials, scopes, and undocumented API behavior are never invented. They remain explicit provisioning inputs or can be replaced by an official OpenAPI/MCP capability when supplied.

Every build now persists the generated artifact manifest and exposes artifact retrieval through the project API.

