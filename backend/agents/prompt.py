from __future__ import annotations

from typing import Any
import os

from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR
from backend.tools.mcp import prompt_mcp_catalog

SUPPORTED_TYPES = {"trigger", "agent", "tool", "condition", "parallel", "loop", "human_approval", "output"}


class ArchitectPrompt:
    @staticmethod
    def render(goal: str, context: ContextGraph) -> str:
        requirements = "\n".join(f"- {item.id} [{item.priority}] {item.statement}" for item in context.requirements) or "- none extracted"
        constraints = "\n".join(f"- {item.id} [{item.severity}] {item.statement}" for item in context.constraints) or "- none extracted"
        tools = "\n".join(
            f"- {tool.id}: {tool.name}; {tool.description or 'no description'}; capabilities={tool.capabilities}; permissions={tool.permissions}; side_effecting={tool.side_effecting}; requires_human_approval={tool.requires_human_approval}; execution_modes={tool.execution_modes or ['mock', 'sandbox', 'live']}"
            for tool in context.tools
        ) or "- none available"
        capabilities = "\n".join(
            f"- {item.id}: {item.name}; kind={item.kind}; method={item.method or '-'}; path={item.path or '-'}; access={item.access}; side_effecting={item.side_effecting}; approval={item.requires_human_approval}; auth_env={'configured' if item.auth_env else 'none'}; input_schema={item.input_schema}; output_schema={item.output_schema}"
            for item in context.capabilities
        ) or "- none compiled"
        examples = "\n".join(f"- input={item.input!r}; expected={item.expected!r}" for item in context.examples) or "- none supplied"
        models = [item.strip() for item in os.getenv("SPECL00M_ALLOWED_BEDROCK_MODELS", os.getenv("SPECL00M_BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")).split(",") if item.strip()]

        return f"""
You are Specloom's autonomous system architect.

MISSION
Turn the user's natural-language problem into the smallest production-safe executable workflow that can actually solve it. You are compiling an executable system, not designing a chatbot conversation.

USER GOAL
{goal}

KNOWN CONTEXT

REQUIREMENTS
{requirements}

CONSTRAINTS
{constraints}

ALLOWED TOOLS
{tools}

COMPILED CAPABILITY CATALOG
{capabilities}

EXAMPLES
{examples}

ALLOWED BEDROCK MODELS
- {", ".join(models)}

CONFIGURED MCP CAPABILITIES
{prompt_mcp_catalog()}

ARCHITECTURE METHOD
1. Identify the desired outcome, inputs, transformations, decisions, external actions, and final outputs.
2. Decompose the work into explicit steps. Use agent nodes for bounded reasoning/judgment and tool nodes for deterministic external effects.
3. Choose capabilities from the COMPILED CAPABILITY CATALOG or ALLOWED TOOLS. Never invent an integration.
4. For a compiled capability, reference its exact id in tool_ref (tool node) or tools (agent node). The compiler will bind the capability metadata after generation.
5. Use condition nodes for explicit routing criteria; use parallel only for independent branches; use bounded loops for finite collections.
6. Put human_approval before every side-effecting capability/tool. Never put write-capable capabilities in an agent tools list.
7. End every executable path at an output node.
8. Preserve requirements and constraints by attaching exact IDs as requirement_refs and constraint_refs; attach exact source IDs as source_refs where relevant.
9. Create tests for high/critical requirements, blocking constraints, representative examples, control flow, approvals, and side effects.
10. Keep model selection within ALLOWED BEDROCK MODELS.
11. Prefer the simplest architecture that satisfies the goal. Do not create multi-agent complexity without a concrete reason.
12. A missing capability means the system is not executable yet. Do not substitute a hallucinated API; the surrounding compiler should report a blocking capability gap.

SUPPORTED NODE TYPES
{", ".join(sorted(SUPPORTED_TYPES))}

HARD SAFETY RULES
- Never invent tools, APIs, credentials, infrastructure, or permissions.
- Never place a side-effecting capability/tool in an agent's tools list.
- Never create a side-effecting tool node without policy_ref and an upstream human_approval node.
- Never create an unbounded loop.
- Never omit an output node.
- Never emit prose outside the Workflow IR JSON object.

OUTPUT CONTRACT
Return exactly one Workflow IR v0.1 JSON object.
""".strip()


def workflow_from_model_payload(payload: dict[str, Any]) -> WorkflowIR:
    return WorkflowIR.model_validate(payload)
