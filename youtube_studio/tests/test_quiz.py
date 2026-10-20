import json
import shutil
import subprocess
import unittest

from PIL import Image

import _ctx
from studio import cast, quiz
from studio import episode as E
from studio.writer import WriterError


def quiz_json(lie_at=2, title="動物のふしぎ"):
    facts = [{"text": f"本当の雑学{i}", "lie": False, "explain": "本当です",
              "source": "動物図鑑"} for i in range(3)]
    facts[lie_at] = {"text": "ウソの雑学", "lie": True, "explain": "本当は違います",
                     "source": ""}
    return {"title": title, "thumbnail_text": "ウソは？", "intro": "こんばんは。今日は動物です。",
            "facts": facts, "description": "どれがウソ？", "tags": ["雑学"],
            "checks": ["図鑑で確認"]}


class QuizLLM(_ctx.FakeLLM):
    def complete(self, system, user):
        self.calls.append(user)
        if self.replies:
            return self.replies.pop(0)
        if "企画を" in user and "topics" in user:
            return json.dumps({"topics": [{"title": f"お題{i}", "angle": "意外"}
                                          for i in range(3)]}, ensure_ascii=False)
        return json.dumps(quiz_json(), ensure_ascii=False)


def fake_character(root, cid):
    """PUPPET-AVATAR と同じ形のキャラ（赤い体・青い下あご）。"""
    folder = root / cid
    folder.mkdir(parents=True)
    base = Image.new("RGBA", (90, 160), (0, 0, 0, 0))
    base.paste((255, 0, 0, 255), (10, 10, 80, 100))
    jaw = Image.new("RGBA", (90, 160), (0, 0, 0, 0))
    jaw.paste((0, 0, 255, 255), (30, 100, 60, 110))
    base.save(folder / "base.png")
    jaw.save(folder / "jaw.png")
    (folder / "character.json").write_text(json.dumps({
        "id": cid, "layers": {"base": "base.png", "jaw": "jaw.png"},
        "motion": {"jaw": {"maxOpen": 54}}}), encoding="utf-8")
    return folder


ROSTER = [{"id": "a", "name": "人形A", "speaker": 1, "credit": "VOICEVOX:A"},
          {"id": "b", "name": "人形B", "speaker": 2, "credit": "VOICEVOX:B",
           "link": "https://example.booth.pm/"},
          {"id": "c", "name": "人形C", "speaker": 3, "credit": "VOICEVOX:C"}]


def quiz_box():
    box = _ctx.Sandbox(format={"mode": "quiz"},
                       cast={"source": "chars", "members": ROSTER})
    for m in ROSTER:
        fake_character(box.dir / "chars", m["id"])
    return box


class ScriptTest(unittest.TestCase):
    def test_exactly_one_lie_is_required(self):
        bad = quiz_json()
        bad["facts"][0]["lie"] = True
        with self.assertRaisesRegex(WriterError, "ちょうど1つ"):
            quiz._check(bad)

    def test_true_facts_need_a_source(self):
        bad = quiz_json()
        bad["facts"][0]["source"] = ""
        with self.assertRaisesRegex(WriterError, "出典"):
            quiz._check(bad)

    def test_letters_are_shuffled_by_machine_and_answer_points_at_the_lie(self):
        positions = set()
        for n in range(12):
            s = quiz.arrange(quiz._check(quiz_json()), seed=f"お題{n}")
            lie = next(i for i in s["items"] if i["lie"])
            self.assertEqual(s["answer"], lie["letter"])
            self.assertEqual([i["letter"] for i in s["items"]], ["A", "B", "C"])
            self.assertIn("ウソは " + s["answer"], s["checks"][0])
            positions.add(s["answer"])
        self.assertGreater(len(positions), 1)  # いつも同じ位置にならない
        again = quiz.arrange(quiz._check(quiz_json()), seed="お題3")
        self.assertEqual(again["answer"],
                         quiz.arrange(quiz._check(quiz_json()), seed="お題3")["answer"])


