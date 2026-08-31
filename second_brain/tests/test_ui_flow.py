"""ブラウザだけで完結する操作の通し確認（コマンド入力なし）。"""

import tempfile
import unittest
import urllib.parse
from pathlib import Path

from _ctx import fresh_store
from secondbrain.app import App
from secondbrain.config import Config
from secondbrain.http_util import Request

FORM = {"content-type": "application/x-www-form-urlencoded"}


class BrowserFlowTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()
        self.app = App(self.store, Config(api_key=None))
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "企画A").mkdir()
        (root / "企画A" / "GR-02_ハンドオフ.md").write_text("本文", encoding="utf-8")
        (root / "ハンドオフ_雑記.md").write_text("x", encoding="utf-8")
        (root / "無関係.md").write_text("x", encoding="utf-8")
        self.root = root

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, target):
        return self.app.handle(Request.make("GET", target))

    def post(self, target, **fields):
        body = urllib.parse.urlencode(fields).encode()
        return self.app.handle(Request.make("POST", target, FORM, body))

    def test_full_flow_without_touching_the_command_line(self):
        # 1) 企画を作る
        created = self.post("/ui/project", name="未分類", summary="PC内のハンドオフ")
        self.assertEqual(created.status, 303)
        self.assertEqual(self.store.get_project("未分類")["name"], "未分類")

        # 2) フォルダを指定して取り込む
        imported = self.post("/ui/import", dir=str(self.root),
                             keywords="ハンドオフ, handoff", project="未分類")
        self.assertEqual(imported.status, 200)
        page = imported.body.decode()
        self.assertIn("2 件を新しく登録しました", page)
        self.assertIn("GR-02_ハンドオフ", page)
        self.assertNotIn("無関係", page)

        # 3) 一覧と検索
        listing = self.get("/handoffs").body.decode()
        self.assertIn("GR-02_ハンドオフ", listing)
        self.assertIn("ハンドオフ_雑記", listing)
        hit = self.get("/handoffs?q=" + urllib.parse.quote("雑記")).body.decode()
        self.assertIn("ハンドオフ_雑記", hit)
        self.assertNotIn("GR-02_ハンドオフ", hit)

        # 4) 別の企画へ付け替える
        self.post("/ui/project", name="企画A")
        handoff = self.store.search_handoffs("GR-02")[0]
        moved = self.post("/ui/handoff/update", id=handoff["id"], project="企画A")
        self.assertEqual(moved.status, 303)
        self.assertEqual(self.store.get_handoff(handoff["id"])["project_id"], "企画A")

        # 5) ファイルが消えたら存在確認で赤くなる
        (self.root / "ハンドオフ_雑記.md").unlink()
        verified = self.post("/ui/verify")
        self.assertIn("missing=1", verified.headers["Location"])
        missing_page = self.get("/handoffs?missing=1").body.decode()
        self.assertIn("見つからない", missing_page)
        self.assertIn("ハンドオフ_雑記", missing_page)

        # 6) 一覧から外してもファイルは残る
        target = self.store.search_handoffs("GR-02")[0]
        path = Path(target["file_path"])
        removed = self.post("/ui/handoff/delete", id=target["id"])
        self.assertEqual(removed.status, 303)
        self.assertIsNone(self.store.get_handoff(target["id"]))
        self.assertTrue(path.exists())

    def test_import_creates_the_project_when_none_is_chosen(self):
        self.post("/ui/import", dir=str(self.root), keywords="ハンドオフ",
                  project="", new_project="あとで仕分け")
        self.assertEqual(self.store.get_project("あとで仕分け")["name"], "あとで仕分け")
        self.assertEqual(len(self.store.list_handoffs("あとで仕分け")), 2)

    def test_import_defaults_to_未分類_when_nothing_is_named(self):
        self.post("/ui/import", dir=str(self.root))
        self.assertIsNotNone(self.store.get_project("未分類"))

    def test_import_without_a_folder_explains_itself(self):
        response = self.post("/ui/import", dir="")
        self.assertIn("フォルダを入力してください", response.body.decode())

    def test_import_with_a_bad_folder_explains_itself(self):
        response = self.post("/ui/import", dir="/no/such/folder")
        self.assertIn("フォルダが見つかりません", response.body.decode())

    def test_dashboard_warns_about_missing_files(self):
        self.post("/ui/import", dir=str(self.root))
        (self.root / "ハンドオフ_雑記.md").unlink()
        self.post("/ui/verify")
        body = self.get("/").body.decode()
        self.assertIn("ファイルが見つからないハンドオフが 1 件", body)

    def test_project_page_opens_for_a_japanese_id(self):
        self.post("/ui/project", name="日本語の企画名")
        encoded = urllib.parse.quote("日本語の企画名")
        response = self.get(f"/project/{encoded}")
        self.assertEqual(response.status, 200)
        self.assertIn("日本語の企画名", response.body.decode())

    def test_project_name_with_a_slash_is_still_usable(self):
        response = self.post("/ui/project", name="企画/テスト")
        self.assertEqual(response.status, 303)
        self.assertIsNotNone(self.store.get_project("企画-テスト"))


if __name__ == "__main__":
    unittest.main()
