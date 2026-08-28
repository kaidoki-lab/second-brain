import json
import unittest
import urllib.error
import urllib.request

from _ctx import seeded_store
from secondbrain.app import App
from secondbrain.config import Config
from secondbrain.http_util import Request
from secondbrain.server import serve_in_thread


def get(app, target, **headers):
    return app.handle(Request.make("GET", target, headers))


def post_json(app, target, payload, **headers):
    headers = {"content-type": "application/json", **headers}
    return app.handle(Request.make("POST", target, headers,
                                   json.dumps(payload).encode()))


def post_form(app, target, body):
    return app.handle(Request.make(
        "POST", target, {"content-type": "application/x-www-form-urlencoded"},
        body.encode()))


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        self.app = App(self.store, Config(api_key=None))

    def body(self, response):
        return json.loads(response.body.decode())

    def test_health_is_public(self):
        response = get(self.app, "/api/health")
        self.assertEqual(response.status, 200)
        self.assertTrue(self.body(response)["ok"])

    def test_context_endpoint_returns_plain_text(self):
        response = get(self.app, "/context/design")
        self.assertEqual(response.status, 200)
        self.assertTrue(response.content_type.startswith("text/plain"))
        self.assertIn("CURRENT PHASE", response.body.decode())

    def test_context_endpoint_can_return_json(self):
        payload = self.body(get(self.app, "/context/design?format=json"))
        self.assertEqual(payload["role"], "design")
        self.assertLessEqual(payload["token_estimate"], 2000)

    def test_context_budget_is_honoured_and_clamped(self):
        payload = self.body(get(self.app, "/context/progress?format=json&budget=150"))
        self.assertLessEqual(payload["token_estimate"], 150)
        self.assertEqual(get(self.app, "/context/progress?budget=abc").status, 400)

    def test_project_current_matches_the_spec_shape(self):
        text = get(self.app, "/project/synaptic_grove/current").body.decode()
        for header in ("PROJECT", "CURRENT_PHASE", "STATUS", "LOCKED",
                       "DEPENDENCIES", "CURRENT_OWNER"):
            self.assertIn(header, text)

    def test_decisions_and_handoffs_by_project(self):
        decisions = self.body(get(self.app, "/decisions/synaptic_grove?status=LOCKED"))
        self.assertEqual(len(decisions), 2)
        handoffs = self.body(get(self.app, "/handoffs/synaptic_grove"))
        self.assertEqual(handoffs[0]["id"], "GR-02")

    def test_brain_endpoints(self):
        snapshot = self.body(get(self.app, "/api/brain"))
        self.assertEqual(snapshot["projects"][0]["project"]["id"], "synaptic_grove")
        markdown = get(self.app, "/brain.md").body.decode()
        self.assertIn("# SECOND BRAIN", markdown)
        self.assertIn("LOCKED DECISIONS", markdown)

    def test_unknown_project_is_404(self):
        self.assertEqual(get(self.app, "/decisions/ghost").status, 404)
        self.assertEqual(get(self.app, "/nope").status, 404)

    def test_post_decision_then_state_then_relation(self):
        created = self.body(post_json(self.app, "/api/decision", {
            "project": "synaptic_grove", "title": "CHANNELの分岐は3方向まで",
            "status": "LOCKED", "phase": "GR-02"}))
        self.assertEqual(created["status"], "LOCKED")
        state = self.body(post_json(self.app, "/api/state", {
            "project": "synaptic_grove", "phase": "GR-03 NODE",
            "status": "IN_PROGRESS", "deliverables": ["NODE assets"]}))
        self.assertEqual(state["phase"], "GR-03 NODE")
        self.assertEqual(state["deliverables"], ["NODE assets"])
        relation = self.body(post_json(self.app, "/api/relation", {
            "project": "synaptic_grove", "src": "GR-03", "rel": "depends_on",
            "dst": "GR-02"}))
        self.assertEqual(relation["dst"], "GR-02")
        # The new state must show up in the next context read.
        self.assertIn("GR-03 NODE", get(self.app, "/context/progress").body.decode())

    def test_post_handoff_indexes_without_reading_the_body(self):
        handoff = self.body(post_json(self.app, "/api/handoff", {
            "id": "GR-03", "project": "synaptic_grove",
            "file_path": "D:\\projects\\x\\GR-03.md", "owner": "Design AI"}))
        self.assertFalse(handoff["file_exists"])
        result = self.body(post_json(self.app, "/api/handoffs/verify",
                                     {"project": "synaptic_grove"}))
        self.assertEqual(result["checked"], 2)

    def test_missing_fields_are_400(self):
        response = post_json(self.app, "/api/decision", {"project": "synaptic_grove"})
        self.assertEqual(response.status, 400)
        self.assertIn("title", self.body(response)["error"])

    def test_malformed_json_is_400(self):
        response = self.app.handle(Request.make(
            "POST", "/api/decision", {"content-type": "application/json"}, b"{oops"))
        self.assertEqual(response.status, 400)

    def test_browser_form_post_redirects(self):
        response = post_form(self.app, "/api/fact",
                             "project=synaptic_grove&body=new+fact&tags=constraint")
        self.assertEqual(response.status, 303)
        self.assertEqual(response.headers["Location"], "/project/synaptic_grove")

    def test_ui_pages_render(self):
        for target in ("/", "/agents", "/project/synaptic_grove",
                       "/preview/context/design"):
            with self.subTest(target=target):
                response = get(self.app, target)
                self.assertEqual(response.status, 200)
                self.assertIn("SECOND BRAIN", response.body.decode())

    def test_html_clients_get_an_html_error(self):
        response = get(self.app, "/project/ghost", accept="text/html")
        self.assertEqual(response.status, 404)
        self.assertIn("<html", response.body.decode())