class JudgeTest(unittest.TestCase):
    def test_first_answer_per_person_counts(self):
        comments = [
            {"author": "@taro", "channel": "U1", "text": "Bかな", "at": "1"},
            {"author": "@taro", "channel": "U1", "text": "やっぱりC", "at": "2"},
            {"author": "花子", "channel": "U2", "text": "ｃ！ #名前NG", "at": "3"},
            {"author": "@jiro★", "channel": "U3", "text": "答えはc", "at": "4"},
            {"author": "通りすがり", "channel": "U4", "text": "おもしろい", "at": "5"},
        ]
        r = quiz.judge(comments, "C")
        self.assertEqual(r["answers"], 3)
        self.assertEqual(r["counts"], {"A": 0, "B": 1, "C": 2})
        self.assertEqual(r["correct"], 2)
        self.assertEqual([w["name"] for w in r["winners"]], ["花子", "jiro"])
        self.assertTrue(r["winners"][0]["hide"])

    def test_recap_reads_names_except_hidden(self):
        script = quiz.arrange(quiz._check(quiz_json()), seed="x")
        result = {"answers": 3, "correct": 2, "counts": {},
                  "winners": [{"channel": "U2", "name": "花子", "hide": True},
                              {"channel": "U3", "name": "jiro", "hide": False}]}
        r = quiz.recap(script, result)
        self.assertIn(f"ウソは{script['answer']}", r["text"])
        self.assertIn("正解は2人", r["text"])
        self.assertIn("jiroさん", r["text"])
        self.assertNotIn("花子", r["text"])
        self.assertEqual(r["names"], ["jiro"])

    def test_recap_without_comments_still_reveals(self):
        script = quiz.arrange(quiz._check(quiz_json()), seed="x")
        r = quiz.recap(script, None)
        self.assertIn("ウソの雑学", r["text"])
        self.assertIsNone(r["correct"])

    def test_ranking_accumulates(self):
        memory = {}
        quiz.update_ranking(memory, [{"channel": "U1", "name": "taro", "hide": False}])
        quiz.update_ranking(memory, [{"channel": "U1", "name": "taro", "hide": False}])
        self.assertEqual(memory["ranking"]["U1"]["correct"], 2)


class CastTest(unittest.TestCase):
    def setUp(self):
        self.box = quiz_box()
        self.addCleanup(self.box.cleanup)

    def test_rotation_never_repeats_and_balances(self):
        studio = self.box.studio()
        picked = []
        for n in range(6):
            m = cast.pick(self.box.cfg, studio.library.all())
            ep = studio.library.create({"title": f"t{n}"})
            ep.set(cast=m["id"], cast_at=f"2026-01-01T00:00:{n:02d}")
            picked.append(m["id"])
        self.assertTrue(all(a != b for a, b in zip(picked, picked[1:])))
        self.assertEqual(sorted(picked), ["a", "a", "b", "b", "c", "c"])

    def test_mouth_images_move_the_jaw_down(self):
        mouths = cast.build_mouths(self.box.dir / "chars" / "a", size=160)
        self.assertEqual(mouths["closed"].size, (160, 160))

        def jaw_top(img):
            for y in range(img.height):
                if any(img.getpixel((x, y))[:3] == (0, 0, 255) for x in range(img.width)):
                    return y
        self.assertGreater(jaw_top(mouths["open"]), jaw_top(mouths["half"]))
        self.assertGreater(jaw_top(mouths["half"]), jaw_top(mouths["closed"]))

    def test_source_folder_is_only_read(self):
        src = self.box.dir / "chars" / "a"
        before = {f.name: f.read_bytes() for f in src.iterdir()}
        out = cast.sprite_dir(self.box.cfg, "a")
        self.assertTrue((out / "open.png").exists())
        self.assertNotEqual(out.parent.parent, src.parent)
        self.assertEqual(before, {f.name: f.read_bytes() for f in src.iterdir()})

    def test_cast_cfg_switches_voice_and_credit(self):
        c = cast.cfg_for(self.box.cfg, "b")
        self.assertEqual(c["voice"]["speaker"], 2)
        self.assertEqual(c["voice"]["credit"], "VOICEVOX:B")
        self.assertTrue(c["avatar"]["enabled"])
        self.assertEqual(self.box.cfg["voice"]["speaker"], 3)  # 元の設定は変えない

    def test_report_groups_views_by_character(self):
        studio = self.box.studio()
        for n, (cid, url) in enumerate([("a", "https://youtube.com/shorts/AAAAAAAAAAA"),
                                        ("a", "https://youtu.be/BBBBBBBBBBB"),
                                        ("b", "https://youtube.com/shorts/CCCCCCCCCCC")]):
            ep = studio.library.create({"title": f"t{n}"})
            ep.set(E.PUBLISHED, cast=cid, published={"url": url})
        stats = {"AAAAAAAAAAA": {"views": 100, "comments": 4},
                 "BBBBBBBBBBB": {"views": 300, "comments": 1},
                 "CCCCCCCCCCC": {"views": 50, "comments": 9}}
        rows = {r["id"]: r for r in cast.report(self.box.cfg, studio.library.all(), stats)}
        self.assertEqual(rows["a"]["published"], 2)
        self.assertEqual(rows["a"]["avg_views"], 200)
        self.assertEqual(rows["b"]["comments"], 9)
        self.assertEqual(rows["c"]["published"], 0)


