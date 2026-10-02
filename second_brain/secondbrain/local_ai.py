"""ローカルAI（Ollama / LM Studio など）を第二の脳につないで育てる。

育てる、とは重みを学習させることではなく、次の循環を回すこと:

    1. 話す   — 第二の脳の確定情報を前提にして、手元のモデルと会話する
    2. 学ぶ   — 会話から「残すべき結論」だけをモデル自身に抜き出させる
    3. 蓄える — 確認したうえで決定事項・事実・私についてへ保存する
    4. 育つ   — 蓄えた内容を焼き込んだ専用モデルを作り直す（Ollama）

会話の全文は保存しない（第二の脳の原則どおり）。残るのは結論だけで、
それが次の会話と次のモデルの前提になる。

通信は標準ライブラリの urllib のみ。ローカル宛てなのでプロキシは使わない。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .context import ContextRouter, estimate_tokens
from .store import Store, now

DEFAULT_URL = "http://127.0.0.1:11434"
DEFAULT_MODEL_NAME = "second-brain"
#: Ollama の既定コンテキスト長は小さいので、第二の脳を載せられる長さに広げる。
NUM_CTX = 8192
#: モデルへ焼き込む知識の上限（会話に使う余白を残す）。
PERSONA_BUDGET = 3000
#: 画面に持ち回す会話の上限（古いものから捨てる）。
HISTORY_LIMIT = 20

#: 画面から1クリックで入れられるモデル（Ollama のモデル名, 表示名, 説明）。
RECOMMENDED: list[tuple[str, str, str]] = [
    ("llama3.2:3b", "Llama 3.2 3B", "軽い（約2GB）。ノートPCやGPUなしでも動く"),
    ("llama3.1:8b", "Llama 3.1 8B", "標準（約4.9GB）。GPUメモリ8GB以上がおすすめ"),
    ("hf.co/elyza/Llama-3-ELYZA-JP-8B-GGUF", "Llama 3 ELYZA JP 8B",
     "日本語を追加学習したLlama（約4.9GB）。日本語の受け答えが自然"),
]
#: モデルの取得は数GBのダウンロードになるので長めに待つ。
PULL_TIMEOUT = 3600

SETTINGS_KEY = "local_ai"
GROWTH_KEY = "local_ai_growth"

Transport = Callable[[str, str, "dict[str, Any] | None", float], Any]


class LocalAIError(Exception):
    """ローカルAIへ届かない・返事が読めないとき。画面にそのまま出す文言を持つ。"""


# ================================================================== 設定

@dataclass
class Settings:
    #: Ollama なら http://127.0.0.1:11434、LM Studio なら http://127.0.0.1:1234/v1
    url: str = DEFAULT_URL
    #: 会話に使うモデル。空なら育てたモデル、それも無ければ元のモデル。
    model: str = ""
    #: 育てる元になるモデル（例: qwen2.5:7b, gemma3:4b）。
    base_model: str = ""
    #: 育てたモデルの名前。
    name: str = DEFAULT_MODEL_NAME

    @property
    def kind(self) -> str:
        """URL が /v1 で終われば OpenAI 互換、それ以外は Ollama とみなす。"""
        return "openai" if self.url.rstrip("/").endswith("/v1") else "ollama"

    def chat_model(self, grown: bool = False) -> str:
        """指定が無ければ、育てたモデル（一度でも育てていれば）→ 元のモデル。"""
        if self.model:
            return self.model
        if grown and self.kind == "ollama":
            return self.name
        return self.base_model


def load_settings(store: Store) -> Settings:
    """保存済みの設定 → 環境変数 → 既定値 の順に埋める。"""
    saved = store.get_meta(SETTINGS_KEY, {}) or {}
    env = {
        "url": os.environ.get("SECOND_BRAIN_LOCAL_AI_URL", ""),
        "model": os.environ.get("SECOND_BRAIN_LOCAL_AI_MODEL", ""),
        "base_model": os.environ.get("SECOND_BRAIN_LOCAL_AI_BASE", ""),
    }
    settings = Settings()
    for key in ("url", "model", "base_model", "name"):
        value = str(saved.get(key) or env.get(key) or "").strip()
        if value:
            setattr(settings, key, value)
    return settings


def save_settings(store: Store, settings: Settings) -> Settings:
    settings.url = settings.url.strip().rstrip("/") or DEFAULT_URL
    settings.name = settings.name.strip() or DEFAULT_MODEL_NAME
    store.set_meta(SETTINGS_KEY, asdict(settings))
    return settings


# ================================================================== 通信

def _urllib_transport(method: str, url: str, payload: dict[str, Any] | None,
                      timeout: float) -> Any:
    data = None
    headers = {"Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data, headers, method=method)
    # 宛先は手元かLAN内なので、社内プロキシ等を経由させない。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8") or "null")


class LocalAI:
    """Ollama と OpenAI 互換サーバー（LM Studio / llama.cpp）の薄い窓口。"""

    def __init__(self, settings: Settings, transport: Transport | None = None,
                 timeout: float = 600, grown: bool = False):
        self.settings = settings
        self.transport = transport or _urllib_transport
        self.timeout = timeout
        #: 一度でも育てていれば、会話には育てたモデルを使う。
        self.grown = grown

    @classmethod
    def from_store(cls, store: Store, transport: Transport | None = None
                   ) -> "LocalAI":
        settings = load_settings(store)
        grown = any(g.get("name") == settings.name for g in growth_log(store))
        return cls(settings, transport, grown=grown)

    def _call(self, method: str, path: str, payload: dict[str, Any] | None = None,
              timeout: float | None = None) -> Any:
        url = self.settings.url.rstrip("/") + path
        try:
            return self.transport(method, url, payload, timeout or self.timeout)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001 - 本文が読めなくても理由は出す
                pass
            raise LocalAIError(f"ローカルAIがエラーを返しました（{exc.code}）: "
                               f"{detail or exc.reason}") from exc
        except (urllib.error.URLError, OSError) as exc:
            hint = ("Ollama を起動してください（タスクトレイのアイコン、"
                    "または ollama serve）。" if self.settings.kind == "ollama"
                    else "LM Studio などでサーバーを開始してください。")
            raise LocalAIError(f"ローカルAIに接続できません（{self.settings.url}）。"
                               f"{hint}") from exc
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise LocalAIError("ローカルAIの返事を読み取れませんでした。"
                               "URLが正しいか確認してください。") from exc

    # -- 状態 ---------------------------------------------------------------

    def models(self) -> list[str]:
        if self.settings.kind == "ollama":
            data = self._call("GET", "/api/tags", timeout=5) or {}
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        data = self._call("GET", "/models", timeout=5) or {}
        return [m.get("id", "") for m in data.get("data", []) if m.get("id")]

    def status(self) -> dict[str, Any]:
        """画面用。届かなくても例外にせず理由を返す。"""
        try:
            models = self.models()
        except LocalAIError as exc:
            return {"ok": False, "error": str(exc), "models": []}
        return {"ok": True, "error": "", "models": models}

    # -- 会話 ---------------------------------------------------------------

    def chat(self, messages: list[dict[str, str]], model: str | None = None) -> str:
        model = model or self.settings.chat_model(self.grown)
        if not model:
            raise LocalAIError("使うモデルが決まっていません。"
                               "設定で「元のモデル」を選んでください。")
        if self.settings.kind == "ollama":
            data = self._call("POST", "/api/chat", {
                "model": model, "messages": messages, "stream": False,
                "options": {"num_ctx": NUM_CTX}}) or {}
            text = (data.get("message") or {}).get("content", "")
        else:
            data = self._call("POST", "/chat/completions", {
                "model": model, "messages": messages, "stream": False}) or {}
            choices = data.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content", "")
        if data.get("error"):
            raise LocalAIError(f"ローカルAIがエラーを返しました: {data['error']}")
        return strip_thinking(text).strip()

    # -- 育成 ---------------------------------------------------------------

    def pull(self, model: str) -> None:
        """Ollama にモデルを取得させる（すでにあれば差分だけ）。"""
        if self.settings.kind != "ollama":
            raise LocalAIError("モデルの取得は Ollama のときだけです。"
                               "LM Studio では画面からモデルを入れてください。")
        model = model.strip()
        if not model:
            raise LocalAIError("取得するモデルを選んでください。")
        data = self._call("POST", "/api/pull", {"model": model, "stream": False},
                          timeout=PULL_TIMEOUT) or {}
        if data.get("error"):
            raise LocalAIError(f"{model} を取得できませんでした: {data['error']}")

    def create_model(self, name: str, base: str, system: str) -> None:
        """第二の脳を焼き込んだモデルを Ollama に作る（同名なら作り直す）。"""
        if self.settings.kind != "ollama":
            raise LocalAIError("モデルを作り直せるのは Ollama のときだけです。"
                               "LM Studio では「会話」と「学び」をお使いください。")
        if not base:
            raise LocalAIError("育てる元のモデルを選んでください。")
        data = self._call("POST", "/api/create", {
            "model": name, "from": base, "system": system,
            "parameters": {"num_ctx": NUM_CTX}, "stream": False}) or {}
        if data.get("error"):
            raise LocalAIError(f"モデルを作れませんでした: {data['error']}")


def strip_thinking(text: str) -> str:
    """推論モデルが出す <think>…</think> は結論ではないので落とす。"""
    while "<think>" in text and "</think>" in text:
        head, _, rest = text.partition("<think>")
        _, _, tail = rest.partition("</think>")
        text = head + tail
    return text


# ================================================================ 文章の組み立て

CHAT_RULES = """あなたは依頼主のPCの中で動くローカルAIです。
下にあるのは「第二の脳」に登録された、この企画の確定情報です。

