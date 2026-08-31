"""ブラウザ画面（日本語UI）。

外部CSS・JSフレームワークは使わない。LANだけで完結し、古い端末でも開ける。
操作はすべてボタンとフォームで完結させ、コマンド入力を前提にしない。
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
body { margin:0; background:var(--bg); color:var(--fg); font:15px/1.7
       -apple-system, "Segoe UI", "Hiragino Kaku Gothic ProN", Meiryo, sans-serif; }
header { padding:12px 20px; border-bottom:1px solid var(--line);
         display:flex; gap:10px; align-items:center; flex-wrap:wrap; }
header h1 { font-size:15px; margin:0 14px 0 0; letter-spacing:.14em;
            white-space:nowrap; }
nav a { color:var(--dim); text-decoration:none; font-size:14px; padding:6px 12px;
        border-radius:6px; display:inline-block; }
nav a:hover { color:var(--fg); background:#1d232c; }
nav a.on { color:var(--fg); background:#1d232c; }
main { padding:20px; max-width:1240px; margin:0 auto; }
h2.page { font-size:20px; margin:0 0 4px; }
p.lead { color:var(--dim); margin:0 0 18px; }
.grid { display:flex; flex-wrap:wrap; gap:16px; align-items:flex-start; }
.card { background:var(--panel); border:1px solid var(--line); border-radius:10px;
        padding:16px 18px; flex:1 1 340px; min-width:300px; }
.card.wide { flex-basis:100%; }
.card h3 { font-size:13px; letter-spacing:.1em; color:var(--dim); margin:0 0 12px; }
table { width:100%; border-collapse:collapse; }
td, th { padding:8px; text-align:left; border-bottom:1px solid var(--line);
         vertical-align:top; }
th { color:var(--dim); font-weight:500; font-size:13px; white-space:nowrap; }
tr:last-child td { border-bottom:none; }
a { color:var(--accent); }
code { font-family:ui-monospace, Consolas, monospace; font-size:13px; }
.path { font-family:ui-monospace, Consolas, monospace; font-size:12px;
        color:var(--dim); word-break:break-all; }
.tag { display:inline-block; padding:1px 9px; border-radius:99px; font-size:12px;
       border:1px solid var(--line); color:var(--dim); white-space:nowrap; }
.ok { color:var(--ok); } .warn { color:var(--warn); } .bad { color:var(--bad); }
.dim { color:var(--dim); }
form { margin:0; } input, select, textarea, button { font:inherit; }
input, select, textarea { background:#0b0f14; color:var(--fg); padding:9px 11px;
       border:1px solid var(--line); border-radius:8px; width:100%; }
button { background:var(--accent); color:#04121c; border:0; border-radius:8px;
         padding:10px 18px; font-weight:700; cursor:pointer; }
button.sub { background:#2b3542; color:var(--fg); font-weight:500;
             padding:7px 12px; font-size:13px; }
button.danger { background:#5a2020; color:#ffbdbd; font-weight:500;
                padding:7px 12px; font-size:13px; }
button:hover { filter:brightness(1.1); }
label { display:block; margin:12px 0 4px; font-size:13px; color:var(--dim); }
.row { display:flex; gap:12px; flex-wrap:wrap; }
.row > * { flex:1 1 180px; }
.actions { margin-top:16px; }
.big { display:inline-block; padding:18px 22px; background:#1d5f8f; color:#fff;
       border:1px solid #2f88c8; border-radius:10px; text-decoration:none;
       font-weight:700; margin:0 12px 12px 0; min-width:230px; }
.big span { display:block; font-weight:400; font-size:13px; color:#bcdcf3;
            margin-top:4px; }
.empty { color:var(--dim); }
.note { background:#0b0f14; border:1px solid var(--line); border-radius:8px;
        padding:12px 14px; color:var(--dim); font-size:13px; margin:14px 0; }
.flash { border-left:4px solid var(--ok); background:#12241a; padding:12px 16px;
         border-radius:8px; margin-bottom:18px; }
.flash.bad { border-left-color:var(--bad); background:#2a1416; }
"""

NAV = [
    ("/", "ダッシュボード"),
    ("/handoffs", "ハンドオフ"),
    ("/import", "取り込み"),
    ("/projects", "企画"),
    ("/profile", "私について"),
    ("/agents", "AI設定"),
]


