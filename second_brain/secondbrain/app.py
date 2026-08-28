"""Routing and endpoint handlers (spec sections 17-18, PHASE 6-7).

Two audiences share one app:
  * agents  -> /context/*, /project/*/current, /api/* (plain text or JSON)
  * humans  -> /, /project/{id}, /agents (HTML, see ui.py)
"""

from __future__ import annotations

import re
from typing import Any, Callable

from . import ui
from .auth import check as auth_check, cookie_for
from .config import Config
from .context import ContextRouter
from .http_util import HttpError, Request, Response
from .store import Invalid, NotFound, Store

Handler = Callable[["App", Request, dict[str, str]], Response]

_ROUTES: list[tuple[str, re.Pattern[str], Handler, bool]] = []


def route(method: str, pattern: str, public: bool = False):
    """Register a handler. `public` skips the API-key check."""
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def decorator(func: Handler) -> Handler:
        _ROUTES.append((method.upper(), regex, func, public))
        return func

    return decorator


class App:
    def __init__(self, store: Store, config: Config | None = None):
        self.store = store
        self.config = config or Config()
        self.router = ContextRouter(store, self.config.token_budget)

    # ------------------------------------------------------------ dispatch

    def handle(self, request: Request) -> Response:
        for method, regex, handler, public in _ROUTES:
            match = regex.match(request.path)
            if not match:
                continue
            if method != request.method:
                continue
            try:
                if not public:
                    auth_check(request, self.config.api_key)
                return handler(self, request, match.groupdict())
            except HttpError as exc:
                return self._error(request, exc.status, exc.message)
            except NotFound as exc:
                return self._error(request, 404, str(exc))
            except Invalid as exc:
                return self._error(request, 400, str(exc))
        return self._error(request, 404, f"no route for {request.method} {request.path}")

    @staticmethod
    def _error(request: Request, status: int, message: str) -> Response:
        if request.wants_html:
            return Response.html(ui.error_page(status, message), status)
        return Response.json({"error": message, "status": status}, status)

    # ------------------------------------------------------------- helpers

    def _payload(self, request: Request) -> dict[str, Any]:
        return request.payload()

    @staticmethod
    def _require(payload: dict[str, Any], *names: str) -> list[Any]:
        missing = [n for n in names if not str(payload.get(n, "")).strip()]
        if missing:
            raise HttpError(400, f"missing field(s): {', '.join(missing)}")
        return [payload[n] for n in names]

    def _written(self, request: Request, data: dict[str, Any],
                redirect_to: str) -> Response:
        """Forms come back to a page; agents get the stored row as JSON."""
        if "application/x-www-form-urlencoded" in request.headers.get("content-type", ""):
            return Response.redirect(redirect_to)
        return Response.json(data, 201)

    def _budget(self, request: Request) -> int:
        raw = request.q("budget")
        if raw is None:
            return self.config.token_budget
        try:
            value = int(raw)
        except ValueError as exc:
            raise HttpError(400, "budget must be an integer") from exc
        return max(100, min(value, 32000))


# =========================================================== agent endpoints

