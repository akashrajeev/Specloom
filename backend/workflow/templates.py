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
                        "model": "bedrock",
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
                        "model": "bedrock",
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
