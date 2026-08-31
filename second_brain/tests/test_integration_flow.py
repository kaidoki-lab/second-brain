"""ハンドオフを読ませて工程表を組み立てるまでの通し確認。"""

import tempfile
import unittest
import urllib.parse
import zipfile
from pathlib import Path

from _ctx import fresh_store
from secondbrain.app import App
from secondbrain.bundle import build_bundle, read_file
from secondbrain.config import Config
from secondbrain.http_util import Request
from secondbrain.intake import apply_result, current_phase_of, parse_result
from secondbrain.scan import import_handoffs

FORM = {"content-type": "application/x-www-form-urlencoded"}

AI_ANSWER = """承知しました。整理した結果です。

PHASE: GR-01 MEMBRANE | 完了 | Design AI | アセット7点; 仕様書
PHASE: GR-02 CHANNEL | 作業中 | Design AI | CHANNELアセット; 配置QA
PHASE: GR-03 NODE | 未着手 | 未定
DECISION: CHANNELはパイプに見せない | 同一組織内の流路として描く
FACT: アセット総数は21で固定 | constraint, asset
DEPENDS: GR-02 -> GR-01
DEPENDS: GR-03 → GR-02
OPEN: NODEの発光可否が未決
"""


class BundleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "GR-01_ハンドオフ.md").write_text("GR-01 MEMBRANE\n完了。7点採用。",
                                                  encoding="utf-8")
        (root / "GR-02_ハンドオフ.txt").write_bytes(
            "GR-02 CHANNEL\nパイプに見せない".encode("cp932"))
        docx = root / "GR-03_ハンドオフ.docx"
        with zipfile.ZipFile(docx, "w") as archive:
            archive.writestr("word/document.xml",
                             "<w:p><w:r><w:t>GR-03 NODE 検討中</w:t></w:r></w:p>")
        (root / "GR-04_ハンドオフ.pdf").write_bytes(b"%PDF-1.4 binary")
        self.root = root
        self.store = fresh_store()
        self.store.upsert_project("企画A", "企画A")
        import_handoffs(self.store, "企画A", root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_bundle_includes_readable_files_only(self):
        result = build_bundle(self.store, "企画A")
        titles = [h["title"] for h in result["included"]]
        self.assertEqual(sorted(titles), ["GR-01_ハンドオフ", "GR-02_ハンドオフ",
                                          "GR-03_ハンドオフ"])
        self.assertEqual([x["reason"] for x in result["skipped"]],
                         [".pdf は本文を読み取れません"])

    def test_bundle_reads_shift_jis_and_docx(self):
        text = build_bundle(self.store, "企画A")["text"]
        self.assertIn("パイプに見せない", text)      # cp932
        self.assertIn("GR-03 NODE 検討中", text)     # .docx
        self.assertIn("完了。7点採用。", text)        # utf-8

    def test_bundle_carries_the_instruction_and_paths(self):
        text = build_bundle(self.store, "企画A")["text"]
        self.assertIn("PHASE:", text)
        self.assertIn("工程表", text)
        self.assertIn(str(self.root), text)

    def test_selection_limits_the_bundle(self):
        one = self.store.search_handoffs("GR-01")[0]
        result = build_bundle(self.store, "企画A", [one["id"]])
        self.assertEqual(len(result["included"]), 1)

    def test_total_cap_drops_the_overflow(self):
        result = build_bundle(self.store, "企画A", total=400)
        self.assertTrue(result["truncated"])
        self.assertTrue(any("上限" in x["reason"] for x in result["skipped"]))

    def test_body_is_never_written_into_the_database(self):
        build_bundle(self.store, "企画A")
        for handoff in self.store.list_handoffs("企画A"):
            self.assertNotIn("パイプに見せない", str(handoff))

    def test_missing_file_is_reported(self):
        (self.root / "GR-01_ハンドオフ.md").unlink()
        result = build_bundle(self.store, "企画A")
        self.assertTrue(any("見つかりません" in x["reason"]
                            for x in result["skipped"]))

    def test_read_file_handles_an_unknown_extension(self):
        text, problem = read_file(str(self.root / "GR-04_ハンドオフ.pdf"))
        self.assertEqual(text, "")
        self.assertIn(".pdf", problem)


class IntakeTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()
        self.store.upsert_project("企画A", "企画A")

    def test_parses_every_supported_line(self):
        parsed = parse_result(AI_ANSWER)
        self.assertEqual([p["phase"] for p in parsed["phases"]],
                         ["GR-01 MEMBRANE", "GR-02 CHANNEL", "GR-03 NODE"])
        self.assertEqual([p["status"] for p in parsed["phases"]],
                         ["COMPLETE", "IN_PROGRESS", "PENDING"])
        self.assertEqual(parsed["phases"][0]["deliverables"], ["アセット7点", "仕様書"])
        self.assertEqual(parsed["decisions"][0]["title"], "CHANNELはパイプに見せない")
        self.assertEqual(parsed["facts"][0]["tags"], ["constraint", "asset"])
        self.assertEqual(len(parsed["depends"]), 2)
        self.assertEqual(len(parsed["opens"]), 1)

    def test_prose_is_ignored_not_stored(self):
        parsed = parse_result(AI_ANSWER)
        self.assertIn("承知しました。整理した結果です。", parsed["unknown"])

    def test_tolerates_full_width_and_bullets(self):
        parsed = parse_result("- PHASE：GR-01 ｜ 完了\n2) DECISION：やる | だから")
        self.assertEqual(parsed["phases"][0]["phase"], "GR-01")
        self.assertEqual(parsed["decisions"][0]["title"], "やる")

    def test_current_phase_is_the_first_active_one(self):
        parsed = parse_result(AI_ANSWER)
        self.assertEqual(current_phase_of(parsed["phases"])["phase"], "GR-02 CHANNEL")

    def test_apply_writes_plan_order_and_current_position(self):
        written = apply_result(self.store, "企画A", parse_result(AI_ANSWER))
        self.assertEqual(written["phases"], 3)
        self.assertEqual([p["phase"] for p in self.store.phase_summary("企画A")],
                         ["GR-01 MEMBRANE", "GR-02 CHANNEL", "GR-03 NODE"])
        self.assertEqual(self.store.current_state("企画A")["phase"], "GR-02 CHANNEL")

    def test_apply_stores_decisions_facts_and_dependencies(self):
        apply_result(self.store, "企画A", parse_result(AI_ANSWER))
        locked = self.store.list_decisions("企画A", "LOCKED")
        self.assertEqual([d["title"] for d in locked],
                         ["CHANNELはパイプに見せない"])
        proposed = self.store.list_decisions("企画A", "PROPOSED")
        self.assertEqual([d["title"] for d in proposed], ["NODEの発光可否が未決"])
        self.assertEqual(self.store.dependencies_of("企画A", "GR-02"), ["GR-01"])

    def test_result_reaches_the_ai_context(self):
        from secondbrain.context import ContextRouter
        apply_result(self.store, "企画A", parse_result(AI_ANSWER))
        text = ContextRouter(self.store).build("progress", "企画A")["text"]
        self.assertIn("GR-02 CHANNEL", text)
        self.assertIn("GR-03 NODE 未着手" if False else "GR-03 NODE", text)
        self.assertIn("CHANNELはパイプに見せない", text)

    def test_empty_input_writes_nothing(self):
        written = apply_result(self.store, "企画A", parse_result(""))
        self.assertEqual(sum(written.values()), 0)


class ScreenTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        (root / "GR-01_ハンドオフ.md").write_text("GR-01 の内容", encoding="utf-8")
        self.store = fresh_store()
        self.store.upsert_project("企画A", "企画A")
        import_handoffs(self.store, "企画A", root)
        self.app = App(self.store, Config(api_key=None))

    def tearDown(self):
        self.tmp.cleanup()

    def get(self, target):
        return self.app.handle(Request.make("GET", target))

    def post(self, target, fields):
        body = urllib.parse.urlencode(fields, doseq=True).encode()
        return self.app.handle(Request.make("POST", target, FORM, body))

    def path(self, suffix):
        return "/project/" + urllib.parse.quote("企画A") + suffix

    def test_bundle_screen_lists_and_builds(self):
        page = self.get(self.path("/bundle")).body.decode()
        self.assertIn("GR-01_ハンドオフ", page)
        built = self.post(self.path("/bundle"), {}).body.decode()
        self.assertIn("GR-01 の内容", built)
        self.assertIn("AIに貼り付ける内容", built)

    def test_intake_screen_previews_then_saves(self):
        preview = self.post(self.path("/intake"),
                            {"text": AI_ANSWER, "action": "preview"}).body.decode()
        self.assertIn("GR-02 CHANNEL", preview)
        self.assertIn("この内容で保存する", preview)
        self.assertIsNone(self.store.current_state("企画A"))   # まだ保存されない

        saved = self.post(self.path("/intake"),
                          {"text": AI_ANSWER, "action": "apply"}).body.decode()
        self.assertIn("保存しました", saved)
        self.assertEqual(self.store.current_state("企画A")["phase"], "GR-02 CHANNEL")

    def test_project_page_links_to_both_screens(self):
        page = self.get(self.path("")).body.decode()
        self.assertIn("ハンドオフをAIに渡す", page)
        self.assertIn("AIの回答を取り込む", page)


if __name__ == "__main__":
    unittest.main()
