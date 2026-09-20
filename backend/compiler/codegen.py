from __future__ import annotations

import ast
import json
import re
from typing import Iterable

from .deployment import DeploymentCompiler
from .infrastructure import InfrastructureCompiler
from .models import Artifact, CompilationBundle, CompilerDiagnostic, SoftwareSpec
from .provisioning import ProvisioningCompiler
from backend.workflow.models import WorkflowIR
from backend.context.models import ContextGraph


class ArtifactCompiler:
    """Generate deterministic, inspectable implementation artifacts from SoftwareSpec."""

    def compile(
        self,
        spec: SoftwareSpec,
        workflow: WorkflowIR,
        context: ContextGraph | None = None,
    ) -> CompilationBundle:
        provisioning_plan = ProvisioningCompiler().compile(
            spec,
            context or ContextGraph(),
        )

        artifacts: list[Artifact] = [
            self._json_artifact(
                "generated/spec/system-spec.json",
                spec.model_dump(mode="json"),
                "spec",
            ),
            self._json_artifact(
                "generated/spec/implementation-plan.json",
                spec.implementation_plan,
                "spec",
            ),
            self._json_artifact(
                "generated/spec/workflow-ir.json",
                workflow.model_dump(mode="json"),
                "spec",
            ),
            self._generated_app(spec, workflow),
            self._dockerfile(),
            self._deployment(spec),
            self._documentation(spec),
            self._provisioning_plan(provisioning_plan),
        ]

        for plan in spec.synthesized_capabilities:
            artifacts.append(
                self._capability_module(
                    plan.family,
                    plan.capability_id,
                    plan.provisioning_env,
                    plan.artifact_paths[0],
                )
            )
            artifacts.append(
                self._capability_test(
                    plan.family,
                    plan.provisioning_env,
                    plan.artifact_paths[1],
                    plan.artifact_paths[0],
                )
            )

        contract_artifacts, contract_registry = self._contract_adapters(
            context or ContextGraph(),
        )
        artifacts.extend(contract_artifacts)
        if contract_registry:
            artifacts.append(
                self._json_artifact(
                    "generated/spec/capability-adapter-registry.json",
                    contract_registry,
                    "spec",
                )
            )

        deployment_plan = DeploymentCompiler().compile(
            spec,
            [item.with_hash() for item in artifacts],
            provisioning_ready=provisioning_plan.ready,
        )
        artifacts.append(
            Artifact(
                path="generated/deploy/deployment-plan.json",
                kind="infrastructure",
                content=json.dumps(
                    deployment_plan.model_dump(mode="json"),
                    indent=2,
                    sort_keys=True,
                ) + "\n",
                generated_from=[spec.id],
            )
        )

        diagnostics = self._verify(artifacts)
        ready_for_runtime = not any(
            item.severity == "blocking" for item in diagnostics
        )
        requires_provisioning = bool(spec.synthesized_capabilities)
        if requires_provisioning:
            diagnostics.append(
                CompilerDiagnostic(
                    severity="warning",
                    code="provisioning-required",
                    message=(
                        "Generated external capability adapters are ready as artifacts "
                        "but require trusted endpoint/auth configuration before live execution."
                    ),
                )
            )

        return CompilationBundle(
            spec=spec,
            artifacts=[item.with_hash() for item in artifacts],
            diagnostics=diagnostics,
            ready_for_runtime=ready_for_runtime,
            requires_provisioning=requires_provisioning,
            provisioning=provisioning_plan.model_dump(mode="json"),
            deployment=deployment_plan.model_dump(mode="json"),
        )

    @staticmethod
    def _json_artifact(path: str, value: dict, kind: str) -> Artifact:
        return Artifact(
            path=path,
            kind=kind,
            content=json.dumps(value, indent=2, sort_keys=True) + "\n",
        )

    @staticmethod
    def _generated_app(spec: SoftwareSpec, workflow: WorkflowIR) -> Artifact:
        content = (
            "from __future__ import annotations\n\n"
            "from fastapi import FastAPI\n\n"
            f"app = FastAPI(title={spec.name!r})\n"
            f"WORKFLOW_ID = {workflow.id!r}\n\n"
            "@app.get(\"/health\")\n"
            "def health() -> dict[str, str]:\n"
            "    return {\"status\": \"ok\", \"workflow_id\": WORKFLOW_ID}\n\n"
            "@app.get(\"/manifest\")\n"
            "def manifest() -> dict[str, object]:\n"
            "    return {\n"
            f"        \"name\": {spec.name!r},\n"
            f"        \"architecture_style\": {spec.architecture_style!r},\n"
            "        \"workflow_id\": WORKFLOW_ID,\n"
            "        \"generated\": True,\n"
            "    }\n"
        )
        return Artifact(
            path="generated/backend/app.py",
            kind="source",
            content=content,
            executable=True,
            generated_from=[workflow.id],
        )

    @staticmethod
    def _dockerfile() -> Artifact:
        content = (
            "FROM python:3.11-slim\n"
            "WORKDIR /app\n"
            "COPY generated/backend/app.py /app/app.py\n"
            "RUN pip install --no-cache-dir fastapi uvicorn\n"
            "EXPOSE 8080\n"
            'CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]\n'
        )
        return Artifact(path="generated/Dockerfile", kind="config", content=content)

    @staticmethod
    def _deployment(spec: SoftwareSpec) -> Artifact:
        return InfrastructureCompiler().compile(spec)

    @staticmethod
    def _provisioning_plan(plan) -> Artifact:
        return Artifact(
            path="generated/provisioning/plan.json",
            kind="infrastructure",
            content=json.dumps(
                plan.model_dump(mode="json"),
                indent=2,
                sort_keys=True,
            ) + "\n",
        )

    @staticmethod
    def _documentation(spec: SoftwareSpec) -> Artifact:
        lines = [
            f"# Generated implementation package: {spec.name}",
            "",
            "This package was synthesized from Specloom SoftwareSpec + Workflow IR.",
            "",
            "## Runtime boundary",
            (
                "Generated external adapters never invent provider URLs or credentials. "
                "Configure their documented environment variables before enabling live mode."
            ),
            "",
            "## Services",
        ]
        lines.extend(
            f"- {item.id}: {item.name} ({item.runtime})"
            for item in spec.services
        )
        lines.extend(["", "## Synthesized capabilities"])
        lines.extend(
            f"- {item.capability_id} -> {', '.join(item.provisioning_env)}"
            for item in spec.synthesized_capabilities
        )
        return Artifact(
            path="generated/README.md",
            kind="documentation",
            content="\n".join(lines) + "\n",
        )

    @staticmethod
    def contract_adapter_path(capability_id: str) -> str:
        safe_id = re.sub(
            r"[^A-Za-z0-9_]+",
            "_",
            capability_id,
        ).strip("_").lower() or "capability"
        return f"generated/capabilities/contracts/{safe_id}.py"

    @staticmethod
    def _contract_adapters(
        context: ContextGraph,
    ) -> tuple[list[Artifact], dict]:
        """Compile verified external capability metadata into deterministic adapters."""
        artifacts: list[Artifact] = []
        registry: dict[str, dict] = {}

        concrete = [
            item
            for item in context.capabilities
            if item.kind in {"openapi", "configured_api"}
            and item.base_url
            and item.path
            and item.method
        ]
        for capability in concrete[:64]:
            path = ArtifactCompiler.contract_adapter_path(capability.id)
            content = ArtifactCompiler._contract_adapter_source(capability)
            artifacts.append(
                Artifact(
                    path=path,
                    kind="source",
                    content=content,
                    executable=True,
                    generated_from=[capability.id],
                )
            )
            registry[capability.id] = {
                "artifact_path": path,
                "method": capability.method,
                "path": capability.path,
                "base_url": capability.base_url,
                "access": capability.access,
                "side_effecting": capability.side_effecting,
                "requires_human_approval": capability.requires_human_approval,
                "auth_env": capability.auth_env,
                "auth_header": capability.auth_header,
            }
        return artifacts, registry

    @staticmethod
    def _contract_adapter_source(capability) -> str:
        method = str(capability.method).upper()
        base_url = str(capability.base_url).rstrip("/")
        path = str(capability.path)
        auth_env = capability.auth_env or ""
        auth_header = capability.auth_header or "Authorization"
        auth_prefix = capability.auth_prefix or ""
        return f'''from __future__ import annotations

import json
import os
import re
from urllib.parse import quote, urlencode, urljoin
from urllib.request import Request, urlopen

CAPABILITY_ID = {capability.id!r}
BASE_URL = {base_url!r}
PATH_TEMPLATE = {path!r}
METHOD = {method!r}
AUTH_ENV = {auth_env!r}
AUTH_HEADER = {auth_header!r}
AUTH_PREFIX = {auth_prefix!r}
ACCESS = {capability.access!r}
SIDE_EFFECTING = {bool(capability.side_effecting)!r}
INPUT_SCHEMA = {json.dumps(capability.input_schema, sort_keys=True)!r}
OUTPUT_SCHEMA = {json.dumps(capability.output_schema, sort_keys=True)!r}


def _render_path(payload: dict) -> str:
    path = PATH_TEMPLATE
    parameters = re.findall(r"\\x7b([^\\x7b\\x7d]+)\\x7d", PATH_TEMPLATE)
    missing = [
        name
        for name in parameters
        if name not in payload
    ]
    if missing:
        raise ValueError(
            CAPABILITY_ID + " missing required path parameters: "
            + ", ".join(sorted(set(missing)))
        )
    for name in parameters:
        path = path.replace(
            "{" + name + "}",
            quote(str(payload[name]), safe=""),
        )
    return path


def invoke(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise TypeError("capability payload must be an object")

    path = _render_path(payload)
    target = urljoin(BASE_URL.rstrip("/") + "/", path.lstrip("/"))
    if not target.lower().startswith("https://"):
        raise RuntimeError("verified contract adapters require HTTPS")

    headers = {{"Accept": "application/json"}}
    if AUTH_ENV:
        token = os.getenv(AUTH_ENV, "").strip()
        if not token:
            raise RuntimeError(
                CAPABILITY_ID + " requires credential environment variable " + AUTH_ENV
            )
        headers[AUTH_HEADER] = AUTH_PREFIX + token

    method = METHOD
    body = None
    request_payload = dict(payload)

    if method in {{"GET", "HEAD", "OPTIONS"}}:
        for segment in list(request_payload):
            if "{" + segment + "}" in PATH_TEMPLATE:
                request_payload.pop(segment, None)
        if request_payload:
            target += ("&" if "?" in target else "?") + urlencode(request_payload, doseq=True)
    else:
        headers["Content-Type"] = "application/json"
        body = json.dumps(request_payload).encode("utf-8")

    request = Request(
        target,
        data=body,
        headers=headers,
        method=method,
    )
    with urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
        status = int(response.status)

    if not raw:
        return {{"status": status}}
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = {{"status": status, "body": raw}}
    if isinstance(value, dict):
        value.setdefault("_http_status", status)
        return value
    return {{"status": status, "data": value}}
'''

    @staticmethod
    def _capability_module(
        family: str,
        capability_id: str,
        env: list[str],
        path: str,
    ) -> Artifact:
        content = f'''from __future__ import annotations

import json
import os
from urllib.parse import urljoin
from urllib.request import Request, urlopen

CAPABILITY_ID = {capability_id!r}
BASE_URL_ENV = {env[0]!r}
PATH_ENV = {env[1]!r}
METHOD_ENV = {env[2]!r}
API_KEY_ENV = {env[3]!r}


def invoke(payload: dict) -> dict:
    base_url = os.getenv(BASE_URL_ENV, "").strip()
    path = os.getenv(PATH_ENV, "").strip()
    method = os.getenv(METHOD_ENV, "POST").strip().upper()
    if not base_url or not path:
        raise RuntimeError(
            CAPABILITY_ID + " requires " + BASE_URL_ENV + " and " + PATH_ENV
        )
    if not base_url.lower().startswith("https://"):
        raise RuntimeError("generated external adapters require HTTPS")
    target = urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    headers = {{"Content-Type": "application/json"}}
    token = os.getenv(API_KEY_ENV, "").strip()
    if token:
        headers["Authorization"] = "Bearer " + token
    body = json.dumps(payload).encode("utf-8") if method not in {{"GET", "HEAD"}} else None
    request = Request(target, data=body, headers=headers, method=method)
    with urlopen(request, timeout=20) as response:
        raw = response.read().decode("utf-8")
    try:
        return json.loads(raw) if raw else {{"status": "ok"}}
    except json.JSONDecodeError:
        return {{"status": "ok", "body": raw}}
'''
        return Artifact(
            path=path,
            kind="source",
            content=content,
            executable=True,
            generated_from=[capability_id],
        )

    @staticmethod
    def _capability_test(
        family: str,
        env: list[str],
        path: str,
        module_path: str,
    ) -> Artifact:
        safe_name = re.sub(r"[^A-Za-z0-9_]+", "_", family).strip("_").lower() or "external_service"
        content = f'''import ast
from pathlib import Path


def test_generated_{safe_name}_adapter_is_python():
    source = Path({module_path!r}).read_text(encoding="utf-8")
    ast.parse(source)


def test_generated_{safe_name}_adapter_requires_configuration():
    source = Path({module_path!r}).read_text(encoding="utf-8")
    assert {env[0]!r} in source
    assert {env[1]!r} in source
'''
        return Artifact(
            path=path,
            kind="test",
            content=content,
            generated_from=[f"capreq_{family}"],
        )

    @staticmethod
    def _verify(artifacts: Iterable[Artifact]) -> list[CompilerDiagnostic]:
        diagnostics: list[CompilerDiagnostic] = []
        for artifact in artifacts:
            parts = artifact.path.split("/")
            if artifact.path.startswith("/") or ".." in parts:
                diagnostics.append(
                    CompilerDiagnostic(
                        severity="blocking",
                        code="unsafe-artifact-path",
                        message="Generated artifact path escapes the project root.",
                        artifact_path=artifact.path,
                    )
                )
            if artifact.path.endswith(".py"):
                try:
                    ast.parse(artifact.content)
                except SyntaxError as exc:
                    diagnostics.append(
                        CompilerDiagnostic(
                            severity="blocking",
                            code="generated-python-syntax",
                            message=str(exc),
                            artifact_path=artifact.path,
                        )
                    )
            if artifact.kind == "spec" and artifact.path.endswith(".json"):
                try:
                    json.loads(artifact.content)
                except json.JSONDecodeError as exc:
                    diagnostics.append(
                        CompilerDiagnostic(
                            severity="blocking",
                            code="generated-json-invalid",
                            message=str(exc),
                            artifact_path=artifact.path,
                        )
                    )
        return diagnostics
