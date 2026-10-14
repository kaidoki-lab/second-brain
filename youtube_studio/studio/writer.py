"""企画と台本をAIに書かせる。

書き手は2種類から選ぶ（channel.json の writer.backend）:

- ``ollama``  手元のローカルAI（第二の脳で育てた ``second-brain`` モデルなど）。無料
- ``claude``  Claude API。台本の質を上げたいとき。``ANTHROPIC_API_KEY`` が必要

どちらも「JSONだけを返す」約束で呼び、受け取ったら必ず形を検査する。
形が崩れていたら理由を添えて1回だけ書き直させる。

収益化の審査（YouTube パートナープログラム）では、量産・使い回しの動画は
収益化の対象外になる。台本には「このチャンネルならではの視点」と
「人が確かめるべき点（checks）」を必ず書かせ、承認画面で人が確かめる。
"""

from __future__ import annotations

import json
import re
import urllib.request
from typing import Any, Callable, Protocol

#: 日本語の読み上げ速度の目安（VOICEVOX 話速1.1で1分あたりの文字数）。
CHARS_PER_MINUTE = 330


class WriterError(Exception):
    """書き手に届かない・返事が使えないとき。"""


class LLM(Protocol):
    def complete(self, system: str, user: str) -> str: ...


# ================================================================== 書き手

Transport = Callable[[str, dict[str, Any], float], dict[str, Any]]


def _post_json_local(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    # ローカル宛てなのでプロキシを通さない。
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, json.dumps(payload).encode("utf-8"),
                                 {"Content-Type": "application/json"})
    with opener.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


class OllamaWriter:
    def __init__(self, url: str, model: str, transport: Transport | None = None):
        self.url = url.rstrip("/")
        self.model = model
        self.transport = transport or _post_json_local

    def complete(self, system: str, user: str) -> str:
        payload = {"model": self.model, "stream": False, "format": "json",
                   "options": {"num_ctx": 8192},
                   "messages": [{"role": "system", "content": system},
                                {"role": "user", "content": user}]}
        try:
            data = self.transport(self.url + "/api/chat", payload, 900)
        except OSError as exc:
            raise WriterError(
                f"ローカルAI（{self.url}）に届きません。Ollama が起動しているか、"
                f"モデル {self.model} が入っているか確かめてください（{exc}）") from exc
        return str(data.get("message", {}).get("content", ""))


class ClaudeWriter:
    def __init__(self, model: str = "claude-opus-5-5", effort: str = "high",
                 client: Any = None):
        self.model = model
        self.effort = effort
        self._client = client

    def client(self) -> Any:
        if self._client is None:
            try:
                import anthropic
            except ImportError as exc:
                raise WriterError("Claude を使うには `pip install anthropic` が必要です") from exc
            self._client = anthropic.Anthropic()
        return self._client

    def complete(self, system: str, user: str) -> str:
        import anthropic
        try:
            response = self.client().beta.messages.create(
                model=self.model,
                max_tokens=16000,
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
                output_config={"effort": self.effort},
                system=system,
                messages=[{"role": "user", "content": user}],
            )
        except anthropic.AuthenticationError as exc:
            raise WriterError("Claude APIキーが無効です（ANTHROPIC_API_KEY）") from exc
        except anthropic.RateLimitError as exc:
            raise WriterError("Claude APIの利用上限に達しました。時間をおいて再実行してください") from exc
        except anthropic.APIStatusError as exc:
            raise WriterError(f"Claude APIエラー（{exc.status_code}）: {exc.message}") from exc
        except anthropic.APIConnectionError as exc:
            raise WriterError("Claude APIに接続できません") from exc
        if response.stop_reason == "refusal":
            raise WriterError("この企画は Claude に断られました。企画を変えてください")
        return "".join(b.text for b in response.content if b.type == "text")


def make_writer(cfg: dict[str, Any]) -> LLM:
    w = cfg["writer"]
    if w.get("backend") == "claude":
        return ClaudeWriter(w.get("claude_model", "claude-opus-5-5"),
                            w.get("claude_effort", "high"))
    return OllamaWriter(w.get("ollama_url", "http://127.0.0.1:11434"),
                        w.get("ollama_model", "second-brain"))


# ================================================================== JSON

