from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from backend.capabilities.models import CapabilitySpec
from backend.context.models import ContextGraph
from backend.workflow.models import WorkflowIR

from .models import DataModelSpec, ServiceSpec


class SystemActor(BaseModel):
    id: str
    name: str
    description: str = ""


class UseCase(BaseModel):
    id: str
    name: str
    goal: str
    requirement_refs: list[str] = Field(default_factory=list)


class AcceptanceCriterion(BaseModel):
    id: str
    statement: str
    source: Literal["requirement", "constraint", "workflow"] = "requirement"
    required: bool = True
    requirement_refs: list[str] = Field(default_factory=list)
    constraint_refs: list[str] = Field(default_factory=list)


class InterfaceSpec(BaseModel):
    id: str
    kind: Literal["http", "event", "schedule", "workflow", "browser", "internal"]
    direction: Literal["inbound", "outbound", "internal"] = "internal"
    contract: dict[str, Any] = Field(default_factory=dict)


class SecuritySpec(BaseModel):
    authentication: str = "unspecified"
    authorization: str = "least-privilege"
    secrets: str = "environment-or-secret-reference"
    side_effect_controls: bool = True
    network_policy: str = "deny-by-default-for-generated-verification"


class ReliabilitySpec(BaseModel):
    retries: bool = False
    timeouts: bool = False
    idempotency: bool = False
    failure_handling: str = "explicit"


class DeploymentSpec(BaseModel):
    targets: list[str] = Field(default_factory=lambda: ["container"])
    immutable_artifacts: bool = True
    health_check: str = "/health"
    promotion_mode: str = "staged"


class VerificationSpec(BaseModel):
    static_checks: list[str] = Field(
        default_factory=lambda: ["path-safety", "python-ast", "json-parse"]
    )
    executable_checks: list[str] = Field(
        default_factory=lambda: ["generated-contract"]
    )
    acceptance_criteria: list[str] = Field(default_factory=list)


class SystemIR(BaseModel):
    """Canonical system representation above Workflow IR and generated source."""

    version: Literal["0.1"] = "0.1"
    id: str
    name: str
    goal: str
    actors: list[SystemActor] = Field(default_factory=list)
    use_cases: list[UseCase] = Field(default_factory=list)
    acceptance_criteria: list[AcceptanceCriterion] = Field(default_factory=list)
    services: list[ServiceSpec] = Field(default_factory=list)
    interfaces: list[InterfaceSpec] = Field(default_factory=list)
    data_models: list[DataModelSpec] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    security: SecuritySpec = Field(default_factory=SecuritySpec)
    reliability: ReliabilitySpec = Field(default_factory=ReliabilitySpec)
    deployment: DeploymentSpec = Field(default_factory=DeploymentSpec)
    verification: VerificationSpec = Field(default_factory=VerificationSpec)
    workflow_id: str
    source_refs: list[str] = Field(default_factory=list)


