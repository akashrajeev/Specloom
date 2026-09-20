from __future__ import annotations

from typing import Any

from .models import WorkflowIR


def research_hunter_template(*, goal: str, has_github_tool: bool) -> WorkflowIR:
    github_mode = "sandbox" if has_github_tool else "mock"
    github_name = "GitHub write tool" if has_github_tool else "GitHub write simulator"

    return WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "research-hunter-v1",
            "name": "ResearchHunter",
            "description": goal,
            "trigger": {
                "id": "daily",
                "type": "trigger",
                "name": "Daily trigger",
                "config": {"mode": "schedule", "cron": "0 8 * * *"},
            },
            "nodes": [
                {
                    "id": "research",
                    "type": "agent",
                    "name": "Research",
                    "config": {
                        "role": "Find recent AI research from configured sources.",
                        "instructions": "Return structured candidates with source URLs.",
                        "model": "amazon.nova-lite-v1:0",
                        "tools": ["web_search"],
                        "output_mode": "structured",
                    },
                },
                {
                    "id": "relevance",
                    "type": "agent",
                    "name": "Relevance",
                    "config": {
                        "role": "Judge relevance against project context.",
                        "model": "amazon.nova-lite-v1:0",
                        "tools": [],
                        "output_mode": "structured",
                    },
                },
                {
                    "id": "approval",
                    "type": "human_approval",
                    "name": "Human Review",
                    "config": {
                        "prompt": "Approve proposed GitHub issues before any write.",
                        "approvers": ["project_owner"],
                    },
                },
                {
                    "id": "github",
                    "type": "tool",
                    "name": github_name,
                    "policy_ref": "github-write",
                    "config": {
                        "tool_ref": "github.create_issue",
                        "mode": github_mode,
                    },
                },
                {
                    "id": "result",
                    "type": "output",
                    "name": "Report",
                    "config": {"mode": "return", "destination": None},
                },
            ],
            "edges": [
                {"from": "daily", "to": "research"},
                {"from": "research", "to": "relevance"},
                {"from": "relevance", "to": "approval"},
                {"from": "approval", "to": "github"},
                {"from": "github", "to": "result"},
            ],
            "variables": [],
            "policies": [
                {
                    "id": "github-write",
                    "rules": ["GitHub writes require prior human approval."]
                }
            ],
            "tests": [
                {
                    "id": "approval-required",
                    "name": "Approval precedes GitHub write",
                    "input": {"approved": False},
                    "expected": {"github_called": False},
                    "tags": ["policy"],
                }
            ],
        }
    )


def deterministic_goal_template(*, goal: str, context: Any) -> WorkflowIR:
    """Safe quota-independent architecture for a new goal.

    This is intentionally generic: it produces an executable control-flow
    skeleton without pretending an unavailable model performed semantic design.
    The goal is preserved as the primary requirement and all side effects are
    placed behind a human-approval gate.
    """
    requirement_ids = [item.id for item in context.requirements if item.priority != "low"]
    constraint_ids = [item.id for item in context.constraints if item.severity == "blocking"]
    return WorkflowIR.model_validate(
        {
            "ir_version": "0.1",
            "id": "goal-fallback-v1",
            "name": "Goal System",
            "description": goal,
            "trigger": {
                "id": "start",
                "type": "trigger",
                "name": "Start",
                "config": {"mode": "manual"},
            },
            "nodes": [
                {
                    "id": "analyze",
                    "type": "agent",
                    "name": "Analyze",
                    "config": {
                        "role": "Analyze the requested outcome and produce a structured execution plan.",
                        "output_mode": "structured",
                        "requirement_refs": requirement_ids,
                        "constraint_refs": constraint_ids,
                    },
                },
                {
                    "id": "execute",
                    "type": "agent",
                    "name": "Execute",
                    "config": {
                        "role": "Perform the bounded transformation required by the requested outcome.",
                        "output_mode": "structured",
                        "requirement_refs": requirement_ids,
                        "constraint_refs": constraint_ids,
                    },
                },
                {
                    "id": "approval",
                    "type": "human_approval",
                    "name": "Human Review",
                    "config": {
                        "prompt": "Review the proposed result before any external or customer-facing action.",
                        "approvers": ["project_owner"],
                        "constraint_refs": constraint_ids,
                    },
                },
                {
                    "id": "result",
                    "type": "output",
                    "name": "Result",
                    "config": {"mode": "return", "destination": None},
                    "requirement_refs": requirement_ids,
                    "constraint_refs": constraint_ids,
                },
            ],
            "edges": [
                {"from": "start", "to": "analyze"},
                {"from": "analyze", "to": "execute"},
                {"from": "execute", "to": "approval"},
                {"from": "approval", "to": "result"},
            ],
            "variables": [],
            "policies": [
                {
                    "id": "human-review",
                    "rules": ["External or customer-facing actions require prior human approval."],
                }
            ],
            "tests": [
                {
                    "id": "approval-before-output",
                    "name": "Human review precedes final result",
                    "input": {"approved": False},
                    "expected": {"result_produced": False},
                    "tags": ["policy"],
                }
            ],
        }
    )
