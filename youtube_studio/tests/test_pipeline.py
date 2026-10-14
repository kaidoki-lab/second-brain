import json
import subprocess
import unittest
from datetime import datetime, timedelta

import _ctx
from studio import episode as E
from studio.config import ConfigError
from studio.pipeline import MAX_PENDING_REVIEW, _utc
from studio.voice import VoiceError


def probe(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                          "stream=codec_type,width,height:format=duration", "-of", "json",
                          str(path)], capture_output=True, text=True, check=True).stdout
    return json.loads(out)


class MakeTest(unittest.TestCase):
    def setUp(self):
        self.box = _ctx.Sandbox()
        self.addCleanup(self.box.cleanup)

    def test_make_runs_plan_to_review_with_real_video_files(self):
        studio = self.box.studio()
        [ep] = studio.make(1)
        self.assertEqual(ep.status, E.REVIEW)
        self.assertEqual(ep.data["outputs"], ["long.mp4", "short.mp4", "thumbnail.png"])
        # 企画は3本できて、1本だけ進んだ
        self.assertEqual(len(studio.library.by_status(E.PLANNED)), 2)

        long_info = probe(ep.file("long.mp4"))
        kinds = {s["codec_type"] for s in long_info["streams"]}
        self.assertEqual(kinds, {"video", "audio"})
        video = next(s for s in long_info["streams"] if s["codec_type"] == "video")
        self.assertEqual((video["width"], video["height"]), (320, 180))
        timeline = json.loads(ep.file("timeline.json").read_text(encoding="utf-8"))
        expected = sum(t["duration"] + 0.25 for t in timeline["long"])
        self.assertAlmostEqual(float(long_info["format"]["duration"]), expected, delta=0.6)

        short = next(s for s in probe(ep.file("short.mp4"))["streams"]
                     if s["codec_type"] == "video")
        self.assertEqual((short["width"], short["height"]), (180, 320))
        # 作業用の連番画像は消してある
        self.assertFalse(ep.file("frames_long").exists())
        # 概要欄に VOICEVOX のクレジットが入る
        self.assertIn("VOICEVOX:", ep.data["final"]["description"])

    def test_stops_making_when_reviews_pile_up(self):
        studio = self.box.studio()
        made = studio.make(MAX_PENDING_REVIEW + 2)
        self.assertEqual(len(made), MAX_PENDING_REVIEW)
        self.assertEqual(studio.make(1), [])
        self.assertIn("今日は作りません", studio.auto()[-1])

    def test_failure_is_recorded_and_next_run_resumes(self):
        studio = self.box.studio()

        class Down:
            def synth(self, text):
                raise VoiceError("VOICEVOX に届きません")

        good_voice = studio._voice
        studio._voice = Down()
        with self.assertRaises(VoiceError):
            studio.make(1)
        [ep] = studio.library.by_status(E.SCRIPTED)
        self.assertIn("VOICEVOX", ep.data["error"])
        calls_before = len(studio.llm.calls)

        studio._voice = good_voice
        [done] = studio.make(1)
        self.assertEqual(done.id, ep.id)
        self.assertEqual(done.status, E.REVIEW)
        self.assertNotIn("error", studio.library.get(ep.id).data)
        self.assertEqual(len(studio.llm.calls), calls_before)  # 台本は書き直さない

    def test_requires_theme_and_audience(self):
        box = _ctx.Sandbox(channel={"theme": "", "audience": ""})
        self.addCleanup(box.cleanup)
        with self.assertRaisesRegex(ConfigError, "テーマ"):
            box.studio().make(1)


