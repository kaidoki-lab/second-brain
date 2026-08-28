"""Server-rendered browser UI (spec PHASE 2).

No build step, no framework, no CDN: one stylesheet inlined into every page so
the UI works on a LAN with no internet, and on old tablet browsers.
"""

from __future__ import annotations

from html import escape
from typing import Any

from .store import Store

STYLE = """
:root { color-scheme: dark; --bg:#0e1116; --panel:#161b22; --line:#2b323c;
        --fg:#e6edf3; --dim:#8b949e; --accent:#5ac8fa; --ok:#3fb950;
        --warn:#d29922; --bad:#f85149; }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--fg); font:14px/1.6
       -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif; }
header { padding:14px 20px; border-bottom:1px solid var(--line);
         display:flex; gap:18px; align-items:baseline; flex-wrap:wrap; }
header h1 { font-size:16px; margin:0; letter-spacing:.16em; }
header a { color:var(--dim); text-decoration:none; font-size:13px; }
header a:hover { color:var(--accent); }
main { padding:20px; max-width:1200px; margin:0 auto; }
.grid { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:8px;
        padding:14px 16px; flex:1 1 320px; min-width:300px; }
.card h2 { font-size:12px; letter-spacing:.18em; color:var(--dim);
           margin:0 0 10px; text-transform:uppercase; }
table { width:100%; border-collapse:collapse; }
td, th { padding:6px 8px; text-align:left; border-bottom:1px solid var(--line);
         vertical-align:top; }
th { color:var(--dim); font-weight:500; font-size:12px; }
tr:last-child td { border-bottom:none; }
a { color:var(--accent); }
code, pre { font-family:ui-monospace, SFMono-Regular, Consolas, monospace; }
pre { background:#0b0f14; border:1px solid var(--line); border-radius:6px;
      padding:14px; overflow-x:auto; white-space:pre-wrap; word-break:break-word; }
.tag { display:inline-block; padding:1px 7px; border-radius:99px; font-size:11px;
       border:1px solid var(--line); color:var(--dim); }
.ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.dim { color:var(--dim); }
form { margin:0; } input, select, textarea, button { font:inherit; }
input, select, textarea { background:#0b0f14; color:var(--fg); padding:6px 8px;
       border:1px solid var(--line); border-radius:6px; width:100%; }
button { background:var(--accent); color:#04121c; border:0; border-radius:6px;
         padding:7px 14px; font-weight:600; cursor:pointer; }
label { display:block; margin:8px 0 2px; font-size:12px; color:var(--dim); }
.row { display:flex; gap:10px; flex-wrap:wrap; }
.row > * { flex:1 1 140px; }
.empty { color:var(--dim); font-style:italic; }
"""


def page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang=\"ja\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>"
        "<header><h1>SECOND BRAIN</h1>"
        "<a href=\"/\">DASHBOARD</a><a href=\"/agents\">AI AGENTS</a>"
        "<a href=\"/brain.md\">brain.md</a><a href=\"/api/brain\">api/brain</a>"
        "</header><main>" + body + "</main></body></html>"
    )


def e(value: Any) -> str:
    return escape("" if value is None else str(value))


def card(title: str, body: str) -> str:
    return f"<section class=\"card\"><h2>{escape(title)}</h2>{body}</section>"


def table(headers: list[str], rows: list[list[str]], empty: str = "なし") -> str:
    if not rows:
        return f"<p class=\"empty\">{escape(empty)}</p>"
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def status_badge(status: str) -> str:
    cls = {"COMPLETE": "ok", "LOCKED": "ok", "ACTIVE": "ok",
           "IN_PROGRESS": "warn", "PROPOSED": "warn", "BLOCKED": "bad",
           "SUPERSEDED": "dim"}.get(status, "dim")
    return f"<span class=\"tag {cls}\">{escape(status)}</span>"


# ------------------------------------------------------------------- pages

