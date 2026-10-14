import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

import _ctx
from studio import episode as E
from studio.review import make_server

class _Stay(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None  # 303 をそのまま受け取る


NO_REDIRECT = urllib.request.build_opener(urllib.request.ProxyHandler({}), _Stay())


class ReviewServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.box = _ctx.Sandbox()
        cls.studio = cls.box.studio()
        cls.eps = cls.studio.make(3)  # 承認・見送り用に2本、表示確認用に1本
        cls.server = make_server(cls.studio, host="127.0.0.1", port=0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.box.cleanup()

    def get(self, path, headers=None):
        req = urllib.request.Request(self.base + path, headers=headers or {})
        try:
            with NO_REDIRECT.open(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as exc:
            return exc.code, dict(exc.headers), exc.read()

    def post(self, path, **form):
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(self.base + path, data=data, method="POST")
        try:
            with NO_REDIRECT.open(req, timeout=10) as r:
                return r.status, r.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()

    def test_index_lists_episodes_waiting_for_review(self):
        status, _, body = self.get("/")
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("確認待ち", html)
        self.assertIn("テスト動画", html)
        self.assertIn("width=device-width", html)

    def test_episode_page_has_players_checks_and_both_buttons(self):
        ep = self.eps[2]
        status, _, body = self.get(f"/ep/{ep.id}")
        html = body.decode()
        self.assertEqual(status, 200)
        self.assertIn(f"/media/{ep.id}/long.mp4", html)
        self.assertIn(f"/media/{ep.id}/short.mp4", html)
        self.assertIn("数字の出典を確認", html)
        self.assertIn("承認する", html)
        self.assertIn("見送る", html)

    def test_media_supports_range_requests_for_seeking(self):
        ep = self.eps[0]
        size = ep.file("long.mp4").stat().st_size
        status, headers, body = self.get(f"/media/{ep.id}/long.mp4", {"Range": "bytes=10-19"})
        self.assertEqual(status, 206)
        self.assertEqual(len(body), 10)
        self.assertEqual(headers["Content-Range"], f"bytes 10-19/{size}")
        self.assertEqual(body, ep.file("long.mp4").read_bytes()[10:20])
        status, _, body = self.get(f"/media/{ep.id}/long.mp4")
        self.assertEqual((status, len(body)), (200, size))

    def test_only_known_files_are_served(self):
        ep = self.eps[0]
        self.assertEqual(self.get(f"/media/{ep.id}/episode.json")[0], 404)
        self.assertEqual(self.get("/media/../channel.json/long.mp4")[0], 404)
        self.assertEqual(self.get("/ep/nope")[0], 404)

    def test_approve_and_reject_through_the_form(self):
        a, b = self.eps[:2]
        status, _ = self.post(f"/ep/{a.id}/approve", title="スマホで直した", tags="x、y",
                              description="", publish_at="")
        self.assertEqual(status, 303)
        got = self.studio.library.get(a.id)
        self.assertEqual(got.status, E.APPROVED)
        self.assertEqual(got.data["final"]["title"], "スマホで直した")
        self.assertEqual(got.data["final"]["tags"], ["x", "y"])
        _, _, body = self.get(f"/ep/{a.id}")
        self.assertIn("YouTube Studio に貼る内容", body.decode())

        status, _ = self.post(f"/ep/{a.id}/published", url="https://youtu.be/abc")
        self.assertEqual(self.studio.library.get(a.id).status, E.PUBLISHED)

        status, _ = self.post(f"/ep/{b.id}/reject", reason="テンポが遅い")
        self.assertEqual(self.studio.library.get(b.id).status, E.REJECTED)
        self.assertEqual(self.studio.library.memory()["feedback"][-1]["episode"], b.id)

        # 二度押しは画面に理由を出す
        status, body = self.post(f"/ep/{b.id}/reject", reason="")
        self.assertEqual(status, 400)
        self.assertIn("できませんでした", body)


class LanOnlyTest(unittest.TestCase):
    def test_outside_addresses_are_refused(self):
        box = _ctx.Sandbox()
        self.addCleanup(box.cleanup)
        server = make_server(box.studio(), host="127.0.0.1", port=0)
        self.addCleanup(server.server_close)
        handler = server.RequestHandlerClass
        allowed = handler.__new__(handler)
        allowed.client_address = ("192.168.1.5", 1)
        self.assertTrue(allowed._allowed())
        allowed.client_address = ("8.8.8.8", 1)
        self.assertFalse(allowed._allowed())


if __name__ == "__main__":
    unittest.main()
