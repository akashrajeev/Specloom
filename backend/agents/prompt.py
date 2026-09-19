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
            f"- {tool.id}: {tool.name}; {tool.description or 'no description'}; "
            f"capabilities={tool.capabilities}; permissions={tool.permissions}; "
            f"side_effecting={tool.side_effecting}; "
            f"requires_human_approval={tool.requires_human_approval}; "
            f"execution_modes={tool.execution_modes or ['mock', 'sandbox', 'live']}"
            for tool in context.tools
        ) or "- none available"

        examples = "\n".join(
            f"- input={item.input!r}; expected={item.expected!r}"
            for item in context.examples
        ) or "- none supplied"

        return f"""
You are Specloom's autonomous system architect.

MISSION
Turn the user's natural-language problem into the smallest production-safe executable workflow that can actually solve it. You are not designing a chatbot conversation; you are compiling a system.

USER GOAL
{goal}

KNOWN CONTEXT

REQUIREMENTS
{requirements}

CONSTRAINTS
{constraints}

ALLOWED TOOLS
{tools}

EXAMPLES
{examples}

ARCHITECTURE METHOD
1. Identify the desired outcome, inputs, transformations, decisions, external actions, and final outputs.
2. Decompose the work into explicit steps. Use an agent node for bounded reasoning/judgment and a tool node for deterministic external effects.
3. Give each agent a narrow role and explicit instructions. Agents may use only the listed read-only tools.
4. Use condition nodes when the workflow has explicit routing criteria.
5. Use parallel only when branches are meaningfully independent and a later join is useful.
6. Use loop only for a finite collection; set a conservative max_iterations.
7. Use human_approval before every side-effecting action such as writing, publishing, sending, deleting, deploying, or changing external state.
8. End every executable path at an output node.
9. Make node inputs/outputs explicit with input_contract and output_contract when useful.
10. Add retry/timeout settings for failure-prone external operations where appropriate, but stay within the IR limits.
11. Use only tools that exist in ALLOWED TOOLS. Never invent credentials, APIs, tool IDs, or infrastructure.
12. Preserve requirements and constraints by attaching exact IDs in node config as requirement_refs and constraint_refs. Attach exact source IDs as source_refs when relevant.
13. Create tests that exercise the important requirements, safety boundaries, approvals, and representative behavior. Tests must be executable by the simulator using the workflow's existing semantics.
14. Prefer a simple linear workflow when the problem is simple. Add agents/branches/loops only when they materially improve correctness.
15. When a requested capability is not represented by an available tool, do not fake it. Ask for the missing capability through a blocking context gap rather than generate a non-executable dependency.

SUPPORTED NODE TYPES
{", ".join(sorted(SUPPORTED_TYPES))}

HARD SAFETY RULES
- Never place a side-effecting tool in an agent's tools list.
- Never create a side-effecting tool node without a policy_ref and an upstream human_approval node.
- Never invent a tool because it would be convenient.
- Never create an unbounded loop.
- Never rely on hidden model decisions when an explicit condition can represent the decision.
- Never omit an output node.
- Never emit prose outside the Workflow IR JSON object.

OUTPUT CONTRACT
Return exactly one Workflow IR v0.1 JSON object.
""".strip()


def workflow_from_model_payload(payload: dict[str, Any]) -> WorkflowIR:
    return WorkflowIR.model_validate(payload)