def dashboard(store: Store) -> str:
    projects = store.list_projects()
    project_rows = []
    active_rows = []
    for project in projects:
        state = store.current_state(project["id"])
        project_rows.append([
            f"<a href=\"/project/{e(project['id'])}\">{e(project['name'])}</a>",
            status_badge(project["status"]),
            e(state["phase"] if state else "-"),
        ])
        if state:
            active_rows.append([e(project["name"]), e(state["phase"]),
                                status_badge(state["status"]),
                                e(state["owner"] or "-")])

    agent_rows = [[e(a["id"]), e(a["name"]), e(a["role"]),
                   f"<a href=\"/preview/context/{e(a['id'])}\">context</a>"]
                  for a in store.list_agents()]

    decisions, handoffs, relations = [], [], []
    for project in projects:
        pid = project["id"]
        for d in store.list_decisions(pid)[-6:]:
            decisions.append([e(d["id"]), e(d["title"]), status_badge(d["status"])])
        for h in store.list_handoffs(pid):
            flag = "<span class=\"ok\">OK</span>" if h["file_exists"] \
                else "<span class=\"bad\">MISSING</span>"
            handoffs.append([e(h["id"]), f"<code>{e(h['file_path'])}</code>",
                             e(h["owner"]), flag])
        for r in store.list_relations(pid):
            relations.append([e(r["src"]), f"<span class=\"dim\">{e(r['rel'])}</span>",
                              e(r["dst"])])

    changes = [[e(c["created_at"][11:19]), e(c["entity"]), e(c["action"]),
                e(c["summary"])] for c in store.recent_changes(12)]

    body = "<div class=\"grid\">"
    body += card("PROJECTS", table(["PROJECT", "STATUS", "PHASE"], project_rows,
                                   "プロジェクト未登録"))
    body += card("ACTIVE PHASES", table(["PROJECT", "PHASE", "STATUS", "OWNER"],
                                        active_rows, "進行中フェーズなし"))
    body += card("AI AGENTS", table(["ID", "NAME", "ROLE", ""], agent_rows))
    body += card("DECISIONS", table(["ID", "TITLE", "STATUS"], decisions))
    body += card("HANDOFFS", table(["ID", "PATH", "OWNER", "FILE"], handoffs))
    body += card("DEPENDENCIES", table(["SRC", "REL", "DST"], relations))
    body += card("RECENT CHANGES", table(["TIME", "ENTITY", "ACTION", "SUMMARY"],
                                         changes))
    body += "</div>"
    body += "<div class=\"grid\" style=\"margin-top:16px\">" \
            + card("NEW PROJECT", _project_form()) + "</div>"
    return page("SECOND BRAIN", body)


def _project_form() -> str:
    return (
        "<form method=\"post\" action=\"/api/project\">"
        "<div class=\"row\"><div><label>id</label>"
        "<input name=\"id\" placeholder=\"synaptic_grove\" required></div>"
        "<div><label>name</label><input name=\"name\" placeholder=\"SYNAPTIC GROVE\">"
        "</div></div>"
        "<label>summary</label><input name=\"summary\">"
        "<p><button type=\"submit\">CREATE</button></p></form>"
    )


