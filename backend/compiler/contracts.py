from __future__ import annotations

import asyncio
import hashlib
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

        candidates: list[tuple[str, str, str | None, str | None]] = []
        for source in context.sources:
            if source.kind == "api_spec":
                text = documents.get(source.id, "")
                if text.strip():
                    candidates.append((source.id, text, source.uri, None))
            elif source.kind == "url" and source.uri:
                candidates.append((source.id, "", source.uri, None))

        # Autonomous research may return explicit public HTTPS references.
        # Only those concrete refs, or refs that resolve to an existing source URI,
        # are eligible for contract acquisition; arbitrary prose is ignored.
        known_source_by_id = {item.id: item for item in context.sources}
        for evidence in context.research_evidence:
            if not isinstance(evidence, dict):
                continue
            task_id = str(evidence.get("task_id") or "research")
            for ref in evidence.get("source_refs", []):
                value = str(ref or "").strip()
                uri = value if value.startswith("https://") else None
                if uri is None and value in known_source_by_id:
                    uri = known_source_by_id[value].uri
                if not uri or not uri.startswith("https://"):
                    continue
                source_id = f"research:{task_id}:{hashlib.sha256(uri.encode("utf-8")).hexdigest()[:12]}"
                if any(existing_id == source_id for existing_id, _, _, _ in candidates):
                    continue
                candidates.append((source_id, "", uri, task_id))

        for source_id, text, uri, research_task_id in candidates[: self.max_sources]:
            try:
                if not text:
                    if not uri:
                        skipped_sources.append(source_id)
                        continue
                    acquired = self._fetch(uri)
                    text = acquired.text
                    source_id = acquired.source.id
                    if research_task_id:
                        acquired = IngestedSource(
                            source=acquired.source.model_copy(
                                update={"name": f"Research contract: {research_task_id}"}
                            ),
                            text=acquired.text,
                        )
                    if acquired.source.id not in known_source_ids:
                        sources.append(acquired.source)
                        known_source_ids.add(acquired.source.id)
                    acquired_documents[acquired.source.id] = text

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