class AuthTest(unittest.TestCase):
    def setUp(self):
        self.app = App(seeded_store(), Config(api_key="secret-key"))

    def test_api_requires_a_key(self):
        self.assertEqual(get(self.app, "/context/design").status, 401)
        self.assertEqual(get(self.app, "/api/brain").status, 401)

    def test_health_stays_public(self):
        self.assertEqual(get(self.app, "/api/health").status, 200)

    def test_bearer_header_is_accepted(self):
        response = get(self.app, "/context/design", authorization="Bearer secret-key")
        self.assertEqual(response.status, 200)

    def test_x_api_key_header_is_accepted(self):
        self.assertEqual(
            get(self.app, "/context/design", **{"x-api-key": "secret-key"}).status, 200)

    def test_wrong_key_is_rejected(self):
        self.assertEqual(
            get(self.app, "/api/brain", authorization="Bearer nope").status, 401)

    def test_login_exchanges_the_key_for_a_cookie(self):
        response = get(self.app, "/login?key=secret-key")
        self.assertEqual(response.status, 303)
        cookie = response.headers["Set-Cookie"]
        self.assertIn("sb_key=secret-key", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertEqual(get(self.app, "/", cookie="sb_key=secret-key").status, 200)

    def test_login_rejects_a_bad_key(self):
        self.assertEqual(get(self.app, "/login?key=wrong").status, 401)


class LiveServerTest(unittest.TestCase):
    """The real socket path: headers, status codes and body framing."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(host="127.0.0.1", port=0, api_key="live-key")
        cls.app = App(seeded_store(), cls.config)
        cls.server, cls.thread = serve_in_thread(cls.app, cls.config)
        cls.base = "http://127.0.0.1:%d" % cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def fetch(self, path, key="live-key", data=None):
        request = urllib.request.Request(self.base + path)
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        if data is not None:
            request.data = json.dumps(data).encode()
            request.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode()

    def test_get_context_over_http(self):
        status, body = self.fetch("/context/builder")
        self.assertEqual(status, 200)
        self.assertIn("IMPLEMENTATION STATE", body)

    def test_write_then_read_over_http(self):
        status, _ = self.fetch("/api/state", data={
            "project": "synaptic_grove", "phase": "GR-04 SYNAPSE",
            "status": "IN_PROGRESS", "actor": "codex"})
        self.assertEqual(status, 201)
        _, body = self.fetch("/project/synaptic_grove/current")
        self.assertIn("GR-04 SYNAPSE", body)

    def test_unauthenticated_request_is_401(self):
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.fetch("/api/brain", key=None)
        self.assertEqual(caught.exception.code, 401)


if __name__ == "__main__":
    unittest.main()
