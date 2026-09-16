"""複数企画をまたぐメモを、1回の貼り付けで振り分けて取り込む。"""

import unittest
import urllib.parse

from _ctx import fresh_store
from secondbrain.app import App
from secondbrain.config import Config
from secondbrain.http_util import Request
from secondbrain.intake import apply_bulk, parse_bulk

FORM = {"content-type": "application/x-www-form-urlencoded"}

MEMO = """これは前置きの文章。

FACT: 作業時間は1日1〜2時間

PROJECT: 山村家 | ACTIVE | 横浜家系ラーメン店
PHASE: 開店準備 | 作業中 | まろ | ポスター; 名刺
DECISION: 屋号は「横浜家系ラーメン 山村家」 | 初期資料の「山村屋」から変更
FACT: オープンは2026-09-26 | 日程
OPEN: 光熱費が3万か30万か未確認

PROJECT: SYNAPTIC GROVE
PHASE: GR-01 MEMBRANE | 完了
PHASE: GR-02 CHANNEL | 作業中
DECISION: 36×36 CELL を正式仕様とする | 32×32案はレガシー
DEPENDS: GR-02 -> GR-01
"""


class ParseBulkTest(unittest.TestCase):
    def setUp(self):
        self.bulk = parse_bulk(MEMO)

    def test_splits_on_project_lines(self):
        self.assertEqual([p["name"] for p in self.bulk["projects"]],
                         ["山村家", "SYNAPTIC GROVE"])

    def test_reads_status_and_summary(self):
        first = self.bulk["projects"][0]
        self.assertEqual(first["status"], "ACTIVE")
        self.assertEqual(first["summary"], "横浜家系ラーメン店")

    def test_status_defaults_to_active(self):
        self.assertEqual(self.bulk["projects"][1]["status"], "ACTIVE")

    def test_entries_land_under_their_own_project(self):
        ramen, grove = self.bulk["projects"]
        self.assertEqual([p["phase"] for p in ramen["parsed"]["phases"]],
                         ["開店準備"])
        self.assertEqual([p["phase"] for p in grove["parsed"]["phases"]],
                         ["GR-01 MEMBRANE", "GR-02 CHANNEL"])
        self.assertEqual(len(ramen["parsed"]["opens"]), 1)
        self.assertEqual(len(grove["parsed"]["depends"]), 1)

    def test_lines_before_the_first_project_are_kept_aside(self):
        self.assertEqual(self.bulk["unassigned_total"], 1)
        self.assertEqual(self.bulk["unassigned"]["facts"][0]["body"],
                         "作業時間は1日1〜2時間")

    def test_counts_are_reported_per_project(self):
        self.assertEqual([p["total"] for p in self.bulk["projects"]], [4, 4])

    def test_full_width_and_bullets_are_accepted(self):
        bulk = parse_bulk("- PROJECT：企画A ｜ ACTIVE\n- PHASE: 工程1 | 完了")
        self.assertEqual(bulk["projects"][0]["name"], "企画A")
        self.assertEqual(bulk["projects"][0]["parsed"]["phases"][0]["status"],
                         "COMPLETE")

    def test_empty_text_is_harmless(self):
        bulk = parse_bulk("")
        self.assertEqual(bulk["projects"], [])
        self.assertEqual(bulk["unassigned_total"], 0)


class ApplyBulkTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()

    def test_creates_projects_and_writes_everything(self):
        result = apply_bulk(self.store, parse_bulk(MEMO))
        self.assertEqual([r["name"] for r in result["projects"]],
                         ["山村家", "SYNAPTIC GROVE"])
        self.assertEqual(result["total"], 8)
        self.assertEqual(self.store.get_project("山村家")["summary"],
                         "横浜家系ラーメン店")
        self.assertEqual(self.store.current_state("SYNAPTIC-GROVE")["phase"],
                         "GR-02 CHANNEL")
        self.assertEqual(self.store.dependencies_of("SYNAPTIC-GROVE", "GR-02"),
                         ["GR-01"])

    def test_unassigned_needs_a_destination(self):
        apply_bulk(self.store, parse_bulk(MEMO))
        self.assertIsNone(self.store.get_project("未分類"))

    def test_unassigned_goes_where_it_is_told(self):
        apply_bulk(self.store, parse_bulk(MEMO), unassigned_project="未分類")
        facts = self.store.list_facts("未分類")
        self.assertEqual([f["body"] for f in facts], ["作業時間は1日1〜2時間"])

    def test_existing_project_is_reused_not_duplicated(self):
        self.store.upsert_project("山村家", "山村家")
        apply_bulk(self.store, parse_bulk(MEMO))
        self.assertEqual(len(self.store.list_projects()), 2)

    def test_second_import_does_not_duplicate_relations(self):
        apply_bulk(self.store, parse_bulk(MEMO))
        apply_bulk(self.store, parse_bulk(MEMO))
        self.assertEqual(len(self.store.list_relations("SYNAPTIC-GROVE")), 1)


class BulkScreenTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()
        self.app = App(self.store, Config(api_key=None))

    def post(self, fields):
        body = urllib.parse.urlencode(fields, doseq=True).encode()
        return self.app.handle(Request.make("POST", "/ui/bulk", FORM, body))

    def test_screen_renders_with_the_format_guide(self):
        page = self.app.handle(Request.make("GET", "/bulk")).body.decode()
        self.assertIn("まとめて取り込み", page)
        self.assertIn("PROJECT:", page)

    def test_preview_does_not_save(self):
        page = self.post({"text": MEMO, "action": "preview"}).body.decode()
        self.assertIn("山村家", page)
        self.assertIn("SYNAPTIC GROVE", page)
        self.assertIn("企画の指定なし", page)
        self.assertEqual(self.store.list_projects(), [])

    def test_apply_saves_and_reports(self):
        page = self.post({"text": MEMO, "action": "apply",
                          "fallback": "未分類"}).body.decode()
        self.assertIn("件を保存しました", page)
        ids = [p["id"] for p in self.store.list_projects()]
        self.assertIn("山村家", ids)
        self.assertIn("SYNAPTIC-GROVE", ids)
        self.assertIn("未分類", ids)

    def test_navigation_includes_the_screen(self):
        page = self.app.handle(Request.make("GET", "/")).body.decode()
        self.assertIn("まとめて取り込み", page)


if __name__ == "__main__":
    unittest.main()