class ApproveTest(unittest.TestCase):
    def setUp(self):
        self.box = _ctx.Sandbox()
        self.addCleanup(self.box.cleanup)

    def test_manual_mode_approve_then_record_url(self):
        studio = self.box.studio()
        [ep] = studio.make(1)
        approved = studio.approve(ep.id, title="直したタイトル", tags=["a", " ", "b"])
        self.assertEqual(approved.status, E.APPROVED)
        self.assertEqual(approved.data["final"]["title"], "直したタイトル")
        self.assertEqual(approved.data["final"]["tags"], ["a", "b"])
        done = studio.mark_published(ep.id, " https://youtu.be/xyz ")
        self.assertEqual(done.status, E.PUBLISHED)
        self.assertEqual(done.data["published"]["url"], "https://youtu.be/xyz")
        with self.assertRaises(ValueError):
            studio.approve(ep.id)

    def test_api_mode_uploads_long_short_and_thumbnail(self):
        box = _ctx.Sandbox(youtube={"upload": "api"})
        self.addCleanup(box.cleanup)
        yt = _ctx.FakeYouTube()
        studio = box.studio(youtube=yt)
        [ep] = studio.make(1)
        when = (datetime.now().astimezone() + timedelta(days=2)).isoformat(timespec="minutes")
        done = studio.approve(ep.id, publish_at=when)
        self.assertEqual(done.status, E.PUBLISHED)
        self.assertEqual([u[0] for u in yt.uploads], ["long.mp4", "short.mp4"])
        self.assertTrue(yt.uploads[0][2].endswith("Z"))
        self.assertIn("#Shorts", yt.uploads[1][1]["title"])
        self.assertIn("https://youtu.be/vid1", yt.uploads[1][1]["description"])
        self.assertEqual(yt.thumbs, ["vid1"])
        self.assertEqual(done.data["published"]["url"], "https://youtu.be/vid1")

    def test_reject_reason_reaches_the_next_script(self):
        llm = _ctx.FakeLLM()
        studio = self.box.studio(llm=llm)
        [ep] = studio.make(1)
        studio.reject(ep.id, "前置きが長い")
        self.assertEqual(studio.library.get(ep.id).status, E.REJECTED)
        studio.make(1)
        self.assertIn("前置きが長い", llm.calls[-1])

    def test_failed_upload_keeps_approval_and_can_be_retried(self):
        box = _ctx.Sandbox(youtube={"upload": "api"})
        self.addCleanup(box.cleanup)
        yt = _ctx.FakeYouTube()
        studio = box.studio(youtube=yt)
        [ep] = studio.make(1)
        real_upload = yt.upload

        def broken(*a, **kw):
            raise OSError("回線が切れた")

        yt.upload = broken
        with self.assertRaises(OSError):
            studio.approve(ep.id)
        stuck = studio.library.get(ep.id)
        self.assertEqual(stuck.status, E.APPROVED)
        self.assertIn("回線が切れた", stuck.data["error"])
        yt.upload = real_upload
        done = studio.upload(stuck)
        self.assertEqual(done.status, E.PUBLISHED)
        self.assertNotIn("error", studio.library.get(ep.id).data)

    def test_two_reviews_approved_without_dates_get_different_days(self):
        studio = self.box.studio()
        a, b = studio.make(2)
        first = studio.approve(a.id).data["final"]["publish_at"]
        second = studio.approve(b.id).data["final"]["publish_at"]
        self.assertNotEqual(first[:10], second[:10])

    def test_next_slot_skips_days_already_taken(self):
        studio = self.box.studio()
        first = studio.next_slot()
        [ep] = studio.make(1)
        studio.approve(ep.id, publish_at=first)
        second = studio.next_slot()
        self.assertGreater(second[:10], first[:10])
        self.assertTrue(first.endswith(":00") or "T18:00" in first)

    def test_past_publish_time_means_publish_now(self):
        self.assertEqual(_utc("2000-01-01T10:00"), "")
        future = (datetime.now().astimezone() + timedelta(days=1)).isoformat()
        self.assertRegex(_utc(future), r"Z$")


class StatsTest(unittest.TestCase):
    def test_auto_imports_stats_and_feeds_planning(self):
        box = _ctx.Sandbox(youtube={"api_key": "k", "channel_id": "UC1"})
        self.addCleanup(box.cleanup)
        llm = _ctx.FakeLLM()
        studio = box.studio(llm=llm, youtube=_ctx.FakeYouTube())
        report = studio.auto()
        self.assertIn("再生数を取り込みました（2本）", report[0])
        self.assertIn("確認待ちに追加", report[-1])
        self.assertIn("伸びた動画（再生 1200）", llm.calls[0])


if __name__ == "__main__":
    unittest.main()
