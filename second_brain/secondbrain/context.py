"""Context Router (spec PHASE 3 + 4).

An agent never reads the brain; it reads a *slice* of the brain shaped by its
role profile. Two rules drive this module:

  * shared facts are shared — the same locked decisions reach every role;
  * thinking is not shared — goal, evaluation axes and prohibitions differ,
    and each role sees a different subset of sections.

Everything is squeezed into a token budget (spec section 12) by dropping the
lowest-priority sections last-first, never the project identity or the role
directive.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable

from .store import Store, NotFound

#: Sections that are never dropped by the budget trimmer.
PINNED = ("project", "role", "goal", "current_phase", "status")

#: Fallback ordering when a role profile does not declare visible_context.
DEFAULT_VISIBLE = [
    "project", "role", "goal", "current_phase", "status", "locked_decisions",
    "dependencies", "deliverables", "handoff", "evaluation_axes", "prohibitions",
]


def estimate_tokens(text: str) -> int:
    """Rough token estimate that does not lie about CJK.

    Latin text is ~4 chars/token; Japanese runs closer to 1 char/token, so we
    count the two separately instead of applying one ratio to both.
    """
    cjk = 0
    other = 0
    for ch in text:
        if unicodedata.east_asian_width(ch) in ("W", "F"):
            cjk += 1
        else:
            other += 1
    return int(cjk + other / 4 + 0.999) if (cjk or other) else 0


@dataclass
class Section:
    name: str
    title: str
    items: list[str] = field(default_factory=list)
    #: Lower number = more important. Derived from visible_context ordering.
    priority: int = 100

    @property
    def empty(self) -> bool:
        return not self.items

    def render(self) -> str:
        body = "\n".join(self.items)
        return f"{self.title}\n{body}"

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "title": self.title, "items": list(self.items)}


# --------------------------------------------------------------------- builders
# Each builder receives the assembled project data and returns display lines.

def _decision_line(decision: dict[str, Any]) -> str:
    text = decision["title"]
    if decision.get("body"):
        text = f"{text} — {decision['body']}"
    return f"- {decision['id']} {text}"


def _b_project(data: dict[str, Any]) -> list[str]:
    project = data["project"]
    return [project["name"], f"id: {project['id']}", f"status: {project['status']}"]


def _b_summary(data: dict[str, Any]) -> list[str]:
    return [data["project"]["summary"]] if data["project"].get("summary") else []


def _b_current_phase(data: dict[str, Any]) -> list[str]:
    state = data.get("state")
    return [state["phase"]] if state else []


def _b_status(data: dict[str, Any]) -> list[str]:
    state = data.get("state")
    return [state["status"]] if state else []


def _b_owner(data: dict[str, Any]) -> list[str]:
    state = data.get("state")
    return [state["owner"]] if state and state.get("owner") else []


def _b_locked_decisions(data: dict[str, Any]) -> list[str]:
    return [_decision_line(d) for d in data["decisions"] if d["status"] == "LOCKED"]


def _b_open_decisions(data: dict[str, Any]) -> list[str]:
    return [_decision_line(d) for d in data["decisions"] if d["status"] == "PROPOSED"]


def _b_facts(data: dict[str, Any]) -> list[str]:
    return [f"- {f['body']}" for f in data["facts"]]


def _tagged_facts(data: dict[str, Any], *tags: str) -> list[str]:
    wanted = set(tags)
    return [f"- {f['body']}" for f in data["facts"] if wanted & set(f["tags"])]


def _b_constraints(data: dict[str, Any]) -> list[str]:
    return _tagged_facts(data, "constraint", "limit", "budget")


def _b_world(data: dict[str, Any]) -> list[str]:
    return _tagged_facts(data, "world", "worldview", "design", "style")


def _b_assets(data: dict[str, Any]) -> list[str]:
    return _tagged_facts(data, "asset", "adopted")


def _b_failures(data: dict[str, Any]) -> list[str]:
    lines = _tagged_facts(data, "failure", "risk", "incident")
    lines += [_decision_line(d) for d in data["decisions"] if d["status"] == "SUPERSEDED"]
    return lines


def _b_api(data: dict[str, Any]) -> list[str]:
    return _tagged_facts(data, "api", "contract", "interface")


def _b_dependencies(data: dict[str, Any]) -> list[str]:
    lines = []
    for node in data["dependencies"]:
        status = data["phase_status"].get(node)
        lines.append(f"- {node}" + (f" {status}" if status else ""))
    return lines


def _b_deliverables(data: dict[str, Any]) -> list[str]:
    state = data.get("state")
    return [f"- {d}" for d in (state["deliverables"] if state else [])]


def _b_handoff(data: dict[str, Any]) -> list[str]:
    lines = []
    for handoff in data["handoffs"]:
        if handoff["status"] != "ACTIVE":
            continue
        missing = "" if handoff["file_exists"] else "  (FILE MISSING)"
        lines.append(f"- {handoff['title']}: {handoff['file_path']}{missing}")
    return lines


def _b_files(data: dict[str, Any]) -> list[str]:
    return _b_handoff(data) + _tagged_facts(data, "file", "path")


def _b_implementation_state(data: dict[str, Any]) -> list[str]:
    return [f"- {p['phase']} {p['status']}" for p in data["phases"]]


def _b_relations(data: dict[str, Any]) -> list[str]:
    return [f"- {r['src']} {r['rel']} {r['dst']}" for r in data["relations"]]


def _b_agents(data: dict[str, Any]) -> list[str]:
    return [f"- {a['name']} ({a['role']})" for a in data["agents"]]


def _b_recent_changes(data: dict[str, Any]) -> list[str]:
    return [f"- {c['created_at']} {c['entity']} {c['action']}: {c['summary']}"
            for c in data["changes"]]


BUILDERS: dict[str, tuple[str, Callable[[dict[str, Any]], list[str]]]] = {
    "project": ("PROJECT", _b_project),
    "summary": ("SUMMARY", _b_summary),
    "current_phase": ("CURRENT PHASE", _b_current_phase),
    "status": ("STATUS", _b_status),
    "owner": ("CURRENT OWNER", _b_owner),
    "locked_decisions": ("LOCKED DECISIONS", _b_locked_decisions),
    "open_decisions": ("OPEN DECISIONS", _b_open_decisions),
    "facts": ("FACTS", _b_facts),
    "constraints": ("CONSTRAINTS", _b_constraints),
    "world": ("WORLD / DESIGN LANGUAGE", _b_world),
    "assets": ("ADOPTED ASSETS", _b_assets),
    "failures": ("FAILURE HISTORY", _b_failures),
    "api": ("IMPLEMENTATION CONTRACT", _b_api),
    "dependencies": ("DEPENDENCIES", _b_dependencies),
    "deliverables": ("DELIVERABLES", _b_deliverables),
    "handoff": ("HANDOFF", _b_handoff),
    "files": ("FILES", _b_files),
    "implementation_state": ("IMPLEMENTATION STATE", _b_implementation_state),
    "relations": ("RELATIONS", _b_relations),
    "agents": ("AI AGENTS", _b_agents),
    "recent_changes": ("RECENT CHANGES", _b_recent_changes),
}

#: Role-directive sections come from the profile, not the project data.
ROLE_SECTIONS = ("role", "goal", "evaluation_axes", "prohibitions", "priority")


class ContextRouter:
    """Builds the per-role slice of a project."""

    def __init__(self, store: Store, budget: int = 2000):
        self.store = store
        self.budget = budget

    # -- resolution --------------------------------------------------------

    def resolve_profile(self, role: str) -> dict[str, Any]:
        """`role` may be a role-profile id or an agent id."""
        profile = self.store.get_role_profile(role)
        if profile:
            return profile
        agent = self.store.get_agent(role)
        if agent:
            profile = self.store.get_role_profile(agent["context_profile"])
            if profile:
                profile = dict(profile)
                profile["agent"] = agent
                return profile
        raise NotFound(f"unknown role or agent: {role}")

    def resolve_project(self, project_id: str | None) -> str:
        if project_id:
            self.store.require_project(project_id)
            return project_id
        active = self.store.list_projects(status="ACTIVE") or self.store.list_projects()
        if not active:
            raise NotFound("no projects registered")
        return active[0]["id"]

    # -- assembly ----------------------------------------------------------

    def _project_data(self, project_id: str) -> dict[str, Any]:
        data = self.store.project_overview(project_id)
        data["agents"] = self.store.list_agents()
        # Dependency nodes are written as ids ("GR-01") while phases carry a
        # label ("GR-01 MEMBRANE"), so index the status under both.
        status_map: dict[str, str] = {}
        for phase in data["phases"]:
            status_map[phase["phase"]] = phase["status"]
            status_map.setdefault(phase["phase"].split()[0], phase["status"])
        data["phase_status"] = status_map
        # Dependencies are declared against the phase id ("GR-02"), which is
        # usually a prefix of the phase label ("GR-02 CHANNEL").
        state = data.get("state")
        if state and not data["dependencies"]:
            head = state["phase"].split()[0]
            data["dependencies"] = self.store.dependencies_of(project_id, head)
        return data

    def visible_sections(self, profile: dict[str, Any]) -> list[str]:
        visible = list(profile.get("visible_context") or DEFAULT_VISIBLE)
        hidden = set(profile.get("hidden_context") or [])
        ordered = [name for name in visible if name not in hidden]
        # The role directive is what makes this agent think differently, so it
        # is always present even if the profile forgot to list it.
        for name in ("goal", "role"):          # identity leads
            if name not in ordered and name not in hidden:
                ordered.insert(0, name)
        for name in ("evaluation_axes", "prohibitions"):   # judgement trails
            if name not in ordered and name not in hidden:
                ordered.append(name)
        return ordered

    def build(self, role: str, project_id: str | None = None,
              budget: int | None = None) -> dict[str, Any]:
        profile = self.resolve_profile(role)
        pid = self.resolve_project(project_id)
        data = self._project_data(pid)
        budget = budget or self.budget

        sections: list[Section] = []
        for index, name in enumerate(self.visible_sections(profile)):
            section = self._build_section(name, profile, data, index)
            if section and not section.empty:
                sections.append(section)

        sections, dropped = self._fit(sections, budget)
        text = render_sections(sections)
        return {
            "role": profile["id"],
            "role_name": profile["name"],
            "agent": profile.get("agent", {}).get("id", ""),
            "project": pid,
            "generated_at": data["project"]["updated_at"],
            "token_budget": budget,
            "token_estimate": estimate_tokens(text),
            "dropped_sections": dropped,
            "sections": [s.as_dict() for s in sections],
            "text": text,
        }

    def _build_section(self, name: str, profile: dict[str, Any],
                       data: dict[str, Any], index: int) -> Section | None:
        priority = 0 if name in PINNED else index + 1
        if name in ROLE_SECTIONS:
            items = self._role_items(name, profile)
            titles = {"role": "ROLE", "goal": "GOAL",
                      "evaluation_axes": "EVALUATION AXES",
                      "prohibitions": "PROHIBITED", "priority": "PRIORITY"}
            return Section(name, titles[name], items, priority)
        entry = BUILDERS.get(name)
        if entry is None:
            return None
        title, builder = entry
        return Section(name, title, builder(data), priority)

    @staticmethod
    def _role_items(name: str, profile: dict[str, Any]) -> list[str]:
        if name == "role":
            agent = profile.get("agent")
            label = profile["name"]
            if agent:
                label = f"{agent['name']} ({agent['role'] or profile['name']})"
            return [label]
        if name == "goal":
            return [profile["goal"]] if profile.get("goal") else []
        if name == "priority":
            return [profile["priority"]] if profile.get("priority") else []
        return [f"- {v}" for v in profile.get(name) or []]

    def _fit(self, sections: list[Section], budget: int
             ) -> tuple[list[Section], list[str]]:
        """Shrink to budget: trim long lists first, then drop tail sections."""
        dropped: list[str] = []
        if estimate_tokens(render_sections(sections)) <= budget:
            return sections, dropped

        # Pass 1 — cap the long list sections, worst offender first.
        for limit in (12, 8, 5, 3):
            for section in sorted(sections, key=lambda s: -len(s.items)):
                if section.priority == 0 or len(section.items) <= limit:
                    continue
                hidden = len(section.items) - limit
                section.items = section.items[:limit] + [f"- (+{hidden} more)"]
            if estimate_tokens(render_sections(sections)) <= budget:
                return sections, dropped

        # Pass 2 — drop whole sections from the least important end.
        while sections and estimate_tokens(render_sections(sections)) > budget:
            victim = max(sections, key=lambda s: s.priority)
            if victim.priority == 0:
                break
            sections.remove(victim)
            dropped.append(victim.name)
        return sections, dropped


def render_sections(sections: list[Section]) -> str:
    return "\n\n".join(s.render() for s in sections if not s.empty)
