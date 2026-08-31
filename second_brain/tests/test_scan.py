"""ファイル名による自動検出と取り込み（本文は読まない）。"""

import tempfile
import unittest
from pathlib import Path

from _ctx import fresh_store
from secondbrain.scan import find_files, guess_phase, import_handoffs


def build_tree(root: Path) -> None:
    (root / "企画A").mkdir()
    (root / "企画A" / "GR-02_ハンドオフ.md").write_text("本文はここにある", encoding="utf-8")
    (root / "企画A" / "メモ.md").write_text("関係ない", encoding="utf-8")
    (root / "企画B").mkdir()
    (root / "企画B" / "handoff_2026.txt").write_text("x", encoding="utf-8")
    (root / "企画B" / "HANDOFF-final.docx").write_text("x", encoding="utf-8")
    (root / "ハンドオフ_雑記.md").write_text("x", encoding="utf-8")
    (root / "node_modules").mkdir()
    (root / "node_modules" / "handoff.md").write_text("x", encoding="utf-8")
    (root / ".git").mkdir()
    (root / ".git" / "ハンドオフ.md").write_text("x", encoding="utf-8")


class FindFilesTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_tree(self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def names(self, **kwargs):
        return sorted(p.name for p in find_files(self.root, **kwargs)["files"])

    def test_finds_japanese_and_romaji_names(self):
        self.assertEqual(self.names(), [
            "GR-02_ハンドオフ.md", "HANDOFF-final.docx", "handoff_2026.txt",
            "ハンドオフ_雑記.md"])

    def test_ignores_unrelated_files(self):
        self.assertNotIn("メモ.md", self.names())

    def test_skips_noise_directories(self):
        found = [str(p) for p in find_files(self.root)["files"]]
        self.assertFalse([p for p in found if "node_modules" in p or ".git" in p])

    def test_non_recursive_stays_at_the_top(self):
        self.assertEqual(self.names(recursive=False), ["ハンドオフ_雑記.md"])

    def test_custom_keyword(self):
        self.assertEqual(self.names(keywords=["雑記"]), ["ハンドオフ_雑記.md"])

    def test_extension_filter(self):
        self.assertEqual(self.names(extensions=[".txt"]), ["handoff_2026.txt"])

    def test_missing_directory_is_reported_not_raised(self):
        result = find_files("/no/such/place")
        self.assertIn("見つかりません", result["error"])
        self.assertEqual(result["files"], [])

    def test_phase_is_guessed_from_the_file_name(self):
        self.assertEqual(guess_phase("GR-02_ハンドオフ.md"), "GR-02")
        self.assertEqual(guess_phase("ハンドオフ.md"), "")


class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_tree(self.root)
        self.store = fresh_store()
        self.store.upsert_project("未分類", "未分類")

    def tearDown(self):
        self.tmp.cleanup()

    def test_import_registers_every_hit(self):
        result = import_handoffs(self.store, "未分類", self.root)
        self.assertEqual(len(result["added"]), 4)
        self.assertTrue(all(h["file_exists"] for h in result["added"]))
        self.assertEqual(len(self.store.list_handoffs("未分類")), 4)

    def test_import_never_stores_the_body(self):
        import_handoffs(self.store, "未分類", self.root)
        for handoff in self.store.list_handoffs("未分類"):
            self.assertNotIn("本文はここにある", str(handoff))

    def test_re_import_does_not_duplicate(self):
        import_handoffs(self.store, "未分類", self.root)
        again = import_handoffs(self.store, "未分類", self.root)
        self.assertEqual(len(again["added"]), 0)
        self.assertEqual(len(again["already"]), 4)
        self.assertEqual(len(self.store.list_handoffs("未分類")), 4)

    def test_moved_file_is_flagged_after_verify(self):
        import_handoffs(self.store, "未分類", self.root)
        (self.root / "ハンドオフ_雑記.md").unlink()
        result = self.store.verify_handoffs()
        self.assertEqual(len(result["missing"]), 1)
        missing = self.store.search_handoffs(missing_only=True)
        self.assertEqual(missing[0]["title"], "ハンドオフ_雑記")

    def test_unknown_project_is_rejected(self):
        from secondbrain.store import NotFound
        with self.assertRaises(NotFound):
            import_handoffs(self.store, "存在しない企画", self.root)


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        build_tree(self.root)
        self.store = fresh_store()
        self.store.upsert_project("未分類", "未分類")
        self.store.upsert_project("企画B", "企画B")
        import_handoffs(self.store, "未分類", self.root)

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_by_keyword(self):
        hits = self.store.search_handoffs("GR-02")
        self.assertEqual([h["title"] for h in hits], ["GR-02_ハンドオフ"])

    def test_search_is_case_insensitive_on_path(self):
        self.assertTrue(self.store.search_handoffs("handoff_2026"))

    def test_search_by_project(self):
        self.assertEqual(len(self.store.search_handoffs(project="未分類")), 4)
        self.assertEqual(len(self.store.search_handoffs(project="企画B")), 0)

    def test_reassign_to_another_project(self):
        handoff = self.store.search_handoffs("GR-02")[0]
        moved = self.store.update_handoff(handoff["id"], project_id="企画B")
        self.assertEqual(moved["project_id"], "企画B")
        self.assertEqual(len(self.store.search_handoffs(project="企画B")), 1)

    def test_delete_removes_the_entry_but_not_the_file(self):
        handoff = self.store.search_handoffs("GR-02")[0]
        path = Path(handoff["file_path"])
        self.store.delete_handoff(handoff["id"])
        self.assertIsNone(self.store.get_handoff(handoff["id"]))
        self.assertTrue(path.exists())      # ファイルは残る


if __name__ == "__main__":
    unittest.main()
