import io
import contextlib
import tempfile
import unittest
from pathlib import Path

from _ctx import fresh_store, seeded_store
from secondbrain.cli import index_directory, main


class IndexTest(unittest.TestCase):
    def test_index_registers_files_without_reading_them(self):
        store = fresh_store()
        store.upsert_project("p1")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "GR-01.md").write_text("本文は読まれない", encoding="utf-8")
            (root / "GR-02.md").write_text("x" * 5000, encoding="utf-8")
            (root / "notes.txt").write_text("skip me", encoding="utf-8")
            registered = index_directory(store, "p1", tmp, "*.md")
        self.assertEqual(registered, ["GR-01", "GR-02"])
        handoffs = store.list_handoffs("p1")
        self.assertTrue(all(h["file_exists"] for h in handoffs))
        # The index stores a reference, never the body.
        for handoff in handoffs:
            self.assertNotIn("本文", str(handoff))

    def test_index_rejects_a_missing_directory(self):
        store = fresh_store()
        store.upsert_project("p1")
        with self.assertRaises(SystemExit):
            index_directory(store, "p1", "/no/such/dir", "*.md")


class CliTest(unittest.TestCase):
    def run_cli(self, *args, db=None):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = main(["--db", db, *args])
        return code, out.getvalue()

    def test_init_seed_context_and_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "brain.db")
            code, out = self.run_cli("init", db=db)
            self.assertEqual(code, 0)
            self.assertIn("progress", out)

            self.run_cli("seed", db=db)
            code, out = self.run_cli("context", "design", db=db)
            self.assertEqual(code, 0)
            self.assertIn("CURRENT PHASE", out)

            target = str(Path(tmp) / "brain.md")
            self.run_cli("export", "--out", target, db=db)
            self.assertIn("SYNAPTIC GROVE", Path(target).read_text(encoding="utf-8"))

    def test_verify_exits_nonzero_when_a_file_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "brain.db")
            self.run_cli("init", db=db)
            self.run_cli("seed", db=db)
            code, out = self.run_cli("verify", db=db)
            self.assertEqual(code, 1)
            self.assertIn("MISSING", out)

    def test_key_prints_a_usable_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, out = self.run_cli("key", db=str(Path(tmp) / "brain.db"))
            self.assertEqual(code, 0)
            self.assertGreaterEqual(len(out.splitlines()[0]), 32)


class ServerGuardTest(unittest.TestCase):
    def test_lan_bind_without_a_key_is_refused(self):
        from secondbrain.app import App
        from secondbrain.config import Config
        from secondbrain.server import serve
        config = Config(host="0.0.0.0", port=0, api_key=None)
        with self.assertRaises(SystemExit) as caught:
            serve(App(seeded_store(), config), config)
        self.assertIn("API key", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
