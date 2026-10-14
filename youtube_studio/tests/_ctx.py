"""テスト用の部品: 偽のAI・偽のVOICEVOX・小さな画面サイズの設定。"""

import json
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import config  # noqa: E402
from studio.episode import Library  # noqa: E402
from studio.pipeline import Studio  # noqa: E402
from studio.voice import VoiceVox, silent_wav  # noqa: E402

LONG_NARRATION = "ここが大事なところです。" * 40


def script_json(title="テスト動画", checks=None):
    return {
        "title": title, "title_options": ["別案A"], "thumbnail_text": "3分で分かる",
        "hook": "この動画を見れば悩みが解決します。最後まで見てください。",
        "sections": [
            {"heading": "一つ目", "points": ["要点A", "要点B"], "narration": LONG_NARRATION},
            {"heading": "二つ目", "points": ["要点C"], "narration": LONG_NARRATION},
        ],
        "outro": "まとめです。次の動画もどうぞ。",
        "short": {"title": "ショート版", "narration": "一番おいしいところだけ話します。以上です。"},
        "description": "結論から言うとこうです。", "tags": ["テスト", "解説"],
        "checks": checks if checks is not None else ["数字の出典を確認"],
    }


class FakeLLM:
    """企画と台本を順に返す。返事は replies を先頭から使い、尽きたら自動で作る。"""

    def __init__(self, replies=None):
        self.replies = list(replies or [])
        self.calls = []

    def complete(self, system, user):
        self.calls.append(user)
        if self.replies:
            return self.replies.pop(0)
        if "企画を" in user and "topics" in user:
            return json.dumps({"topics": [{"title": f"企画{i}", "angle": "独自の切り口",
                                           "why": "需要がある"} for i in range(3)]},
                              ensure_ascii=False)
        return json.dumps(script_json(), ensure_ascii=False)


def fake_voice_transport(url, body, timeout):
    if "/audio_query" in url:
        return json.dumps({"speedScale": 1.0}).encode()
    return silent_wav(0.4)


def fake_voice():
    return VoiceVox(transport=fake_voice_transport)


class Sandbox:
    """一時フォルダに youtube_studio の設定を用意する。"""

    def __init__(self, **overrides):
        self.dir = Path(tempfile.mkdtemp(prefix="ytstudio-"))
        base = Path(__file__).resolve().parents[1]
        shutil.copy(base / "channel.json", self.dir / "channel.json")
        patch = {"channel": {"name": "テストch", "theme": "家計の見直し",
                             "audience": "共働きの30代"},
                 "format": {"long_minutes": 1, "plan_batch": 3},
                 "render": {"width": 320, "height": 180, "fps": 10}}
        self.cfg = config.merge(config.load(self.dir), config.merge(patch, overrides))

    def studio(self, llm=None, youtube=None):
        return Studio(self.cfg, llm=llm or FakeLLM(), voice=fake_voice(), youtube=youtube,
                      library=Library(self.dir / "episodes"))

    def cleanup(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class FakeYouTube:
    def __init__(self):
        self.uploads = []
        self.thumbs = []

    def upload(self, video, meta, publish_at=""):
        self.uploads.append((video.name, meta, publish_at))
        return f"vid{len(self.uploads)}"

    def set_thumbnail(self, video_id, image):
        self.thumbs.append(video_id)

    def channel_videos(self, limit=50):
        return [{"id": "a", "title": "伸びた動画", "views": 1200},
                {"id": "b", "title": "伸びなかった動画", "views": 30}]
