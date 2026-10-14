import json
import unittest

import _ctx
from studio.youtube import TOKEN_URL, YouTube, YouTubeError


class FakeGoogle:
    def __init__(self):
        self.calls = []

    def __call__(self, method, url, headers, data):
        body = data.read() if hasattr(data, "read") else data
        self.calls.append((method, url, headers, body))
        if url == TOKEN_URL:
            return 200, {}, json.dumps({"access_token": "fresh", "expires_in": 3600}).encode()
        if "uploadType=resumable" in url:
            return 200, {"location": "https://upload.example/session1"}, b""
        if url.startswith("https://upload.example/"):
            return 200, {}, json.dumps({"id": "VID123"}).encode()
        if "/thumbnails/set" in url:
            return 403, {}, json.dumps({"error": {"message": "phone not verified"}}).encode()
        if "/channels?" in url:
            return 200, {}, json.dumps({"items": [{"contentDetails": {
                "relatedPlaylists": {"uploads": "UU1"}}}]}).encode()
        if "/playlistItems?" in url:
            return 200, {}, json.dumps({"items": [{"contentDetails": {"videoId": "v1"}},
                                                  {"contentDetails": {"videoId": "v2"}}]}).encode()
        if "/videos?" in url:
            return 200, {}, json.dumps({"items": [
                {"id": "v1", "snippet": {"title": "A"}, "statistics": {"viewCount": "10"}},
                {"id": "v2", "snippet": {"title": "B"}, "statistics": {"viewCount": "5",
                                                                       "likeCount": "1"}}]}).encode()
        return 404, {}, b"{}"


class YouTubeTest(unittest.TestCase):
    def setUp(self):
        self.box = _ctx.Sandbox()
        self.addCleanup(self.box.cleanup)
        secrets_dir = self.box.dir / "secrets"
        secrets_dir.mkdir()
        (secrets_dir / "client_secret.json").write_text(json.dumps(
            {"installed": {"client_id": "cid", "client_secret": "cs"}}))
        self.google = FakeGoogle()

    def yt(self, token=None, clock=1000.0, **youtube):
        if token is not None:
            (self.box.dir / "secrets" / "token.json").write_text(json.dumps(token))
        self.box.cfg["youtube"].update(youtube)
        return YouTube(self.box.cfg, transport=self.google, clock=lambda: clock)

    def test_expired_token_is_refreshed_and_saved(self):
        yt = self.yt({"access_token": "old", "refresh_token": "r", "expires_at": 10})
        self.assertEqual(yt.access_token(), "fresh")
        saved = json.loads((self.box.dir / "secrets" / "token.json").read_text())
        self.assertEqual(saved["refresh_token"], "r")
        form = self.google.calls[0][3].decode()
        self.assertIn("grant_type=refresh_token", form)

    def test_resumable_upload_sends_metadata_then_file(self):
        yt = self.yt({"access_token": "tok", "refresh_token": "r", "expires_at": 99999})
        video = self.box.dir / "v.mp4"
        video.write_bytes(b"x" * 1000)
        vid = yt.upload(video, {"title": "題", "description": "説明", "tags": ["t"]},
                        "2030-01-01T09:00:00Z")
        self.assertEqual(vid, "VID123")
        start, put = self.google.calls
        meta = json.loads(start[3])
        self.assertEqual(meta["status"]["privacyStatus"], "private")
        self.assertEqual(meta["status"]["publishAt"], "2030-01-01T09:00:00Z")
        self.assertFalse(meta["status"]["selfDeclaredMadeForKids"])
        self.assertEqual(start[2]["X-Upload-Content-Length"], "1000")
        self.assertEqual(start[2]["Authorization"], "Bearer tok")
        self.assertEqual(put[0], "PUT")
        self.assertEqual(len(put[3]), 1000)

    def test_api_errors_carry_googles_message(self):
        yt = self.yt({"access_token": "tok", "refresh_token": "r", "expires_at": 99999})
        img = self.box.dir / "t.png"
        img.write_bytes(b"png")
        with self.assertRaisesRegex(YouTubeError, "phone not verified"):
            yt.set_thumbnail("VID", img)

    def test_channel_videos_with_api_key_only(self):
        yt = self.yt(api_key="KEY", channel_id="UC1")
        videos = yt.channel_videos()
        self.assertEqual([(v["id"], v["views"]) for v in videos], [("v1", 10), ("v2", 5)])
        first_url = self.google.calls[0][1]
        self.assertIn("key=KEY", first_url)
        self.assertIn("id=UC1", first_url)
        self.assertNotIn("Authorization", self.google.calls[0][2])

    def test_missing_setup_is_explained(self):
        with self.assertRaisesRegex(YouTubeError, "auth"):
            self.yt().channel_videos()
        with self.assertRaisesRegex(YouTubeError, "run.py auth"):
            self.yt().access_token()


if __name__ == "__main__":
    unittest.main()
