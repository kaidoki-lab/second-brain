import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import _ctx  # noqa: F401

from fxbot.cli import main


def call(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        code = main(list(argv))
    return code, out.getvalue()


class CliTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.csv = str(self.dir / "s.csv")
        self.assertEqual(call("sample", "--out", self.csv, "--bars", "1200")[0], 0)

    def test_backtest_writes_trades(self):
        trades = self.dir / "t.csv"
        code, out = call("backtest", "--csv", self.csv, "--params", "fast=10,slow=40", "--trades", str(trades))
        self.assertEqual(code, 0)
        self.assertIn("最大ドローダウン", out)
        self.assertTrue(trades.read_text(encoding="utf-8").startswith("direction,"))

    def test_optimize(self):
        code, out = call("optimize", "--csv", self.csv, "--grid", "fast=10,20", "slow=20,40", "--top", "3")
        self.assertEqual(code, 0)
        self.assertIn("fast=10,slow=40", out)
        self.assertNotIn("fast=20,slow=20", out)

    def test_bad_params_is_error_not_crash(self):
        code, out = call("backtest", "--csv", self.csv, "--params", "nope=1")
        self.assertEqual(code, 1)
        self.assertIn("[エラー]", out)

    def test_strategies(self):
        self.assertIn("breakout", call("strategies")[1])


if __name__ == "__main__":
    unittest.main()
