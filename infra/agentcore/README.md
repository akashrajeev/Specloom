# Specloom AgentCore runtime

This directory is the production AgentCore execution target for compiled Specloom Workflow IR.

## Deploy

```bash
npm install -g @aws/agentcore
agentcore --version

cd infra/agentcore
agentcore dev
agentcore deploy --dry-run
agentcore deploy
agentcore status
```

The entrypoint is `app.py` with the `specloom_runtime` AgentCore entrypoint. It accepts:

```json
{
  "workflow": { "ir_version": "0.1", "...": "..." },
  "input_data": {}
}
```

For direct ZIP packaging, install Linux ARM64-compatible wheels:

```bash
rm -rf deployment_package deployment_package.zip
mkdir deployment_package
uv pip install \
  --python-platform aarch64-manylinux2014 \
  --python-version 3.13 \
  --target=deployment_package \
  --only-binary=:all: \
  -r requirements.txt
cp app.py deployment_package/
cd deployment_package && zip -r ../deployment_package.zip .
```

AgentCore's current direct-code documentation recommends Python 3.13; Python 3.11 is past its listed deprecation date. The deployed execution role must allow the Bedrock model and any downstream capability backends used by the workflow.

Specloom remains the authority for requirements, capability selection, policy enforcement, proof tests, and promotion. AgentCore is an execution target, not the architecture authority.
