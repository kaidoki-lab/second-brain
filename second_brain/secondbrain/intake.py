"""AIが返した「工程表」を読み取って、第二の脳へ取り込む。

会話ではなく結論だけを保存するための入口。想定する書式:

    PHASE: GR-01 MEMBRANE | 完了 | Design AI | アセット7点; 仕様書
    DECISION: CHANNELはパイプに見せない | 同一組織内の流路として描く
    FACT: アセット総数は21で固定 | constraint
    DEPENDS: GR-02 -> GR-01
    OPEN: NODEの発光可否が未決

全角の「：」「｜」、行頭の「-」「*」、番号付きも許容する。
"""

from __future__ import annotations

import re
from typing import Any

from .store import Store

#: 日本語の状態表記 → 内部コード。
STATUS_MAP = {
    "未着手": "PENDING", "着手前": "PENDING", "予定": "PENDING",
    "作業中": "IN_PROGRESS", "進行中": "IN_PROGRESS", "実行中": "IN_PROGRESS",
    "完了": "COMPLETE", "済": "COMPLETE", "完成": "COMPLETE",
    "停止中": "BLOCKED", "ブロック": "BLOCKED", "中断": "BLOCKED",
    "待ち": "WAITING", "保留": "WAITING",
}
KNOWN_STATUSES = {"PENDING", "IN_PROGRESS", "COMPLETE", "BLOCKED", "WAITING"}

LABELS = {
    "PHASE": "phases", "工程": "phases",
    "DECISION": "decisions", "決定": "decisions",
    "FACT": "facts", "事実": "facts",
    "DEPENDS": "depends", "依存": "depends",
    "OPEN": "opens", "未決": "opens",
}

LINE_RE = re.compile(r"^\s*(?:[-*・]|\d+[.)])?\s*([A-Za-z一-龥]+)\s*[:：]\s*(.+)$")


def _split(value: str) -> list[str]:
    parts = re.split(r"[|｜]", value)
    return [p.strip() for p in parts]


