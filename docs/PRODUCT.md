# Specloom Product

> **Give it a problem. Specloom architects the system.**

## Product model

Specloom turns a problem statement and available context into a validated, executable agentic workflow.

The product is not centered on a chat transcript. The primary artifact is the generated system graph, represented by Workflow IR.

## Core experience

~~~text
Build
 ↓
Understand
 ↓
Detect gaps
 ↓
Design
 ↓
Validate
 ↓
Evaluate
 ↓
Repair
 ↓
Deploy
 ↓
Run
 ↓
Observe
~~~

### Build

The user starts with a goal and optional contextual material.

### Understand

Specloom normalizes sources into a Context Graph containing requirements, constraints, tools/capabilities, entities, examples, and provenance.

### Detect gaps

When required information is missing, the compiler can stop and request clarification instead of inventing a behaviorally significant assumption.

### Design

The architect produces Workflow IR.

The model-backed path uses Strands and Amazon Bedrock. A deterministic architect is also available for local development and automated tests.

### Validate

Deterministic validators check graph structure, references, requirements, constraints, capability bindings, tool permissions, policies, loops, and terminal outputs.

### Evaluate

Requirement-oriented tests and evaluation checks provide evidence that the generated workflow covers the intended behavior.

### Repair

A failure can produce a bounded IR/configuration repair. Applying a repair creates a new workflow version rather than silently changing historical state.

### Deploy

Specloom produces deployment artifacts and metadata and can promote a generated system when deployment prerequisites and approval requirements are satisfied.

### Run

The stored Workflow IR is executed through the configured runtime. Execution events, approvals, errors, outputs, and provenance are exposed through the control plane.

## Primary UI views

- Build / New System
- Context
- System
- Tests
- Deploy
- Run history
- Node inspector
- Provenance
- Approvals

## Product invariants

### One graph

Workflow IR is the canonical execution graph.

### One execution boundary

External capabilities pass through the policy-aware Tool Gateway.

### One explanation path

Workflow nodes can expose their linked requirements, constraints, sources, tests, and dependencies.

### Versioned change

Workflow repairs and activation changes create or activate workflow versions rather than rewriting historical state.

## Supported capability classes

The repository supports capability paths for:

- public web search;
- public URL fetch;
- GitHub repository reads and issue/code search;
- GitHub issue creation;
- configured API operations;
- OpenAPI-backed capabilities;
- read-only MCP servers;
- synthesized capabilities produced by the compiler.

Actual availability depends on project configuration and credentials.

## Product boundary

Specloom is an implementation-focused system compiler/runtime with a deployable AWS control plane.

The repository provides the compiler, UI, runtime adapters, policy boundary, persistence adapters, and deployment infrastructure. A live cloud environment still requires deployment into an AWS account and configuration of the required credentials and services.