class FakeCommentsYouTube(_ctx.FakeYouTube):
    def __init__(self, comments):
        super().__init__()
        self._comments = comments
        self.asked = []

    def comments(self, video_id):
        self.asked.append(video_id)
        return self._comments


class FlowTest(unittest.TestCase):
    """台本と音声まで（ffmpeg を使わない部分）。"""

    def setUp(self):
        self.box = quiz_box()
        self.addCleanup(self.box.cleanup)

    def _publish(self, studio, ep, url):
        ep.set(E.PUBLISHED, published={"url": url}, published_at=E.now())

    def test_next_episode_opens_with_answer_and_winners(self):
        box = quiz_box()
        self.addCleanup(box.cleanup)
        box.cfg["youtube"].update({"api_key": "k", "channel_id": "UC1"})
        first_ep_answer = []
        yt = FakeCommentsYouTube([])
        studio = box.studio(llm=QuizLLM(), youtube=yt)
        [ep1] = studio.plan(1)
        ep1 = studio.write(ep1)
        first_ep_answer.append(ep1.data["script"]["answer"])
        self.assertNotIn("recap", ep1.data["script"])
        self._publish(studio, ep1, "https://youtube.com/shorts/AAAAAAAAAAA")
        yt._comments = [{"author": "@taro", "channel": "U1", "text": first_ep_answer[0],
                         "at": "1"},
                        {"author": "@miss", "channel": "U2", "text": "Z", "at": "2"}]

        [ep2] = studio.plan(1)
        ep2 = studio.write(ep2)
        recap = ep2.data["script"]["recap"]
        self.assertEqual(yt.asked, ["AAAAAAAAAAA"])
        self.assertEqual(recap["from"], ep1.id)
        self.assertIn("taroさん", recap["text"])
        self.assertNotEqual(ep2.data["cast"], ep1.data["cast"])
        self.assertEqual(studio.library.get(ep1.id).data["revealed_in"], ep2.id)
        self.assertEqual(studio.library.memory()["ranking"]["U1"]["correct"], 1)

        ep2 = studio.speak(ep2)
        timeline = json.loads(ep2.file("timeline.json").read_text(encoding="utf-8"))
        self.assertEqual(list(timeline), ["short"])
        first = timeline["short"][0]
        self.assertEqual(first["heading"], "前回の答え")
        self.assertEqual(first["mark"], recap["answer"])
        self.assertEqual([c["letter"] for c in timeline["short"][-1]["cards"]], ["A", "B", "C"])
        self.assertIn("コメント", "".join(t["text"] for t in timeline["short"][-2:]))

        # 同じ回は2度答え合わせしない
        [ep3] = studio.plan(1)
        self.assertNotIn("recap", studio.write(ep3).data["script"])

    def test_without_youtube_the_answer_is_still_revealed(self):
        studio = self.box.studio(llm=QuizLLM())
        [ep1] = studio.plan(1)
        ep1 = studio.write(ep1)
        self._publish(studio, ep1, "https://youtu.be/AAAAAAAAAAA")
        [ep2] = studio.plan(1)
        recap = studio.write(ep2).data["script"]["recap"]
        self.assertIsNone(recap["correct"])
        self.assertIn("ウソの雑学", recap["text"])

    def test_uses_each_characters_voice(self):
        spoken = []

        def transport(url, body, timeout):
            spoken.append(url)
            return _ctx.fake_voice_transport(url, body, timeout)

        studio = self.box.studio(llm=QuizLLM())
        studio._voice = _ctx.VoiceVox(transport=transport)
        [ep] = studio.plan(1)
        ep = studio.speak(studio.write(ep))
        speaker = cast.member(self.box.cfg, ep.data["cast"])["speaker"]
        self.assertTrue(all(f"speaker={speaker}" in u for u in spoken))

    def test_description_has_cast_link_and_credit(self):
        studio = self.box.studio(llm=QuizLLM())
        [ep] = studio.plan(1)
        ep = studio.write(ep)
        ep.data["cast"] = "b"
        desc = studio.default_meta(ep)["description"]
        self.assertIn("出演: 人形B", desc)
        self.assertIn("https://example.booth.pm/", desc)
        self.assertIn("VOICEVOX:B", desc)
        self.assertIn(quiz.NAME_NG, desc)
        self.assertNotIn(ep.data["script"]["answer"] + "（", desc)

    def test_waits_until_previous_episode_is_published(self):
        studio = self.box.studio(llm=QuizLLM())
        [ep] = studio.plan(1)
        ep.set(E.REVIEW)
        self.assertEqual(studio.make(1), [])
        self.assertIn("公開されていない", studio.auto()[-1])