def normalise_status(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return "PENDING"
    upper = value.upper().replace(" ", "_")
    if upper in KNOWN_STATUSES:
        return upper
    for word, code in STATUS_MAP.items():
        if word in value:
            return code
    return "PENDING"


def parse_result(text: str) -> dict[str, Any]:
    """AIの出力を解析する。解釈できない行は unknown に残して見せる。"""
    parsed: dict[str, Any] = {"phases": [], "decisions": [], "facts": [],
                              "depends": [], "opens": [], "unknown": []}
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or set(line) <= {"-", "=", "―"}:
            continue
        match = LINE_RE.match(line)
        if not match:
            parsed["unknown"].append(line)
            continue
        label, rest = match.group(1).upper(), match.group(2).strip()
        key = LABELS.get(label) or LABELS.get(match.group(1))
        if key is None:
            parsed["unknown"].append(line)
            continue

        fields = _split(rest)
        if key == "phases":
            deliverables = [d.strip() for d in re.split(r"[;；、]", fields[3])
                            if d.strip()] if len(fields) > 3 else []
            parsed["phases"].append({
                "phase": fields[0],
                "status": normalise_status(fields[1] if len(fields) > 1 else ""),
                "owner": fields[2] if len(fields) > 2 else "",
                "deliverables": deliverables,
            })
        elif key == "decisions":
            parsed["decisions"].append({
                "title": fields[0],
                "body": fields[1] if len(fields) > 1 else "",
            })
        elif key == "facts":
            tags = [t.strip() for t in re.split(r"[,、]", fields[1])
                    if t.strip()] if len(fields) > 1 else []
            parsed["facts"].append({"body": fields[0], "tags": tags})
        elif key == "depends":
            pair = re.split(r"->|→|＞|>", rest)
            if len(pair) >= 2:
                parsed["depends"].append({"src": pair[0].strip(),
                                          "dst": pair[1].strip()})
            else:
                parsed["unknown"].append(line)
        elif key == "opens":
            parsed["opens"].append({"title": fields[0]})
    return parsed


#: 箇条書きの記号や番号を落とすための形。
BULLET_RE = re.compile(r"^\s*(?:[-*・‣▪、]|\d+[.)、]|[（(]\d+[）)])\s*")
#: 1項目の長さ上限（長文はメモではなく資料なので弾く）。
MEMORY_ITEM_MAX = 300


def parse_memory(text: str, category: str = "") -> list[dict[str, Any]]:
    """AIが書き出した「あなたについての記憶」を1行1件に整える。

    見出し・空行・記号だけの行は落とす。行末の #タグ は分けて取り出す。
    """
    items: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") and " " not in line[:3]:
            continue
        if set(line) <= {"-", "=", "―", "─", "*", "・"}:
            continue
        line = BULLET_RE.sub("", line).strip()
        if not line or len(line) > MEMORY_ITEM_MAX:
            continue
        tags = re.findall(r"#([^\s#]+)", line)
        body = re.sub(r"\s*#[^\s#]+", "", line).strip(" 　:：")
        if not body or body in seen:
            continue
        seen.add(body)
        items.append({"body": body, "tags": tags, "category": category})
    return items


def current_phase_of(phases: list[dict[str, Any]]) -> dict[str, Any] | None:
    """いま取り組む工程＝最初の作業中。無ければ最初の未着手。"""
    for status in ("IN_PROGRESS", "BLOCKED", "WAITING", "PENDING"):
        for phase in phases:
            if phase["status"] == status:
                return phase
    return phases[-1] if phases else None


def apply_result(store: Store, project_id: str, parsed: dict[str, Any],
                 actor: str = "intake") -> dict[str, Any]:
    """解析結果を保存する。工程は並び順どおりに登録する。"""
    store.require_project(project_id)
    written = {"phases": 0, "decisions": 0, "facts": 0, "depends": 0, "opens": 0}

    for phase in parsed["phases"]:
        if not phase["phase"]:
            continue
        store.set_state(project_id, phase["phase"], phase["status"],
                        phase["owner"], deliverables=phase["deliverables"],
                        actor=actor)
        written["phases"] += 1

    # append-only なので、最後にもう一度書いた工程が「現在地」になる。
    current = current_phase_of(parsed["phases"])
    if current and written["phases"] > 1:
        store.set_state(project_id, current["phase"], current["status"],
                        current["owner"], deliverables=current["deliverables"],
                        actor=actor)

    for decision in parsed["decisions"]:
        if decision["title"]:
            store.add_decision(project_id, decision["title"], decision["body"],
                               status="LOCKED", actor=actor)
            written["decisions"] += 1

    for fact in parsed["facts"]:
        if fact["body"]:
            store.add_fact(project_id, fact["body"], tags=fact["tags"], actor=actor)
            written["facts"] += 1

    for link in parsed["depends"]:
        if link["src"] and link["dst"]:
            store.add_relation(project_id, link["src"], "depends_on", link["dst"],
                               actor=actor)
            written["depends"] += 1

    for open_item in parsed["opens"]:
        if open_item["title"]:
            store.add_decision(project_id, open_item["title"], "",
                               status="PROPOSED", actor=actor)
            written["opens"] += 1

    return written


# ====================================================== 複数企画を一度に取り込む

#: `PROJECT: 名前 | 状態` で企画の切り替わりを表す。
PROJECT_RE = re.compile(
    r"^\s*(?:[-*・]|\d+[.)])?\s*(?:PROJECT|PROJ|企画)\s*[:：]\s*(.+)$", re.IGNORECASE)


def parse_bulk(text: str) -> dict[str, Any]:
    """PROJECT行で区切られた文章を、企画ごとの取り込み内容に分解する。

    企画をまたぐメモを1回の貼り付けで登録するための入口。PROJECT行より前に
    書かれた分は unassigned に入れ、画面側で行き先を選ばせる。
    """
    sections: list[dict[str, Any]] = []
    lead: list[str] = []
    current: dict[str, Any] | None = None

    for raw in (text or "").splitlines():
        match = PROJECT_RE.match(raw.strip())
        if match:
            fields = _split(match.group(1))
            current = {"name": fields[0].strip(),
                       "status": (fields[1].strip().upper()
                                  if len(fields) > 1 and fields[1].strip()
                                  else "ACTIVE"),
                       "summary": fields[2].strip() if len(fields) > 2 else "",
                       "lines": []}
            sections.append(current)
            continue
        (current["lines"] if current else lead).append(raw)

    projects = []
    for section in sections:
        if not section["name"]:
            continue
        parsed = parse_result("\n".join(section["lines"]))
        projects.append({"name": section["name"], "status": section["status"],
                         "summary": section["summary"], "parsed": parsed,
                         "total": _count(parsed)})
    unassigned = parse_result("\n".join(lead))
    return {"projects": projects, "unassigned": unassigned,
            "unassigned_total": _count(unassigned)}


def _count(parsed: dict[str, Any]) -> int:
    return sum(len(parsed[key]) for key in
               ("phases", "decisions", "facts", "depends", "opens"))


def apply_bulk(store: Store, bulk: dict[str, Any], actor: str = "bulk",
               unassigned_project: str = "") -> dict[str, Any]:
    """企画ごとに登録する。無い企画はここで作る。"""
    from .store import slugify_id

    results = []
    for entry in bulk["projects"]:
        project_id = slugify_id(entry["name"])
        store.upsert_project(project_id, entry["name"], entry["status"] or "ACTIVE",
                             entry.get("summary", ""), actor=actor)
        written = apply_result(store, project_id, entry["parsed"], actor=actor)
        results.append({"project": project_id, "name": entry["name"],
                        "written": written})

    if unassigned_project and _count(bulk["unassigned"]):
        project_id = slugify_id(unassigned_project)
        store.upsert_project(project_id, unassigned_project, actor=actor)
        written = apply_result(store, project_id, bulk["unassigned"], actor=actor)
        results.append({"project": project_id, "name": unassigned_project,
                        "written": written})
    return {"projects": results,
            "total": sum(sum(r["written"].values()) for r in results)}
