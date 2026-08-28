"""Runtime configuration for the Second Brain server.

Everything is overridable through environment variables so the same code runs
on a laptop (loopback, no auth) and behind an HTTPS tunnel (LAN bind, API key).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

#: Target size of a generated context payload (spec section 12).
CONTEXT_TOKEN_BUDGET_MIN = 500
CONTEXT_TOKEN_BUDGET_MAX = 2000


def default_db_path() -> Path:
    """Where the brain lives when the user did not say."""
    env = os.environ.get("SECOND_BRAIN_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".second_brain" / "brain.db"


@dataclass
class Config:
    db_path: Path = field(default_factory=default_db_path)
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    api_key: str | None = None
    #: Token budget applied to /context responses.
    token_budget: int = CONTEXT_TOKEN_BUDGET_MAX

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            db_path=default_db_path(),
            host=os.environ.get("SECOND_BRAIN_HOST", DEFAULT_HOST),
            port=int(os.environ.get("SECOND_BRAIN_PORT", DEFAULT_PORT)),
            api_key=os.environ.get("SECOND_BRAIN_API_KEY") or None,
            token_budget=int(
                os.environ.get("SECOND_BRAIN_TOKEN_BUDGET", CONTEXT_TOKEN_BUDGET_MAX)
            ),
        )

    @property
    def is_loopback(self) -> bool:
        return self.host in ("127.0.0.1", "localhost", "::1")

    @property
    def auth_required(self) -> bool:
        """Auth is required whenever a key exists, or whenever we are reachable
        from outside this machine. A LAN/public bind without a key is refused
        at startup rather than silently served."""
        return self.api_key is not None