def extract_json(text: str) -> Any:
    """返事からJSONを取り出す。```json の囲みや前置きがあっても読む。"""
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fenced:
        text = fenced.group(1)
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        raise WriterError("返事にJSONがありません")
    start = min(starts)
    end = max(text.rfind("}"), text.rfind("]"))
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as exc:
        raise WriterError(f"返事のJSONが壊れています: {exc}") from exc


def ask_json(llm: LLM, system: str, user: str,
             check: Callable[[Any], Any]) -> Any:
    """JSONで答えさせ、check で検査する。だめなら理由を添えて1回だけやり直す。"""
    reply = llm.complete(system, user)
    try:
        return check(extract_json(reply))
    except WriterError as first:
        retry = (user + "\n\n# 前回の返事の問題\n" + str(first)
                 + "\n問題を直して、指定どおりのJSONだけを返してください。")
        return check(extract_json(llm.complete(system, retry)))


# ================================================================== 共通の前提

def channel_brief(cfg: dict[str, Any]) -> str:
    ch = cfg["channel"]
    lines = [
        f"チャンネル名: {ch.get('name') or '（未定）'}",
        f"テーマ: {ch['theme']}",
        f"視聴者: {ch['audience']}",
    ]
    if ch.get("promise"):
        lines.append(f"視聴者への約束（見ると得られるもの）: {ch['promise']}")
    lines.append(f"話し方: {ch.get('tone', '')}")
    if ch.get("forbidden"):
        lines.append("禁止: " + " / ".join(ch["forbidden"]))
    return "\n".join(lines)


def learning_brief(memory: dict[str, Any], published: list[dict[str, Any]],
                   brain_context: str = "") -> str:
    parts: list[str] = []
    stats = memory.get("stats", {})
    if stats:
        ranked = sorted(stats.values(), key=lambda s: s.get("views", 0), reverse=True)
        top = [f"- {s['title']}（再生 {s.get('views', 0)}）" for s in ranked[:5]]
        low = [f"- {s['title']}（再生 {s.get('views', 0)}）" for s in ranked[-3:]
               if s not in ranked[:5]]
        parts.append("# よく見られた動画\n" + "\n".join(top))
        if low:
            parts.append("# 伸びなかった動画\n" + "\n".join(low))
    if published:
        parts.append("# 作成済みの企画（重複させない）\n"
                     + "\n".join(f"- {p['title']}" for p in published[-40:]))
    if memory.get("feedback"):
        parts.append("# 運営者からの指摘（必ず守る）\n"
                     + "\n".join(f"- {f['text']}" for f in memory["feedback"][-15:]))
    if brain_context.strip():
        parts.append("# 第二の脳にある確定事実（引用してよい事実はこれだけ）\n"
                     + brain_context.strip())
    return "\n\n".join(parts)


SYSTEM = """あなたはYouTubeチャンネルの構成作家です。
目的は、視聴者が最後まで見て「得した」と感じ、次の動画も見たくなる動画を作ることです。
YouTubeの収益化審査では、量産型・使い回し・中身の薄い動画は収益化されません。
必ずこのチャンネルならではの視点・整理・具体例を入れてください。
確かでない数字や出来事を作ってはいけません。確かめが必要な主張は checks に書き出してください。
返事は指定されたJSONだけを返し、前置きや説明は書かないでください。"""


# ================================================================== 企画

def _check_topics(data: Any) -> list[dict[str, Any]]:
    items = data.get("topics") if isinstance(data, dict) else data
    if not isinstance(items, list) or not items:
        raise WriterError('{"topics": [...]} の形で企画を返してください')
    out = []
    for item in items:
        if not isinstance(item, dict) or not str(item.get("title", "")).strip():
            raise WriterError("各企画には title が必要です")
        out.append({"title": str(item["title"]).strip(),
                    "angle": str(item.get("angle", "")).strip(),
                    "why": str(item.get("why", "")).strip(),
                    "search_phrase": str(item.get("search_phrase", "")).strip()})
    return out


def plan_topics(llm: LLM, cfg: dict[str, Any], memory: dict[str, Any],
                published: list[dict[str, Any]], brain_context: str = "",
                count: int = 5) -> list[dict[str, Any]]:
    user = f"""# チャンネル
{channel_brief(cfg)}

{learning_brief(memory, published, brain_context)}

# 依頼
次に作る動画の企画を{count}本考えてください。
- 視聴者が実際に検索する・気になる問いから出発する
- 伸びた動画の型を活かし、伸びなかった型は避ける
- 作成済みと同じ企画は出さない
- 1本で1つの問いに答え切れる大きさにする

# 返す形
{{"topics": [{{"title": "動画タイトル案（32文字以内）",
  "angle": "このチャンネルならではの切り口",
  "why": "なぜ今この視聴者に刺さるか",
  "search_phrase": "視聴者が検索しそうな言葉"}}]}}"""
    return _check_topics(ask_json(llm, SYSTEM, user, _check_topics))[:count]


