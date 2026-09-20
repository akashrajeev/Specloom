from __future__ import annotations

import hashlib
import re
from typing import Iterable

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph

from .models import CapabilityRequirement, SynthesizedCapabilityPlan


_FAMILY_PATTERNS: dict[str, tuple[str, ...]] = {
    "email": (r"\b(email|e-mail|mailbox|inbox|smtp)\b",),
    "slack": (r"\bslack\b",),
    "calendar": (r"\b(calendar|meeting|appointment)\b",),
    "database": (r"\b(database|postgres(?:ql)?|mysql|sqlite|sql)\b",),
    "jira": (r"\bjira\b",),
    "linear": (r"\blinear\b",),
    "sms": (r"\b(sms|text message|twilio)\b",),
    "storage": (r"\b(s3|object storage|bucket|file storage|upload file)\b",),
    "payments": (r"\b(payment|stripe|checkout|charge|refund)\b",),
    "notification": (r"\b(notification|notify|alert|escalat)\b",),
    "browser": (r"\b(browser|website|web page|navigate|click|scrape)\b",),
}

_EXTERNAL_ACTION = re.compile(
    r"\b(send|connect|sync|call|invoke|fetch|query|upload|download|publish|post|book|notify|message|charge|refund)\b",
    re.I,
)
_WRITE_ACTION = re.compile(
    r"\b(send|create|update|delete|publish|upload|post|book|notify|message|charge|refund|sync|write)\b",
    re.I,
)



def infer_capability_requirements(
    goal: str,
    context: ContextGraph,
) -> list[CapabilityRequirement]:
    """Produce the canonical capability requirements for goal-relevant context capabilities."""
    requirements: list[CapabilityRequirement] = []
    seen: set[str] = set()

    for capability in context.capabilities:
        family = _capability_family(capability)
        family_patterns = _FAMILY_PATTERNS.get(family, ())
        matched = any(
            re.search(pattern, goal, re.I)
            for pattern in family_patterns
        )
        if not matched:
            tokens = {
                str(value).lower()
                for value in [capability.name, capability.id, *capability.tags]
                if value
            }
            matched = any(
                re.search(rf"\b{re.escape(token)}\b", goal, re.I)
                for token in tokens
                if len(token) >= 4 and token not in {
                    "api", "openapi", "configured", "synthesized",
                    "generated_http", "external", "service", "tool",
                }
            )
        if not matched or capability.id in seen:
            continue

        requirements.append(
            CapabilityRequirement(
                id=f"capreq:{capability.id}",
                family=family,
                purpose=capability.description or capability.name,
                access=(
                    "write"
                    if _WRITE_ACTION.search(goal)
                    and any(
                        re.search(rf"\b{re.escape(term)}\b", goal, re.I)
                        for term in {family, *capability.tags}
                        if term
                    )
                    else capability.access
                ),
                external=capability.kind in {
                    "synthesized", "openapi", "configured_api", "mcp",
                },
                required=True,
            )
        )
        seen.add(capability.id)

    return requirements


def _capability_family(capability: CapabilitySpec) -> str:
    for tag in capability.tags:
        if tag not in {"api", "openapi", "synthesized", "generated_http"}:
            return str(tag)
    if capability.id.startswith("synth:"):
        parts = capability.id.split(":")
        if len(parts) > 1:
            return parts[1]
    return capability.name.split()[0].lower()



def synthesize_missing_capabilities(
    goal: str,
    context: ContextGraph,
) -> tuple[
    list[CapabilitySpec],
    list[CapabilityRequirement],
    list[SynthesizedCapabilityPlan],
]:
    """Create explicit provider-neutral capability contracts for missing integrations.

    The synthesizer never invents provider endpoints. External details remain configuration
    inputs or are filled later from an official API/OpenAPI source. This turns a missing
    integration from a compiler dead-end into an implementation artifact with a hard
    provisioning boundary.
    """
    available = _available_tokens(context)
    capabilities: list[CapabilitySpec] = []
    requirements: list[CapabilityRequirement] = []
    plans: list[SynthesizedCapabilityPlan] = []

    matched_family = False

    for family, patterns in _FAMILY_PATTERNS.items():
        if not any(re.search(pattern, goal, re.I) for pattern in patterns):
            continue
        matched_family = True
        if _family_available(family, available):
            continue
        _append_synthesized(
            family=family,
            goal=goal,
            capabilities=capabilities,
            requirements=requirements,
            plans=plans,
        )

    # A universal compiler cannot depend on an ever-growing hand-written integration list.
    # For an explicitly external action whose domain is unknown, synthesize a generic HTTP
    # contract rather than pretending a provider is known. This is still gated by provisioning.
    if _EXTERNAL_ACTION.search(goal) and not matched_family and not _external_capability_available(context):
        _append_synthesized(
            family="external-service",
            goal=goal,
            capabilities=capabilities,
            requirements=requirements,
            plans=plans,
        )

    return capabilities, requirements, plans