def page(title: str, body: str, current: str = "") -> str:
    links = "".join(
        f'<a href="{href}" class="{"on" if href == current else ""}">{label}</a>'
        for href, label in NAV)
    return (
        '<!doctype html><html lang="ja"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{escape(title)}</title><style>{STYLE}</style></head><body>"
        f'<header><h1>第二の脳</h1><nav>{links}</nav></header><main>{body}</main>'
        "</body></html>"
    )


def e(value: Any) -> str:
    return escape("" if value is None else str(value))


def card(title: str, body: str, wide: bool = False) -> str:
    cls = "card wide" if wide else "card"
    return f'<section class="{cls}"><h3>{escape(title)}</h3>{body}</section>'


def table(headers: list[str], rows: list[list[str]], empty: str = "まだありません"
          ) -> str:
    if not rows:
        return f'<p class="empty">{escape(empty)}</p>'
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>"
                   for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


STATUS_JA = {
    "ACTIVE": "進行中", "COMPLETE": "完了", "IN_PROGRESS": "作業中",
    "PENDING": "未着手",
    "BLOCKED": "停止中", "WAITING": "待ち", "LOCKED": "確定", "PROPOSED": "検討中",
    "SUPERSEDED": "破棄", "ARCHIVED": "保管",
}


def status_badge(status: str) -> str:
    cls = {"COMPLETE": "ok", "LOCKED": "ok", "ACTIVE": "ok", "IN_PROGRESS": "warn",
           "PROPOSED": "warn", "BLOCKED": "bad", "SUPERSEDED": "dim"}.get(status, "dim")
    return f'<span class="tag {cls}">{escape(STATUS_JA.get(status, status))}</span>'


def file_flag(exists: bool) -> str:
    return ('<span class="ok">あり</span>' if exists
            else '<span class="bad">見つからない</span>')


def flash(message: str, bad: bool = False) -> str:
    if not message:
        return ""
    cls = "flash bad" if bad else "flash"
    return f'<div class="{cls}">{escape(message)}</div>'


def project_options(store: Store, selected: str = "", blank: str = "") -> str:
    out = f'<option value="">{escape(blank)}</option>' if blank else ""
    for project in store.list_projects():
        mark = " selected" if project["id"] == selected else ""
        out += (f'<option value="{e(project["id"])}"{mark}>'
                f'{e(project["name"])}</option>')
    return out


# ============================================================ ダッシュボード

def dashboard(store: Store, message: str = "") -> str:
    projects = store.list_projects()
    handoffs = store.list_handoffs()
    missing = [h for h in handoffs if not h["file_exists"]]

    body = flash(message)
    body += '<h2 class="page">ダッシュボード</h2>'
    body += ('<p class="lead">PC内のハンドオフと、企画ごとの決定事項をまとめて'
             '管理します。ファイルは移動しません。場所を覚えておくだけです。</p>')

    body += ('<div>'
             '<a class="big" href="/import">📥 ハンドオフを取り込む'
             '<span>フォルダを指定して自動で探します</span></a>'
             '<a class="big" href="/handoffs">🔍 ハンドオフを探す'
             f'<span>登録済み {len(handoffs)} 件から検索</span></a>'
             '<a class="big" href="/profile">👤 私について'
             f'<span>全AI共通の前提 {len(store.list_profile())} 件</span></a>'
             '</div>')

    if missing:
        body += ('<div class="note"><span class="bad">'
                 f'ファイルが見つからないハンドオフが {len(missing)} 件あります。</span>'
                 ' 移動または削除された可能性があります。'
                 ' <a href="/handoffs?missing=1">確認する</a></div>')

    rows = []
    for project in projects:
        state = store.current_state(project["id"])
        count = len(store.list_handoffs(project["id"]))
        rows.append([
            f'<a href="/project/{e(project["id"])}">{e(project["name"])}</a>',
            status_badge(project["status"]),
            e(state["phase"]) if state else '<span class="dim">-</span>',
            f'{count} 件',
        ])

    changes = [[e(c["created_at"][5:16].replace("T", " ")), e(c["entity"]),
                e(c["summary"])] for c in store.recent_changes(10)]

    body += '<div class="grid">'
    body += card("企画", table(["企画", "状態", "現在の工程", "ハンドオフ"], rows,
                               "企画がまだありません。取り込み時に作成できます。"))
    body += card("最近の変更", table(["日時", "種類", "内容"], changes))
    body += "</div>"
    return page("第二の脳", body, "/")


# ============================================================== ハンドオフ

