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

    The showcase path uses bounded, goal-aware templates so the recorded demo
    remains executable even when model quotas are unavailable. It never claims
    an LLM performed semantic design.
    """
    requirement_ids = [item.id for item in context.requirements if item.priority != "low"]
    constraint_ids = [item.id for item in context.constraints if item.severity == "blocking"]
    lowered = goal.lower()

    # Preserve the existing research demo contract while adding goal-specific
    # showcase templates for the second demo use cases.
    if any(term in lowered for term in ("research", "ai developments", "github issue")):
        return research_hunter_template(
            goal=goal,
            has_github_tool=any("github" in tool.name.lower() for tool in context.tools),
        )

    if any(term in lowered for term in ("support", "ticket", "customer request", "triage")):
        return WorkflowIR.model_validate(
            {
                "ir_version": "0.1",
                "id": "support-triage-generated",
                "name": "Support Triage",
                "description": goal,
                "trigger": {
                    "id": "request",
                    "type": "trigger",
                    "name": "Support request",
                    "config": {"mode": "manual"},
                },
                "nodes": [
                    {
                        "id": "classify",
                        "type": "agent",
                        "name": "Classify",
                        "config": {
                            "role": "Classify the request as billing, technical, account, or urgent.",
                            "output_mode": "structured",
                            "requirement_refs": requirement_ids,
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "draft",
                        "type": "agent",
                        "name": "Draft Response",
                        "config": {
                            "role": "Draft a concise helpful response using the classified issue.",
                            "output_mode": "structured",
                            "requirement_refs": requirement_ids,
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "review",
                        "type": "human_approval",
                        "name": "Escalation Review",
                        "config": {
                            "prompt": "Review the drafted response and urgent classification before release.",
                            "approvers": ["support_lead"],
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "result",
                        "type": "output",
                        "name": "Response",
                        "config": {"mode": "return", "destination": None},
                        "requirement_refs": requirement_ids,
                        "constraint_refs": constraint_ids,
                    },
                ],
                "edges": [
                    {"from": "request", "to": "classify"},
                    {"from": "classify", "to": "draft"},
                    {"from": "draft", "to": "review"},
                    {"from": "review", "to": "result"},
                ],
                "variables": [],
                "policies": [
                    {
                        "id": "support-review",
                        "rules": ["Customer-facing support responses require prior human review."],
                    }
                ],
                "tests": [
                    {
                        "id": "support-flow",
                        "name": "Classify and draft support response",
                        "input": {"message": "I cannot access my account"},
                        "expected": {"classification": "account", "drafted": True},
                        "tags": ["demo"],
                    }
                ],
            }
        )

    if any(term in lowered for term in ("document", "brief", "summarize", "summary", "report")):
        return WorkflowIR.model_validate(
            {
                "ir_version": "0.1",
                "id": "document-brief-generated",
                "name": "Document Brief",
                "description": goal,
                "trigger": {
                    "id": "document",
                    "type": "trigger",
                    "name": "Document received",
                    "config": {"mode": "manual"},
                },
                "nodes": [
                    {
                        "id": "extract",
                        "type": "agent",
                        "name": "Extract",
                        "config": {
                            "role": "Extract key facts, entities, dates, and decisions from the supplied document.",
                            "output_mode": "structured",
                            "requirement_refs": requirement_ids,
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "verify",
                        "type": "agent",
                        "name": "Verify",
                        "config": {
                            "role": "Check extracted claims against supplied context and flag uncertainty.",
                            "output_mode": "structured",
                            "requirement_refs": requirement_ids,
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "brief",
                        "type": "agent",
                        "name": "Executive Brief",
                        "config": {
                            "role": "Turn verified findings into a concise executive brief with decisions, risks, and next actions.",
                            "output_mode": "structured",
                            "requirement_refs": requirement_ids,
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "review",
                        "type": "human_approval",
                        "name": "Brief Review",
                        "config": {
                            "prompt": "Review the brief for accuracy and unresolved uncertainty before release.",
                            "approvers": ["project_owner"],
                            "constraint_refs": constraint_ids,
                        },
                    },
                    {
                        "id": "result",
                        "type": "output",
                        "name": "Brief",
                        "config": {"mode": "return", "destination": None},
                        "requirement_refs": requirement_ids,
                        "constraint_refs": constraint_ids,
                    },
                ],
                "edges": [
                    {"from": "document", "to": "extract"},
                    {"from": "extract", "to": "verify"},
                    {"from": "verify", "to": "brief"},
                    {"from": "brief", "to": "review"},
                    {"from": "review", "to": "result"},
                ],
                "variables": [],
                "policies": [
                    {
                        "id": "brief-review",
                        "rules": ["Executive-facing briefs require human review before release."],
                    }
                ],
                "tests": [
                    {
                        "id": "brief-flow",
                        "name": "Extract, verify and summarize",
                        "input": {"document": "Quarterly launch review"},
                        "expected": {"briefed": True},
                        "tags": ["demo"],
                    }
                ],
            }
        )

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