def project_page(store: Store, project_id: str) -> str:
    data = store.project_overview(project_id)
    project, state = data["project"], data["state"]
    head = (f"<h2 style=\"letter-spacing:.1em\">{e(project['name'])} "
            f"{status_badge(project['status'])}</h2>"
            f"<p class=\"dim\">{e(project['summary'])}</p>")

    now_rows = [["CURRENT PHASE", e(state["phase"]) if state else "-"],
                ["STATUS", status_badge(state["status"]) if state else "-"],
                ["OWNER", e(state["owner"]) if state else "-"],
                ["DEPENDENCIES", ", ".join(e(d) for d in data["dependencies"]) or "-"]]
    deliverables = "".join(f"<li>{e(d)}</li>"
                           for d in (state["deliverables"] if state else []))

    body = head + "<div class=\"grid\">"
    body += card("CURRENT", table(["", ""], now_rows)
                 + (f"<ul>{deliverables}</ul>" if deliverables else ""))
    body += card("PHASES", table(
        ["PHASE", "STATUS", "OWNER"],
        [[e(p["phase"]), status_badge(p["status"]), e(p["owner"] or "-")]
         for p in data["phases"]]))
    body += card("DECISIONS", table(
        ["ID", "TITLE", "STATUS"],
        [[e(d["id"]), e(d["title"]) + (f"<br><span class=\"dim\">{e(d['body'])}</span>"
                                       if d["body"] else ""),
          status_badge(d["status"])] for d in data["decisions"]]))
    body += card("FACTS", table(
        ["FACT", "TAGS"],
        [[e(f["body"]), " ".join(f"<span class=\"tag\">{e(t)}</span>"
                                 for t in f["tags"])] for f in data["facts"]]))
    body += card("HANDOFFS", table(
        ["ID", "TITLE", "PATH", "OWNER", "FILE"],
        [[e(h["id"]), e(h["title"]), f"<code>{e(h['file_path'])}</code>",
          e(h["owner"]),
          "<span class=\"ok\">OK</span>" if h["file_exists"]
          else "<span class=\"bad\">MISSING</span>"] for h in data["handoffs"]]))
    body += card("RELATIONS", table(
        ["SRC", "REL", "DST"],
        [[e(r["src"]), f"<span class=\"dim\">{e(r['rel'])}</span>", e(r["dst"])]
         for r in data["relations"]]))
    body += card("RECENT CHANGES", table(
        ["TIME", "ENTITY", "ACTION", "SUMMARY"],
        [[e(c["created_at"][11:19]), e(c["entity"]), e(c["action"]), e(c["summary"])]
         for c in data["changes"]]))
    body += "</div>"

    body += "<div class=\"grid\" style=\"margin-top:16px\">"
    body += card("ADD DECISION", _decision_form(project_id))
    body += card("UPDATE STATE", _state_form(project_id))
    body += card("INDEX HANDOFF", _handoff_form(project_id))
    body += card("ADD RELATION", _relation_form(project_id))
    body += card("ADD FACT", _fact_form(project_id))
    body += "</div>"

    body += "<div class=\"grid\" style=\"margin-top:16px\">" + card(
        "CONTEXT PREVIEW",
        "".join(f"<p><a href=\"/preview/context/{e(a['id'])}?project={e(project_id)}\">"
                f"{e(a['name'])} → /context/{e(a['id'])}</a></p>"
                for a in store.list_agents())) + "</div>"
    return page(f"{project['name']} — SECOND BRAIN", body)


def _hidden(project_id: str) -> str:
    return f"<input type=\"hidden\" name=\"project\" value=\"{e(project_id)}\">"


def _decision_form(pid: str) -> str:
    return ("<form method=\"post\" action=\"/api/decision\">" + _hidden(pid) +
            "<label>title</label><input name=\"title\" required>"
            "<label>body</label><textarea name=\"body\" rows=\"3\"></textarea>"
            "<div class=\"row\"><div><label>status</label>"
            "<select name=\"status\"><option>LOCKED</option><option>PROPOSED</option>"
            "<option>SUPERSEDED</option></select></div>"
            "<div><label>phase</label><input name=\"phase\"></div></div>"
            "<p><button type=\"submit\">SAVE DECISION</button></p></form>")


def _state_form(pid: str) -> str:
    return ("<form method=\"post\" action=\"/api/state\">" + _hidden(pid) +
            "<label>phase</label><input name=\"phase\" required>"
            "<div class=\"row\"><div><label>status</label>"
            "<select name=\"status\"><option>IN_PROGRESS</option>"
            "<option>COMPLETE</option><option>BLOCKED</option>"
            "<option>WAITING</option></select></div>"
            "<div><label>owner</label><input name=\"owner\"></div></div>"
            "<label>deliverables (1行1件)</label>"
            "<textarea name=\"deliverables\" rows=\"3\"></textarea>"
            "<p><button type=\"submit\">SET STATE</button></p></form>")


def _handoff_form(pid: str) -> str:
    return ("<form method=\"post\" action=\"/api/handoff\">" + _hidden(pid) +
            "<div class=\"row\"><div><label>id</label>"
            "<input name=\"id\" required></div>"
            "<div><label>phase</label><input name=\"phase\"></div></div>"
            "<label>title</label><input name=\"title\">"
            "<label>file_path</label><input name=\"file_path\" required "
            "placeholder=\"D:\\projects\\...\\GR-02.md\">"
            "<label>owner</label><input name=\"owner\">"
            "<p><button type=\"submit\">INDEX</button></p></form>")


