"""「ウソはどれだ」形式（channel.json の format.mode = "quiz"）。

毎回のショート:

    前回の答え合わせ（ウソの正体・正解者の名前）← 機械で作る。AIに書かせない
    出演キャラのあいさつ                         ← AI
    A・B・C の雑学（1つだけウソ）                ← AI。並び順は機械でシャッフル
    「ウソだと思う記号をコメントで」             ← 固定文

視聴者の回答はコメントから集める（1人1回目の回答だけ数える）。
「#名前NG」と書いた人の名前は読み上げない。
"""

from __future__ import annotations

import hashlib
import random
import re
import unicodedata
from typing import Any

from .writer import LLM, SYSTEM, WriterError, ask_json, channel_brief, learning_brief

LETTERS = ("A", "B", "C")
FACT_MAX = 45
DEFAULT_CALL = "ウソだと思う記号を、コメントで教えてね。答えは次の動画で発表します。"
NAME_NG = "#名前NG"
MAX_NAMES = 5

QUIZ_RULES = """# 雑学クイズの決まり
- 3つの雑学のうち、ちょうど1つだけがウソ。残り2つは本当で、出典を書けるもの
- ウソは「本当っぽいけど無害」なものにする。健康・医療・お金・災害・事件・政治・
  宗教・実在の人物や企業・特定の地域や国の悪口は題材にしない
- 本当の雑学は、聞いた人が「え、本当に？」と思う意外なものにする
- 3つとも同じくらいの長さ・言い回しにして、文体でウソが見抜けないようにする
- 各雑学は話し言葉で{fact_max}文字以内。記号・URL・絵文字・括弧書きを入れない
- タイトルとサムネの言葉に答えを書かない"""


def enabled(cfg: dict[str, Any]) -> bool:
    return cfg.get("format", {}).get("mode") == "quiz"


# ================================================================== 台本

