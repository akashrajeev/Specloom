from __future__ import annotations

import hashlib
import os
import re
from typing import Iterable

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph

from .capability_discovery import BedrockCapabilityDiscovery, DiscoveredCapability
from .decomposition import ProblemDecomposition
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
    *,
    problem_decomposition: ProblemDecomposition | None = None,
) -> list[CapabilityRequirement]:
    """Produce the canonical capability requirements for goal-relevant context capabilities."""
    requirements: list[CapabilityRequirement] = []
    seen: set[str] = set()
    decomposition_families = {
        _normalize_family(family)
        for step in (problem_decomposition.steps if problem_decomposition is not None else ())
        for family in step.capability_families
    }
    decomposition_refs = (
        set(problem_decomposition.capability_refs)
        if problem_decomposition is not None
        else set()
    )

    for capability in context.capabilities:
        family = _capability_family(capability)
        family_patterns = _FAMILY_PATTERNS.get(family, ())
        matched = any(
            re.search(pattern, goal, re.I)
            for pattern in family_patterns
        )
        matched_via_decomposition = bool(
            capability.id in decomposition_refs
            or _normalize_family(family) in decomposition_families
        )
        if not matched and matched_via_decomposition:
            matched = True
        if family == "external-service" and not matched:
            matched = bool(
                _EXTERNAL_ACTION.search(goal)
                and re.search(
                    r"\b(external|api|service|endpoint|webhook)\b",
                    goal,
                    re.I,
                )
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
                    capability.access
                    if matched_via_decomposition
                    else (
                        "write"
                        if capability.side_effecting and _is_write_intent(goal, family)
                        else "read"
                    )
                ),
                external=capability.kind in {
                    "synthesized", "openapi", "configured_api", "mcp",
                },
                required=True,
            )
        )
        seen.add(capability.id)

    return requirements