- ここに書かれていることは事実として扱う
- ここに無いことを言うときは「推測ですが」と前置きする
- 確定事項と食い違う提案をするときは、どの確定事項とぶつかるかを明示する
- 日本語で、短く、次に何をすればよいかが分かるように答える"""

REFLECT_PROMPT = """ここまでの会話を振り返り、今後も残すべき「結論」だけを抜き出してください。
会話の要約・感想・あいさつは不要です。上の確定情報にすでにあることも書かないでください。

出力は次の形式の行だけにしてください（当てはまるものだけ。説明文は付けない）。

DECISION: 会話の中で決まったこと | 補足
FACT: 新しく分かった前提や制約 | タグをカンマ区切り
OPEN: まだ決まっていないこと
PHASE: 工程名 | 状態(未着手/作業中/完了/停止中) | 担当 | 成果物をセミコロン区切り
PROFILE: 依頼主本人について分かったこと（好み・進め方・避けたいこと） | 分類

残すべきことが何も無ければ「なし」とだけ書いてください。"""


def chat_system_prompt(router: ContextRouter, role: str = "local",
                       project: str | None = None) -> str:
    try:
        context = router.build(role, project)["text"]
    except Exception:  # noqa: BLE001 - 企画が無くても会話はできる
        profile = router.store.list_profile(limit=12)
        context = "\n".join(["ABOUT THE USER"] + [f"- {p['body']}" for p in profile]
                            ) if profile else "(まだ何も登録されていません)"
    return f"{CHAT_RULES}\n\n----- 第二の脳 -----\n{context}"


def trim_history(history: list[dict[str, str]]) -> list[dict[str, str]]:
    clean = [{"role": m["role"], "content": str(m.get("content", ""))}
             for m in history
             if isinstance(m, dict) and m.get("role") in ("user", "assistant")]
    return clean[-HISTORY_LIMIT:]


def parse_history(raw: str) -> list[dict[str, str]]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    return trim_history(data) if isinstance(data, list) else []


def converse(ai: LocalAI, router: ContextRouter, history: list[dict[str, str]],
             message: str, role: str = "local", project: str | None = None
             ) -> list[dict[str, str]]:
    """1往復進めて、新しい会話履歴を返す（保存はしない）。"""
    history = trim_history(history) + [{"role": "user", "content": message}]
    messages = [{"role": "system",
                 "content": chat_system_prompt(router, role, project)}] + history
    answer = ai.chat(messages)
    return trim_history(history + [{"role": "assistant", "content": answer}])


def reflect(ai: LocalAI, router: ContextRouter, history: list[dict[str, str]],
            role: str = "local", project: str | None = None) -> str:
    """会話から残すべき結論を取り込み書式で書かせる。"""
    history = trim_history(history)
    if not history:
        raise LocalAIError("まだ会話がありません。先に話しかけてください。")
    messages = ([{"role": "system",
                  "content": chat_system_prompt(router, role, project)}]
                + history + [{"role": "user", "content": REFLECT_PROMPT}])
    return ai.chat(messages)


# ================================================================== 育成

PERSONA_HEAD = """あなたは「第二の脳」で育てられた、依頼主専属のローカルAIです。
以下は依頼主と一緒に確定させてきた知識です。これを前提に、依頼主の進め方に合わせて答えてください。
ここに無いことは推測だと明示し、確定事項と食い違う提案をするときはその旨を伝えてください。"""


def knowledge_counts(store: Store) -> dict[str, int]:
    projects = store.list_projects()
    return {
        "profile": len(store.list_profile()),
        "projects": len(projects),
        "decisions": sum(len(store.list_decisions(p["id"], "LOCKED"))
                         for p in projects),
        "facts": sum(len(store.list_facts(p["id"])) for p in projects),
    }


def build_persona(store: Store, budget: int = PERSONA_BUDGET) -> str:
    """モデルに焼き込む知識。長すぎれば企画ごとの件数を絞って収める。"""
    for per_project in (8, 5, 3, 1, 0):
        text = _persona(store, per_project)
        if estimate_tokens(text) <= budget:
            return text
    return text[: budget]


def _persona(store: Store, per_project: int) -> str:
    lines = [PERSONA_HEAD]
    profile = store.list_profile(limit=40)
    if profile:
        lines += ["", "## 依頼主について"] + [f"- {p['body']}" for p in profile]

    projects = (store.list_projects(status="ACTIVE") or store.list_projects())
    if projects:
        lines += ["", "## 進行中の企画"]
    for project in projects:
        state = store.current_state(project["id"])
        head = f"### {project['name']}"
        if state:
            head += f"（現在: {state['phase']}）"
        lines += ["", head]
        if project["summary"]:
            lines.append(project["summary"])
        if not per_project:
            continue
        locked = store.list_decisions(project["id"], "LOCKED")[-per_project:]
        lines += [f"- 決定: {d['title']}" for d in locked]
        facts = store.list_facts(project["id"])[-per_project:]
        lines += [f"- 事実: {f['body']}" for f in facts]
    return "\n".join(lines)


def modelfile(base: str, system: str) -> str:
    """手で `ollama create` したい人向けの Modelfile。"""
    safe = system.replace('"""', "”””")
    return (f"FROM {base}\n"
            f"PARAMETER num_ctx {NUM_CTX}\n"
            f'SYSTEM """{safe}"""\n')