@route("GET", "/api/health", public=True)
def health(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.json({
        "ok": True,
        "auth_required": app.config.auth_required,
        "projects": len(app.store.list_projects()),
        "agents": len(app.store.list_agents()),
    })


@route("GET", "/context/{role}")
def context_text(app: App, request: Request, params: dict[str, str]) -> Response:
    result = app.router.build(params["role"], request.q("project"),
                              app._budget(request))
    if request.q("format") == "json":
        return Response.json(result)
    return Response.text(result["text"] + "\n")


@route("GET", "/api/context")
def context_json(app: App, request: Request, _: dict[str, str]) -> Response:
    role = request.q("role")
    if not role:
        raise HttpError(400, "role query parameter is required")
    return Response.json(app.router.build(role, request.q("project"),
                                          app._budget(request)))


@route("GET", "/project/{id}/current")
def project_current(app: App, request: Request, params: dict[str, str]) -> Response:
    pid = params["id"]
    overview = app.store.project_overview(pid)
    state = overview["state"]
    if request.q("format") == "json":
        return Response.json({
            "project": overview["project"],
            "state": state,
            "phases": overview["phases"],
            "dependencies": app.store.dependencies_of(
                pid, state["phase"].split()[0]) if state else [],
            "locked_decisions": [d for d in overview["decisions"]
                                 if d["status"] == "LOCKED"],
            "handoffs": [h for h in overview["handoffs"] if h["status"] == "ACTIVE"],
        })
    return Response.text(render_current(app, overview) + "\n")


def render_current(app: App, overview: dict[str, Any]) -> str:
    project, state = overview["project"], overview["state"]
    lines = ["PROJECT", project["name"], "", "CURRENT_PHASE",
             state["phase"] if state else "(none)", "", "STATUS",
             state["status"] if state else "(none)"]
    locked = [d for d in overview["decisions"] if d["status"] == "LOCKED"]
    if locked:
        lines += ["", "LOCKED"] + [f"{d['id']} {d['title']}" for d in locked]
    if state:
        deps = app.store.dependencies_of(project["id"], state["phase"].split()[0])
        statuses = {p["phase"]: p["status"] for p in overview["phases"]}
        if deps:
            lines += ["", "DEPENDENCIES"] + [
                f"{d} {statuses.get(d, '')}".strip() for d in deps]
        if state["owner"]:
            lines += ["", "CURRENT_OWNER", state["owner"]]
    return "\n".join(lines)


@route("GET", "/decisions/{project}")
def decisions_for(app: App, request: Request, params: dict[str, str]) -> Response:
    pid = params["project"]
    app.store.require_project(pid)
    return Response.json(app.store.list_decisions(pid, request.q("status")))


@route("GET", "/handoffs/{project}")
def handoffs_for(app: App, request: Request, params: dict[str, str]) -> Response:
    pid = params["project"]
    app.store.require_project(pid)
    return Response.json(app.store.list_handoffs(pid, request.q("status")))


@route("GET", "/api/brain")
def api_brain(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.json(app.store.brain_snapshot())


@route("GET", "/brain.md")
def brain_md(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.text(render_brain_markdown(app.store),
                         content_type="text/markdown; charset=utf-8")


def render_brain_markdown(store: Store) -> str:
    out = ["# SECOND BRAIN", ""]
    for project in store.list_projects():
        pid = project["id"]
        state = store.current_state(pid)
        out += [f"## {project['name']} (`{pid}`) — {project['status']}"]
        if project["summary"]:
            out += ["", project["summary"]]
        out += ["", f"- CURRENT PHASE: {state['phase'] if state else '(none)'}",
                f"- STATUS: {state['status'] if state else '(none)'}"]
        if state and state["owner"]:
            out.append(f"- OWNER: {state['owner']}")
        locked = store.list_decisions(pid, "LOCKED")
        if locked:
            out += ["", "### LOCKED DECISIONS"]
            out += [f"- {d['id']} {d['title']}" for d in locked]
        handoffs = store.list_handoffs(pid, "ACTIVE")
        if handoffs:
            out += ["", "### HANDOFFS"]
            out += [f"- {h['title']}: `{h['file_path']}`"
                    + ("" if h["file_exists"] else " (FILE MISSING)")
                    for h in handoffs]
        relations = store.list_relations(pid)
        if relations:
            out += ["", "### RELATIONS"]
            out += [f"- {r['src']} {r['rel']} {r['dst']}" for r in relations]
        out.append("")
    out += ["## AI AGENTS", ""]
    for agent in store.list_agents():
        out.append(f"- `{agent['id']}` {agent['name']} — {agent['role']} "
                   f"(profile: {agent['context_profile']})")
    return "\n".join(out) + "\n"


# ------------------------------------------------------------- read helpers

@route("GET", "/api/projects")
def api_projects(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.json(app.store.list_projects(request.q("status")))


@route("GET", "/api/project/{id}")
def api_project(app: App, request: Request, params: dict[str, str]) -> Response:
    return Response.json(app.store.project_overview(params["id"]))


@route("GET", "/api/agents")
def api_agents(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.json(app.store.list_agents())


@route("GET", "/api/roles")
def api_roles(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.json(app.store.list_role_profiles())


@route("GET", "/api/changes")
def api_changes(app: App, request: Request, _: dict[str, str]) -> Response:
    limit = int(request.q("limit", "20") or 20)
    return Response.json(app.store.recent_changes(limit, request.q("project")))


# ========================================================== write endpoints

@route("POST", "/api/project")
def post_project(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    app._require(payload, "id")
    project = app.store.upsert_project(
        payload["id"], payload.get("name", ""), payload.get("status", "ACTIVE"),
        payload.get("summary", ""), actor=payload.get("actor", ""))
    return app._written(request, project, f"/project/{project['id']}")


@route("POST", "/api/decision")
def post_decision(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    pid, title = app._require(payload, "project", "title")
    decision = app.store.add_decision(
        pid, title, payload.get("body", ""), payload.get("status", "LOCKED"),
        payload.get("phase", ""), payload.get("tags"), payload.get("id"),
        actor=payload.get("actor", ""))
    return app._written(request, decision, f"/project/{pid}")


@route("POST", "/api/state")
def post_state(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    pid, phase = app._require(payload, "project", "phase")
    state = app.store.set_state(
        pid, phase, payload.get("status", "IN_PROGRESS"), payload.get("owner", ""),
        payload.get("note", ""), payload.get("deliverables"),
        actor=payload.get("actor", ""))
    return app._written(request, state, f"/project/{pid}")


@route("POST", "/api/handoff")
def post_handoff(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    hid, pid, path = app._require(payload, "id", "project", "file_path")
    handoff = app.store.upsert_handoff(
        hid, pid, path, payload.get("title", ""), payload.get("phase", ""),
        payload.get("owner", ""), payload.get("status", "ACTIVE"),
        actor=payload.get("actor", ""))
    return app._written(request, handoff, f"/project/{pid}")


@route("POST", "/api/relation")
def post_relation(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    pid, src, rel, dst = app._require(payload, "project", "src", "rel", "dst")
    relation = app.store.add_relation(pid, src, rel, dst,
                                      actor=payload.get("actor", ""))
    return app._written(request, relation, f"/project/{pid}")


@route("POST", "/api/fact")
def post_fact(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    pid, body = app._require(payload, "project", "body")
    fact = app.store.add_fact(pid, body, payload.get("key", ""), payload.get("tags"),
                              payload.get("source", ""), actor=payload.get("actor", ""))
    return app._written(request, fact, f"/project/{pid}")


@route("POST", "/api/agent")
def post_agent(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    app._require(payload, "id")
    agent = app.store.upsert_agent(
        payload["id"], payload.get("name", ""), payload.get("role", ""),
        payload.get("context_profile", ""), payload.get("model", ""),
        payload.get("status", "ACTIVE"), actor=payload.get("actor", ""))
    return app._written(request, agent, "/agents")


@route("POST", "/api/role")
def post_role(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    app._require(payload, "id")
    profile = app.store.upsert_role_profile(
        payload["id"], payload.get("name", ""), payload.get("goal", ""),
        payload.get("priority", ""), payload.get("visible_context"),
        payload.get("hidden_context"), payload.get("evaluation_axes"),
        payload.get("prohibitions"), actor=payload.get("actor", ""))
    return app._written(request, profile, "/agents")


@route("POST", "/api/handoffs/verify")
def post_verify(app: App, request: Request, _: dict[str, str]) -> Response:
    payload = app._payload(request)
    result = app.store.verify_handoffs(payload.get("project") or None)
    return app._written(request, result, "/")


# =============================================================== browser UI

@route("GET", "/")
def ui_home(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.html(ui.dashboard(app.store))


@route("GET", "/project/{id}")
def ui_project(app: App, request: Request, params: dict[str, str]) -> Response:
    return Response.html(ui.project_page(app.store, params["id"]))


@route("GET", "/agents")
def ui_agents(app: App, request: Request, _: dict[str, str]) -> Response:
    return Response.html(ui.agents_page(app.store))


@route("GET", "/preview/context/{role}")
def ui_context(app: App, request: Request, params: dict[str, str]) -> Response:
    result = app.router.build(params["role"], request.q("project"),
                              app._budget(request))
    return Response.html(ui.context_page(app.store, result))


@route("GET", "/login", public=True)
def ui_login(app: App, request: Request, _: dict[str, str]) -> Response:
    key = request.q("key")
    if key and app.config.api_key and key == app.config.api_key:
        return Response.redirect("/", cookie_for(key))
    return Response.html(ui.login_page(bool(key)), 200 if not key else 401)
