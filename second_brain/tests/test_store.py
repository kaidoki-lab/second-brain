import unittest

from _ctx import fresh_store, seeded_store
from secondbrain.store import Invalid, NotFound


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()

    def test_project_upsert_is_idempotent(self):
        self.store.upsert_project("p1", "P One")
        self.store.upsert_project("p1", "P One Renamed")
        self.assertEqual(len(self.store.list_projects()), 1)
        self.assertEqual(self.store.get_project("p1")["name"], "P One Renamed")

    def test_project_id_is_validated(self):
        with self.assertRaises(Invalid):
            self.store.upsert_project("bad id/../x")

    def test_writes_require_a_known_project(self):
        with self.assertRaises(NotFound):
            self.store.add_decision("ghost", "title")

    def test_decision_ids_increment(self):
        self.store.upsert_project("p1")
        first = self.store.add_decision("p1", "one")["id"]
        second = self.store.add_decision("p1", "two")["id"]
        self.assertEqual((first, second), ("DECISION-0001", "DECISION-0002"))

    def test_state_is_append_only_and_latest_wins(self):
        self.store.upsert_project("p1")
        self.store.set_state("p1", "GR-01", "COMPLETE")
        self.store.set_state("p1", "GR-02", "IN_PROGRESS")
        self.assertEqual(self.store.current_state("p1")["phase"], "GR-02")
        self.assertEqual(len(self.store.state_history("p1")), 2)
        self.assertEqual([p["phase"] for p in self.store.phase_summary("p1")],
                         ["GR-01", "GR-02"])

    def test_phase_summary_keeps_only_the_latest_row_per_phase(self):
        self.store.upsert_project("p1")
        self.store.set_state("p1", "GR-01", "IN_PROGRESS")
        self.store.set_state("p1", "GR-01", "COMPLETE")
        summary = self.store.phase_summary("p1")
        self.assertEqual([(p["phase"], p["status"]) for p in summary],
                         [("GR-01", "COMPLETE")])

    def test_relations_are_deduplicated(self):
        self.store.upsert_project("p1")
        self.store.add_relation("p1", "GR-02", "depends_on", "GR-01")
        self.store.add_relation("p1", "GR-02", "depends_on", "GR-01")
        self.assertEqual(len(self.store.list_relations("p1")), 1)
        self.assertEqual(self.store.dependencies_of("p1", "GR-02"), ["GR-01"])
        self.assertEqual(self.store.dependents_of("p1", "GR-01"), ["GR-02"])

    def test_handoff_records_a_missing_file(self):
        self.store.upsert_project("p1")
        handoff = self.store.upsert_handoff("GR-02", "p1", "/nope/GR-02.md")
        self.assertFalse(handoff["file_exists"])
        result = self.store.verify_handoffs("p1")
        self.assertEqual(result["missing"], ["GR-02"])

    def test_handoff_verifies_an_existing_file(self):
        self.store.upsert_project("p1")
        handoff = self.store.upsert_handoff("self", "p1", __file__)
        self.assertTrue(handoff["file_exists"])

    def test_tags_accept_a_comma_separated_string(self):
        self.store.upsert_project("p1")
        fact = self.store.add_fact("p1", "asset budget 7/21", tags="constraint, budget")
        self.assertEqual(fact["tags"], ["constraint", "budget"])

    def test_every_write_lands_in_the_change_log(self):
        self.store.upsert_project("p1")
        self.store.add_decision("p1", "d")
        entities = {c["entity"] for c in self.store.recent_changes(10, "p1")}
        self.assertEqual(entities, {"project", "decision"})


class SeedTest(unittest.TestCase):
    def test_seed_is_idempotent(self):
        store = seeded_store()
        from secondbrain.defaults import seed_demo
        seed_demo(store)
        self.assertEqual(len(store.list_decisions("synaptic_grove")), 2)
        self.assertEqual(len(store.list_facts("synaptic_grove")), 5)
        self.assertEqual(len(store.list_relations("synaptic_grove")), 3)


if __name__ == "__main__":
    unittest.main()
