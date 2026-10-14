"""VOICEVOX で読み上げ音声を作る。

文ごとに音声を作り、その長さで字幕と画面の切り替えを合わせる。
VOICEVOX は商用利用できるが、動画の概要欄に「VOICEVOX:キャラクター名」の
表記が必要（channel.json の voice.credit を概要欄へ自動で足す）。
"""

from __future__ import annotations

import io
import json
import re
import urllib.parse
import urllib.request
import wave
from typing import Any, Callable

Transport = Callable[[str, bytes | None, float], bytes]


class VoiceError(Exception):
    pass


def _post_local(url: str, body: bytes | None, timeout: float) -> bytes:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=body if body is not None else b"",
                                 headers={"Content-Type": "application/json"}, method="POST")
    with opener.open(req, timeout=timeout) as resp:
        return resp.read()


def split_sentences(text: str, limit: int = 60) -> list[str]:
    """句点・改行で区切る。長すぎる文は読点で折る（字幕に収めるため）。"""
    out: list[str] = []
    for raw in re.split(r"(?<=[。！？!?])|\n+", text):
        s = raw.strip()
        while len(s) > limit:
            cut = s.rfind("、", 0, limit)
            cut = cut + 1 if cut > limit // 3 else limit
            out.append(s[:cut].strip())
            s = s[cut:].strip()
        if s:
            out.append(s)
    return out


class VoiceVox:
    def __init__(self, url: str = "http://127.0.0.1:50021", speaker: int = 3,
                 speed: float = 1.1, transport: Transport | None = None):
        self.url = url.rstrip("/")
        self.speaker = int(speaker)
        self.speed = float(speed)
        self.transport = transport or _post_local

    def synth(self, text: str) -> bytes:
        q = urllib.parse.urlencode({"text": text, "speaker": self.speaker})
        try:
            query = json.loads(self.transport(f"{self.url}/audio_query?{q}", None, 60))
            query["speedScale"] = self.speed
            query["postPhonemeLength"] = 0.15
            return self.transport(f"{self.url}/synthesis?speaker={self.speaker}",
                                  json.dumps(query).encode("utf-8"), 120)
        except OSError as exc:
            raise VoiceError(
                f"VOICEVOX（{self.url}）に届きません。VOICEVOX を起動してから"
                f"もう一度実行してください（{exc}）") from exc


def make_voice(cfg: dict[str, Any]) -> VoiceVox:
    v = cfg["voice"]
    return VoiceVox(v.get("engine_url", "http://127.0.0.1:50021"),
                    v.get("speaker", 3), v.get("speed", 1.1))


# ================================================================== WAV

def duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes() / float(w.getframerate())


def concat(wavs: list[bytes], gap: float = 0.25) -> bytes:
    """同じ形式のWAVを、間に無音を挟んでつなぐ。"""
    if not wavs:
        raise VoiceError("つなぐ音声がありません")
    out = io.BytesIO()
    params = None
    with wave.open(out, "wb") as dst:
        for chunk in wavs:
            with wave.open(io.BytesIO(chunk)) as src:
                p = src.getparams()
                if params is None:
                    params = p
                    dst.setparams(p)
                elif (p.nchannels, p.sampwidth, p.framerate) != (
                        params.nchannels, params.sampwidth, params.framerate):
                    raise VoiceError("音声の形式がそろっていません")
                dst.writeframes(src.readframes(src.getnframes()))
                silence = int(params.framerate * gap) * params.nchannels * params.sampwidth
                dst.writeframes(b"\x00" * silence)
    return out.getvalue()


def silent_wav(seconds: float, rate: int = 24000) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(b"\x00\x00" * int(rate * seconds))
    return out.getvalue()