def handoff_list(store: Store, query: str = "", project: str = "",
                 missing_only: bool = False, message: str = "") -> str:
    results = store.search_handoffs(query, project or None,
                                    missing_only=missing_only)
    total = len(store.list_handoffs())

    body = flash(message)
    body += '<h2 class="page">ハンドオフ一覧</h2>'
    body += (f'<p class="lead">登録済み {total} 件。ファイルの中身は読み込まず、'
             '置き場所だけを覚えています。</p>')

    search = (
        '<form method="get" action="/handoffs"><div class="row">'
        '<div style="flex:2 1 260px"><label>キーワード（ファイル名・工程・担当）</label>'
        f'<input name="q" value="{e(query)}" placeholder="例: GR-02"></div>'
        '<div><label>企画</label><select name="project">'
        + project_options(store, project, blank="すべて") + '</select></div>'
        '<div><label>絞り込み</label><select name="missing">'
        f'<option value="">すべて</option>'
        f'<option value="1"{" selected" if missing_only else ""}>'
        'ファイルが見つからないものだけ</option></select></div>'
        '</div><div class="actions"><button type="submit">検索</button> '
        '<a class="dim" href="/handoffs" style="margin-left:12px">条件をクリア</a>'
        '</div></form>')
    body += card("検索", search, wide=True)

    rows = []
    for handoff in results:
        controls = (
            f'<form method="post" action="/ui/handoff/update" class="row" '
            f'style="gap:6px">'
            f'<input type="hidden" name="id" value="{e(handoff["id"])}">'
            f'<select name="project" style="flex:1 1 120px">'
            + project_options(store, handoff["project_id"]) +
            '</select>'
            '<button class="sub" type="submit">企画を変更</button></form>'
            f'<form method="post" action="/ui/handoff/delete" '
            f'onsubmit="return confirm(\'一覧から外します。ファイル自体は消えません。'
            f'よろしいですか？\')" style="margin-top:6px">'
            f'<input type="hidden" name="id" value="{e(handoff["id"])}">'
            '<button class="danger" type="submit">一覧から外す</button></form>')
        rows.append([
            f'<b>{e(handoff["title"])}</b>'
            f'<div class="path">{e(handoff["file_path"])}</div>',
            e(handoff["project_id"]),
            e(handoff["phase"]) or '<span class="dim">-</span>',
            file_flag(handoff["file_exists"]),
            controls,
        ])

    listing = table(["ファイル", "企画", "工程", "実ファイル", "操作"], rows,
                    "該当するハンドオフがありません。")
    verify = ('<form method="post" action="/ui/verify" style="margin-bottom:14px">'
              '<button class="sub" type="submit">'
              'すべてのファイルの存在を確認する</button></form>')
    body += '<div class="grid">' + card(f"結果 {len(results)} 件", verify + listing,
                                        wide=True) + "</div>"
    return page("ハンドオフ一覧", body, "/handoffs")


# ================================================================ 取り込み

def import_page(store: Store, result: dict[str, Any] | None = None,
                form: dict[str, str] | None = None, message: str = "",
                bad: bool = False) -> str:
    form = form or {}
    body = flash(message, bad)
    body += '<h2 class="page">ハンドオフの取り込み</h2>'
    body += ('<p class="lead">フォルダを指定すると、その中（サブフォルダ含む）から'
             'ファイル名に「ハンドオフ」を含むファイルを自動で探して登録します。</p>')

    body += ('<div class="note">ファイルは<b>移動もコピーも変更もしません</b>。'
             '中身も開きません。記録するのは「どこに何があるか」だけです。<br>'
             '同じファイルを二度取り込んでも重複しません。</div>')

    fields = (
        '<form method="post" action="/ui/import">'
        '<label>探すフォルダ（このPC内のパス）</label>'
        f'<input name="dir" required placeholder="例: D:\\projects"'
        f' value="{e(form.get("dir", ""))}">'
        '<div class="row">'
        '<div><label>ファイル名に含まれる言葉（カンマ区切り）</label>'
        f'<input name="keywords" value="'
        f'{e(form.get("keywords", "ハンドオフ, handoff"))}"></div>'
        '<div><label>登録先の企画</label><select name="project">'
        + project_options(store, form.get("project", ""), blank="（新しく作る）") +
        '</select></div>'
        '<div><label>新しい企画の名前（上で「新しく作る」を選んだ場合）</label>'
        f'<input name="new_project" placeholder="例: 未分類"'
        f' value="{e(form.get("new_project", ""))}"></div>'
        '</div>'
        '<div class="actions"><button type="submit">この条件で取り込む</button></div>'
        '</form>')
    body += '<div class="grid">' + card("取り込み条件", fields, wide=True) + "</div>"

    if result:
        added, already = result["added"], result["already"]
        summary = table(["項目", "結果"], [
            ["新しく登録", f'<b class="ok">{len(added)} 件</b>'],
            ["すでに登録済み", f"{len(already)} 件"],
            ["調べたファイル数", f"{result['scanned']} 件"],
            ["かかった時間", f"{result['seconds']} 秒"],
        ])
        if result.get("stopped"):
            summary += ('<p class="warn">※ 件数が多いため途中で打ち切りました。'
                        'フォルダをもう少し絞って再実行してください。</p>')
        listing = table(
            ["ファイル", "工程", "場所"],
            [[e(h["title"]), e(h["phase"]) or '<span class="dim">-</span>',
              f'<span class="path">{e(h["file_path"])}</span>'] for h in added],
            "新しく登録されたものはありません（すべて登録済みでした）。")
        body += ('<div class="grid">' + card("取り込み結果", summary)
                 + card("登録したファイル", listing, wide=False) + "</div>"
                 + '<p style="margin-top:16px">'
                   '<a href="/handoffs">→ ハンドオフ一覧で確認する</a></p>')
    return page("ハンドオフの取り込み", body, "/import")


