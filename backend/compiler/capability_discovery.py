from __future__ import annotations

import json
import os
import re
from typing import Any

from pydantic import BaseModel, Field

from backend.bedrock_config import resolve_bedrock_model
from backend.context.models import ContextGraph


class DiscoveredCapability(BaseModel):
    family: str = Field(min_length=2, max_length=64)
    purpose: str = Field(min_length=1, max_length=300)
    access: str = "read"
    side_effecting: bool = False
    requires_human_approval: bool = False
    evidence: list[str] = Field(default_factory=list)


class CapabilityDiscovery(BaseModel):
    capabilities: list[DiscoveredCapability] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


class BedrockCapabilityDiscovery:
    """Discover provider-neutral capability families from arbitrary goals.

    This compiler is deliberately provider-blind: it can name a capability family
    such as CRM, ERP, issue tracker, object storage, or browser automation, but it
    never invents provider URLs, credentials, endpoint paths, or undocumented APIs.
    """

    def __init__(self, model_id: str = "") -> None:
        try:
            from strands import Agent
            from strands.models import BedrockModel
        except ImportError as exc:
            raise RuntimeError(
                "AWS capability-discovery dependencies are missing. "
                "Install backend/requirements-aws.txt"
            ) from exc

        resolved = resolve_bedrock_model(model_id)
        self._agent = Agent(
            model=BedrockModel(model_id=resolved),
            system_prompt=(
                "You are Specloom's open-world capability discovery compiler. "
                "Infer only the external capability families materially required by the goal. "
                "Use provider-neutral family names, never provider URLs or invented API operations. "
                "Mark write/side-effecting operations accurately and require human approval when "
                "the goal performs consequential external actions. "
                "Return only CapabilityDiscovery JSON."
            ),
        )

    def discover(
        self,
        *,
        goal: str,
        context: ContextGraph,
        problem_decomposition: dict[str, Any] | None = None,
    ) -> CapabilityDiscovery:
        known = sorted(
            {
                token
                for item in context.capabilities
                for token in [item.name, item.id, *item.tags]
                if token
            }
        )
        prompt = (
            "Identify missing external capability families needed to implement the goal.\n\n"
            f"GOAL:\n{goal}\n\n"
            f"KNOWN CAPABILITIES:\n{json.dumps(known, indent=2)}\n\n"
            f"CONTEXT:\n{context.model_dump_json(indent=2)}\n\n"
            f"DECOMPOSITION:\n{json.dumps(problem_decomposition or {}, indent=2)}\n\n"
            "Use the decomposition to identify capabilities needed by subproblems, especially adapter/service steps. "
            "Do not propose providers, base URLs, credentials, endpoint paths, or undocumented APIs. "
            "Return the minimum capability family set. "
            "Examples of acceptable family names include crm, erp, issue-tracker, "
            "messaging, object-storage, browser, payments, database."
        )
        result = self._agent(
            prompt,
            structured_output_model=CapabilityDiscovery,
        )
        structured = getattr(result, "structured_output", result)
        if isinstance(structured, CapabilityDiscovery):
            value = structured
        elif isinstance(structured, dict):
            value = CapabilityDiscovery.model_validate(structured)
        else:
            value = CapabilityDiscovery.model_validate(json.loads(str(structured)))

        normalized: list[DiscoveredCapability] = []
        seen: set[str] = set()
        for item in value.capabilities:
            family = re.sub(r"[^a-z0-9-]+", "-", item.family.lower()).strip("-")
            if len(family) < 2 or family in seen:
                continue
            seen.add(family)
            access = "write" if item.access.lower() == "write" else "read"
            normalized.append(
                item.model_copy(
                    update={
                        "family": family,
                        "access": access,
                        "side_effecting": bool(
                            item.side_effecting or access == "write"
                        ),
                        "requires_human_approval": bool(
                            item.requires_human_approval
                            or access == "write"
                        ),
                    }
                )
            )
        return CapabilityDiscovery(
            capabilities=normalized,
            uncertainties=value.uncertainties,
        )