def has_model(models: list[str], name: str) -> bool:
    """Ollama は "llama3.2:3b" を、タグ省略なら ":latest" 付きで返す。"""
    return name in models or f"{name}:latest" in models


def install_model(ai: LocalAI, store: Store, model: str) -> Settings:
    """モデルを取得し、育てる元のモデルとして設定する。"""
    ai.pull(model)
    settings = ai.settings
    settings.base_model = model.strip()
    return save_settings(store, settings)


def growth_log(store: Store) -> list[dict[str, Any]]:
    return list(store.get_meta(GROWTH_KEY, []) or [])


def grow(ai: LocalAI, store: Store) -> dict[str, Any]:
    """いまの第二の脳を焼き込んでモデルを作り直し、成長記録に1行足す。"""
    settings = ai.settings
    persona = build_persona(store)
    ai.create_model(settings.name, settings.base_model, persona)
    ai.grown = True
    log = growth_log(store)
    entry = {"at": now(), "name": settings.name, "base": settings.base_model,
             "tokens": estimate_tokens(persona), **knowledge_counts(store)}
    store.set_meta(GROWTH_KEY, (log + [entry])[-50:])
    store.log_change("local_ai", settings.name, "grown",
                     f"{settings.base_model} → {settings.name}", actor="local-ai")
    store.conn.commit()
    return entry


# ================================================================== 学び

def parse_learning(text: str) -> dict[str, Any]:
    """reflect の出力を取り込み書式として読む。「なし」なら空。"""
    from .intake import parse_bulk
    return parse_bulk(text)


def learning_total(bulk: dict[str, Any]) -> int:
    return (bulk["unassigned_total"] + len(bulk["profile"])
            + sum(p["total"] for p in bulk["projects"]))


def apply_learning(store: Store, text: str, project_id: str = "") -> dict[str, Any]:
    """確認済みの学びを保存する。企画の指定が無い行は、話していた企画へ入れる。"""
    from .intake import apply_bulk, apply_result
    bulk = parse_learning(text)
    result = apply_bulk(store, bulk, actor="local-ai")
    if project_id and bulk["unassigned_total"]:
        written = apply_result(store, project_id, bulk["unassigned"],
                               actor="local-ai")
        result["projects"].append({"project": project_id, "name": project_id,
                                   "written": written})
        result["total"] += sum(written.values())
    return result
