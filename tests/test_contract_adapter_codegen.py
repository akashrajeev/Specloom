from __future__ import annotations

import ast
import json

from backend.capabilities.models import CapabilitySpec
from backend.compiler.codegen import ArtifactCompiler
from backend.compiler.models import SoftwareSpec
from backend.context.models import ContextGraph
from backend.workflow.models import Node, Trigger, WorkflowIR


def _workflow() -> WorkflowIR:
    return WorkflowIR(
        ir_version="0.1",
        id="contract-adapter-workflow",
        name="Contract Adapter Workflow",
        trigger=Trigger(
            id="trigger",
            type="trigger",
            name="Manual",
            config={"mode": "manual"},
        ),
        nodes=[Node(id="output", type="output", name="Output")],
        edges=[{"from": "trigger", "to": "output"}],
        variables=[],
        policies=[],
        tests=[],
    )


def _capability() -> CapabilitySpec:
    return CapabilitySpec(
        id="apiop:orders:create-order",
        kind="openapi",
        name="Create order",
        description="Create an order",
        method="POST",
        path="/orders/{id}",
        base_url="https://api.example.test/v1",
        access="write",
        permissions=["READ", "WRITE"],
        side_effecting=True,
        requires_human_approval=True,
        auth_env="ORDERS_API_KEY",
        auth_header="Authorization",
        auth_prefix="Bearer ",
        input_schema={
            "type": "object",
            "properties": {"id": {"type": "string"}, "body": {"type": "object"}},
        },
        output_schema={"type": "object"},
        tags=["orders", "api", "openapi", "write"],
    )


def test_verified_contract_generates_executable_adapter_artifact():
    capability = _capability()
    source = ArtifactCompiler._contract_adapter_source(capability)

    ast.parse(source)
    assert "PATH_TEMPLATE = '/orders/{id}'" in source
    assert "BASE_URL = 'https://api.example.test/v1'" in source
    assert "AUTH_ENV = 'ORDERS_API_KEY'" in source
    assert "urlopen" in source


def test_generated_contract_adapter_uses_exact_verified_endpoint(monkeypatch):
    capability = _capability()
    namespace: dict[str, object] = {}
    exec(ArtifactCompiler._contract_adapter_source(capability), namespace)

    observed: dict[str, object] = {}

    class Response:
        status = 201

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"id":"created"}'

    def fake_urlopen(request, timeout):
        observed["url"] = request.full_url
        observed["method"] = request.method
        observed["headers"] = dict(request.header_items())
        observed["body"] = request.data
        observed["timeout"] = timeout
        return Response()

    namespace["urlopen"] = fake_urlopen
    monkeypatch.setenv("ORDERS_API_KEY", "secret-token")

    invoke = namespace["invoke"]
    result = invoke({"id": "A/B", "body": {"amount": 10}})

    assert observed["url"] == "https://api.example.test/v1/orders/A%2FB"
    assert observed["method"] == "POST"
    assert observed["timeout"] == 20
    assert "Authorization" in observed["headers"]
    assert observed["headers"]["Authorization"] == "Bearer secret-token"
    assert json.loads(observed["body"].decode("utf-8")) == {
        "id": "A/B",
        "body": {"amount": 10},
    }
    assert result["_http_status"] == 201


def test_contract_registry_and_adapter_are_emitted():
    capability = _capability()
    context = ContextGraph(capabilities=[capability])
    spec = SoftwareSpec(
        id="contract-adapter",
        name="Contract Adapter",
        goal="Use a verified order API.",
        capability_requirements=[],
        contract_proven=True,
    )

    bundle = ArtifactCompiler().compile(spec, _workflow(), context=context)

    adapter = next(
        item for item in bundle.artifacts
        if item.path == "generated/capabilities/contracts/apiop_orders_create_order.py"
    )
    registry = next(
        item for item in bundle.artifacts
        if item.path == "generated/spec/capability-adapter-registry.json"
    )

    assert "https://api.example.test/v1" in adapter.content
    payload = json.loads(registry.content)
    assert payload[capability.id]["artifact_path"] == adapter.path
    assert payload[capability.id]["method"] == "POST"



def test_universal_compiler_proves_selected_contract_adapter(monkeypatch):
    from backend.compiler.universal import UniversalCompiler

    monkeypatch.setenv("SPECL00M_IMPLEMENTATION_MODE", "deterministic")
    capability = _capability()
    context = ContextGraph(
        capabilities=[capability],
    )
    bundle = UniversalCompiler().compile(
        "Create an order using the orders API.",
        context,
        _workflow(),
    )

    assert bundle.spec.contract_proven is True
    assert bundle.spec.contract_adapters_proven is True
    assert bundle.spec.contract_adapters_missing == []
    assert capability.id in bundle.spec.contract_adapter_artifacts
    assert (
        bundle.spec.contract_adapter_artifacts[capability.id]
        == "generated/capabilities/contracts/apiop_orders_create_order.py"
    )
