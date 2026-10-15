import io
import json
import math
import subprocess
import unittest
import wave
from array import array

import _ctx
from studio import avatar
from studio.avatar import AvatarError


def tone(pattern, rate=24000, step=0.1):
    """pattern の各文字ごとに step 秒: '.'=無音 '-'=小さい声 '#'=大きい声。"""
    amp = {".": 0, "-": 2500, "#": 12000}
    data = array("h")
    for ch in pattern:
        for i in range(int(rate * step)):
            data.append(int(amp[ch] * math.sin(2 * math.pi * 200 * i / rate)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return buf.getvalue()


class TrackTest(unittest.TestCase):
    def test_mouth_follows_loudness(self):
        track = avatar.mouth_track(tone("..##..--.."), fps=10)
        self.assertEqual(len(track), 10)
        self.assertEqual(track[0], 0)
        self.assertEqual(track[2:4], [2, 2])
        self.assertEqual(track[6:8], [1, 1])
        self.assertEqual(track[-1], 0)

    def test_silence_keeps_mouth_closed(self):
        self.assertEqual(set(avatar.mouth_track(tone("....."), fps=10)), {0})

    def test_blinks_are_short_and_repeat(self):
        blinks = avatar.blink_track(30 * 20, fps=30)
        starts = [i for i in range(1, len(blinks)) if blinks[i] and not blinks[i - 1]]
        self.assertGreaterEqual(len(starts), 3)
        self.assertLess(sum(blinks), len(blinks) * 0.1)


class StreamTest(unittest.TestCase):
    def setUp(self):
        self.box = _ctx.Sandbox()
        self.addCleanup(self.box.cleanup)

    def test_switch_list_covers_the_whole_narration(self):
        listing = avatar.write_stream(self.box.cfg, tone("#.#-..##" * 3), 30, 120,
                                      self.box.dir / "work")
        text = listing.read_text(encoding="utf-8")
        total = sum(float(line.split()[1]) for line in text.splitlines()
                    if line.startswith("duration"))
        self.assertAlmostEqual(total, 2.4, delta=0.05)
        self.assertIn("avatar_open.png", text)
        self.assertEqual(len(list((self.box.dir / "work").glob("avatar_*.png"))), 6)

    def test_custom_avatar_images_are_used(self):
        from PIL import Image
        folder = self.box.dir / "my_avatar"
        folder.mkdir()
        for name, color in (("closed", "red"), ("half", "green"), ("open", "blue")):
            Image.new("RGBA", (400, 200), color).save(folder / f"{name}.png")
        self.box.cfg["avatar"]["dir"] = "my_avatar"
        images = avatar.sprites(self.box.cfg, 100)
        self.assertEqual(images[(2, False)].getpixel((5, 5))[:3], (0, 0, 255))
        self.assertEqual(images[(2, False)].size, (100, 50))  # 縦横比を保つ
        self.assertIs(images[(0, True)], images[(0, False)])  # 瞬き画像が無ければ使い回す

    def test_missing_custom_image_is_explained(self):
        (self.box.dir / "empty").mkdir()
        self.box.cfg["avatar"]["dir"] = "empty"
        with self.assertRaisesRegex(AvatarError, "closed.png"):
            avatar.sprites(self.box.cfg, 100)

    def test_avatar_stays_clear_of_text_areas(self):
        size, x, y = avatar.layout((1920, 1080), self.box.cfg)
        self.assertGreater(x, 1920 / 2)
        self.assertLess(y + size, 1080 - 211)            # 2行字幕の帯より上
        size, x, y = avatar.layout((1080, 1920), self.box.cfg)
        self.assertLess(y + size, 1920 - 420 - 245)      # ショートの字幕の帯より上


class RenderWithAvatarTest(unittest.TestCase):
    def test_video_with_puppet_keeps_audio_length(self):
        box = _ctx.Sandbox(avatar={"enabled": True})
        self.addCleanup(box.cleanup)
        [ep] = box.studio().make(1)
        info = json.loads(subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json",
             str(ep.file("long.mp4"))], capture_output=True, text=True, check=True).stdout)
        timeline = json.loads(ep.file("timeline.json").read_text(encoding="utf-8"))
        expected = sum(t["duration"] + 0.25 for t in timeline["long"])
        self.assertAlmostEqual(float(info["format"]["duration"]), expected, delta=0.6)


if __name__ == "__main__":
    unittest.main()
