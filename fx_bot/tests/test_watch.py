"""watch: state files that stop updating are reported once, recovery and clean stops too."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

import _ctx  # noqa: F401

from fxbot import watch

NOW = datetime(2026, 10, 27, 15, 0, 0)


def write(root, name, minutes_ago, stopped=False):
    path = Path(root) / name / "state_USDJPY-_210003.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"updated": (NOW - timedelta(minutes=minutes_ago)).isoformat(), "stopped": stopped,
                                "symbol": "USDJPY-", "timeframe": "H1", "magic": 210003, "strategy": "combo"}),
                    encoding="utf-8")
    return path


class WatchTest(unittest.TestCase):
    def test_status(self):
        s = {"updated": NOW.isoformat()}
        self.assertEqual(watch.status(s, NOW + timedelta(minutes=5), 10), "ok")
        self.assertEqual(watch.status(s, NOW + timedelta(minutes=11), 10), "stale")
        self.assertEqual(watch.status(dict(s, stopped=True), NOW + timedelta(hours=5), 10), "stopped")

    def test_reports_each_change_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a", 0)
            write(tmp, "b", 0, stopped=True)
            logs, clock = [], [NOW]
            steps = [lambda: None,
                     lambda: clock.__setitem__(0, NOW + timedelta(minutes=15)),      # a goes quiet
                     lambda: clock.__setitem__(0, NOW + timedelta(minutes=16)),      # still quiet: no repeat
                     lambda: write(tmp, "a", -16),                                   # a updates again
                     ]

            def sleep(_):
                if not steps:
                    raise KeyboardInterrupt
                steps.pop(0)()

            with self.assertRaises(KeyboardInterrupt):
                watch.run_watch(tmp, 10, 60, logs.append, now=lambda: clock[0], sleep=sleep)
        self.assertEqual(sum("[停止の疑い]" in m for m in logs), 1)
        self.assertEqual(sum("[復旧]" in m for m in logs), 1)
        self.assertTrue(any("停止済み" in m for m in logs))


if __name__ == "__main__":
    unittest.main()
