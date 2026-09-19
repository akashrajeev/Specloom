from __future__ import annotations

import os
import re
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


_current_workspace: ContextVar[str | None] = ContextVar("specloom_workspace", default=None)
_current_identity: ContextVar["AuthIdentity | None"] = ContextVar("specloom_identity", default=None)


@dataclass(frozen=True)
class AuthIdentity:
    subject: str
    username: str | None
    email: str | None
    groups: tuple[str, ...]
    workspace_id: str | None
    claims: dict[str, Any]


def current_workspace_id() -> str | None:
    return _current_workspace.get()


def current_identity() -> AuthIdentity | None:
    return _current_identity.get()


def _workspace_from_claims(claims: dict[str, Any]) -> str | None:
    explicit = claims.get("custom:workspace_id") or claims.get("workspace_id")
    if explicit:
        return _safe_workspace(str(explicit))
    groups = claims.get("cognito:groups") or claims.get("groups") or []
    if isinstance(groups, (list, tuple)):
        for group in groups:
            match = re.fullmatch(r"specloom:workspace:([A-Za-z0-9_-]{1,100})", str(group))
            if match:
                return match.group(1)
    return None


def _safe_workspace(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", value):
        raise ValueError("invalid workspace identifier")
    return value


def verify_cognito_token(token: str) -> AuthIdentity:
    try:
        import jwt
        from jwt import PyJWKClient
    except ImportError as exc:
        raise RuntimeError("Install PyJWT with backend/requirements-aws.txt for Cognito authentication") from exc

    issuer = os.getenv("SPECL00M_COGNITO_ISSUER", "").rstrip("/")
    client_id = os.getenv("SPECL00M_COGNITO_CLIENT_ID", "").strip()
    if not issuer:
        raise RuntimeError("SPECL00M_COGNITO_ISSUER is required when auth mode is cognito")

    jwks = PyJWKClient(f"{issuer}/.well-known/jwks.json")
    signing_key = jwks.get_signing_key_from_jwt(token)
    claims = jwt.decode(
        token,
        signing_key.key,
        algorithms=["RS256"],
        options={"verify_aud": False},
        issuer=issuer,
    )

    if client_id:
        aud = claims.get("aud")
        token_client = claims.get("client_id")
        if aud != client_id and token_client != client_id:
            raise ValueError("token audience/client_id does not match Specloom client")
    subject = str(claims.get("sub") or "").strip()
    if not subject:
        raise ValueError("token subject is missing")

    groups_raw = claims.get("cognito:groups") or claims.get("groups") or []
    groups = tuple(str(item) for item in groups_raw) if isinstance(groups_raw, (list, tuple)) else ()
    return AuthIdentity(
        subject=subject,
        username=str(claims.get("username") or claims.get("cognito:username") or "") or None,
        email=str(claims.get("email") or "") or None,
        groups=groups,
        workspace_id=_workspace_from_claims(claims),
        claims=claims,
    )


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Optional Cognito JWT authentication with workspace identity propagation."""

    async def dispatch(self, request: Request, call_next):
        mode = os.getenv("SPECL00M_AUTH_MODE", "off").lower()
        if mode in {"off", "disabled"} or request.url.path == "/health":
            return await call_next(request)
        if mode != "cognito":
            return JSONResponse({"detail": f"unsupported auth mode: {mode}"}, status_code=500)

        header = request.headers.get("authorization", "")
        if not header.lower().startswith("bearer "):
            return JSONResponse({"detail": "missing bearer token"}, status_code=401)

        try:
            identity = verify_cognito_token(header.split(" ", 1)[1].strip())
        except Exception as exc:
            return JSONResponse({"detail": f"invalid authentication token: {exc}"}, status_code=401)

        if not identity.workspace_id:
            return JSONResponse(
                {"detail": "authenticated user is not assigned to a Specloom workspace"},
                status_code=403,
            )

        request.state.identity = identity
        token_workspace = _current_workspace.set(identity.workspace_id)
        token_identity = _current_identity.set(identity)
        try:
            return await call_next(request)
        finally:
            _current_workspace.reset(token_workspace)
            _current_identity.reset(token_identity)