class SystemCompiler:
    """Deterministically lower ContextGraph + WorkflowIR into a canonical SystemIR."""

    def compile(
        self,
        goal: str,
        context: ContextGraph,
        workflow: WorkflowIR,
        services: list[ServiceSpec],
        data_models: list[DataModelSpec],
    ) -> SystemIR:
        goal_slug = self._slug(goal)
        actors = [
            SystemActor(
                id="user",
                name="User",
                description="Human or upstream system that supplies the problem intent.",
            ),
            SystemActor(
                id="runtime",
                name="System Runtime",
                description="Generated software responsible for executing the compiled design.",
            ),
        ]

        use_cases = [
            UseCase(
                id=f"usecase-{requirement.id}",
                name=requirement.statement[:80],
                goal=requirement.statement,
                requirement_refs=[requirement.id],
            )
            for requirement in context.requirements
            if requirement.priority != "low"
        ]

        criteria: list[AcceptanceCriterion] = [
            AcceptanceCriterion(
                id=f"accept-{requirement.id}",
                statement=requirement.statement,
                source="requirement",
                requirement_refs=[requirement.id],
            )
            for requirement in context.requirements
            if requirement.priority != "low"
        ]
        criteria.extend(
            AcceptanceCriterion(
                id=f"constraint-{constraint.id}",
                statement=f"System must satisfy constraint: {constraint.statement}",
                source="constraint",
                constraint_refs=[constraint.id],
            )
            for constraint in context.constraints
            if constraint.severity in {"blocking", "warning"}
        )
        criteria.append(
            AcceptanceCriterion(
                id="accept-workflow-valid",
                statement="The compiled Workflow IR is structurally valid and executable by the runtime.",
                source="workflow",
            )
        )

        interfaces = self._interfaces(workflow)
        reliability = self._reliability(workflow)
        security = self._security(context)
        capability_ids = [item.id for item in context.capabilities]

        return SystemIR(
            id=f"system-ir-{goal_slug}",
            name=self._name(goal),
            goal=goal,
            actors=actors,
            use_cases=use_cases,
            acceptance_criteria=criteria,
            services=services,
            interfaces=interfaces,
            data_models=data_models,
            capabilities=capability_ids,
            security=security,
            reliability=reliability,
            deployment=DeploymentSpec(
                targets=["container", "aws"],
                immutable_artifacts=True,
                health_check="/health",
                promotion_mode="staged",
            ),
            verification=VerificationSpec(
                acceptance_criteria=[item.id for item in criteria],
            ),
            workflow_id=workflow.id,
            source_refs=[source.id for source in context.sources],
        )

    @staticmethod
    def _interfaces(workflow: WorkflowIR) -> list[InterfaceSpec]:
        interfaces: list[InterfaceSpec] = []
        mode = workflow.trigger.config.get("mode")
        if mode in {"manual", "webhook", "event"}:
            interfaces.append(
                InterfaceSpec(
                    id="trigger-input",
                    kind="http" if mode == "webhook" else "event",
                    direction="inbound",
                    contract={"trigger_mode": mode},
                )
            )
        elif mode == "schedule":
            interfaces.append(
                InterfaceSpec(
                    id="scheduled-trigger",
                    kind="schedule",
                    direction="inbound",
                    contract={"trigger_mode": mode},
                )
            )

        for node in workflow.nodes:
            if node.type == "tool":
                interfaces.append(
                    InterfaceSpec(
                        id=f"tool-{node.id}",
                        kind="internal",
                        direction="outbound",
                        contract={
                            "tool_ref": node.config.get("tool_ref"),
                            "capability_id": node.config.get("capability", {}).get("id")
                            if isinstance(node.config.get("capability"), dict)
                            else None,
                        },
                    )
                )
        return interfaces

    @staticmethod
    def _reliability(workflow: WorkflowIR) -> ReliabilitySpec:
        retries = any(node.retry and node.retry.max_attempts > 0 for node in workflow.nodes)
        timeouts = any(node.timeout_seconds for node in workflow.nodes)
        idempotency = any(
            node.config.get("idempotency_key")
            for node in workflow.nodes
        )
        return ReliabilitySpec(
            retries=retries,
            timeouts=timeouts,
            idempotency=bool(idempotency),
        )

    @staticmethod
    def _security(context: ContextGraph) -> SecuritySpec:
        auth = "unspecified"
        for requirement in context.requirements:
            if re.search(r"\b(auth|authentication|login|oauth|jwt|identity)\b", requirement.statement, re.I):
                auth = requirement.statement
                break

        side_effects = any(
            item.side_effecting
            for item in context.tools
        )
        return SecuritySpec(
            authentication=auth,
            authorization="least-privilege",
            secrets="environment-or-secret-reference",
            side_effect_controls=side_effects or bool(context.capabilities),
            network_policy="deny-by-default-for-generated-verification",
        )

    @staticmethod
    def _slug(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40] or "system"

    @staticmethod
    def _name(goal: str) -> str:
        words = [word for word in re.findall(r"[A-Za-z0-9]+", goal) if len(word) > 2][:6]
        return "Specloom " + (" ".join(word.title() for word in words) or "Generated System")
