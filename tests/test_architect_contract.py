import sys
import types

from backend.agents.bedrock_architect import BedrockArchitect
from backend.agents.prompt import ArchitectPrompt
from backend.context.models import ContextGraph, ContextTool
from backend.workflow.models import WorkflowIR


def test_architect_prompt_is_problem_agnostic():
    context = ContextGraph(
        tools=[
            ContextTool(
                id="web_search",
                name="Web Search",
                capabilities=["search", "read"],
                permissions=["READ"],
            )
        ]
    )
    prompt = ArchitectPrompt.render(
        "Monitor a product changelog and open a ticket when a breaking change is detected.",
        context,
    )
    assert "ResearchHunter" not in prompt
    assert "product changelog" in prompt
    assert "web_search" in prompt
    assert "smallest production-safe executable workflow" in prompt


def test_workflow_ir_preserves_explicit_node_config():
    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "generic-config",
            "name": "Generic config",
            "trigger": {
                "id": "start",
                "type": "trigger",
                "name": "Start",
                "config": {"mode": "manual"},
            },
            "nodes": [
                {
                    "id": "agent",
                    "type": "agent",
                    "name": "Analyze",
                    "config": {
                        "role": "Analyze the supplied input.",
                        "output_mode": "structured",
                        "requirement_refs": ["req_1"],
                        "source_refs": ["src_1"],
                    },
                },
                {
                    "id": "out",
                    "type": "output",
                    "name": "Return",
                    "config": {"mode": "return"},
                },
            ],
            "edges": [
                {"from": "start", "to": "agent"},
                {"from": "agent", "to": "out"},
            ],
            "variables": [],
            "policies": [],
            "tests": [],
        }
    )
    assert workflow.nodes[0].config["requirement_refs"] == ["req_1"]


def test_bedrock_architect_repairs_semantic_workflow(monkeypatch):
    first = {
        "ir_version": "0.1",
        "id": "bad",
        "name": "Bad plan",
        "trigger": {
            "id": "start",
            "type": "trigger",
            "name": "Start",
            "config": {"mode": "manual"},
        },
        "nodes": [
            {
                "id": "write",
                "type": "tool",
                "name": "Write",
                "policy_ref": "write-policy",
                "config": {
                    "tool_ref": "github.create_issue",
                    "mode": "live",
                },
            },
            {
                "id": "out",
                "type": "output",
                "name": "Return",
                "config": {"mode": "return"},
            },
        ],
        "edges": [
            {"from": "start", "to": "write"},
            {"from": "write", "to": "out"},
        ],
        "variables": [],
        "policies": [{"id": "write-policy", "rules": ["approval required"]}],
        "tests": [],
    }

    second = {
        "ir_version": "0.1",
        "id": "fixed",
        "name": "Fixed plan",
        "trigger": {
            "id": "start",
            "type": "trigger",
            "name": "Start",
            "config": {"mode": "manual"},
        },
        "nodes": [
            {
                "id": "review",
                "type": "human_approval",
                "name": "Review",
                "config": {
                    "prompt": "Approve the write.",
                    "approvers": ["project_owner"],
                },
            },
            {
                "id": "write",
                "type": "tool",
                "name": "Write",
                "policy_ref": "write-policy",
                "config": {
                    "tool_ref": "github.create_issue",
                    "mode": "sandbox",
                },
            },
            {
                "id": "out",
                "type": "output",
                "name": "Return",
                "config": {"mode": "return"},
            },
        ],
        "edges": [
            {"from": "start", "to": "review"},
            {"from": "review", "to": "write"},
            {"from": "write", "to": "out"},
        ],
        "variables": [],
        "policies": [{"id": "write-policy", "rules": ["approval required"]}],
        "tests": [],
    }

    class FakeAgent:
        calls = 0
        prompts: list[str] = []

        def __init__(self, **kwargs):
            self.kwargs = kwargs

        def structured_output(self, _model, *, prompt):
            self.__class__.calls += 1
            self.__class__.prompts.append(prompt)
            return WorkflowIR.model_validate(first if self.__class__.calls == 1 else second)

    fake_strands = types.ModuleType("strands")
    fake_strands.Agent = FakeAgent
    fake_models = types.ModuleType("strands.models")
    fake_models.BedrockModel = lambda **kwargs: kwargs
    monkeypatch.setitem(sys.modules, "strands", fake_strands)
    monkeypatch.setitem(sys.modules, "strands.models", fake_models)

    architect = BedrockArchitect(model_id="test-model", max_repairs=2)
    result = architect.build(
        "Create a ticket when a monitored change crosses the supplied threshold.",
        ContextGraph(
            tools=[
                ContextTool(
                    id="github.create_issue",
                    name="GitHub Create Issue",
                    capabilities=["github", "write"],
                    permissions=["READ", "WRITE"],
                    side_effecting=True,
                    requires_human_approval=True,
                )
            ]
        ),
    )

    assert result.id == "fixed"
    assert FakeAgent.calls == 2
    assert "side-effecting tool" in FakeAgent.prompts[1]
