"""「私について」— 企画に属さない、全AI共通の前提。"""

import unittest
import urllib.parse

from _ctx import fresh_store, seeded_store
from secondbrain.app import App
from secondbrain.config import Config
from secondbrain.context import PROFILE_LIMIT, ContextRouter
from secondbrain.http_util import Request
from secondbrain.intake import parse_memory
from secondbrain.store import Invalid, NotFound

FORM = {"content-type": "application/x-www-form-urlencoded"}

MEMORY = """私について記憶していることは以下です。

- 日本語でのやり取りを好む #style
* 専門用語を避けた説明を求める
1. SOT21という旧タブレットをLAN操作盤にしている
・企画は「第二の脳」と「SOT21操作盤」を並行して進めている
---
- 日本語でのやり取りを好む
"""


class ParseMemoryTest(unittest.TestCase):
    def test_strips_bullets_numbers_and_duplicates(self):
        items = parse_memory(MEMORY)
        bodies = [i["body"] for i in items]
        self.assertIn("日本語でのやり取りを好む", bodies)
        self.assertIn("専門用語を避けた説明を求める", bodies)
        self.assertIn("SOT21という旧タブレットをLAN操作盤にしている", bodies)
        self.assertEqual(len(bodies), len(set(bodies)))      # 重複は1つに

    def test_keeps_tags_out_of_the_body(self):
        item = next(i for i in parse_memory(MEMORY)
                    if i["body"] == "日本語でのやり取りを好む")
        self.assertEqual(item["tags"], ["style"])

    def test_drops_separators_and_blank_lines(self):
        bodies = [i["body"] for i in parse_memory(MEMORY)]
        self.assertNotIn("---", bodies)
        self.assertNotIn("", bodies)

    def test_category_is_applied_to_every_item(self):
        items = parse_memory("- あ\n- い", category="進め方")
        self.assertEqual({i["category"] for i in items}, {"進め方"})

    def test_overlong_lines_are_skipped(self):
        items = parse_memory("- " + "あ" * 400)
        self.assertEqual(items, [])

    def test_empty_input_is_empty_output(self):
        self.assertEqual(parse_memory(""), [])


class ProfileStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()

    def test_add_and_list_in_priority_order(self):
        self.store.add_profile("ふつうの前提")
        self.store.add_profile("最優先の前提", priority=99)
        self.assertEqual([i["body"] for i in self.store.list_profile()],
                         ["最優先の前提", "ふつうの前提"])

    def test_same_body_is_not_stored_twice(self):
        self.store.add_profile("日本語で回答する")
        self.store.add_profile("日本語で回答する", category="進め方")
        items = self.store.list_profile()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["category"], "進め方")   # 上書きされる

    def test_empty_body_is_rejected(self):
        with self.assertRaises(Invalid):
            self.store.add_profile("   ")

    def test_filter_by_category(self):
        self.store.add_profile("あ", category="進め方")
        self.store.add_profile("い", category="環境")
        self.assertEqual(len(self.store.list_profile("環境")), 1)

    def test_delete_and_clear(self):
        first = self.store.add_profile("あ")
        self.store.add_profile("い")
        self.store.delete_profile(first["id"])
        self.assertEqual(len(self.store.list_profile()), 1)
        self.assertEqual(self.store.clear_profile(), 1)
        self.assertEqual(self.store.list_profile(), [])

    def test_delete_unknown_is_reported(self):
        with self.assertRaises(NotFound):
            self.store.delete_profile(999)

    def test_writes_are_logged(self):
        self.store.add_profile("あ")
        self.assertTrue(any(c["entity"] == "profile"
                            for c in self.store.recent_changes(5)))


class ProfileContextTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        self.store.add_profile("日本語で回答する。専門用語は避ける",
                               category="進め方", priority=90)
        self.store.add_profile("SOT21をLAN操作盤として使っている", category="環境")
        self.router = ContextRouter(self.store)

    def test_every_role_receives_the_profile(self):
        for role in ("progress", "design", "builder", "critic", "explorer"):
            with self.subTest(role=role):
                text = self.router.build(role)["text"]
                self.assertIn("ABOUT THE USER", text)
                self.assertIn("日本語で回答する", text)

    def test_profile_survives_a_tight_budget(self):
        result = self.router.build("progress", budget=150)
        self.assertIn("ABOUT THE USER", result["text"])
        self.assertLessEqual(result["token_estimate"], 150)

    def test_only_the_top_items_are_handed_over(self):
        for index in range(PROFILE_LIMIT + 5):
            self.store.add_profile(f"項目{index}", priority=10)
        text = self.router.build("design")["text"]
        block = text.split("ABOUT THE USER")[1].split("\n\n")[0]
        self.assertEqual(len([l for l in block.splitlines() if l.startswith("- ")]),
                         PROFILE_LIMIT)

    def test_no_profile_means_no_section(self):
        store = seeded_store()
        self.assertNotIn("ABOUT THE USER", ContextRouter(store).build("design")["text"])


class ProfileScreenTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()
        self.app = App(self.store, Config(api_key=None))

    def get(self, target):
        return self.app.handle(Request.make("GET", target))

    def post(self, target, fields):
        body = urllib.parse.urlencode(fields, doseq=True).encode()
        return self.app.handle(Request.make("POST", target, FORM, body))

    def test_preview_then_save_only_the_checked_items(self):
        preview = self.post("/ui/profile", {"text": MEMORY, "category": "進め方",
                                            "action": "preview"}).body.decode()
        self.assertIn("取り込む項目を選ぶ", preview)
        self.assertEqual(self.store.list_profile(), [])     # まだ保存されない

        saved = self.post("/ui/profile", {
            "category": "進め方", "action": "apply",
            "item": ["日本語でのやり取りを好む", "専門用語を避けた説明を求める"]})
        self.assertEqual(saved.status, 303)
        self.assertEqual(len(self.store.list_profile()), 2)
        self.assertEqual(self.store.list_profile()[0]["category"], "進め方")

    def test_delete_from_the_screen(self):
        self.store.add_profile("消す前提")
        item = self.store.list_profile()[0]
        response = self.post("/ui/profile/delete", {"id": item["id"]})
        self.assertEqual(response.status, 303)
        self.assertEqual(self.store.list_profile(), [])

    def test_delete_without_an_id_is_400(self):
        self.assertEqual(self.post("/ui/profile/delete", {"id": ""}).status, 400)

    def test_export_box_appears_once_there_is_something(self):
        self.assertNotIn("AIに渡す用", self.get("/profile").body.decode())
        self.store.add_profile("日本語で回答する")
        page = self.get("/profile").body.decode()
        self.assertIn("AIに渡す用", page)
        self.assertIn("日本語で回答する", page)

    def test_navigation_and_dashboard_link(self):
        self.assertIn("私について", self.get("/").body.decode())

    def test_api_read_and_write(self):
        import json
        created = self.app.handle(Request.make(
            "POST", "/api/profile", {"content-type": "application/json"},
            json.dumps({"body": "日本語で回答する", "category": "進め方",
                        "priority": 80}).encode()))
        self.assertEqual(created.status, 201)
        listed = json.loads(self.get("/api/profile").body.decode())
        self.assertEqual(listed[0]["body"], "日本語で回答する")

    def test_mcp_exposes_the_profile(self):
        import json
        from secondbrain.mcp_server import MCPServer
        self.store.add_profile("日本語で回答する")
        server = MCPServer(self.store)
        result = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                "params": {"name": "get_profile", "arguments": {}}})
        payload = json.loads(result["result"]["content"][0]["text"])
        self.assertEqual(payload[0]["body"], "日本語で回答する")


if __name__ == "__main__":
    unittest.main()