# ================================================================== 企画

def projects_page(store: Store, message: str = "") -> str:
    body = flash(message)
    body += '<h2 class="page">企画</h2>'
    body += '<p class="lead">企画ごとに、現在の工程・決定事項・ハンドオフをまとめます。</p>'

    rows = []
    for project in store.list_projects():
        state = store.current_state(project["id"])
        rows.append([
            f'<a href="/project/{e(project["id"])}">{e(project["name"])}</a>',
            status_badge(project["status"]),
            e(state["phase"]) if state else '<span class="dim">未設定</span>',
            f'{len(store.list_decisions(project["id"]))} 件',
            f'{len(store.list_handoffs(project["id"]))} 件',
        ])
    body += '<div class="grid">'
    body += card("企画一覧", table(["企画", "状態", "現在の工程", "決定事項",
                                    "ハンドオフ"], rows), wide=True)
    body += card("新しい企画を作る",
                 '<form method="post" action="/ui/project">'
                 '<label>企画の名前</label>'
                 '<input name="name" required placeholder="例: SYNAPTIC GROVE">'
                 '<label>ひとこと説明（任意）</label><input name="summary">'
                 '<div class="actions"><button type="submit">作成</button></div>'
                 '</form>', wide=True)
    body += "</div>"
    return page("企画", body, "/projects")


def project_page(store: Store, project_id: str, message: str = "") -> str:
    data = store.project_overview(project_id)
    project, state = data["project"], data["state"]

    body = flash(message)
    body += f'<h2 class="page">{e(project["name"])} {status_badge(project["status"])}</h2>'
    body += f'<p class="lead">{e(project["summary"])}</p>'

    now_rows = [
        ["現在の工程", e(state["phase"]) if state else '<span class="dim">未設定</span>'],
        ["状態", status_badge(state["status"]) if state else "-"],
        ["担当", e(state["owner"]) if state and state["owner"] else "-"],
        ["前提となる工程", "、".join(e(d) for d in data["dependencies"]) or "-"],
    ]
    deliverables = "".join(f"<li>{e(d)}</li>"
                           for d in (state["deliverables"] if state else []))

    body += '<div class="grid">'
    body += card("いまの状況", table(["", ""], now_rows)
                 + (f"<ul>{deliverables}</ul>" if deliverables else ""))
    body += card("工程の履歴", table(
        ["工程", "状態", "担当"],
        [[e(p["phase"]), status_badge(p["status"]), e(p["owner"] or "-")]
         for p in data["phases"]], "まだ登録がありません"))
    body += card("決定事項", table(
        ["内容", "状態"],
        [[f'<b>{e(d["title"])}</b>'
          + (f'<div class="dim">{e(d["body"])}</div>' if d["body"] else ""),
          status_badge(d["status"])] for d in data["decisions"]]), wide=True)
    body += card("事実・制約", table(
        ["内容", "タグ"],
        [[e(f["body"]), " ".join(f'<span class="tag">{e(t)}</span>'
                                 for t in f["tags"])] for f in data["facts"]]))
    body += card("ハンドオフ", table(
        ["ファイル", "実ファイル"],
        [[f'{e(h["title"])}<div class="path">{e(h["file_path"])}</div>',
          file_flag(h["file_exists"])] for h in data["handoffs"]]))
    body += "</div>"

    body += ('<div style="margin-top:18px">'
             f'<a class="big" href="/project/{e(project_id)}/bundle">'
             '📦 ハンドオフをAIに渡す<span>本文をまとめて1つの文章にします</span></a>'
             f'<a class="big" href="/project/{e(project_id)}/intake">'
             '🧩 AIの回答を取り込む<span>工程表・決定事項として保存します</span></a>'
             '</div>')

    body += '<div class="grid" style="margin-top:18px">'
    body += card("決定事項を追加", _decision_form(project_id))
    body += card("工程を更新", _state_form(project_id))
    body += card("事実・制約を追加", _fact_form(project_id))
    body += "</div>"

    body += ('<div class="grid" style="margin-top:18px">' + card(
        "AIへ渡すコンテキスト",
        '<p class="dim">下のリンクを開いて、表示された文章をそのままAIチャットへ'
        '貼り付けてください。役割ごとに中身が変わります。</p>'
        + "".join(
            f'<p><a href="/preview/context/{e(a["id"])}?project={e(project_id)}">'
            f'{e(a["name"])} 用のコンテキストを見る</a></p>'
            for a in store.list_agents()), wide=True) + "</div>")
    return page(f"{project['name']} — 第二の脳", body)