def _normalize_family(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", str(value).lower()).strip("-")


def _capability_family(capability: CapabilitySpec) -> str:
    for tag in capability.tags:
        if tag not in {"api", "openapi", "synthesized", "generated_http"}:
            return str(tag)
    if capability.id.startswith("synth:"):
        parts = capability.id.split(":")
        if len(parts) > 1:
            return parts[1]
    return capability.name.split()[0].lower()



_WRITE_INTENT_PATTERNS: dict[str, tuple[str, ...]] = {
    "email": (
        r"\b(send\w*|forward\w*|reply\w*|mail\w*)\b.{0,80}\b(email|e-mail|recipient|inbox)\b",
        r"\b(email|e-mail)\b.{0,60}\b(send\w*|forward\w*|reply\w*)\b",
    ),
    "slack": (
        r"\b(send|post|publish|message|notify)\b.{0,80}\b(slack|channel)\b",
        r"\b(slack|channel)\b.{0,60}\b(send|post|publish|message)\b",
    ),
    "calendar": (
        r"\b(book|schedule|create|update|cancel|reschedule)\b.{0,80}\b(meeting|appointment|calendar)\b",
        r"\b(calendar|meeting|appointment)\b.{0,60}\b(book|schedule|update|cancel)\b",
    ),
    "database": (
        r"\b(insert|update|delete|write|save|store)\b.{0,80}\b(database|db|record|sql)\b",
        r"\b(database|db|record|sql)\b.{0,60}\b(insert|update|delete|write|save|store)\b",
    ),
    "jira": (
        r"\b(create|update|delete|transition|comment|assign)\b.{0,80}\bjira\b",
        r"\bjira\b.{0,60}\b(create|update|delete|transition|comment|assign)\b",
    ),
    "linear": (
        r"\b(create|update|delete|comment|assign)\b.{0,80}\blinear\b",
        r"\blinear\b.{0,60}\b(create|update|delete|comment|assign)\b",
    ),
    "sms": (
        r"\b(send|message|text)\b.{0,80}\b(sms|text message|twilio)\b",
        r"\b(sms|text message)\b.{0,60}\b(send|message|text)\b",
    ),
    "storage": (
        r"\b(upload|delete|write|save|store)\b.{0,80}\b(s3|bucket|object storage|file storage)\b",
        r"\b(s3|bucket|object storage|file storage)\b.{0,60}\b(upload|delete|write|save|store)\b",
    ),
    "payments": (
        r"\b(charge|refund|pay|capture|checkout)\b.{0,80}\b(payment|stripe|checkout)\b",
        r"\b(payment|stripe|checkout)\b.{0,60}\b(charge|refund|pay|capture)\b",
    ),
    "notification": (
        r"\b(send|trigger|publish|notify|alert)\b.{0,80}\b(notification|alert)\b",
        r"\b(notification|alert)\b.{0,60}\b(send|trigger|publish|notify)\b",
    ),
    "browser": (),
}


def _is_write_intent(goal: str, family: str) -> bool:
    if family == "external-service":
        source_context = re.search(
            r"\b(from|using|based\s+on|read|retrieve|fetch|query|search|parse)\b",
            goal,
            re.I,
        )
        return bool(_WRITE_ACTION.search(goal)) and source_context is None

    specific_patterns = _WRITE_INTENT_PATTERNS.get(family, ())
    if any(re.search(pattern, goal, re.I | re.S) for pattern in specific_patterns):
        return True

    family_pattern = rf"\b{re.escape(family.rstrip('s'))}s?\b"
    write_near_family = rf"\b(send\w*|create\w*|update\w*|delete\w*|publish\w*|upload\w*|post\w*|book\w*|notify\w*|message\w*|charge\w*|refund\w*|insert\w*|save\w*|store\w*)\b(?:\W+\w+){{0,4}}\W+{family_pattern}"
    family_near_write = rf"{family_pattern}(?:\W+\w+){{0,4}}\W+\b(create\w*|update\w*|delete\w*|publish\w*|upload\w*|post\w*|book\w*|notify\w*|message\w*|charge\w*|refund\w*|insert\w*|save\w*|store\w*)\b"
    source_from_family = rf"\b(from|using|based\s+on|read\w*|retrieve\w*|fetch\w*|query|search\w*|parse\w*)\b(?:\W+\w+){{0,4}}\W+{family_pattern}"

    if re.search(source_from_family, goal, re.I | re.S):
        return False
    return bool(
        re.search(write_near_family, goal, re.I | re.S)
        or re.search(family_near_write, goal, re.I | re.S)
    )


def _capability_access(goal: str, capability: CapabilitySpec, family: str) -> str:
    if not capability.side_effecting:
        return "read"
    return "write" if _is_write_intent(goal, family) else "read"


def synthesize_missing_capabilities(
    goal: str,
    context: ContextGraph,
    *,
    discovered: Iterable[DiscoveredCapability] | None = None,
    problem_decomposition: ProblemDecomposition | None = None,
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

    # Open-world discovery can add provider-neutral families that are not part
    # of the deterministic vocabulary (CRM, ERP, issue tracker, etc.).
    for item in discovered or ():
        if _family_available(item.family, available):
            continue
        matched_family = True
        _append_synthesized(
            family=item.family,
            goal=goal,
            capabilities=capabilities,
            requirements=requirements,
            plans=plans,
            access_override=item.access,
            purpose_override=item.purpose,
            side_effecting_override=item.side_effecting,
            approval_override=item.requires_human_approval,
        )

    # Decomposition may identify an integration family even when the original
    # natural-language goal never names the provider or even the domain family.
    decomposition_families: dict[str, list[str]] = {}
    if problem_decomposition is not None:
        for step in problem_decomposition.steps:
            for family in step.capability_families:
                normalized = re.sub(r"[^a-z0-9-]+", "-", family.lower()).strip("-")
                if len(normalized) >= 2:
                    decomposition_families.setdefault(normalized, []).append(step.objective)

    known_families = {
        _normalize_family(_capability_family(item))
        for item in context.capabilities
        if item.kind != "synthesized"
    }
    known_families.update(
        re.sub(r"[^a-z0-9-]+", "-", item.family.lower()).strip("-")
        for item in discovered or ()
    )
    for family, objectives in decomposition_families.items():
        if family in known_families:
            continue
        matched_family = True
        decomposition_goal = goal + "\nSubproblem responsibilities:\n" + "\n".join(objectives)
        _append_synthesized(
            family=family,
            goal=decomposition_goal,
            capabilities=capabilities,
            requirements=requirements,
            plans=plans,
        )
        known_families.add(family)

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
    access_override: str | None = None,
    purpose_override: str | None = None,
    side_effecting_override: bool | None = None,
    approval_override: bool | None = None,
) -> None:
    write = _is_write_intent(goal, family)
    access = access_override if access_override in {"read", "write"} else ("write" if write else "read")
    write = access == "write"
    capability_id = _stable_capability_id(family, goal)
    family_slug = re.sub(r"[^A-Za-z0-9_]+", "_", family).strip("_").lower() or "external_service"
    normalized_family = family_slug.upper()
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
            f"generated/capabilities/{family_slug}.py",
            f"generated/tests/test_{family_slug}.py",
        ],
        configuration_required=True,
    )

    requirements.append(
        CapabilityRequirement(
            id=f"capreq_{family}",
            family=family,
            purpose=purpose_override or f"Provide the {family} capability requested by the user's goal.",
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
            side_effecting=(
                bool(side_effecting_override)
                if side_effecting_override is not None
                else write
            ),
            requires_human_approval=(
                bool(approval_override)
                if approval_override is not None
                else write
            ),
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
