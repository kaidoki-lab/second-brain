import io
import json
import unittest

from _ctx import seeded_store
from secondbrain.mcp_server import TOOLS, MCPServer

REQUIRED_TOOLS = {"get_project_state", "get_context", "get_decisions",
                  "get_handoffs", "get_dependencies", "write_decision",
                  "update_state"}


class McpTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        self.server = MCPServer(self.store)

    def call(self, name, **args):
        response = self.server.handle({
            "jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": args}})
        return response["result"]

    def text(self, result):
        return result["content"][0]["text"]

    def test_initialize_reports_tool_capability(self):
        result = self.server.handle(
            {"jsonrpc": "2.0", "id": 0, "method": "initialize"})["result"]
        self.assertIn("tools", result["capabilities"])
        self.assertEqual(result["serverInfo"]["name"], "second-brain")

    def test_spec_tools_are_exposed(self):
        names = {tool["name"] for tool in TOOLS}
        self.assertTrue(REQUIRED_TOOLS.issubset(names))
        listed = self.server.handle(
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list"})["result"]["tools"]
        self.assertEqual(len(listed), len(TOOLS))
        for tool in listed:
            self.assertEqual(tool["inputSchema"]["type"], "object")

    def test_notifications_get_no_reply(self):
        self.assertIsNone(self.server.handle(
            {"jsonrpc": "2.0", "method": "notifications/initialized"}))

    def test_unknown_method_is_an_rpc_error(self):
        response = self.server.handle({"jsonrpc": "2.0", "id": 9, "method": "nope"})
        self.assertEqual(response["error"]["code"], -32601)

    def test_get_project_state(self):
        state = json.loads(self.text(
            self.call("get_project_state", project="synaptic_grove")))
        self.assertEqual(state["current_phase"], "GR-02 CHANNEL")
        self.assertEqual(state["dependencies"], ["GR-01"])
        self.assertEqual(len(state["locked_decisions"]), 2)

    def test_get_context_differs_per_role(self):
        design = self.text(self.call("get_context", role="design"))
        builder = self.text(self.call("get_context", role="builder"))
        self.assertNotEqual(design, builder)
        self.assertIn("視覚・体験設計", design)
        self.assertIn("IMPLEMENTATION STATE", builder)

    def test_get_dependencies_defaults_to_the_current_phase(self):
        deps = json.loads(self.text(
            self.call("get_dependencies", project="synaptic_grove")))
        self.assertEqual(deps["node"], "GR-02")
        self.assertEqual(deps["depends_on"], ["GR-01"])

    def test_write_decision_and_update_state_round_trip(self):
        decision = json.loads(self.text(self.call(
            "write_decision", project="synaptic_grove", title="NODEは発光させない",
            status="LOCKED", tags=["design"], actor="critic")))
        self.assertEqual(decision["tags"], ["design"])
        self.call("update_state", project="synaptic_grove", phase="GR-03 NODE",
                  status="IN_PROGRESS", deliverables=["NODE assets"])
        self.assertEqual(self.store.current_state("synaptic_grove")["phase"],
                         "GR-03 NODE")
        # A different model reading afterwards sees the same truth.
        self.assertIn("GR-03 NODE", self.text(self.call("get_context", role="design")))

    def test_write_handoff_and_relation(self):
        self.call("write_handoff", id="GR-03", project="synaptic_grove",
                  file_path="D:\\x\\GR-03.md", owner="Design AI")
        self.call("write_relation", project="synaptic_grove", src="GR-03",
                  rel="depends_on", dst="GR-02")
        self.assertEqual(self.store.dependencies_of("synaptic_grove", "GR-03"),
                         ["GR-02"])

    def test_tool_errors_are_reported_in_band(self):
        result = self.call("get_project_state", project="ghost")
        self.assertTrue(result["isError"])
        self.assertIn("unknown project", self.text(result))
        missing = self.call("write_decision", project="synaptic_grove")
        self.assertTrue(missing["isError"])
        unknown = self.call("no_such_tool")
        self.assertTrue(unknown["isError"])

    def test_stdio_loop_speaks_line_delimited_json(self):
        stdin = io.StringIO(
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}) + "\n"
            + "not json\n"
            + json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
            + json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                          "params": {"name": "list_projects", "arguments": {}}}) + "\n")
        stdout = io.StringIO()
        self.server.run(stdin, stdout)
        lines = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual([line["id"] for line in lines], [1, 2])
        projects = json.loads(lines[1]["result"]["content"][0]["text"])
        self.assertEqual(projects[0]["id"], "synaptic_grove")


if __name__ == "__main__":
    unittest.main()
