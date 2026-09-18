from __future__ import annotations

from backend.runtime.bedrock_runner import BedrockAgentRunner
from backend.runtime.executor import RuntimeExecutor
from backend.workflow.models import WorkflowIR

try:
    from bedrock_agentcore.runtime import BedrockAgentCoreApp
except ImportError as exc:
    raise RuntimeError("Install backend/requirements-aws.txt to run the AgentCore entrypoint.") from exc

app = BedrockAgentCoreApp()


@app.entrypoint
def specloom_runtime(payload: dict):
    workflow = WorkflowIR.model_validate(payload.get("workflow"))
    input_data = payload.get("input_data") or {}
    executor = RuntimeExecutor(agent_runner=BedrockAgentRunner())
    return executor.run(workflow, input_data)


if __name__ == "__main__":
    app.run()
