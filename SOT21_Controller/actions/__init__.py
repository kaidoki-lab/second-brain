"""Action registry.

Buttons on the tablet never carry a command line — they carry an action *name*.
Every name must be registered here, and every command a name can run must be
listed in config.json. That is the whole security model: the browser cannot
express a command the PC did not already agree to.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


class ActionError(Exception):
    """Expected failure: shown on the tablet, logged as an error."""


@dataclass
class Result:
    success: bool
    message: str
    detail: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        out = {"success": self.success, "message": self.message}
        if self.detail:
            out["detail"] = self.detail
        if self.data:
            out["data"] = self.data
        return out


@dataclass
class Action:
    name: str
    label: str
    group: str
    handler: Callable[[Any, dict[str, Any]], Result]
    params: dict[str, Any] = field(default_factory=dict)
    confirm: bool = False
    hidden: bool = False


REGISTRY: dict[str, Action] = {}
#: Order the groups appear on the panel.
GROUPS = ["SYSTEM", "OBS", "AUTOMATION", "FILE", "PC CONTROL", "SECOND BRAIN"]


def action(name: str, label: str, group: str, params: dict[str, Any] | None = None,
           confirm: bool = False, hidden: bool = False):
    def decorator(func: Callable[[Any, dict[str, Any]], Result]):
        REGISTRY[name] = Action(name, label, group, func, params or {}, confirm, hidden)
        return func
    return decorator


def alias(name: str, label: str, group: str, target: str,
          params: dict[str, Any], confirm: bool = False) -> None:
    """A second button for an existing handler with different baked-in params."""
    base = REGISTRY[target]
    REGISTRY[name] = Action(name, label, group, base.handler, params, confirm)


def run(name: str, params: dict[str, Any], ctx: Any) -> Result:
    entry = REGISTRY.get(name)
    if entry is None:
        raise ActionError(f"未登録のアクションです: {name}")
    merged = {**entry.params, **(params or {})}
    return entry.handler(ctx, merged)


def catalog() -> list[dict[str, Any]]:
    """Buttons for the UI, grouped in panel order."""
    groups = []
    for group in GROUPS:
        buttons = [
            {"name": a.name, "label": a.label, "params": a.params,
             "confirm": a.confirm}
            for a in REGISTRY.values() if a.group == group and not a.hidden
        ]
        if buttons:
            groups.append({"group": group, "buttons": buttons})
    return groups


def load() -> None:
    """Import every action module (registration happens on import)."""
    from . import (  # noqa: F401
        pc_status, run_command, obs_control, file_control, network_control,
        brain_control,
    )