def _hidden(project_id: str) -> str:
    return f'<input type="hidden" name="project" value="{e(project_id)}">'


def _decision_form(pid: str) -> str:
    return ('<form method="post" action="/api/decision">' + _hidden(pid) +
            "<label>決まったこと</label><input name=\"title\" required "
            'placeholder="例: CHANNELはパイプに見せない">'
            '<label>補足（任意）</label><textarea name="body" rows="3"></textarea>'
            '<div class="row"><div><label>状態</label>'
            '<select name="status"><option value="LOCKED">確定</option>'
            '<option value="PROPOSED">検討中</option>'
            '<option value="SUPERSEDED">破棄</option></select></div>'
            '<div><label>工程（任意）</label><input name="phase"></div></div>'
            '<div class="actions"><button type="submit">保存</button></div></form>')


def _state_form(pid: str) -> str:
    return ('<form method="post" action="/api/state">' + _hidden(pid) +
            '<label>いまの工程</label><input name="phase" required '
            'placeholder="例: GR-02 CHANNEL">'
            '<div class="row"><div><label>状態</label>'
            '<select name="status"><option value="IN_PROGRESS">作業中</option>'
            '<option value="COMPLETE">完了</option>'
            '<option value="BLOCKED">停止中</option>'
            '<option value="WAITING">待ち</option></select></div>'
            '<div><label>担当</label><input name="owner"></div></div>'
            '<label>成果物（1行に1つ）</label>'
            '<textarea name="deliverables" rows="3"></textarea>'
            '<div class="actions"><button type="submit">更新</button></div></form>')


def _fact_form(pid: str) -> str:
    return ('<form method="post" action="/api/fact">' + _hidden(pid) +
            '<label>事実・制約</label><input name="body" required '
            'placeholder="例: アセット総数は21で固定">'
            '<label>タグ（カンマ区切り・任意）</label>'
            '<input name="tags" placeholder="constraint, asset, world">'
            '<div class="actions"><button type="submit">追加</button></div></form>')


# ============================================================== 私について

def _profile_paste_form(text: str, category: str) -> str:
    return (
        '<form method="post" action="/ui/profile">'
        '<div class="row"><div><label>分類（任意）</label>'
        f'<input name="category" value="{e(category)}" '
        'placeholder="例: 進め方 / 環境 / 好み"></div></div>'
        '<label>AIの回答を貼り付け</label>'
        f'<textarea name="text" rows="10" placeholder="ここに貼り付け">{e(text)}</textarea>'
        '<div class="actions"><button type="submit" name="action" value="preview">'
        '内容を確認する</button></div></form>')


def _profile_preview(items: list[dict[str, Any]], category: str) -> str:
    checks = "".join(
        '<label style="margin:0 0 8px">'
        f'<input type="checkbox" name="item" value="{e(item["body"])}" checked '
        'style="width:auto;margin-right:8px">'
        f'{e(item["body"])}'
        + "".join(f'<span class="tag">{e(t)}</span>' for t in item["tags"])
        + "</label>"
        for item in items)
    return (
        '<p class="dim">不要な行（前置きの文など）はチェックを外してください。</p>'
        '<form method="post" action="/ui/profile">'
        f'<input type="hidden" name="category" value="{e(category)}">'
        + checks +
        '<div class="actions"><button type="submit" name="action" value="apply">'
        'この内容で保存する</button></div></form>')


