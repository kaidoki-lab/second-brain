"""API key auth (spec PHASE 7).

Agents send `Authorization: Bearer <key>` (or `X-API-Key`). A browser cannot
set headers, so the UI trades `?key=` once for a session cookie.
"""

from __future__ import annotations

import hmac
import secrets

from .http_util import HttpError, Request

COOKIE_NAME = "sb_key"


def generate_key() -> str:
    return secrets.token_urlsafe(32)


def presented_key(request: Request) -> str | None:
    header = request.headers.get("authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip()
    if request.headers.get("x-api-key"):
        return request.headers["x-api-key"].strip()
    if request.q("key"):
        return request.q("key")
    for chunk in request.headers.get("cookie", "").split(";"):
        name, _, value = chunk.strip().partition("=")
        if name == COOKIE_NAME:
            return value
    return None


def check(request: Request, api_key: str | None) -> None:
    """Raise 401 unless the request carries the configured key."""
    if not api_key:
        return
    presented = presented_key(request)
    if not presented or not hmac.compare_digest(presented, api_key):
        raise HttpError(401, "missing or invalid API key")


def cookie_for(key: str, secure: bool = False) -> str:
    flags = "; HttpOnly; SameSite=Strict; Path=/; Max-Age=2592000"
    return f"{COOKIE_NAME}={key}{flags}" + ("; Secure" if secure else "")
