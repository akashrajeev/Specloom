from __future__ import annotations

import hashlib
import json
import re
from typing import Any
from urllib.parse import urljoin, urlparse

from .models import CapabilitySpec


_READ_METHODS = {"GET", "HEAD", "OPTIONS"}
_WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


class OpenAPICompileError(ValueError):
    pass


def compile_openapi(
    spec_text: str,
    *,
    source_id: str,
    source_name: str,
    base_url_override: str | None = None,
    auth_env: str | None = None,
    auth_header: str = "Authorization",
    auth_prefix: str = "Bearer ",
) -> list[CapabilitySpec]:
    document = _load_document(spec_text)
    version = str(document.get("openapi") or "")
    if not version.startswith("3."):
        raise OpenAPICompileError("Specloom requires an OpenAPI 3.x document")

    base_url = _resolve_base_url(document, base_url_override)
    paths = document.get("paths")
    if not isinstance(paths, dict):
        raise OpenAPICompileError("OpenAPI document must contain a paths object")

    capabilities: list[CapabilitySpec] = []
    prefix = _slug(source_name)[:30] or "api"
    for raw_path, path_item in paths.items():
        if not isinstance(path_item, dict):
            continue
        path_level_parameters = path_item.get("parameters") if isinstance(path_item.get("parameters"), list) else []
        for raw_method, operation in path_item.items():
            method = str(raw_method).upper()
            if method not in _READ_METHODS | _WRITE_METHODS or not isinstance(operation, dict):
                continue

            operation_id = str(operation.get("operationId") or f"{method.lower()}_{_slug(str(raw_path))}")
            capability_id = f"apiop:{prefix}:{_slug(operation_id)}"
            access = "read" if method in _READ_METHODS else "write"
            security = operation.get("security", document.get("security", []))
            operation_auth_env = str(
                operation.get("x-specloom-auth-env")
                or auth_env
                or ""
            ).strip() or None
            inferred_header, inferred_prefix = _infer_auth_binding(document, security)
            operation_auth_header = str(
                operation.get("x-specloom-auth-header")
                or inferred_header
                or auth_header
                or "Authorization"
            )
            operation_auth_prefix = str(
                operation.get("x-specloom-auth-prefix")
                if operation.get("x-specloom-auth-prefix") is not None
                else inferred_prefix if inferred_prefix is not None else auth_prefix
            )
            if security and not operation_auth_env:
                raise OpenAPICompileError(
                    f"operation {operation_id} declares security but no auth_env was supplied; "
                    "provide auth_env or x-specloom-auth-env"
                )

            input_schema = _operation_input_schema(path_level_parameters, operation)
            output_schema = _operation_output_schema(operation.get("responses"))
            tags = ["api", "openapi", access]
            tags.extend(str(item) for item in operation.get("tags", []) if item)
            permissions = ["READ"] if access == "read" else ["READ", "WRITE"]

            capabilities.append(
                CapabilitySpec(
                    id=capability_id,
                    kind="openapi",
                    name=str(operation.get("summary") or operation_id),
                    description=str(
                        operation.get("description")
                        or operation.get("summary")
                        or f"{method} {raw_path} from {source_name}"
                    ),
                    source_id=source_id,
                    operation_id=operation_id,
                    method=method,
                    path=str(raw_path),
                    base_url=base_url,
                    access=access,
                    permissions=permissions,
                    side_effecting=access == "write",
                    requires_human_approval=access == "write",
                    auth_env=operation_auth_env if security else None,
                    auth_header=operation_auth_header,
                    auth_prefix=operation_auth_prefix,
                    input_schema=input_schema,
                    output_schema=output_schema,
                    tags=tags,
                )
            )

    if not capabilities:
        raise OpenAPICompileError("OpenAPI document contains no executable operations")
    return capabilities


def _infer_auth_binding(document: dict[str, Any], security: Any) -> tuple[str | None, str | None]:
    if not security:
        return None, None
    schemes = document.get("components", {}).get("securitySchemes", {})
    if not isinstance(schemes, dict) or not schemes:
        return None, None
    if not isinstance(security, list) or not security or not isinstance(security[0], dict):
        return None, None
    scheme_name = next(iter(security[0]), None)
    scheme = schemes.get(scheme_name) if scheme_name else None
    if not isinstance(scheme, dict):
        return None, None
    kind = str(scheme.get("type") or "").lower()
    if kind == "apikey":
        return str(scheme.get("name") or "X-API-Key"), ""
    if kind == "http":
        scheme_value = str(scheme.get("scheme") or "").lower()
        if scheme_value == "bearer":
            return "Authorization", "Bearer "
        if scheme_value == "basic":
            return "Authorization", "Basic "
        return "Authorization", ""
    if kind in {"oauth2", "openidconnect"}:
        return "Authorization", "Bearer "
    return None, None


def _load_document(spec_text: str) -> dict[str, Any]:
    try:
        value = json.loads(spec_text)
    except json.JSONDecodeError:
        try:
            import yaml
        except ImportError as exc:
            raise OpenAPICompileError("Install PyYAML to ingest OpenAPI YAML documents") from exc
        try:
            value = yaml.safe_load(spec_text)
        except Exception as exc:
            raise OpenAPICompileError(f"invalid OpenAPI JSON/YAML: {exc}") from exc
    if not isinstance(value, dict):
        raise OpenAPICompileError("OpenAPI document root must be an object")
    return value


def _resolve_base_url(document: dict[str, Any], override: str | None) -> str:
    value = str(override or "").strip()
    if not value:
        servers = document.get("servers")
        if isinstance(servers, list) and servers and isinstance(servers[0], dict):
            value = str(servers[0].get("url") or "").strip()
    if not value:
        raise OpenAPICompileError("OpenAPI capability compilation requires a server URL or base_url override")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise OpenAPICompileError("OpenAPI server URL must use HTTPS and include a hostname")
    if parsed.username or parsed.password:
        raise OpenAPICompileError("OpenAPI server URLs may not contain credentials")
    return value.rstrip("/")


def _operation_input_schema(path_parameters: list[Any], operation: dict[str, Any]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    all_parameters = [*path_parameters, *(operation.get("parameters") or [])]
    for parameter in all_parameters:
        if not isinstance(parameter, dict):
            continue
        name = str(parameter.get("name") or "").strip()
        if not name:
            continue
        schema = parameter.get("schema")
        properties[name] = schema if isinstance(schema, dict) else {"type": "string"}
        if parameter.get("required") or str(parameter.get("in")) == "path":
            required.append(name)

    request_body = operation.get("requestBody")
    if isinstance(request_body, dict):
        content = request_body.get("content")
        if isinstance(content, dict) and content:
            media, media_spec = next(iter(content.items()))
            schema = media_spec.get("schema") if isinstance(media_spec, dict) else None
            properties["body"] = schema if isinstance(schema, dict) else {"type": "object"}
            if request_body.get("required"):
                required.append("body")

    result: dict[str, Any] = {"type": "object", "properties": properties}
    if required:
        result["required"] = sorted(set(required))
    return result


def _operation_output_schema(responses: Any) -> dict[str, Any]:
    if not isinstance(responses, dict):
        return {}
    for status in ("200", "201", "202", "204", "default"):
        response = responses.get(status)
        if not isinstance(response, dict):
            continue
        content = response.get("content")
        if isinstance(content, dict) and content:
            media_spec = next(iter(content.values()))
            if isinstance(media_spec, dict) and isinstance(media_spec.get("schema"), dict):
                return dict(media_spec["schema"])
    return {}


def _slug(value: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()
    return clean or hashlib.sha1(value.encode("utf-8")).hexdigest()[:10]