def _profile_row(item: dict[str, Any]) -> list[str]:
    delete = (
        '<form method="post" action="/ui/profile/delete" '
        "onsubmit=\"return confirm('この項目を削除しますか？')\">"
        f'<input type="hidden" name="id" value="{e(item["id"])}">'
        '<button class="danger" type="submit">削除</button></form>')
    tags = "".join(f'<span class="tag">{e(t)}</span>' for t in item["tags"])
    return [e(item["body"]) + tags,
            e(item["category"]) or '<span class="dim">-</span>', delete]


def profile_page(store: Store, items: list[dict[str, Any]] | None = None,
                 text: str = "", category: str = "", message: str = "") -> str:
    """全AI共通の前提「私について」の管理画面。"""
    from .context import PROFILE_LIMIT
    saved = store.list_profile()

    body = flash(message)
    body += '<h2 class="page">私について</h2>'
    body += ('<p class="lead">企画に関係なく、どのAIにも毎回渡る前提です。'
             'ChatGPTやClaudeが覚えているあなたの情報を、ここへ集約できます。</p>')
    body += ('<div class="note"><b>取り出し方</b>: ChatGPTやClaudeにこう聞いてください。'
             '<br><code>私について記憶していることを、1行に1件ずつ、箇条書きで'
             '全部書き出してください。</code><br>'
             'その回答をそのまま下の枠に貼り付ければ取り込めます。<br><br>'
             '⚠️ パスワード・住所・口座番号などは入れないでください。'
             'ここに入れた内容は、あなたが使うすべてのAIへ渡ります。</div>')

    body += ('<div class="grid">'
             + card("貼り付けて取り込む", _profile_paste_form(text, category),
                    wide=True) + "</div>")

    if items:
        body += ('<div class="grid" style="margin-top:18px">'
                 + card(f"取り込む項目を選ぶ（{len(items)} 件）",
                        _profile_preview(items, category), wide=True) + "</div>")

    note = ""
    if len(saved) > PROFILE_LIMIT:
        note = (f'<p class="warn">※ AIへ渡るのは優先度の高い上位 {PROFILE_LIMIT} 件'
                f'です（現在 {len(saved)} 件登録）。</p>')
    body += ('<div class="grid" style="margin-top:18px">' + card(
        f"登録済み（{len(saved)} 件）",
        note + table(["内容", "分類", ""], [_profile_row(i) for i in saved],
                     "まだ登録がありません。上の枠に貼り付けてください。"),
        wide=True) + "</div>")

    if saved:
        export = "私について\\n" + "\\n".join(f"- {i['body']}" for i in saved)
        copy_js = ("var t=document.getElementById('profile-export');t.select();"
                   "document.execCommand('copy');this.textContent='コピーしました'")
        body += ('<div class="grid" style="margin-top:18px">' + card(
            "AIに渡す用（コピー）",
            '<p class="dim">新しいAIチャットを始めるとき、これを貼れば前提が揃います。'
            '</p>'
            '<textarea id="profile-export" rows="8" onclick="this.select()" readonly>'
            f'{e(export)}</textarea>'
            f'<div class="actions"><button type="button" onclick="{copy_js}">'
            '全部コピー</button></div>', wide=True) + "</div>")
    return page("私について", body, "/profile")


# ================================================================ AI設定

