# Specloom

> Give it the context. It builds the system.

Specloom is an agentic system compiler. A user provides a goal plus context (documents, URLs, APIs, code, rules, examples, and constraints). Specloom analyzes that context, identifies requirements and gaps, synthesizes a workflow, generates tests, simulates the workflow, repairs failures, and deploys a runnable agentic system.

## Core loop

Goal + Context → Context Analysis → Requirements → Gap Detection → Workflow Synthesis → Validation → Tests → Simulation → Repair → Deploy → Run.

The workflow graph is the source of truth. The Context Graph describes what the system knows; the Workflow IR describes what it will do.

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

The MVP does not permit arbitrary generated code to execute automatically.

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

See `schemas/workflow-ir.schema.json`.

A workflow contains metadata, trigger, nodes, edges, variables, policies, and tests.

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
- **Architect** — generates Workflow IR.
- **Builder** — resolves tool bindings and compiles the IR.
- **Evaluator** — generates tests and evaluates simulation.
- **Repairer** — diagnoses failures and proposes bounded IR patches.

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

## First showcase

ResearchHunter: every morning, find new AI research from configured sources, judge relevance against project context, deduplicate, verify metadata, and prepare GitHub issues for human approval.

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
