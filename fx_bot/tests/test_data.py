import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import _ctx  # noqa: F401

from fxbot import data


class DataTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_roundtrip(self):
        bars = data.synthetic(n=50)
        path = self.dir / "x.csv"
        data.write_csv(path, bars)
        self.assertEqual(data.load_csv(path), bars)

    def test_mt5_export_format(self):
        path = self.dir / "mt5.csv"
        path.write_text(
            "<DATE>\t<TIME>\t<OPEN>\t<HIGH>\t<LOW>\t<CLOSE>\t<TICKVOL>\t<VOL>\t<SPREAD>\n"
            "2024.01.02\t01:00:00\t141.020\t141.100\t140.900\t141.050\t812\t0\t3\n"
            "2024.01.02\t00:00:00\t141.000\t141.050\t140.950\t141.020\t500\t0\t3\n",
            encoding="utf-8",
        )
        bars = data.load_csv(path)
        self.assertEqual(bars[0].time, datetime(2024, 1, 2, 0, 0))   # sorted
        self.assertEqual(bars[1].close, 141.05)
        self.assertEqual(bars[1].volume, 812)

    def test_missing_columns(self):
        path = self.dir / "bad.csv"
        path.write_text("time,price\n2024-01-01,1\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            data.load_csv(path)

    def test_synthetic_is_deterministic_and_valid(self):
        a, b = data.synthetic(n=200, seed=7), data.synthetic(n=200, seed=7)
        self.assertEqual(a, b)
        for bar in a:
            self.assertLessEqual(bar.low, min(bar.open, bar.close))
            self.assertGreaterEqual(bar.high, max(bar.open, bar.close))


if __name__ == "__main__":
    unittest.main()