def _check(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise WriterError("台本はJSONオブジェクトで返してください")
    for key in ("title", "intro", "facts", "description"):
        if not data.get(key):
            raise WriterError(f"台本に {key} がありません")
    facts = data["facts"]
    if not isinstance(facts, list) or len(facts) != 3:
        raise WriterError("facts はちょうど3つにしてください")
    lies = 0
    for i, f in enumerate(facts, 1):
        if not isinstance(f, dict) or not str(f.get("text", "")).strip():
            raise WriterError(f"facts の{i}番目に text がありません")
        if len(str(f["text"]).strip()) > FACT_MAX:
            raise WriterError(f"facts の{i}番目が長すぎます（{FACT_MAX}文字以内）")
        if not str(f.get("explain", "")).strip():
            raise WriterError(f"facts の{i}番目に explain（本当／ウソの理由）がありません")
        f["lie"] = f.get("lie") is True
        if f["lie"]:
            lies += 1
        elif not str(f.get("source", "")).strip():
            raise WriterError(f"facts の{i}番目は本当の雑学なので source（出典）が必要です")
    if lies != 1:
        raise WriterError(f"ウソはちょうど1つにしてください（いま{lies}つ）")
    return data


def write(llm: LLM, cfg: dict[str, Any], topic: dict[str, Any], memory: dict[str, Any],
          published: list[dict[str, Any]], brain_context: str = "",
          member: dict[str, Any] | None = None) -> dict[str, Any]:
    cast_line = ""
    if member:
        cast_line = (f"\n# 今回の出演キャラ\n名前: {member.get('name', member['id'])}\n"
                     f"話し方: {member.get('persona', '')}\n"
                     "intro はこのキャラの口調で書く（雑学の中身は普通の言い方でよい）\n")
    user = f"""# チャンネル
{channel_brief(cfg)}

{learning_brief(memory, published, brain_context)}
{cast_line}
{QUIZ_RULES.format(fact_max=FACT_MAX)}

# 今回のお題
{topic['title']}（{topic.get('angle', '')}）

# 返す形
{{"title": "タイトル（28文字以内。答えを書かない）",
  "thumbnail_text": "サムネの言葉（10文字以内）",
  "intro": "出演キャラのあいさつとお題の紹介（2文以内）",
  "facts": [{{"text": "雑学", "lie": false, "explain": "本当である理由（1〜2文）",
             "source": "出典（本・公的機関・百科事典など）"}},
            {{"text": "雑学", "lie": true, "explain": "どこがウソで、本当はどうなのか（1〜2文）",
             "source": ""}},
            {{"text": "雑学", "lie": false, "explain": "…", "source": "…"}}],
  "description": "概要欄の1〜2行（答えを書かない）",
  "tags": ["タグ"],
  "checks": ["人が確かめるべき点（本当の雑学2つの事実確認は必ず入れる）"]}}"""
    data = ask_json(llm, SYSTEM, user, _check)
    return arrange(data, seed=topic.get("title", ""))


def arrange(data: dict[str, Any], seed: str) -> dict[str, Any]:
    """並び順を機械で決めて A/B/C を振る（AIはウソを最後に置きがちなため）。"""
    rnd = random.Random(int(hashlib.sha256(seed.encode("utf-8")).hexdigest(), 16))
    facts = list(data["facts"])
    rnd.shuffle(facts)
    items = [{"letter": letter, "text": str(f["text"]).strip(), "lie": f["lie"],
              "explain": str(f.get("explain", "")).strip(),
              "source": str(f.get("source", "")).strip()}
             for letter, f in zip(LETTERS, facts)]
    answer = next(i["letter"] for i in items if i["lie"])
    checks = [str(c) for c in data.get("checks", []) if str(c).strip()]
    checks.insert(0, f"ウソは {answer}（{next(i['text'] for i in items if i['lie'])}）。"
                     "切り抜かれて広まっても害がない内容か")
    return {
        "format": "quiz",
        "title": str(data["title"])[:100],
        "title_options": [str(t) for t in data.get("title_options", [])],
        "thumbnail_text": str(data.get("thumbnail_text") or data["title"])[:20],
        "intro": str(data["intro"]).strip(),
        "items": items,
        "answer": answer,
        "description": str(data["description"]).strip(),
        "tags": [str(t) for t in data.get("tags", []) if str(t).strip()][:15],
        "checks": checks,
        "short": {"title": str(data["title"])[:90]},
    }


# ================================================================== 回答の集計

def read_answer(text: str) -> str:
    """コメントの中の最初の A/B/C（全角・小文字も可）。"""
    norm = unicodedata.normalize("NFKC", text).upper()
    m = re.search(r"(?<![A-Z])([ABC])(?![A-Z])", norm)
    return m.group(1) if m else ""


def speakable(name: str) -> str:
    """読み上げ・画面に出せる名前（@ を外し、記号を除いて12文字まで）。"""
    name = unicodedata.normalize("NFKC", name).lstrip("@")
    name = re.sub(r"[^\w぀-ヿ一-鿿]", "", name)
    return name[:12]


def judge(comments: list[dict[str, Any]], answer: str) -> dict[str, Any]:
    """comments: [{"author", "channel", "text", "at"}]。1人1回目の回答だけ数える。"""
    first: dict[str, dict[str, Any]] = {}
    for c in sorted(comments, key=lambda c: c.get("at", "")):
        letter = read_answer(c.get("text", ""))
        who = c.get("channel") or c.get("author", "")
        if not letter or not who or who in first:
            continue
        first[who] = {"letter": letter, "name": c.get("author", ""),
                      "hide": NAME_NG.lower() in unicodedata.normalize(
                          "NFKC", c.get("text", "")).lower()}
    counts = {letter: 0 for letter in LETTERS}
    winners = []
    for who, a in first.items():
        counts[a["letter"]] += 1
        if a["letter"] == answer:
            winners.append({"channel": who, "name": speakable(a["name"]), "hide": a["hide"]})
    return {"answers": len(first), "counts": counts, "correct": len(winners),
            "winners": winners}


def update_ranking(memory: dict[str, Any], winners: list[dict[str, Any]]) -> None:
    ranking = memory.setdefault("ranking", {})
    for w in winners:
        row = ranking.setdefault(w["channel"], {"name": w["name"], "correct": 0})
        row["correct"] += 1
        row["name"] = w["name"] or row["name"]
        row["hide"] = w["hide"]


def recap(prev_script: dict[str, Any], result: dict[str, Any] | None) -> dict[str, Any]:
    """前回の答え合わせ。読み上げる文も画面も、集計結果から機械で作る。"""
    answer = prev_script["answer"]
    lie = next(i for i in prev_script["items"] if i["letter"] == answer)
    text = f"前回の答え合わせ。ウソは{answer}、{lie['text']}、でした。{lie['explain']}"
    names: list[str] = []
    if result is not None:
        names = [w["name"] for w in result["winners"] if w["name"] and not w["hide"]]
        if result["correct"]:
            shown = names[:MAX_NAMES]
            rest = result["correct"] - len(shown)
            text += f" 正解は{result['correct']}人。"
            if shown:
                text += "、".join(f"{n}さん" for n in shown)
                text += f"、ほか{rest}人、" if rest > 0 else "、"
                text += "正解です。"
        elif result["answers"]:
            text += " 今回は正解者がいませんでした。"
    return {"answer": answer, "lie": lie["text"], "explain": lie["explain"],
            "text": text, "names": names[:MAX_NAMES],
            "correct": result["correct"] if result else None,
            "answers": result["answers"] if result else None}


# ================================================================== 読み上げの並び

def timeline_items(script: dict[str, Any], cfg: dict[str, Any]) -> list[dict[str, Any]]:
    """(画面の内容, 読み上げる文) の並び。voice が1つずつ音声にする。"""
    head = cfg.get("quiz", {}).get("heading") or "ウソはどれだ？"
    call = cfg.get("quiz", {}).get("call") or DEFAULT_CALL
    out: list[dict[str, Any]] = []
    r = script.get("recap")
    if r:
        card = [{"letter": r["answer"], "text": r["lie"]}]
        out.append({"heading": "前回の答え", "cards": card, "mark": r["answer"],
                    "names": r.get("names", []), "text": r["text"]})
    out.append({"heading": head, "cards": [], "text": script["intro"]})
    shown: list[dict[str, str]] = []
    for item in script["items"]:
        shown = shown + [{"letter": item["letter"], "text": item["text"]}]
        out.append({"heading": head, "cards": shown,
                    "text": f"{item['letter']}。{item['text']}"})
    out.append({"heading": head, "cards": shown, "text": call})
    return out


def description(script: dict[str, Any], cfg: dict[str, Any], member: dict[str, Any] | None
                ) -> str:
    parts = [script["description"]]
    parts.append("A・B・C のうち、ウソはひとつだけ。ウソだと思う記号をコメントで！"
                 f"\n答えと正解者の名前は次の動画で発表します（名前を読まれたくない方は「{NAME_NG}」と書いてください）。")
    if member:
        cast_line = f"出演: {member.get('name', member['id'])}"
        if member.get("link"):
            cast_line += f"\n{member['link']}"
        parts.append(cast_line)
    footer = cfg.get("quiz", {}).get("footer", "")
    if footer:
        parts.append(footer)
    credit = cfg["voice"].get("credit", "")
    if credit:
        parts.append(credit)
    return "\n\n".join(p.strip() for p in parts if p and p.strip())
