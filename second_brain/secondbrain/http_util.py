"""Tiny request/response plumbing so the app layer stays framework-free."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs


class HttpError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, list[str]] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    @classmethod
    def make(cls, method: str, target: str, headers: dict[str, str] | None = None,
             body: bytes = b"") -> "Request":
        path, _, raw_query = target.partition("?")
        return cls(method.upper(), path, parse_qs(raw_query),
                   {k.lower(): v for k, v in (headers or {}).items()}, body)

    def q(self, name: str, default: str | None = None) -> str | None:
        values = self.query.get(name)
        return values[0] if values else default

    def json(self) -> dict[str, Any]:
        if not self.body:
            return {}
        try:
            data = json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HttpError(400, f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise HttpError(400, "JSON body must be an object")
        return data

    def form(self) -> dict[str, str]:
        parsed = parse_qs(self.body.decode("utf-8", "replace"))
        return {k: v[0] for k, v in parsed.items()}

    def payload(self) -> dict[str, Any]:
        """JSON for agents, form-encoded for the browser UI."""
        ctype = self.headers.get("content-type", "")
        if "application/x-www-form-urlencoded" in ctype:
            return dict(self.form())
        return self.json()

    @property
    def wants_html(self) -> bool:
        return "text/html" in self.headers.get("accept", "")


@dataclass
class Response:
    status: int = 200
    body: bytes = b""
    content_type: str = "text/plain; charset=utf-8"
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, data: Any, status: int = 200) -> "Response":
        blob = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        return cls(status, blob.encode("utf-8"), "application/json; charset=utf-8")

    @classmethod
    def text(cls, body: str, status: int = 200,
             content_type: str = "text/plain; charset=utf-8") -> "Response":
        return cls(status, body.encode("utf-8"), content_type)

    @classmethod
    def html(cls, body: str, status: int = 200) -> "Response":
        return cls(status, body.encode("utf-8"), "text/html; charset=utf-8")

    @classmethod
    def redirect(cls, location: str, cookie: str | None = None) -> "Response":
        headers = {"Location": location}
        if cookie:
            headers["Set-Cookie"] = cookie
        return cls(303, b"", "text/plain; charset=utf-8", headers)