def bundle_page(store: Store, project_id: str, result: dict[str, Any] | None = None,
                selected: set[str] | None = None) -> str:
    """ハンドオフ本文をまとめてAIへ渡すための画面。"""
    project = store.require_project(project_id)
    handoffs = store.list_handoffs(project_id)
    selected = selected if selected is not None else {h["id"] for h in handoffs}

    body = f'<h2 class="page">{e(project["name"])} — ハンドオフをAIに渡す</h2>'
    body += ('<p class="lead">選んだハンドオフの本文を読み込んで、1つの文章にまとめます。'
             'それをAIチャットに貼り付けると、工程表と決定事項が返ってきます。</p>')
    body += ('<div class="note">本文は<b>この画面で読み出すだけ</b>で、第二の脳には'
             '保存しません。保存するのは、AIが出した工程と決定事項だけです。<br>'
             '.md .txt .csv .json .docx は読めます。.pdf は読めないので除外されます。'
             '</div>')

    checks = "".join(
        f'<label style="margin:0 0 6px"><input type="checkbox" name="handoff" '
        f'value="{e(h["id"])}" style="width:auto;margin-right:8px"'
        f'{" checked" if h["id"] in selected else ""}> {e(h["title"])}'
        f'<span class="dim"> — {e(h["phase"] or "工程不明")}</span>'
        f'<div class="path">{e(h["file_path"])}</div></label>'
        for h in handoffs)
    form = (f'<form method="post" action="/project/{e(project_id)}/bundle">'
            + (checks or '<p class="empty">このハンドオフがまだありません。'
                         '「取り込み」画面で登録してください。</p>')
            + '<div class="actions"><button type="submit">'
              'この内容でまとめる</button></div></form>')
    body += '<div class="grid">' + card(f"対象を選ぶ（{len(handoffs)} 件）", form,
                                        wide=True) + "</div>"

    if result:
        rows = [["まとめた文字数", f"{result['chars']:,} 文字"
                 f"（およそ {result['approx_tokens']:,} トークン）"],
                ["含めたファイル", f"{len(result['included'])} 件"],
                ["除外したファイル", f"{len(result['skipped'])} 件"]]
        summary = table(["項目", "内容"], rows)
        if result["skipped"]:
            summary += table(["除外したファイル", "理由"],
                             [[e(x["title"]), e(x["reason"])]
                              for x in result["skipped"]])
        body += ('<div class="grid" style="margin-top:18px">'
                 + card("結果", summary, wide=True) + "</div>")
        body += ('<div class="grid" style="margin-top:18px">' + card(
            "AIに貼り付ける内容",
            '<p class="dim">枠の中をクリックすると全選択されます。'
            'コピーして、ChatGPTやClaudeの新しいチャットに貼り付けてください。</p>'
            f'<textarea id="bundle" rows="18" onclick="this.select()" readonly>'
            f'{e(result["text"])}</textarea>'
            '<div class="actions">'
            '<button type="button" onclick="var t=document.getElementById(\'bundle\');'
            't.select();document.execCommand(\'copy\');'
            'this.textContent=\'コピーしました\'">全部コピー</button> '
            f'<a href="/project/{e(project_id)}/intake" style="margin-left:14px">'
            '→ AIの回答を取り込む</a></div>', wide=True) + "</div>")
    return page(f"{project['name']} — AIに渡す", body)


def intake_page(store: Store, project_id: str, text: str = "",
                parsed: dict[str, Any] | None = None, written: dict[str, int] | None
                = None) -> str:
    """AIが返した工程表を取り込む画面（貼り付け → 確認 → 保存）。"""
    project = store.require_project(project_id)
    body = f'<h2 class="page">{e(project["name"])} — AIの回答を取り込む</h2>'
    body += ('<p class="lead">AIが出した工程表・決定事項を貼り付けてください。'
             '内容を確認してから保存します。</p>')

    if written:
        body = flash(
            f"保存しました: 工程 {written['phases']} 件 / 決定事項 "
            f"{written['decisions']} 件 / 事実 {written['facts']} 件 / "
            f"依存 {written['depends']} 件 / 未決 {written['opens']} 件") + body

    body += ('<div class="note">読み取れる書式:<br>'
             '<code>PHASE: 工程名 | 状態 | 担当 | 成果物</code><br>'
             '<code>DECISION: 決まったこと | 補足</code><br>'
             '<code>FACT: 前提や制約 | タグ</code><br>'
             '<code>DEPENDS: 後の工程 -&gt; 先に必要な工程</code><br>'
             '<code>OPEN: まだ決まっていないこと</code><br>'
             'それ以外の行は無視されます（説明文が混じっていても大丈夫です）。</div>')

    body += '<div class="grid">' + card("AIの回答を貼り付ける",
        f'<form method="post" action="/project/{e(project_id)}/intake">'
        f'<textarea name="text" rows="14" placeholder="ここに貼り付け">{e(text)}</textarea>'
        '<div class="actions"><button type="submit" name="action" value="preview">'
        '内容を確認する</button></div></form>', wide=True) + "</div>"

    if parsed:
        phase_rows = [[e(p["phase"]), status_badge(p["status"]), e(p["owner"] or "-"),
                       "、".join(e(d) for d in p["deliverables"]) or "-"]
                      for p in parsed["phases"]]
        blocks = card("工程表", table(["工程", "状態", "担当", "成果物"], phase_rows),
                      wide=True)
        blocks += card("決定事項", table(
            ["内容", "補足"],
            [[e(d["title"]), e(d["body"])] for d in parsed["decisions"]]))
        blocks += card("事実・制約", table(
            ["内容", "タグ"],
            [[e(f["body"]), "、".join(e(t) for t in f["tags"])]
             for f in parsed["facts"]]))
        blocks += card("依存関係", table(
            ["工程", "先に必要"],
            [[e(d["src"]), e(d["dst"])] for d in parsed["depends"]]))
        blocks += card("まだ決まっていないこと", table(
            ["内容"], [[e(o["title"])] for o in parsed["opens"]]))
        if parsed["unknown"]:
            blocks += card("読み飛ばした行", table(
                ["内容"], [[e(u)] for u in parsed["unknown"][:20]]))
        body += ('<div class="grid" style="margin-top:18px">' + blocks + "</div>")

        total = sum(len(parsed[k]) for k in
                    ("phases", "decisions", "facts", "depends", "opens"))
        body += ('<div class="grid" style="margin-top:18px">' + card(
            "保存",
            f'<p>{total} 件を第二の脳へ保存します。よろしいですか？</p>'
            f'<form method="post" action="/project/{e(project_id)}/intake">'
            f'<input type="hidden" name="text" value="{e(text)}">'
            '<div class="actions"><button type="submit" name="action" value="apply">'
            'この内容で保存する</button></div></form>', wide=True) + "</div>")
    return page(f"{project['name']} — 回答の取り込み", body)


