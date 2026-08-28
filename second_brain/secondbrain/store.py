"""Data access layer.

Every write goes through here so that (a) timestamps are consistent and
(b) the change log that feeds RECENT CHANGES is never forgotten.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from . import db


class NotFound(Exception):
    """Raised when a referenced project/agent/handoff does not exist."""


class Invalid(Exception):
    """Raised when caller input cannot be stored as-is."""


def now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _json_list(value: Any) -> str:
    """Accept a list, a newline/comma separated string, or None."""
    if value is None or value == "":
        return "[]"
    if isinstance(value, str):
        parts = [p.strip() for p in re.split(r"[\n,]", value)]
        value = [p for p in parts if p]
    if not isinstance(value, (list, tuple)):
        raise Invalid(f"expected a list, got {type(value).__name__}")
    return json.dumps([str(v) for v in value], ensure_ascii=False)


def loads(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [str(v) for v in parsed] if isinstance(parsed, list) else []


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    out = dict(row)
    for key in ("tags", "deliverables", "visible_context", "hidden_context",
                "evaluation_axes", "prohibitions"):
        if key in out:
            out[key] = loads(out[key])
    if "file_exists" in out:
        out["file_exists"] = bool(out["file_exists"])
    return out


def rows_to_dicts(rows: Iterable[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(r) for r in rows]  # type: ignore[misc]


SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def check_id(value: str, label: str) -> str:
    value = (value or "").strip()
    if not value:
        raise Invalid(f"{label} is required")
    if not SLUG_RE.match(value):
        raise Invalid(
            f"{label} must be letters, digits, '-', '_' or '.' (got {value!r})"
        )
    return value


class Store:
    """All reads and writes against one brain database."""

    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    @classmethod
    def open(cls, db_path: str | Path) -> "Store":
        conn = db.connect(db_path)
        db.init_db(conn)
        return cls(conn)

    def close(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- changes

    def log_change(self, entity: str, entity_id: str, action: str,
                   summary: str = "", project_id: str = "",
                   actor: str = "") -> None:
        self.conn.execute(
            "INSERT INTO changes(project_id, entity, entity_id, action, summary,"
            " actor, created_at) VALUES (?,?,?,?,?,?,?)",
            (project_id, entity, entity_id, action, summary, actor, now()),
        )

    def recent_changes(self, limit: int = 20, project_id: str | None = None
                       ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM changes"
        args: list[Any] = []
        if project_id:
            sql += " WHERE project_id = ?"
            args.append(project_id)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        return rows_to_dicts(self.conn.execute(sql, args))

    # --------------------------------------------------------------- projects

    def upsert_project(self, id: str, name: str = "", status: str = "ACTIVE",
                       summary: str = "", actor: str = "") -> dict[str, Any]:
        id = check_id(id, "project id")
        name = name or id
        ts = now()
        with self.conn:
            existed = self.get_project(id) is not None
            self.conn.execute(
                "INSERT INTO projects(id, name, status, summary, created_at,"
                " updated_at) VALUES (?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name,"
                " status=excluded.status, summary=excluded.summary,"
                " updated_at=excluded.updated_at",
                (id, name, status, summary, ts, ts),
            )
            self.log_change("project", id, "updated" if existed else "created",
                            name, project_id=id, actor=actor)
        return self.get_project(id)  # type: ignore[return-value]

    def get_project(self, id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM projects WHERE id = ?", (id,)).fetchone()
        )

    def require_project(self, id: str) -> dict[str, Any]:
        project = self.get_project(id)
        if project is None:
            raise NotFound(f"unknown project: {id}")
        return project

    def list_projects(self, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM projects WHERE status = ? ORDER BY id", (status,))
        else:
            rows = self.conn.execute("SELECT * FROM projects ORDER BY id")
        return rows_to_dicts(rows)

    # ---------------------------------------------------------- role profiles

    def upsert_role_profile(self, id: str, name: str = "", goal: str = "",
                            priority: str = "", visible_context: Any = None,
                            hidden_context: Any = None, evaluation_axes: Any = None,
                            prohibitions: Any = None, actor: str = "") -> dict[str, Any]:
        id = check_id(id, "role profile id")
        ts = now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO role_profiles(id, name, goal, priority, visible_context,"
                " hidden_context, evaluation_axes, prohibitions, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, goal=excluded.goal,"
                " priority=excluded.priority, visible_context=excluded.visible_context,"
                " hidden_context=excluded.hidden_context,"
                " evaluation_axes=excluded.evaluation_axes,"
                " prohibitions=excluded.prohibitions, updated_at=excluded.updated_at",
                (id, name or id, goal, priority, _json_list(visible_context),
                 _json_list(hidden_context), _json_list(evaluation_axes),
                 _json_list(prohibitions), ts, ts),
            )
            self.log_change("role_profile", id, "upserted", name or id, actor=actor)
        return self.get_role_profile(id)  # type: ignore[return-value]

    def get_role_profile(self, id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM role_profiles WHERE id = ?", (id,)).fetchone()
        )

    def list_role_profiles(self) -> list[dict[str, Any]]:
        return rows_to_dicts(self.conn.execute("SELECT * FROM role_profiles ORDER BY id"))

    # ----------------------------------------------------------------- agents

    def upsert_agent(self, id: str, name: str = "", role: str = "",
                     context_profile: str = "", model: str = "",
                     status: str = "ACTIVE", actor: str = "") -> dict[str, Any]:
        id = check_id(id, "agent id")
        profile = context_profile or id
        if self.get_role_profile(profile) is None:
            raise NotFound(f"unknown role profile: {profile}")
        ts = now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO agents(id, name, role, context_profile, model, status,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role,"
                " context_profile=excluded.context_profile, model=excluded.model,"
                " status=excluded.status, updated_at=excluded.updated_at",
                (id, name or id, role, profile, model, status, ts, ts),
            )
            self.log_change("agent", id, "upserted", name or id, actor=actor)
        return self.get_agent(id)  # type: ignore[return-value]

    def get_agent(self, id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM agents WHERE id = ?", (id,)).fetchone()
        )

    def list_agents(self) -> list[dict[str, Any]]:
        return rows_to_dicts(self.conn.execute("SELECT * FROM agents ORDER BY id"))

    # ------------------------------------------------------------------ facts

    def add_fact(self, project_id: str, body: str, key: str = "", tags: Any = None,
                 source: str = "", actor: str = "") -> dict[str, Any]:
        self.require_project(project_id)
        if not (body or "").strip():
            raise Invalid("fact body is required")
        with self.conn:
            cur = self.conn.execute(
                "INSERT INTO facts(project_id, key, body, tags, source, created_at)"
                " VALUES (?,?,?,?,?,?)",
                (project_id, key, body.strip(), _json_list(tags), source, now()),
            )
            fact_id = str(cur.lastrowid)
            self.log_change("fact", fact_id, "created", body.strip()[:80],
                            project_id=project_id, actor=actor)
        return self.get_fact(int(fact_id))  # type: ignore[return-value]

    def get_fact(self, id: int) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM facts WHERE id = ?", (id,)).fetchone()
        )

    def list_facts(self, project_id: str) -> list[dict[str, Any]]:
        return rows_to_dicts(self.conn.execute(
            "SELECT * FROM facts WHERE project_id = ? ORDER BY id", (project_id,)))

    # -------------------------------------------------------------- decisions

    def next_decision_id(self) -> str:
        row = self.conn.execute(
            "SELECT id FROM decisions WHERE id LIKE 'DECISION-%' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        seq = 0
        if row:
            match = re.search(r"(\d+)$", row["id"])
            if match:
                seq = int(match.group(1))
        return f"DECISION-{seq + 1:04d}"

    def add_decision(self, project_id: str, title: str, body: str = "",
                     status: str = "LOCKED", phase: str = "", tags: Any = None,
                     id: str | None = None, actor: str = "") -> dict[str, Any]:
        self.require_project(project_id)
        if not (title or "").strip():
            raise Invalid("decision title is required")
        decision_id = check_id(id, "decision id") if id else self.next_decision_id()
        ts = now()
        with self.conn:
            existed = self.get_decision(decision_id) is not None
            self.conn.execute(
                "INSERT INTO decisions(id, project_id, title, body, status, phase,"
                " tags, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET title=excluded.title,"
                " body=excluded.body, status=excluded.status, phase=excluded.phase,"
                " tags=excluded.tags, updated_at=excluded.updated_at",
                (decision_id, project_id, title.strip(), body.strip(), status, phase,
                 _json_list(tags), ts, ts),
            )
            self.log_change("decision", decision_id,
                            "updated" if existed else "created",
                            f"{status}: {title.strip()[:70]}",
                            project_id=project_id, actor=actor)
        return self.get_decision(decision_id)  # type: ignore[return-value]

    def get_decision(self, id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM decisions WHERE id = ?", (id,)).fetchone()
        )

    def list_decisions(self, project_id: str, status: str | None = None
                       ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM decisions WHERE project_id = ?"
        args: list[Any] = [project_id]
        if status:
            sql += " AND status = ?"
            args.append(status)
        sql += " ORDER BY id"
        return rows_to_dicts(self.conn.execute(sql, args))

    # ------------------------------------------------------------------ state

    def set_state(self, project_id: str, phase: str, status: str = "IN_PROGRESS",
                  owner: str = "", note: str = "", deliverables: Any = None,
                  actor: str = "") -> dict[str, Any]:
        self.require_project(project_id)
        if not (phase or "").strip():
            raise Invalid("phase is required")
        with self.conn:
            self.conn.execute(
                "INSERT INTO states(project_id, phase, status, owner, note,"
                " deliverables, created_at) VALUES (?,?,?,?,?,?,?)",
                (project_id, phase.strip(), status, owner, note,
                 _json_list(deliverables), now()),
            )
            self.log_change("state", phase.strip(), "set", f"{phase.strip()} {status}",
                            project_id=project_id, actor=actor)
        return self.current_state(project_id)  # type: ignore[return-value]

    def current_state(self, project_id: str) -> dict[str, Any] | None:
        return row_to_dict(self.conn.execute(
            "SELECT * FROM states WHERE project_id = ? ORDER BY id DESC LIMIT 1",
            (project_id,)).fetchone())

    def state_history(self, project_id: str, limit: int = 50) -> list[dict[str, Any]]:
        return rows_to_dicts(self.conn.execute(
            "SELECT * FROM states WHERE project_id = ? ORDER BY id DESC LIMIT ?",
            (project_id, limit)))

    def phase_summary(self, project_id: str) -> list[dict[str, Any]]:
        """Latest status per phase, oldest phase first — the implementation map."""
        rows = self.conn.execute(
            "SELECT s.* FROM states s JOIN (SELECT phase, MAX(id) AS id FROM states"
            " WHERE project_id = ? GROUP BY phase) latest ON s.id = latest.id"
            " ORDER BY s.id", (project_id,))
        return rows_to_dicts(rows)

    # --------------------------------------------------------------- handoffs

    def upsert_handoff(self, id: str, project_id: str, file_path: str,
                       title: str = "", phase: str = "", owner: str = "",
                       status: str = "ACTIVE", actor: str = "",
                       verify: bool = True) -> dict[str, Any]:
        """Index a handoff file. The body is never read (spec section 15)."""
        id = check_id(id, "handoff id")
        self.require_project(project_id)
        if not (file_path or "").strip():
            raise Invalid("file_path is required")
        file_path = file_path.strip()
        exists, checked_at = (0, "")
        if verify:
            exists, checked_at = (1 if path_exists(file_path) else 0, now())
        ts = now()
        with self.conn:
            self.conn.execute(
                "INSERT INTO handoffs(id, project_id, phase, title, file_path, owner,"
                " status, file_exists, checked_at, created_at, updated_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(id) DO UPDATE SET project_id=excluded.project_id,"
                " phase=excluded.phase, title=excluded.title,"
                " file_path=excluded.file_path, owner=excluded.owner,"
                " status=excluded.status, file_exists=excluded.file_exists,"
                " checked_at=excluded.checked_at, updated_at=excluded.updated_at",
                (id, project_id, phase, title or id, file_path, owner, status,
                 exists, checked_at, ts, ts),
            )
            self.log_change("handoff", id, "indexed", f"{title or id} -> {file_path}",
                            project_id=project_id, actor=actor)
        return self.get_handoff(id)  # type: ignore[return-value]

    def get_handoff(self, id: str) -> dict[str, Any] | None:
        return row_to_dict(
            self.conn.execute("SELECT * FROM handoffs WHERE id = ?", (id,)).fetchone()
        )

    def list_handoffs(self, project_id: str | None = None, status: str | None = None
                      ) -> list[dict[str, Any]]:
        sql, args = "SELECT * FROM handoffs", []
        where = []
        if project_id:
            where.append("project_id = ?")
            args.append(project_id)
        if status:
            where.append("status = ?")
            args.append(status)
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY project_id, id"
        return rows_to_dicts(self.conn.execute(sql, args))

    def verify_handoffs(self, project_id: str | None = None) -> dict[str, Any]:
        """Existence check only — never parse the body."""
        checked, missing = 0, []
        ts = now()
        with self.conn:
            for handoff in self.list_handoffs(project_id):
                exists = path_exists(handoff["file_path"])
                self.conn.execute(
                    "UPDATE handoffs SET file_exists = ?, checked_at = ? WHERE id = ?",
                    (1 if exists else 0, ts, handoff["id"]),
                )
                checked += 1
                if not exists:
                    missing.append(handoff["id"])
        return {"checked": checked, "missing": missing, "checked_at": ts}

    # -------------------------------------------------------------- relations

    def add_relation(self, project_id: str, src: str, rel: str, dst: str,
                     actor: str = "") -> dict[str, Any]:
        self.require_project(project_id)
        src, rel, dst = src.strip(), rel.strip(), dst.strip()
        if not (src and rel and dst):
            raise Invalid("src, rel and dst are required")
        with self.conn:
            self.conn.execute(
                "INSERT INTO relations(project_id, src, rel, dst, created_at)"
                " VALUES (?,?,?,?,?) ON CONFLICT DO NOTHING",
                (project_id, src, rel, dst, now()),
            )
            self.log_change("relation", f"{src} {rel} {dst}", "created",
                            f"{src} {rel} {dst}", project_id=project_id, actor=actor)
        row = self.conn.execute(
            "SELECT * FROM relations WHERE project_id=? AND src=? AND rel=? AND dst=?",
            (project_id, src, rel, dst)).fetchone()
        return row_to_dict(row)  # type: ignore[return-value]

    def list_relations(self, project_id: str, src: str | None = None,
                       rel: str | None = None, dst: str | None = None
                       ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM relations WHERE project_id = ?"
        args: list[Any] = [project_id]
        for column, value in (("src", src), ("rel", rel), ("dst", dst)):
            if value:
                sql += f" AND {column} = ?"
                args.append(value)
        sql += " ORDER BY id"
        return rows_to_dicts(self.conn.execute(sql, args))

    def dependencies_of(self, project_id: str, node: str) -> list[str]:
        return [r["dst"] for r in self.list_relations(project_id, src=node,
                                                      rel="depends_on")]

    def dependents_of(self, project_id: str, node: str) -> list[str]:
        return [r["src"] for r in self.list_relations(project_id, rel="depends_on",
                                                      dst=node)]

    # -------------------------------------------------------------- aggregate

    def project_overview(self, project_id: str) -> dict[str, Any]:
        project = self.require_project(project_id)
        state = self.current_state(project_id)
        phase = state["phase"] if state else ""
        return {
            "project": project,
            "state": state,
            "phases": self.phase_summary(project_id),
            "facts": self.list_facts(project_id),
            "decisions": self.list_decisions(project_id),
            "handoffs": self.list_handoffs(project_id),
            "relations": self.list_relations(project_id),
            "dependencies": self.dependencies_of(project_id, phase) if phase else [],
            "changes": self.recent_changes(10, project_id),
        }

    def brain_snapshot(self) -> dict[str, Any]:
        return {
            "generated_at": now(),
            "projects": [self.project_overview(p["id"]) for p in self.list_projects()],
            "agents": self.list_agents(),
            "role_profiles": self.list_role_profiles(),
            "changes": self.recent_changes(20),
        }


def path_exists(file_path: str) -> bool:
    """Existence check that tolerates Windows-style paths stored from another PC."""
    try:
        return Path(file_path).exists()
    except OSError:
        return False
