from __future__ import annotations

from typing import Any

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR

SUPPORTED_TYPES = {
    "trigger",
    "agent",
    "tool",
    "condition",
    "parallel",
    "loop",
    "human_approval",
    "output",
}


class ArchitectPrompt:
    @staticmethod
    def render(goal: str, context: ContextGraph) -> str:
        requirements = "\n".join(
            f"- {item.id} [{item.priority}] {item.statement}"
            for item in context.requirements
        ) or "- none extracted"

        constraints = "\n".join(
            f"- {item.id} [{item.severity}] {item.statement}"
            for item in context.constraints
        ) or "- none extracted"

        tools = "\n".join(
            f"- {tool.id}: {tool.name}; capabilities={tool.capabilities}; permissions={tool.permissions}"
            for tool in context.tools
        ) or "- none available"

        examples = "\n".join(
            f"- input={item.input!r}; expected={item.expected!r}"
            for item in context.examples
        ) or "- none supplied"

        return f"""
You are Specloom's system architect.

USER GOAL:
{goal}

REQUIREMENTS:
{requirements}

CONSTRAINTS:
{constraints}

ALLOWED TOOLS:
{tools}

EXAMPLES:
{examples}

Design one executable Workflow IR v0.1.

Allowed node types:
{", ".join(sorted(SUPPORTED_TYPES))}

Safety rules:
1. Never invent credentials or tools.
2. Never bind a side-effecting tool directly to an agent; model writes must be dedicated tool nodes preceded by human approval.
3. Every loop must define max_iterations between 1 and 1000.
4. Every workflow must end at an output node.
5. Preserve requirements and constraints in node configuration or policy references.
6. Prefer explicit conditions over hidden agent decisions.
7. When a node is driven by context, add `requirement_refs`, `constraint_refs`, and `source_refs` inside its config using exact IDs supplied above.\n8. Return only the Workflow IR JSON object.
""".strip()


def workflow_from_model_payload(payload: dict[str, Any]) -> WorkflowIR:
    return WorkflowIR.model_validate(payload)
