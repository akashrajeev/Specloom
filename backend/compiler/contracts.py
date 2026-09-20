from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field

from backend.capabilities.openapi import OpenAPICompileError, compile_openapi
from backend.context.ingestion import IngestionError, IngestedSource, ingest_url
from backend.context.models import ContextGraph, ContextTool


@dataclass(frozen=True)
class CapabilityContractAcquisitionResult:
    acquired_sources: list[str] = field(default_factory=list)
    acquired_capabilities: list[str] = field(default_factory=list)
    acquired_documents: dict[str, str] = field(default_factory=dict)
    skipped_sources: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CapabilityContractAcquirer:
    """Acquire explicitly supplied public API contracts without inventing endpoints."""

    def __init__(self, *, max_sources: int = 5) -> None:
        self.max_sources = max(1, min(max_sources, 10))

    def acquire(
        self,
        goal: str,
        context: ContextGraph,
        documents: dict[str, str],
    ) -> tuple[ContextGraph, CapabilityContractAcquisitionResult]:
        _ = goal
        acquired_sources: list[str] = []
        acquired_capabilities: list[str] = []
        acquired_documents: dict[str, str] = {}
        skipped_sources: list[str] = []
        errors: list[str] = []

        sources = list(context.sources)
        capabilities = list(context.capabilities)
        tools = list(context.tools)
        known_source_ids = {item.id for item in sources}
        known_capability_ids = {item.id for item in capabilities}
        known_tool_ids = {item.id for item in tools}

        candidates: list[tuple[str, str, str | None]] = []
        for source in context.sources:
            if source.kind == "api_spec":
                text = documents.get(source.id, "")
                if text.strip():
                    candidates.append((source.id, text, source.uri))
            elif source.kind == "url" and source.uri:
                candidates.append((source.id, "", source.uri))

        for source_id, text, uri in candidates[: self.max_sources]:
            try:
                if not text:
                    if not uri:
                        skipped_sources.append(source_id)
                        continue
                    acquired = self._fetch(uri)
                    text = acquired.text
                    if acquired.source.id not in known_source_ids:
                        sources.append(acquired.source)
                        known_source_ids.add(acquired.source.id)
                    acquired_documents[acquired.source.id] = text
                    source_id = acquired.source.id

                if not self._looks_like_openapi(text):
                    skipped_sources.append(source_id)
                    continue

                source_name = next(
                    (item.name for item in sources if item.id == source_id),
                    uri or source_id,
                )
                compiled = compile_openapi(
                    text,
                    source_id=source_id,
                    source_name=source_name,
                )
                for capability in compiled:
                    if capability.id in known_capability_ids:
                        continue
                    capabilities.append(capability)
                    known_capability_ids.add(capability.id)
                    acquired_capabilities.append(capability.id)
                    if capability.id not in known_tool_ids:
                        tools.append(
                            ContextTool.model_validate(
                                capability.to_context_tool()
                            )
                        )
                        known_tool_ids.add(capability.id)
                acquired_sources.append(source_id)
            except (
                IngestionError,
                OpenAPICompileError,
                OSError,
                ValueError,
            ) as exc:
                errors.append(f"{source_id}: {exc}")

        updated = context.model_copy(
            update={
                "sources": sources,
                "capabilities": capabilities,
                "tools": tools,
            }
        )
        return updated, CapabilityContractAcquisitionResult(
            acquired_sources=acquired_sources,
            acquired_capabilities=acquired_capabilities,
            acquired_documents=acquired_documents,
            skipped_sources=skipped_sources,
            errors=errors,
        )

    @staticmethod
    def _fetch(url: str) -> IngestedSource:
        return asyncio.run(
            ingest_url(url, name=f"API contract: {url}")
        )

    @staticmethod
    def _looks_like_openapi(text: str) -> bool:
        try:
            document = json.loads(text)
        except json.JSONDecodeError:
            try:
                import yaml

                document = yaml.safe_load(text)
            except Exception:
                return False
        return (
            isinstance(document, dict)
            and str(document.get("openapi") or "").startswith("3.")
        )