def _append_synthesized(
    *,
    family: str,
    goal: str,
    capabilities: list[CapabilitySpec],
    requirements: list[CapabilityRequirement],
    plans: list[SynthesizedCapabilityPlan],
) -> None:
    write = bool(_WRITE_ACTION.search(goal))
    access = "write" if write else "read"
    capability_id = _stable_capability_id(family, goal)
    normalized_family = re.sub(r"[^A-Za-z0-9]+", "_", family).upper()
    env_prefix = "SPECL00M_SYNTH_" + normalized_family

    plan = SynthesizedCapabilityPlan(
        capability_id=capability_id,
        family=family,
        rationale=(
            f"No trusted {family} integration is configured; synthesize a provider-neutral "
            "adapter contract instead of hallucinating an API."
        ),
        runtime="generated_http",
        provisioning_env=[
            f"{env_prefix}_BASE_URL",
            f"{env_prefix}_PATH",
            f"{env_prefix}_METHOD",
            f"{env_prefix}_API_KEY",
        ],
        artifact_paths=[
            f"generated/capabilities/{family}.py",
            f"generated/tests/test_{family}.py",
        ],
        configuration_required=True,
    )

    requirements.append(
        CapabilityRequirement(
            id=f"capreq_{family}",
            family=family,
            purpose=f"Provide the {family} capability requested by the user's goal.",
            access=access,
            external=True,
            required=True,
        )
    )

    capabilities.append(
        CapabilitySpec(
            id=capability_id,
            kind="synthesized",
            name=f"Synthesized {family} adapter",
            description=(
                f"Provider-neutral {family} capability generated by Specloom; "
                "endpoint/auth configuration is supplied separately."
            ),
            access=access,
            permissions=["READ", "WRITE"] if write else ["READ"],
            side_effecting=write,
            requires_human_approval=write,
            tags=[family, "synthesized", "generated_http"],
            input_schema={
                "type": "object",
                "additionalProperties": True,
                "description": f"Payload for the configured {family} adapter.",
            },
            output_schema={"type": "object", "additionalProperties": True},
            runtime="generated_http",
            implementation_artifacts=plan.artifact_paths,
            provisioning_env=plan.provisioning_env,
            synthesis_reason=plan.rationale,
            execution_modes=["mock", "sandbox", "live"],
        )
    )
    plans.append(plan)


def _available_tokens(context: ContextGraph) -> set[str]:
    tokens: set[str] = set()
    synthesized_ids = {
        capability.id
        for capability in context.capabilities
        if capability.kind == "synthesized"
    }
    for tool in context.tools:
        if tool.id in synthesized_ids or tool.id.startswith("synth:"):
            continue
        tokens.update(str(value).lower() for value in tool.capabilities)
        tokens.add(tool.name.lower())
        tokens.add(tool.id.lower())
    for capability in context.capabilities:
        tokens.update(str(value).lower() for value in capability.tags)
        tokens.add(capability.name.lower())
        tokens.add(capability.id.lower())
    return tokens


def _family_available(family: str, available: Iterable[str]) -> bool:
    candidates = {
        family,
        family.rstrip("s"),
        family.replace("notification", "notify"),
    }
    return any(
        candidate in token or token in candidate
        for token in available
        for candidate in candidates
    )


def _external_capability_available(context: ContextGraph) -> bool:
    return any(
        capability.kind in {"openapi", "configured_api", "mcp"}
        or "external" in capability.tags
        for capability in context.capabilities
    )


def _stable_capability_id(family: str, goal: str) -> str:
    digest = hashlib.sha1(
        f"{family}:{goal.strip().lower()}".encode("utf-8")
    ).hexdigest()[:10]
    return f"synth:{family}:{digest}"
