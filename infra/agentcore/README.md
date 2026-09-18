# Specloom AgentCore Runtime

The production execution target is Amazon Bedrock AgentCore Runtime.

The runtime contract accepts a validated Workflow IR payload, executes the graph through the Specloom runtime executor, emits structured execution events, and returns the final output.

For an initial AWS deployment, scaffold a Python Strands project with the current AgentCore CLI, then adapt the generated entrypoint to call the Specloom runtime executor.

Packages:
- strands-agents
- bedrock-agentcore

Keep production credentials outside the Workflow IR. Tool permissions belong to runtime configuration and policy enforcement.