def agents_page(store: Store) -> str:
    body = '<h2 class="page">AI設定</h2>'
    body += ('<p class="lead">同じ企画でも、AIごとに<b>見せる情報と評価軸を変えます</b>。'
             '確定した事実は全員に共有し、考え方は共有しません。</p>')
    body += '<div class="grid">'
    for profile in store.list_role_profiles():
        agents = [a for a in store.list_agents()
                  if a["context_profile"] == profile["id"]]
        rows = [
            ["目的", e(profile["goal"])],
            ["優先", e(profile["priority"])],
            ["見せる情報", " ".join(f'<span class="tag">{e(v)}</span>'
                                    for v in profile["visible_context"]) or "-"],
            ["見せない情報", " ".join(f'<span class="tag dim">{e(v)}</span>'
                                      for v in profile["hidden_context"]) or "-"],
            ["評価軸", "、".join(e(v) for v in profile["evaluation_axes"]) or "-"],
            ["禁止", '<span class="bad">'
             + "、".join(e(v) for v in profile["prohibitions"]) + "</span>"],
            ["コンテキスト", ", ".join(
                f'<a href="/preview/context/{e(a["id"])}">{e(a["name"])}</a>'
                for a in agents) or "-"],
        ]
        body += card(f'{profile["name"]}（{profile["id"]}）', table(["", ""], rows))
    body += "</div>"
    return page("AI設定", body, "/agents")


def context_page(store: Store, result: dict[str, Any]) -> str:
    tokens = result["token_estimate"]
    cls = "ok" if tokens <= result["token_budget"] else "bad"
    body = f'<h2 class="page">{e(result["role_name"])} 用のコンテキスト</h2>'
    body += (f'<p class="lead">企画: {e(result["project"])} ／ '
             f'<span class="{cls}">約 {tokens} トークン</span>'
             f'（上限 {e(result["token_budget"])}）</p>')
    body += ('<div class="note">この枠の中身をコピーして、AIチャットの最初に'
             '貼り付けてください。役割が違えば中身も変わります。</div>')
    body += (f'<pre style="background:#0b0f14;border:1px solid var(--line);'
             f'border-radius:8px;padding:16px;white-space:pre-wrap;'
             f'word-break:break-word">{e(result["text"])}</pre>')
    return page(f"コンテキスト（{result['role']}）", body)


def login_page(failed: bool) -> str:
    warn = '<p class="bad">APIキーが違います。</p>' if failed else ""
    body = '<div class="grid">' + card(
        "ログイン", warn + '<form method="get" action="/login">'
        '<label>APIキー</label><input name="key" type="password" required>'
        '<div class="actions"><button type="submit">入る</button></div></form>'
    ) + "</div>"
    return page("ログイン", body)


def error_page(status: int, message: str) -> str:
    return page(str(status), '<div class="grid">' + card(
        f"エラー {status}", f'<p class="bad">{escape(message)}</p>'
        '<p><a href="/">← ダッシュボードに戻る</a></p>') + "</div>")
