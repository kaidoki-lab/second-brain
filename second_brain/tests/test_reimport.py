"""同じ内容を二度取り込んでもデータが増えないこと。

まろの環境では import.bat を何度も押す運用になるため、再取り込みが
無害であることを保証する。
"""

import io
import contextlib
import tempfile
import unittest
from pathlib import Path

from _ctx import fresh_store
from secondbrain.cli import main
from secondbrain.intake import apply_bulk, parse_bulk

MEMO = """PROFILE: 呼び名は「まろ」 | 基本
PROFILE: 低スペックPC。作業は1日1〜2時間 | 環境

PROJECT: 山村家 | ACTIVE | ラーメン店
PHASE: 開店準備 | 作業中 | まろ | ポスター; 名刺
PHASE: オープン企画 | 未着手
DECISION: 屋号は「横浜家系ラーメン 山村家」 | 山村屋から変更
FACT: オープンは2026-09-26 | 日程
OPEN: 光熱費が3万か30万か未確認
DEPENDS: オープン企画 -> 開店準備
"""


def snapshot(store):
    return {
        "projects": len(store.list_projects()),
        "profile": len(store.list_profile()),
        "decisions": len(store.list_decisions("山村家")),
        "facts": len(store.list_facts("山村家")),
        "phases": len(store.phase_summary("山村家")),
        "states": len(store.state_history("山村家")),
        "relations": len(store.list_relations("山村家")),
        "current": store.current_state("山村家")["phase"],
    }


class ReimportTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()

    def test_importing_three_times_changes_nothing(self):
        apply_bulk(self.store, parse_bulk(MEMO))
        first = snapshot(self.store)
        apply_bulk(self.store, parse_bulk(MEMO))
        apply_bulk(self.store, parse_bulk(MEMO))
        self.assertEqual(snapshot(self.store), first)

    def test_expected_counts_on_the_first_import(self):
        apply_bulk(self.store, parse_bulk(MEMO))
        self.assertEqual(snapshot(self.store), {
            # states が3なのは、現在地を示すために「開店準備」を最後へ
            # もう一度積むため（append-only で最後の行＝現在地）。
            "projects": 1, "profile": 2, "decisions": 2, "facts": 1,
            "phases": 2, "states": 3, "relations": 1, "current": "開店準備"})

    def test_same_decision_title_updates_instead_of_adding(self):
        apply_bulk(self.store, parse_bulk(MEMO))
        changed = MEMO.replace("| 山村屋から変更", "| 看板もこの表記で統一")
        apply_bulk(self.store, parse_bulk(changed))
        decisions = self.store.list_decisions("山村家")
        self.assertEqual(len(decisions), 2)
        locked = [d for d in decisions if d["status"] == "LOCKED"][0]
        self.assertEqual(locked["body"], "看板もこの表記で統一")

    def test_a_real_status_change_is_recorded(self):
        apply_bulk(self.store, parse_bulk(MEMO))
        done = MEMO.replace("PHASE: 開店準備 | 作業中 | まろ | ポスター; 名刺",
                            "PHASE: 開店準備 | 完了 | まろ | ポスター; 名刺")
        apply_bulk(self.store, parse_bulk(done))
        phases = {p["phase"]: p["status"] for p in self.store.phase_summary("山村家")}
        self.assertEqual(phases["開店準備"], "COMPLETE")
        self.assertEqual(self.store.current_state("山村家")["phase"], "オープン企画")

    def test_facts_are_not_duplicated_across_projects(self):
        self.store.upsert_project("別企画", "別企画")
        self.store.add_fact("山村家", "同じ文言") if self.store.get_project("山村家") \
            else None
        apply_bulk(self.store, parse_bulk(MEMO))
        self.store.add_fact("別企画", "オープンは2026-09-26")
        self.assertEqual(len(self.store.list_facts("別企画")), 1)
        self.assertEqual(len(self.store.list_facts("山村家")), 1)


class LoadCommandTest(unittest.TestCase):
    def test_load_reads_a_file_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "brain.db")
            source = Path(tmp) / "input.txt"
            source.write_text(MEMO, encoding="utf-8")

            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--db", db, "load", "--file", str(source)])
            self.assertEqual(code, 0)
            printed = out.getvalue()
            self.assertIn("私について  2 件", printed)
            self.assertIn("山村家", printed)

    def test_load_accepts_shift_jis(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "brain.db")
            source = Path(tmp) / "input.txt"
            source.write_bytes(MEMO.encode("cp932"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--db", db, "load", "--file", str(source)]), 0)

    def test_missing_file_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = main(["--db", str(Path(tmp) / "b.db"), "load",
                             "--file", str(Path(tmp) / "nope.txt")])
            self.assertEqual(code, 1)
            self.assertIn("見つかりません", out.getvalue())


if __name__ == "__main__":
    unittest.main()
