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

        def __call__(self, prompt, *, structured_output_model):
            self.__class__.calls += 1
            self.__class__.prompts.append(prompt)
            return types.SimpleNamespace(
                structured_output=WorkflowIR.model_validate(
                    first if self.__class__.calls == 1 else second
                )
            )

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


def test_architecture_coverage_rejects_uncovered_critical_context():
    from backend.context.models import ContextGraph, Requirement
    from backend.workflow.validator import validate_architecture_coverage

    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "coverage",
            "name": "Coverage",
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
                    "config": {"role": "Analyze", "output_mode": "structured"},
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
    context = ContextGraph(
        requirements=[
            Requirement(
                id="req_critical",
                statement="The system must preserve the audit trail.",
                priority="critical",
            )
        ]
    )
    errors = validate_architecture_coverage(workflow, context)
    assert "important requirement is not covered: req_critical" in errors


def test_validator_rejects_unconfigured_mcp_server(monkeypatch):
    from backend.workflow.validator import validate_workflow

    monkeypatch.setenv("SPECL00M_MCP_SERVERS", '{"mcpServers":{}}')
    monkeypatch.setenv("SPECL00M_MCP_READONLY_SERVERS", "[]")

    workflow = WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "mcp-validation",
            "name": "MCP validation",
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
                    "name": "Agent",
                    "config": {
                        "role": "Read from docs",
                        "output_mode": "structured",
                        "mcp_servers": ["docs"],
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

    errors = validate_workflow(workflow)
    assert any("references unknown MCP server: docs" in error for error in errors)
