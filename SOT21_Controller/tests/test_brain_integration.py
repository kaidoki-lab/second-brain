"""SOT21 panel <-> SECOND BRAIN, over a real HTTP server on a real socket.

This is the 連動 check: the tablet reads the same brain the AIs read, and a
write from the panel is visible in the next context an AI pulls.
"""

import json
import sys
import unittest
from pathlib import Path

from _ctx import BASE, make_app, make_config

BRAIN_DIR = BASE.parent / "second_brain"
sys.path.insert(0, str(BRAIN_DIR))

from secondbrain.app import App as BrainApp  # noqa: E402
from secondbrain.config import Config as BrainConfig  # noqa: E402
from secondbrain.context import ContextRouter  # noqa: E402
from secondbrain.defaults import install_defaults, seed_demo  # noqa: E402
from secondbrain.server import serve_in_thread  # noqa: E402
from secondbrain.store import Store  # noqa: E402

API_KEY = "panel-key"


@unittest.skipUnless(BRAIN_DIR.is_dir(), "second_brain が隣にない")
class BrainIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = Store.open(":memory:")
        install_defaults(cls.store)
        cls.project = seed_demo(cls.store)
        brain_config = BrainConfig(host="127.0.0.1", port=0, api_key=API_KEY)
        cls.brain_server, _ = serve_in_thread(BrainApp(cls.store, brain_config),
                                              brain_config)
        cls.brain_url = "http://127.0.0.1:%d" % cls.brain_server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.brain_server.shutdown()
        cls.brain_server.server_close()

    def setUp(self):
        # States are append-only, so each test starts from the same position
        # regardless of what an earlier test wrote.
        self.store.set_state(self.project, "GR-02 CHANNEL", "IN_PROGRESS",
                             owner="Design AI", deliverables=["CHANNEL assets"],
                             actor="test")

    def panel(self, **brain_overrides):
        brain = {"enabled": True, "url": self.brain_url, "api_key": API_KEY,
                 "project": self.project, "roles": ["progress", "design", "builder"]}
        brain.update(brain_overrides)
        app, _ = make_app(make_config(brain=brain))
        return app.test_client()

    def run_action(self, action, client=None, **params):
        client = client or self.panel()
        return client.post("/api/action",
                           json={"action": action, "params": params}).get_json()

    def test_panel_shows_the_brain_group_and_role_buttons(self):
        html = self.panel().get("/").get_data(as_text=True)
        self.assertIn("SECOND BRAIN", html)
        self.assertIn("企画の現在地", html)
        for role in ("PROGRESS", "DESIGN", "BUILDER"):
            self.assertIn(f"{role} コンテキスト", html)

    def test_current_position_is_read_from_the_brain(self):
        result = self.run_action("brain_status")
        self.assertTrue(result["success"], result)
        self.assertEqual(result["message"], "GR-02 CHANNEL")
        self.assertIn("SYNAPTIC GROVE", result["detail"])
        self.assertIn("LOCKED", result["detail"])

    def test_each_role_button_returns_a_different_context(self):
        design = self.run_action("brain_context_design")["detail"]
        builder = self.run_action("brain_context_builder")["detail"]
        self.assertNotEqual(design, builder)
        self.assertIn("視覚・体験設計", design)
        self.assertIn("IMPLEMENTATION STATE", builder)
        # Same shared facts, different thinking.
        for text in (design, builder):
            self.assertIn("CHANNELはパイプや配線に見せない", text)

    def test_handoff_index_is_listed_with_a_file_flag(self):
        result = self.run_action("brain_handoffs")
        self.assertIn("GR-02", result["detail"])
        self.assertIn("MISS", result["detail"])  # demo path is a Windows path
        self.assertEqual(result["data"]["count"], 1)

    def test_health_check_button(self):
        result = self.run_action("brain_open")
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["health"]["projects"], 1)

    def test_completing_a_phase_from_the_tablet_reaches_every_ai(self):
        client = self.panel()
        before = ContextRouter(self.store).build("progress")["text"]
        self.assertIn("GR-02 CHANNEL", before)

        result = self.run_action("brain_phase_complete", client=client)
        self.assertTrue(result["success"], result)
        self.assertIn("COMPLETE", result["message"])

        state = self.store.current_state(self.project)
        self.assertEqual((state["phase"], state["status"]),
                         ("GR-02 CHANNEL", "COMPLETE"))
        after = ContextRouter(self.store).build("progress")["text"]
        self.assertIn("GR-02 CHANNEL COMPLETE", after)

        # Idempotent: pressing it twice does not create a second write.
        again = self.run_action("brain_phase_complete", client=client)
        self.assertTrue(again["success"])
        self.assertIn("既に COMPLETE", again["message"])

    def test_wrong_api_key_is_explained_not_swallowed(self):
        client = self.panel(api_key="wrong")
        result = self.run_action("brain_status", client=client)
        self.assertFalse(result["success"])
        self.assertIn("api_key", result["message"])

    def test_unreachable_brain_is_explained(self):
        client = self.panel(url="http://127.0.0.1:1")
        result = self.run_action("brain_status", client=client)
        self.assertFalse(result["success"])
        self.assertIn("接続できません", result["message"])

    def test_disabled_brain_is_refused(self):
        client = self.panel(enabled=False)
        result = self.run_action("brain_open", client=client)
        self.assertFalse(result["success"])
        self.assertIn("brain.enabled", result["message"])


if __name__ == "__main__":
    unittest.main()
