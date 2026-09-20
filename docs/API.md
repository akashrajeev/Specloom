# Specloom API Reference

The FastAPI application exposes the control plane under /api/v1.

For the authoritative OpenAPI contract, start the backend and open:

~~~text
http://localhost:8000/docs
~~~

## Health and discovery

| Method | Path | Purpose |
|---|---|---|
| GET | /health | Process health check |
| GET | /api/v1/config | Effective runtime/compiler configuration |
| GET | /api/v1/workflow/example | Example Workflow IR and validation results |

## Projects

| Method | Path | Purpose |
|---|---|---|
| GET | /api/v1/projects/{project_id} | Project state, workflow, versions, and artifacts |
| GET | /api/v1/projects/{project_id}/context | Current Context Graph |
| GET | /api/v1/projects/{project_id}/capabilities | Available project capabilities |

## Context ingestion

### Add text

~~~http
POST /api/v1/projects/{project_id}/context/text
Content-Type: application/json
~~~

Typical payload:

~~~json
{
  "name": "requirements",
  "content": "The system must preserve an audit trail."
}
~~~

### Add URL

~~~http
POST /api/v1/projects/{project_id}/context/url
Content-Type: application/json
~~~

Typical payload:

~~~json
{
  "url": "https://example.com/specification",
  "name": "Specification"
}
~~~

### Add file

~~~http
POST /api/v1/projects/{project_id}/context/file
Content-Type: multipart/form-data
~~~

The API accepts uploaded source files and ingests supported document formats.

## Build

### Build a system

~~~http
POST /api/v1/projects/{project_id}/build
Content-Type: application/json
~~~

Payload:

~~~json
{
  "goal": "Build a support triage system that classifies requests and requires approval for urgent cases.",
  "gap_answers": {}
}
~~~

A build response can include:

- readiness state;
- blocking gaps;
- Workflow IR;
- execution plan;
- architecture/review information;
- generated artifacts;
- capability bindings;
- deployment metadata.

### Autonomous build

~~~http
POST /api/v1/projects/{project_id}/autobuild
Content-Type: application/json
~~~

The request includes the goal, gap answers, target, and approval state.

Production-targeted builds can pause in awaiting_approval and resume through:

~~~http
POST /api/v1/projects/{project_id}/autobuild/{run_id}/resume
Content-Type: application/json
~~~

Payload:

~~~json
{
  "approved": true
}
~~~

Before promotion, the service checks that the recorded generated-artifact hashes still match the current project artifacts.

## Validation and evaluation

### Evaluate Workflow IR

~~~http
POST /api/v1/projects/{project_id}/evaluate
Content-Type: application/json
~~~

Evaluates the workflow's generated or attached tests.

### Repair

~~~http
POST /api/v1/projects/{project_id}/repair
Content-Type: application/json
~~~

Proposes a supported bounded repair when evaluation exposes a repairable failure.

### Apply repair

~~~http
POST /api/v1/projects/{project_id}/repair/apply
Content-Type: application/json
~~~

Applies an allowed IR/configuration repair and creates a new workflow version.

## Runtime

### Execute a workflow

~~~http
POST /api/v1/projects/{project_id}/run
Content-Type: application/json
~~~

Payload:

~~~json
{
  "workflow": {},
  "input_data": {
    "customer_request": "..."
  }
}
~~~

The backend selects the configured runtime path.

### Trigger stored workflow

~~~http
POST /api/v1/projects/{project_id}/trigger
Content-Type: application/json
~~~

Used to invoke an already stored workflow with runtime input.

### Run history

~~~http
GET /api/v1/projects/{project_id}/runs
~~~

### Run detail

~~~http
GET /api/v1/projects/{project_id}/runs/{run_id}
~~~

## Durable approvals

~~~http
GET  /api/v1/projects/{project_id}/durable/approvals
POST /api/v1/projects/{project_id}/durable/runs/{run_id}/approve/{node_id}
POST /api/v1/projects/{project_id}/durable/runs/{run_id}/reject/{node_id}
~~~

These routes resolve persisted Step Functions callback approvals.

## Workflow versions

~~~http
GET  /api/v1/projects/{project_id}/versions
POST /api/v1/projects/{project_id}/versions/{version}/activate
~~~

Workflow changes are represented as versions instead of mutating historical workflows in place.

## Node execution mode

~~~http
PATCH /api/v1/projects/{project_id}/nodes/{node_id}/mode
Content-Type: application/json
~~~

Payload:

~~~json
{
  "mode": "sandbox"
}
~~~

Allowed modes are:

~~~text
mock
sandbox
live
~~~

## Provenance and artifacts

~~~http
GET /api/v1/projects/{project_id}/provenance
GET /api/v1/projects/{project_id}/artifacts
GET /api/v1/projects/{project_id}/artifacts/{artifact_path}
~~~

Pass node_id as a query parameter to provenance to inspect one node.

Generated artifacts include hashes so the service can reason about the exact compiled output.

## Deployment

~~~http
GET  /api/v1/deploy/status
GET  /api/v1/projects/{project_id}/deploy/check
GET  /api/v1/projects/{project_id}/deploy/plan
POST /api/v1/projects/{project_id}/deploy/generated
GET  /api/v1/projects/{project_id}/deploy/history
POST /api/v1/projects/{project_id}/deploy/rollback
~~~

Production promotion requires deployment readiness checks and explicit approval.

## Authentication

Authentication is implemented as middleware.

When SPECL00M_AUTH_MODE=cognito:

1. the request must include a bearer token;
2. the token is verified against the configured Cognito issuer/JWKs;
3. the client/audience is checked when configured;
4. a Specloom workspace identity must be present;
5. the workspace is propagated into project storage access.

When authentication is off, the same API can be used locally without a bearer token.

## Typical application sequence

~~~text
GET /health
     ↓
GET /api/v1/config
     ↓
POST /api/v1/projects/{id}/context/...
     ↓
POST /api/v1/projects/{id}/build
     ↓
POST /api/v1/projects/{id}/evaluate
     ↓
POST /api/v1/projects/{id}/run
     ↓
GET /api/v1/projects/{id}/runs
~~~

The UI follows this API-driven lifecycle rather than embedding compiler or runtime behavior in the browser.
