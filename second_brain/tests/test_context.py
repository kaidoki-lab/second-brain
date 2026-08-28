import unittest

from _ctx import seeded_store
from secondbrain.context import ContextRouter, estimate_tokens
from secondbrain.store import NotFound

ROLES = ["progress", "design", "builder", "critic", "explorer"]


class ContextRouterTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        self.router = ContextRouter(self.store, 2000)

    def sections(self, role):
        return {s["name"] for s in self.router.build(role)["sections"]}

    def test_every_role_stays_inside_the_token_budget(self):
        for role in ROLES:
            result = self.router.build(role)
            with self.subTest(role=role):
                self.assertLessEqual(result["token_estimate"], 2000)
                self.assertGreater(result["token_estimate"], 0)

    def test_roles_receive_different_slices(self):
        slices = {role: self.sections(role) for role in ROLES}
        pairs = [(a, b) for a in ROLES for b in ROLES if a < b]
        for a, b in pairs:
            with self.subTest(pair=(a, b)):
                self.assertNotEqual(slices[a], slices[b])

    def test_shared_facts_reach_every_role(self):
        for role in ROLES:
            text = self.router.build(role)["text"]
            with self.subTest(role=role):
                self.assertIn("CHANNELはパイプや配線に見せない", text)

    def test_hidden_context_is_withheld(self):
        # Explorer must not see the detail of the current proposal.
        explorer = self.router.build("explorer")["text"]
        self.assertNotIn("HANDOFF", explorer)
        self.assertNotIn("IMPLEMENTATION STATE", explorer)
        # Design must not be steered by implementation state.
        self.assertNotIn("IMPLEMENTATION STATE", self.router.build("design")["text"])
        # Builder must not be handed the world-building language.
        self.assertNotIn("WORLD / DESIGN LANGUAGE",
                         self.router.build("builder")["text"])

    def test_thinking_is_not_shared(self):
        axes = {}
        for role in ROLES:
            text = self.router.build(role)["text"]
            axes[role] = text.split("EVALUATION AXES")[1]
        self.assertEqual(len(set(axes.values())), len(ROLES))

    def test_prohibitions_are_always_present(self):
        for role in ROLES:
            with self.subTest(role=role):
                self.assertIn("PROHIBITED", self.router.build(role)["text"])

    def test_agent_id_resolves_to_its_profile(self):
        by_agent = self.router.build("codex")
        by_role = self.router.build("builder")
        self.assertEqual(by_agent["role"], "builder")
        self.assertEqual(by_agent["agent"], "codex")
        self.assertEqual(self.sections("codex"), self.sections("builder"))
        self.assertIn("Codex", by_agent["text"])
        self.assertNotIn("Codex (", by_role["text"])

    def test_unknown_role_is_rejected(self):
        with self.assertRaises(NotFound):
            self.router.build("nobody")

    def test_dependency_status_is_resolved_from_the_phase_label(self):
        text = self.router.build("progress")["text"]
        self.assertIn("- GR-01 COMPLETE", text)

    def test_a_tight_budget_drops_low_priority_sections_first(self):
        result = self.router.build("progress", budget=180)
        self.assertLessEqual(result["token_estimate"], 180)
        self.assertTrue(result["dropped_sections"])
        names = [s["name"] for s in result["sections"]]
        for pinned in ("project", "current_phase", "status", "role"):
            self.assertIn(pinned, names)
        self.assertNotIn("recent_changes", names)

    def test_a_tight_budget_truncates_long_lists_before_dropping(self):
        for index in range(30):
            self.store.add_decision("synaptic_grove", f"決定 {index}", status="LOCKED")
        full = self.router.build("critic", budget=100000)
        budget = int(full["token_estimate"] * 0.7)
        result = self.router.build("critic", budget=budget)
        self.assertLessEqual(result["token_estimate"], budget)
        self.assertIn("more)", result["text"])
        # Truncation happened instead of losing whole sections.
        self.assertEqual(result["dropped_sections"], [])

    def test_missing_handoff_file_is_flagged(self):
        self.assertIn("(FILE MISSING)", self.router.build("design")["text"])

    def test_project_defaults_to_the_first_active_one(self):
        self.assertEqual(self.router.build("design")["project"], "synaptic_grove")

    def test_estimate_counts_cjk_heavier_than_latin(self):
        self.assertGreater(estimate_tokens("あ" * 20), estimate_tokens("a" * 20))


if __name__ == "__main__":
    unittest.main()
