from unittest.mock import patch

from backend.compiler.contracts import CapabilityContractAcquirer
from backend.context.ingestion import IngestedSource
from backend.context.models import ContextGraph, Source
from backend.context.models import ContextTool


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
    context = ContextGraph(sources=[source])
    context, result = CapabilityContractAcquirer().acquire(
        "Create tickets using the ticket API.",
        context,
        {"src_api": __import__("json").dumps(OPENAPI)},
    )

    assert result.errors == []
    assert result.acquired_sources == ["src_api"]
    assert result.acquired_capabilities == ["apiop:ticket-api:create-ticket"]
    assert any(item.id == "apiop:ticket-api:create-ticket" for item in context.capabilities)


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
        text=__import__("json").dumps(OPENAPI),
    )

    with patch.object(CapabilityContractAcquirer, "_fetch", return_value=fetched):
        context, result = CapabilityContractAcquirer().acquire(
            "Create tickets using the ticket API.",
            ContextGraph(sources=[source]),
            {},
        )

    assert result.errors == []
    assert result.acquired_sources == ["src_fetched"]
    assert result.acquired_documents["src_fetched"] == fetched.text
    assert any(item.id == "apiop:api-contract:create-ticket" for item in context.capabilities)


def test_contract_acquirer_ignores_non_openapi_url_documents():
    source = Source(
        id="src_docs",
        kind="url",
        name="HTML documentation",
        uri="https://tickets.example.com/docs",
    )
    fetched = IngestedSource(
        source=Source(
            id="src_docs",
            kind="url",
            name="HTML documentation",
            uri="https://tickets.example.com/docs",
        ),
        text="<html><body>not an OpenAPI document</body></html>",
    )

    with patch.object(CapabilityContractAcquirer, "_fetch", return_value=fetched):
        context, result = CapabilityContractAcquirer().acquire(
            "Use the ticket API.",
            ContextGraph(sources=[source]),
            {},
        )

    assert result.acquired_capabilities == []
    assert result.skipped_sources == ["src_docs"]