class StageTest(unittest.TestCase):
    """劇場の画面（ffmpeg を使わずに1枚だけ描く）。"""

    def test_quiz_frame_draws_cards_and_stamp(self):
        from studio.render import Painter
        box = quiz_box()
        self.addCleanup(box.cleanup)
        painter = Painter(box.cfg)
        cards = [{"letter": "A", "text": "本当の雑学"}, {"letter": "C", "text": "ウソの雑学"}]
        plain = painter.quiz_slide((540, 960), "ウソはどれだ？", cards, "字幕", 0.5)
        marked = painter.quiz_slide((540, 960), "前回の答え", cards, "字幕", 0.5, mark="C",
                                    names=["taro"])
        self.assertEqual(plain.size, (540, 960))

        def reds(img):
            return sum(1 for r, g, b in img.getdata() if r > 170 and g < 70 and b < 70)
        self.assertGreater(reds(marked), reds(plain) + 200)   # 朱の判子と札のふち


def can_render():
    exe = shutil.which("ffmpeg")
    if not exe:
        return False
    out = subprocess.run([exe, "-hide_banner", "-encoders"], capture_output=True, text=True)
    return "libx264" in out.stdout


@unittest.skipUnless(can_render(), "libx264 入りの ffmpeg が必要")
class RenderQuizTest(unittest.TestCase):
    def test_make_builds_a_vertical_short_only(self):
        box = quiz_box()
        self.addCleanup(box.cleanup)
        studio = box.studio(llm=QuizLLM())
        [ep] = studio.make(1)
        self.assertEqual(ep.status, E.REVIEW)
        self.assertEqual(ep.data["outputs"], ["short.mp4"])
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "stream=width,height", "-of", "json",
             str(ep.file("short.mp4"))], capture_output=True, text=True, check=True).stdout)
        video = next(s for s in info["streams"] if "width" in s)
        self.assertEqual((video["width"], video["height"]), (180, 320))

    def test_api_upload_of_short_only_episode(self):
        box = quiz_box()
        self.addCleanup(box.cleanup)
        box.cfg["youtube"]["upload"] = "api"
        yt = _ctx.FakeYouTube()
        studio = box.studio(llm=QuizLLM(), youtube=yt)
        [ep] = studio.make(1)
        done = studio.approve(ep.id)
        self.assertEqual(done.status, E.PUBLISHED)
        self.assertEqual(yt.uploads[0][0], "short.mp4")
        self.assertIn("#Shorts", yt.uploads[0][1]["title"])
        self.assertEqual(done.data["published"]["url"], "https://youtube.com/shorts/vid1")


if __name__ == "__main__":
    unittest.main()
