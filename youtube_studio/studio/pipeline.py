"""チャンネル運営の流れ全体。

    auto（毎日1回、タスクスケジューラから）
      1. 再生数を取り込む（設定があれば）
      2. 企画が尽きていれば、伸びた動画・見送り理由を踏まえて企画を足す
      3. 次の企画を 台本 → 音声 → 動画 → 確認待ち まで進める

    人がやること（スマホから数分）
      確認画面で見る → 承認（予約投稿）か、理由を書いて見送り

確認待ちが溜まっているときは新しく作らない（見られない動画を量産しない）。

format.mode = "quiz"（ウソはどれだ）のときは、出演キャラを毎回入れ替え、
前回の答え合わせを次の回の冒頭に入れる。答え合わせが前回とずれないよう、
前の回が公開されるまで次の回は作らない。
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import brain, cast, quiz
from .config import path as cfg_path, require_channel
from .episode import (APPROVED, IN_PROGRESS, PLANNED, PUBLISHED, REJECTED, REVIEW,
                      SCRIPTED, VOICED, Episode, Library, now)
from .render import render, render_thumbnail
from .voice import VoiceVox, duration, make_voice, split_sentences
from .writer import LLM, make_writer, plan_topics, write_script

#: 確認待ちがこの本数に達したら、新しい動画は作らない。
MAX_PENDING_REVIEW = 3
SHORT_LIMIT = 58.0


class Studio:
    def __init__(self, cfg: dict[str, Any], llm: LLM | None = None,
                 voice: VoiceVox | None = None, youtube: Any = None,
                 library: Library | None = None):
        self.cfg = cfg
        self.library = library or Library(cfg_path(cfg, "episodes"))
        self._llm = llm
        self._voice = voice
        self._youtube = youtube

    @property
    def llm(self) -> LLM:
        if self._llm is None:
            self._llm = make_writer(self.cfg)
        return self._llm

    @property
    def voice(self) -> VoiceVox:
        if self._voice is None:
            self._voice = make_voice(self.cfg)
        return self._voice

    @property
    def youtube(self) -> Any:
        if self._youtube is None:
            from .youtube import YouTube
            self._youtube = YouTube(self.cfg)
        return self._youtube

    # ---------------------------------------------------------- 企画

    def made_titles(self) -> list[dict[str, Any]]:
        out = []
        for ep in self.library:
            title = (ep.data.get("script") or {}).get("title") or ep.data["topic"]["title"]
            out.append({"title": title, "status": ep.status})
        known = {o["title"] for o in out}
        for s in self.library.memory().get("stats", {}).values():
            if s["title"] not in known:
                out.append({"title": s["title"], "status": PUBLISHED})
        return out

    def plan(self, count: int | None = None) -> list[Episode]:
        require_channel(self.cfg)
        count = count or int(self.cfg["format"].get("plan_batch", 5))
        topics = plan_topics(self.llm, self.cfg, self.library.memory(), self.made_titles(),
                             brain.context(self.cfg), count)
        return [self.library.create(t) for t in topics]

    # ---------------------------------------------------------- 制作

    def write(self, ep: Episode) -> Episode:
        if quiz.enabled(self.cfg):
            return self.write_quiz(ep)
        script = write_script(self.llm, self.cfg, ep.data["topic"], self.library.memory(),
                              self.made_titles(), brain.context(self.cfg))
        return ep.set(SCRIPTED, script=script)

    def write_quiz(self, ep: Episode) -> Episode:
        member = cast.pick(self.cfg, self.library.all()) if cast.enabled(self.cfg) else None
        script = quiz.write(self.llm, self.cfg, ep.data["topic"], self.library.memory(),
                            self.made_titles(), brain.context(self.cfg), member)
        prev = self.last_unrevealed()
        if prev is not None:
            script["recap"] = quiz.recap(prev.data["script"], self.collect_answers(prev))
            script["recap"]["from"] = prev.id
            prev.set(revealed_in=ep.id)
        fields: dict[str, Any] = {"script": script}
        if member:
            fields.update(cast=member["id"], cast_at=now())
        return ep.set(SCRIPTED, **fields)

    def last_unrevealed(self) -> Episode | None:
        """まだ答え合わせしていない、いちばん新しい公開済みのクイズ回。"""
        done = [ep for ep in self.library.by_status(PUBLISHED)
                if (ep.data.get("script") or {}).get("format") == "quiz"]
        done.sort(key=lambda ep: ep.data.get("published_at", ""))
        if not done or done[-1].data.get("revealed_in"):
            return None
        return done[-1]

    def collect_answers(self, ep: Episode) -> dict[str, Any] | None:
        """コメントから回答を集めて採点する。取れなければ None（答えだけ発表する）。"""
        ids = cast.video_ids(ep)
        if not ids or not self.youtube_ready(self.cfg["youtube"]):
            return None
        try:
            comments = self.youtube.comments(ids[0])
        except Exception as exc:
            ep.set(comments_error=str(exc))
            return None
        result = quiz.judge(comments, ep.data["script"]["answer"])
        memory = self.library.memory()
        quiz.update_ranking(memory, result["winners"])
        self.library.save_memory(memory)
        ep.set(results=result)
        return result

    def ep_cfg(self, ep: Episode) -> dict[str, Any]:
        """その回の設定（出演キャラがいれば、絵と声をそのキャラに差し替える）。"""
        if ep.data.get("cast"):
            return cast.cfg_for(self.cfg, ep.data["cast"])
        return self.cfg

    def voice_for(self, cfg: dict[str, Any]) -> VoiceVox:
        base = self.voice
        speaker = int(cfg["voice"].get("speaker", base.speaker))
        if speaker == base.speaker:
            return base
        return VoiceVox(base.url, speaker, base.speed, base.transport)

    def _timeline(self, items: list[tuple[str, list[str], str]] | list[dict[str, Any]],
                  prefix: str, folder: Path, limit: float | None = None,
                  voice: VoiceVox | None = None) -> list[dict[str, Any]]:
        """items は (見出し, 要点, 文) か、画面の内容と "text" を持つ dict。"""
        voice = voice or self.voice
        timeline: list[dict[str, Any]] = []
        total = 0.0
        for item in items:
            if isinstance(item, dict):
                screen = {k: v for k, v in item.items() if k != "text"}
                text = item["text"]
            else:
                heading, points, text = item
                screen = {"heading": heading, "points": points}
            for sentence in split_sentences(text):
                wav = voice.synth(sentence)
                length = duration(wav)
                if limit is not None and total + length > limit:
                    return timeline
                name = f"{prefix}_{len(timeline):03d}.wav"
                (folder / name).write_bytes(wav)
                timeline.append({**screen, "text": sentence,
                                 "audio": name, "duration": round(length, 3)})
                total += length + 0.25
        return timeline

    def speak(self, ep: Episode) -> Episode:
        script = ep.data["script"]
        folder = ep.file("voice")
        folder.mkdir(exist_ok=True)
        if script.get("format") == "quiz":
            ecfg = self.ep_cfg(ep)
            short = self._timeline(quiz.timeline_items(script, ecfg), "short", folder,
                                   voice=self.voice_for(ecfg))
            ep.file("timeline.json").write_text(
                json.dumps({"short": short}, ensure_ascii=False, indent=1), encoding="utf-8")
            seconds = sum(t["duration"] + 0.25 for t in short)
            return ep.set(VOICED, short_seconds=round(seconds, 1))
        headings = [s["heading"] for s in script["sections"]]
        long_items = [(script["title"], [], script["hook"])]
        long_items += [(s["heading"], s.get("points", []), s["narration"])
                       for s in script["sections"]]
        if script.get("outro"):
            long_items.append(("まとめ", headings[:4], script["outro"]))
        timeline = {"long": self._timeline(long_items, "long", folder)}
        if self.cfg["format"].get("shorts", True):
            short = script["short"]
            timeline["short"] = self._timeline(
                [(short.get("title") or script["title"], [], short["narration"])],
                "short", folder, SHORT_LIMIT)
        ep.file("timeline.json").write_text(json.dumps(timeline, ensure_ascii=False, indent=1),
                                             encoding="utf-8")
        seconds = sum(t["duration"] + 0.25 for t in timeline["long"])
        return ep.set(VOICED, long_seconds=round(seconds, 1))

    def build(self, ep: Episode) -> Episode:
        timeline = json.loads(ep.file("timeline.json").read_text(encoding="utf-8"))
        r = self.cfg["render"]
        w, h = int(r.get("width", 1920)), int(r.get("height", 1080))
        voice_dir = ep.file("voice")
        if ep.data["script"].get("format") == "quiz":
            # ショートだけ（縦型。答えが出る本編は作らない）
            render(self.ep_cfg(ep), timeline["short"], voice_dir, ep.file("short.mp4"),
                   (min(w, h), max(w, h)), ep.file("frames_short"))
            _clear(ep.file("frames_short"))
            return ep.set(REVIEW, outputs=["short.mp4"], review_since=now(),
                          final=self.default_meta(ep))
        render(self.cfg, timeline["long"], voice_dir, ep.file("long.mp4"), (w, h),
               ep.file("frames_long"))
        outputs = ["long.mp4"]
        if timeline.get("short"):
            # 縦型は横型の幅と高さを入れ替える（1920x1080 → 1080x1920）
            render(self.cfg, timeline["short"], voice_dir, ep.file("short.mp4"), (h, w),
                   ep.file("frames_short"))
            outputs.append("short.mp4")
        script = ep.data["script"]
        render_thumbnail(self.cfg, script["thumbnail_text"], ep.file("thumbnail.png"),
                         self.cfg["channel"].get("name", ""))
        outputs.append("thumbnail.png")
        for frames in ("frames_long", "frames_short"):
            _clear(ep.file(frames))
        return ep.set(REVIEW, outputs=outputs, review_since=now(),
                      final=self.default_meta(ep))

    def advance(self, ep: Episode) -> Episode:
        """承認の手前まで1段ずつ進める。途中で止まっても次回は続きから。"""
        steps = {PLANNED: self.write, SCRIPTED: self.speak, VOICED: self.build}
        while ep.status in steps:
            ep = steps[ep.status](ep)
        return ep

    def waiting_for_publish(self) -> bool:
        """クイズで、前の回がまだ公開されていない（答え合わせがずれるので次を作らない）。"""
        return quiz.enabled(self.cfg) and bool(self.library.by_status(REVIEW, APPROVED))

    def make(self, count: int = 1) -> list[Episode]:
        require_channel(self.cfg)
        made = []
        for _ in range(count):
            if len(self.library.by_status(REVIEW)) >= MAX_PENDING_REVIEW:
                break
            if self.waiting_for_publish():
                break
            queue = self.library.by_status(*IN_PROGRESS)
            if not queue:
                queue = self.plan()
            ep = queue[0]
            try:
                ep = self.advance(ep)
            except Exception as exc:
                ep.set(error=f"{type(exc).__name__}: {exc}", error_at=now())
                raise
            if ep.data.pop("error", None):
                ep.save()
            made.append(ep)
        return made

    # ---------------------------------------------------------- 承認・投稿

    def description(self, script: dict[str, Any]) -> str:
        parts = [script["description"].strip()]
        credit = self.cfg["voice"].get("credit", "")
        if credit:
            parts.append(credit)
        return "\n\n".join(p for p in parts if p)

    def default_meta(self, ep: Episode) -> dict[str, Any]:
        script = ep.data["script"]
        if script.get("format") == "quiz":
            member = cast.member(self.cfg, ep.data["cast"]) if ep.data.get("cast") else None
            desc = quiz.description(script, self.ep_cfg(ep), member)
        else:
            desc = self.description(script)
        # 公開日時は承認したときに空き枠から決める（確認待ちが複数あっても重ならない）
        return {"title": script["title"], "description": desc,
                "tags": script.get("tags", [])}

    def next_slot(self) -> str:
        """次の空いている公開枠（毎日 publish_hour 時、1日1本）。"""
        hour = int(self.cfg["youtube"].get("publish_hour", 18))
        taken = {(ep.data.get("final") or {}).get("publish_at", "")[:10]
                 for ep in self.library.by_status(APPROVED, PUBLISHED)}
        slot = datetime.now().astimezone().replace(hour=hour, minute=0, second=0, microsecond=0)
        if slot <= datetime.now().astimezone() + timedelta(hours=1):
            slot += timedelta(days=1)
        while slot.date().isoformat() in taken:
            slot += timedelta(days=1)
        return slot.isoformat(timespec="minutes")

    def approve(self, ep_id: str, title: str = "", description: str = "",
                tags: list[str] | None = None, publish_at: str = "") -> Episode:
        ep = self.library.get(ep_id)
        if ep.status != REVIEW:
            raise ValueError(f"この動画は確認待ちではありません（{ep.status}）")
        meta = dict(ep.data.get("final") or self.default_meta(ep))
        if title.strip():
            meta["title"] = title.strip()[:100]
        if description.strip():
            meta["description"] = description.strip()
        if tags is not None:
            meta["tags"] = [t.strip() for t in tags if t.strip()]
        meta["publish_at"] = publish_at.strip() or self.next_slot()
        ep.set(APPROVED, final=meta, approved_at=now())
        if self.cfg["youtube"].get("upload") == "api":
            return self.upload(ep)
        return ep

    def upload(self, ep: Episode) -> Episode:
        """API で投稿する。失敗したら理由を残し、確認画面から押し直せる。"""
        if ep.status != APPROVED:
            raise ValueError(f"この動画は投稿待ちではありません（{ep.status}）")
        try:
            return self._upload(ep)
        except Exception as exc:
            ep.set(error=f"投稿に失敗: {exc}", error_at=now())
            raise

    def _upload(self, ep: Episode) -> Episode:
        meta = ep.data["final"]
        when = _utc(meta.get("publish_at", ""))
        if not ep.file("long.mp4").exists():   # ショートだけの回（クイズ）
            short_meta = {**meta, "title": meta["title"][:90] + " #Shorts"}
            video_id = self.youtube.upload(ep.file("short.mp4"), short_meta, when)
            url = f"https://youtube.com/shorts/{video_id}"
            brain.record_published(self.cfg, meta["title"], url)
            ep.data.pop("error", None)
            return ep.set(PUBLISHED, published={"video_id": video_id, "url": url},
                          published_at=now())
        video_id = self.youtube.upload(ep.file("long.mp4"), meta, when)
        result: dict[str, Any] = {"video_id": video_id,
                                  "url": f"https://youtu.be/{video_id}"}
        try:
            self.youtube.set_thumbnail(video_id, ep.file("thumbnail.png"))
        except Exception as exc:  # サムネが失敗しても投稿は成功扱い
            result["thumbnail_error"] = str(exc)
        if ep.file("short.mp4").exists():
            short = ep.data["script"]["short"]
            short_meta = {"title": (short.get("title") or meta["title"])[:90] + " #Shorts",
                          "description": f"本編はこちら https://youtu.be/{video_id}\n\n"
                                         + meta["description"],
                          "tags": meta.get("tags", [])}
            result["short_id"] = self.youtube.upload(ep.file("short.mp4"), short_meta, when)
        brain.record_published(self.cfg, meta["title"], result["url"])
        ep.data.pop("error", None)
        return ep.set(PUBLISHED, published=result, published_at=now())

    def mark_published(self, ep_id: str, url: str) -> Episode:
        """手動で投稿したあと、そのURLを記録する。"""
        ep = self.library.get(ep_id)
        if ep.status not in (REVIEW, APPROVED):
            raise ValueError(f"この動画は投稿待ちではありません（{ep.status}）")
        url = url.strip()
        brain.record_published(self.cfg, ep.data["final"]["title"], url)
        return ep.set(PUBLISHED, published={"url": url}, published_at=now())

    def reject(self, ep_id: str, reason: str) -> Episode:
        ep = self.library.get(ep_id)
        if ep.status != REVIEW:
            raise ValueError(f"この動画は確認待ちではありません（{ep.status}）")
        title = ep.data["script"]["title"]
        if reason.strip():
            self.library.add_feedback(f"{reason.strip()}（見送り: {title}）", ep.id)
        return ep.set(REJECTED, reject_reason=reason.strip())

    # ---------------------------------------------------------- 振り返り

    def refresh_stats(self) -> int:
        videos = self.youtube.channel_videos()
        memory = self.library.memory()
        memory["stats"] = {v["id"]: v for v in videos}
        memory["stats_at"] = now()
        self.library.save_memory(memory)
        return len(videos)

    def auto(self) -> list[str]:
        report = []
        y = self.cfg["youtube"]
        if self.youtube_ready(y):
            try:
                report.append(f"再生数を取り込みました（{self.refresh_stats()}本）")
            except Exception as exc:
                report.append(f"再生数の取り込みは飛ばしました: {exc}")
        pending = len(self.library.by_status(REVIEW))
        if pending >= MAX_PENDING_REVIEW:
            report.append(f"確認待ちが{pending}本あるので、今日は作りません")
            return report
        if self.waiting_for_publish():
            report.append("前の回がまだ公開されていないので、今日は作りません"
                          "（答え合わせがずれないように。公開したらURLを記録してください）")
            return report
        for ep in self.make(1):
            report.append(f"確認待ちに追加: {ep.data['script']['title']}")
        return report

    def youtube_ready(self, y: dict[str, Any]) -> bool:
        return (cfg_path(self.cfg, y.get("token", "secrets/token.json")).exists()
                or bool(y.get("api_key") and y.get("channel_id")))


def _utc(local_iso: str) -> str:
    if not local_iso:
        return ""
    dt = datetime.fromisoformat(local_iso)
    if dt.tzinfo is None:
        dt = dt.astimezone()
    if dt <= datetime.now(timezone.utc) + timedelta(minutes=15):
        return ""  # 過去や直近の時刻なら予約せず、そのまま公開する
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _clear(folder: Path) -> None:
    if folder.exists():
        for f in folder.iterdir():
            f.unlink()
        folder.rmdir()
