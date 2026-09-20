# Specloom Product

> **Give it a problem. Specloom architects the system.**

## Product model

Specloom turns a problem statement and available context into a validated agentic workflow.

The product is not centered on a chat transcript. The primary artifact is the generated system graph.

## Core experience

~~~text
Build → Understand → Detect gaps → Design → Test → Repair → Deploy → Run
~~~

### Build

The user starts with a goal and optional context.

### Understand

Specloom normalizes sources into a Context Graph containing requirements, constraints, tools/capabilities, entities, examples, and provenance.

### Detect gaps

When required information is missing, the system can stop and ask for a clarification instead of inventing a behaviorally significant assumption.

### Design

The architect produces Workflow IR.

The generic production architecture path uses the model-backed architect. A deterministic showcase architect remains available for local development and tests.

### Test

Workflow validation and generated/evaluator tests check structure, policy boundaries, coverage, and expected behavior.

### Repair

A failure can produce a bounded IR/configuration repair. Applying a repair creates a new workflow version.

### Deploy

The system produces deployment artifacts/metadata and can promote a generated system when deployment prerequisites and approval requirements are satisfied.

### Run

The same Workflow IR is executed through the configured runtime. Runtime traces are persisted and exposed in the UI.

## Demo philosophy

The Demo Gallery is a set of **real problem starters**.

A demo does not bypass the compiler:

~~~text
Demo problem
    ↓
Normal Build dialog
    ↓
Architecture generation
    ↓
Validation
    ↓
Tests
    ↓
Run
    ↓
Approval when required
    ↓
Output + trace
~~~

Demo inputs are synthetic and repeatable. The execution path is the normal application path.

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

Workflow repairs and activation changes create/activate workflow versions rather than silently rewriting the historical version.

## Supported capability classes

The current repository supports capability paths for:

- public web search;
- public URL fetch;
- GitHub repository reads and issue/code search;
- GitHub issue creation;
- configured API operations;
- OpenAPI-backed capabilities;
- read-only MCP servers;
- synthesized capabilities produced by the compiler.

Actual availability depends on the current project configuration.

## Product boundary

Specloom is currently an implementation-focused compiler/runtime prototype with a deployable AWS control plane.

The repository provides the architecture, compiler, UI, runtime adapters, and deployment infrastructure, but a live AWS environment still requires deployment into an AWS account and configuration of the required credentials/services.
