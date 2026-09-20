import json
from unittest.mock import patch

from backend.compiler.contracts import CapabilityContractAcquirer
from backend.context.ingestion import IngestedSource
from backend.context.models import ContextGraph, Source


OPENAPI = {
    "openapi": "3.0.3",
    "info": {"title": "Ticket API", "version": "1.0.0"},
    "servers": [{"url": "https://tickets.example.com"}],
    "paths": {
        "/tickets": {
            "post": {
                "operationId": "createTicket",
                "summary": "Create ticket",
                "responses": {"201": {"description": "created"}},
            }
        }
    },
}


def test_contract_acquirer_compiles_explicit_api_spec_document():
    source = Source(id="src_api", kind="api_spec", name="Ticket API")
    context, result = CapabilityContractAcquirer().acquire(
        "Create tickets using the ticket API.",
        ContextGraph(sources=[source]),
        {"src_api": json.dumps(OPENAPI)},
    )

    assert result.errors == []
    assert result.acquired_sources == ["src_api"]
    assert result.acquired_capabilities == ["apiop:ticket-api:createticket"]
    assert any(
        item.id == "apiop:ticket-api:createticket"
        for item in context.capabilities
    )


def test_contract_acquirer_fetches_only_explicit_url_sources():
    source = Source(
        id="src_url",
        kind="url",
        name="Ticket API document",
        uri="https://tickets.example.com/openapi.json",
    )
    fetched = IngestedSource(
        source=Source(
            id="src_fetched",
            kind="url",
            name="API contract",
            uri="https://tickets.example.com/openapi.json",
        ),
        text=json.dumps(OPENAPI),
    )

    with patch.object(
        CapabilityContractAcquirer,
        "_fetch",
        return_value=fetched,
    ):
        context, result = CapabilityContractAcquirer().acquire(
            "Create tickets using the ticket API.",
            ContextGraph(sources=[source]),
            {},
        )

    assert result.errors == []
    assert result.acquired_sources == ["src_fetched"]
    assert result.acquired_documents["src_fetched"] == fetched.text
    assert any(
        item.id == "apiop:api-contract:createticket"
        for item in context.capabilities
    )


def test_contract_acquirer_ignores_non_openapi_url_documents():
    source = Source(
        id="src_docs",
        kind="url",
        name="HTML documentation",
        uri="https://tickets.example.com/docs",
    )
    fetched = IngestedSource(
        source=source,
        text="<html><body>not an OpenAPI document</body></html>",
    )

    with patch.object(
        CapabilityContractAcquirer,
        "_fetch",
        return_value=fetched,
    ):
        context, result = CapabilityContractAcquirer().acquire(
            "Use the ticket API.",
            ContextGraph(sources=[source]),
            {},
        )

    assert result.acquired_capabilities == []
    assert result.skipped_sources == ["src_docs"]
    assert context.capabilities == []



def test_contract_acquirer_accepts_only_explicit_research_https_refs():
    fetched = IngestedSource(
        source=Source(
            id="src_research_contract",
            kind="url",
            name="API contract",
            uri="https://tickets.example.com/openapi.json",
        ),
        text=json.dumps(OPENAPI),
    )
    context = ContextGraph(
        research_evidence=[
            {
                "task_id": "research-integration-contracts",
                "summary": "Found the official contract.",
                "source_refs": [
                    "https://tickets.example.com/openapi.json",
                    "ignore this prose",
                ],
                "confidence": 1.0,
            }
        ]
    )

    with patch.object(
        CapabilityContractAcquirer,
        "_fetch",
        return_value=fetched,
    ) as fetch:
        updated, result = CapabilityContractAcquirer().acquire(
            "Create tickets using a ticket API.",
            context,
            {},
        )

    fetch.assert_called_once_with("https://tickets.example.com/openapi.json")
    assert result.errors == []
    assert result.acquired_capabilities == ["apiop:api-contract:createticket"]
    assert any(
        item.id == "apiop:api-contract:createticket"
        for item in updated.capabilities
    )



def test_contract_acquirer_reports_verified_and_unresolved_capability_families():
    from backend.capabilities.models import CapabilitySpec
    from backend.compiler.contracts import CapabilityContractAcquirer
    from backend.context.models import ContextGraph

    placeholders = [
        CapabilitySpec(
            id="synth:crm:create",
            kind="synthesized",
            name="CRM writer",
            description="Create CRM leads",
            access="write",
            side_effecting=True,
            tags=["crm"],
        ),
        CapabilitySpec(
            id="synth:erp:create",
            kind="synthesized",
            name="ERP writer",
            description="Create ERP purchase orders",
            access="write",
            side_effecting=True,
            tags=["erp"],
        ),
    ]
    verified_crm = CapabilitySpec(
        id="apiop:crm:create-lead",
        kind="openapi",
        name="Create CRM lead",
        description="Create CRM lead",
        access="write",
        side_effecting=True,
        tags=["crm", "lead"],
        base_url="https://crm.example",
        method="POST",
        path="/leads",
    )
    acquirer = CapabilityContractAcquirer()

    context = ContextGraph(capabilities=[*placeholders, verified_crm])
    updated, result = acquirer.acquire(
        "Create CRM leads and ERP purchase orders.",
        context,
        {},
    )

    assert "crm" in {item.lower() for item in result.verified_capability_families}
    assert "erp" in {item.lower() for item in result.unresolved_capability_families}
    assert updated.capabilities
