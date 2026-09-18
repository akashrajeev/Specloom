# Specloom Architecture

## Layers

1. Experience — React and workflow visualization.
2. Control plane — FastAPI, context analysis, synthesis, validation, simulation, deployment orchestration.
3. Execution plane — Strands/AgentCore and deterministic tools.
4. AWS foundation — Bedrock, S3, DynamoDB, API Gateway, EventBridge, Lambda, CloudWatch, optional Step Functions/OpenSearch.

## Invariant

The LLM never directly controls production execution. It proposes structured IR. Deterministic validation and policy checks gate execution.

## Context provenance

Each extracted fact records source ID, locator when available, extracted statement, confidence, and linked requirements.

## Versioning

Projects version context snapshots, requirement specifications, workflow IR, tests, and deployments. A repair creates a new candidate version.

## Runtime safety

Tools are allowlisted. Write-capable tools require policy. High-impact writes may require human approval. Loop iterations, timeouts, and retries are bounded. Simulation defaults to mock/sandbox mode.