# ================================================================== 台本

def narration_chars(script: dict[str, Any]) -> int:
    body = [script.get("hook", ""), script.get("outro", "")]
    body += [s.get("narration", "") for s in script.get("sections", [])]
    return sum(len(t) for t in body)


def check_script(data: Any, minutes: float) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise WriterError("台本はJSONオブジェクトで返してください")
    for key in ("title", "hook", "sections", "description", "thumbnail_text"):
        if not data.get(key):
            raise WriterError(f"台本に {key} がありません")
    sections = data["sections"]
    if not isinstance(sections, list) or len(sections) < 2:
        raise WriterError("sections は2つ以上にしてください")
    for i, s in enumerate(sections, 1):
        if not isinstance(s, dict) or not s.get("heading") or not s.get("narration"):
            raise WriterError(f"sections の{i}番目に heading と narration が必要です")
        points = s.get("points") or []
        s["points"] = [str(p) for p in points][:4] if isinstance(points, list) else []
    need = int(minutes * CHARS_PER_MINUTE * 0.7)
    have = narration_chars(data)
    if have < need:
        raise WriterError(f"読み上げ原稿が短すぎます（{have}文字。{need}文字以上必要）")
    short = data.get("short")
    if not isinstance(short, dict) or not short.get("narration"):
        data["short"] = {"title": data["title"], "narration": data["hook"]}
    data["short"]["narration"] = str(data["short"]["narration"])[:CHARS_PER_MINUTE]
    data["title"] = str(data["title"])[:100]
    data["tags"] = [str(t) for t in data.get("tags", []) if str(t).strip()][:15]
    data["checks"] = [str(c) for c in data.get("checks", []) if str(c).strip()]
    data["outro"] = str(data.get("outro", ""))
    return data


def write_script(llm: LLM, cfg: dict[str, Any], topic: dict[str, Any],
                 memory: dict[str, Any], published: list[dict[str, Any]],
                 brain_context: str = "") -> dict[str, Any]:
    minutes = float(cfg["format"].get("long_minutes", 8))
    chars = int(minutes * CHARS_PER_MINUTE)
    user = f"""# チャンネル
{channel_brief(cfg)}

{learning_brief(memory, published, brain_context)}

# 今回の企画
タイトル案: {topic['title']}
切り口: {topic.get('angle', '')}
狙い: {topic.get('why', '')}

# 依頼
約{minutes:g}分（読み上げ原稿の合計 約{chars}文字）の解説動画の台本を書いてください。
- hook: 最初の15秒。視聴者の悩みを言い当て、最後まで見ると何が分かるかを約束する
- sections: 4〜7個。各 narration は話し言葉。points は画面に出す短い要点（各20文字以内、最大4つ）
- outro: まとめと、次に見てほしい内容への誘導（「チャンネル登録」を押し付けない）
- short: 縦型ショート用の別原稿（60秒以内、約{CHARS_PER_MINUTE}文字以内）。本編の一番おいしい部分を単体で分かる形に
- checks: 事実確認が必要な主張・数字を全部（なければ空配列）
- description: 概要欄。1行目で動画の結論、続けて目次（00:00 形式は不要）
- 読み上げ原稿に記号・URL・絵文字・括弧書きを入れない（音声合成が読めないため）

# 返す形
{{"title": "タイトル（32文字以内）",
  "title_options": ["別案1", "別案2"],
  "thumbnail_text": "サムネに載せる言葉（12文字以内）",
  "hook": "読み上げ原稿",
  "sections": [{{"heading": "見出し", "points": ["要点"], "narration": "読み上げ原稿"}}],
  "outro": "読み上げ原稿",
  "short": {{"title": "ショートのタイトル", "narration": "読み上げ原稿"}},
  "description": "概要欄",
  "tags": ["タグ"],
  "checks": ["確認が必要な主張"]}}"""
    return ask_json(llm, SYSTEM, user, lambda d: check_script(d, minutes))