def _relation_form(pid: str) -> str:
    return ("<form method=\"post\" action=\"/api/relation\">" + _hidden(pid) +
            "<div class=\"row\"><div><label>src</label><input name=\"src\" required>"
            "</div><div><label>rel</label><input name=\"rel\" value=\"depends_on\" "
            "required></div><div><label>dst</label><input name=\"dst\" required>"
            "</div></div><p><button type=\"submit\">LINK</button></p></form>")


def _fact_form(pid: str) -> str:
    return ("<form method=\"post\" action=\"/api/fact\">" + _hidden(pid) +
            "<label>body</label><input name=\"body\" required>"
            "<label>tags (カンマ区切り)</label><input name=\"tags\" "
            "placeholder=\"constraint, asset\">"
            "<p><button type=\"submit\">ADD FACT</button></p></form>")


def agents_page(store: Store) -> str:
    body = "<div class=\"grid\">"
    for profile in store.list_role_profiles():
        agents = [a for a in store.list_agents()
                  if a["context_profile"] == profile["id"]]
        rows = [
            ["GOAL", e(profile["goal"])],
            ["PRIORITY", e(profile["priority"])],
            ["SEES", " ".join(f"<span class=\"tag\">{e(v)}</span>"
                              for v in profile["visible_context"]) or "-"],
            ["HIDDEN", " ".join(f"<span class=\"tag dim\">{e(v)}</span>"
                                for v in profile["hidden_context"]) or "-"],
            ["AXES", "、".join(e(v) for v in profile["evaluation_axes"]) or "-"],
            ["PROHIBITED", "<span class=\"bad\">"
             + "、".join(e(v) for v in profile["prohibitions"]) + "</span>"],
            ["AGENTS", ", ".join(
                f"<a href=\"/preview/context/{e(a['id'])}\">{e(a['name'])}</a>"
                for a in agents) or "-"],
        ]
        body += card(f"{profile['name']}  ({profile['id']})", table(["", ""], rows))
    body += "</div>"
    body += "<div class=\"grid\" style=\"margin-top:16px\">" + card(
        "REGISTER AGENT",
        "<form method=\"post\" action=\"/api/agent\"><div class=\"row\">"
        "<div><label>id</label><input name=\"id\" required></div>"
        "<div><label>name</label><input name=\"name\"></div>"
        "<div><label>role</label><input name=\"role\"></div>"
        "<div><label>context_profile</label><select name=\"context_profile\">"
        + "".join(f"<option>{e(p['id'])}</option>" for p in store.list_role_profiles())
        + "</select></div></div><p><button type=\"submit\">SAVE</button></p></form>"
    ) + "</div>"
    return page("AI AGENTS — SECOND BRAIN", body)


def context_page(store: Store, result: dict[str, Any]) -> str:
    tokens = result["token_estimate"]
    cls = "ok" if tokens <= result["token_budget"] else "bad"
    dropped = ", ".join(result["dropped_sections"]) or "なし"
    body = (f"<h2>{e(result['role_name'])} — {e(result['project'])}</h2>"
            f"<p class=\"dim\">GET <code>/context/{e(result['role'])}"
            f"?project={e(result['project'])}</code> · "
            f"<span class=\"{cls}\">≈{tokens} tokens</span> / budget "
            f"{e(result['token_budget'])} · dropped: {e(dropped)}</p>"
            f"<pre>{e(result['text'])}</pre>")
    return page(f"context/{result['role']}", body)


def login_page(failed: bool) -> str:
    warn = "<p class=\"bad\">APIキーが違います。</p>" if failed else ""
    body = ("<div class=\"grid\">" + card(
        "LOGIN", warn + "<form method=\"get\" action=\"/login\">"
        "<label>API KEY</label><input name=\"key\" type=\"password\" required>"
        "<p><button type=\"submit\">ENTER</button></p></form>") + "</div>")
    return page("LOGIN — SECOND BRAIN", body)


def error_page(status: int, message: str) -> str:
    return page(f"{status}", "<div class=\"grid\">"
                + card(str(status), f"<p class=\"bad\">{escape(message)}</p>"
                       "<p><a href=\"/\">← dashboard</a></p>") + "</div>")
