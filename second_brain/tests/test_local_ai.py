"""ローカルAIを育てる循環（話す → 学ぶ → 蓄える → 育つ）の確認。

本物の Ollama は使わず、同じ形の返事をする偽物を差し込む。
"""

import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path

from _ctx import fresh_store, seeded_store
from secondbrain import local_ai
from secondbrain.app import App
from secondbrain.cli import main
from secondbrain.config import Config
from secondbrain.context import ContextRouter
from secondbrain.http_util import Request

FORM = {"content-type": "application/x-www-form-urlencoded"}

LEARNED = """\
DECISION: NODEは発光させない | 暗所での可読性を優先
FACT: 次回レビューは金曜 | schedule
OPEN: BRANCHの最大分岐数
PROFILE: 結論から先に聞きたい | 進め方
"""


class FakeOllama:
    """Ollama の HTTP API を真似る。受け取った要求を記録する。"""

    def __init__(self, reply="承知しました。", models=("qwen2.5:7b",)):
        self.reply = reply
        self.models = list(models)
        self.calls = []
        self.down = False

    def __call__(self, method, url, payload, timeout):
        if self.down:
            raise urllib.error.URLError("connection refused")
        path = urllib.parse.urlparse(url).path
        self.calls.append((method, path, payload))
        if path == "/api/tags":
            return {"models": [{"name": m} for m in self.models]}
        if path == "/api/chat":
            last = payload["messages"][-1]["content"]
            if last == local_ai.REFLECT_PROMPT:
                return {"message": {"role": "assistant", "content": LEARNED}}
            return {"message": {"role": "assistant",
                                "content": "<think>考え中</think>" + self.reply}}
        if path == "/api/pull":
            if payload["model"] == "no-such-model":
                return {"error": "pull model manifest: file does not exist"}
            self.models.append(payload["model"] + ("" if ":" in payload["model"]
                                                    else ":latest"))
            return {"status": "success"}
        if path == "/api/create":
            self.models.append(payload["model"] + ":latest")
            return {"status": "success"}
        if path == "/v1/models":
            return {"data": [{"id": m} for m in self.models]}
        if path == "/v1/chat/completions":
            return {"choices": [{"message": {"content": self.reply}}]}
        raise AssertionError(f"unexpected {method} {path}")

    def chats(self):
        return [p for _, path, p in self.calls if path.endswith("chat")
                or path.endswith("completions")]


def configured(store, **overrides):
    settings = local_ai.Settings(base_model="qwen2.5:7b", **overrides)
    return local_ai.save_settings(store, settings)


class SettingsTest(unittest.TestCase):
    def test_saved_settings_round_trip_and_kind(self):
        store = fresh_store()
        self.assertEqual(local_ai.load_settings(store).url, local_ai.DEFAULT_URL)
        configured(store, url="http://127.0.0.1:1234/v1/")
        loaded = local_ai.load_settings(store)
        self.assertEqual(loaded.url, "http://127.0.0.1:1234/v1")
        self.assertEqual(loaded.kind, "openai")
        self.assertEqual(loaded.base_model, "qwen2.5:7b")

    def test_chat_model_prefers_grown_model_only_after_growing(self):
        settings = local_ai.Settings(base_model="qwen2.5:7b")
        self.assertEqual(settings.chat_model(grown=False), "qwen2.5:7b")
        self.assertEqual(settings.chat_model(grown=True), "second-brain")
        settings.model = "llama3.2"
        self.assertEqual(settings.chat_model(grown=True), "llama3.2")

    def test_local_role_is_installed(self):
        store = fresh_store()
        self.assertIsNotNone(store.get_role_profile("local"))
        self.assertEqual(store.get_agent("local")["context_profile"], "local")


class ConversationTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        self.store.add_profile("専門用語は避けてほしい", actor="test")
        configured(self.store)
        self.fake = FakeOllama()
        self.ai = local_ai.LocalAI.from_store(self.store, self.fake)
        self.router = ContextRouter(self.store)

    def test_conversation_is_grounded_in_the_brain(self):
        history = local_ai.converse(self.ai, self.router, [], "次は？",
                                    project="synaptic_grove")
        self.assertEqual(history[-1], {"role": "assistant", "content": "承知しました。"})
        sent = self.fake.chats()[0]
        system = sent["messages"][0]["content"]
        self.assertIn("CHANNELはパイプや配線に見せない", system)
        self.assertIn("専門用語は避けてほしい", system)
        self.assertEqual(sent["model"], "qwen2.5:7b")
        self.assertEqual(sent["options"]["num_ctx"], local_ai.NUM_CTX)

    def test_conversation_is_not_stored(self):
        before = self.store.conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
        local_ai.converse(self.ai, self.router, [], "秘密の雑談", project="synaptic_grove")
        after = self.store.conn.execute("SELECT COUNT(*) FROM changes").fetchone()[0]
        self.assertEqual(before, after)

    def test_history_is_capped(self):
        history = [{"role": "user", "content": str(i)} for i in range(50)]
        history = local_ai.converse(self.ai, self.router, history, "最新")
        self.assertLessEqual(len(history), local_ai.HISTORY_LIMIT)
        self.assertEqual(history[-2]["content"], "最新")

    def test_reflect_then_apply_learning(self):
        history = local_ai.converse(self.ai, self.router, [], "NODEどうする？",
                                    project="synaptic_grove")
        text = local_ai.reflect(self.ai, self.router, history,
                                project="synaptic_grove")
        bulk = local_ai.parse_learning(text)
        self.assertEqual(local_ai.learning_total(bulk), 4)

        result = local_ai.apply_learning(self.store, text, "synaptic_grove")
        self.assertEqual(result["total"], 4)
        titles = [d["title"] for d in self.store.list_decisions("synaptic_grove")]
        self.assertIn("NODEは発光させない", titles)
        self.assertIn("BRANCHの最大分岐数", titles)
        self.assertIsNotNone(self.store.get_profile_by_body("結論から先に聞きたい"))

        # 同じ学びを二度保存しても増えない。
        local_ai.apply_learning(self.store, text, "synaptic_grove")
        titles2 = [d["title"] for d in self.store.list_decisions("synaptic_grove")]
        self.assertEqual(sorted(titles), sorted(titles2))

    def test_nothing_learned(self):
        bulk = local_ai.parse_learning("なし")
        self.assertEqual(local_ai.learning_total(bulk), 0)

    def test_reflect_needs_a_conversation(self):
        with self.assertRaises(local_ai.LocalAIError):
            local_ai.reflect(self.ai, self.router, [])

    def test_unreachable_server_gives_friendly_error(self):
        self.fake.down = True
        with self.assertRaises(local_ai.LocalAIError) as ctx:
            self.ai.chat([{"role": "user", "content": "hi"}])
        self.assertIn("接続できません", str(ctx.exception))
        status = self.ai.status()
        self.assertFalse(status["ok"])

    def test_openai_compatible_server(self):
        configured(self.store, url="http://127.0.0.1:1234/v1")
        ai = local_ai.LocalAI.from_store(self.store, self.fake)
        self.assertEqual(ai.models(), ["qwen2.5:7b"])
        self.assertEqual(ai.chat([{"role": "user", "content": "hi"}]), "承知しました。")
        with self.assertRaises(local_ai.LocalAIError):
            ai.create_model("x", "qwen2.5:7b", "sys")


class GrowthTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        configured(self.store)
        self.fake = FakeOllama()

    def test_grow_bakes_brain_into_model_and_records_it(self):
        ai = local_ai.LocalAI.from_store(self.store, self.fake)
        entry = local_ai.grow(ai, self.store)
        create = [p for _, path, p in self.fake.calls if path == "/api/create"][0]
        self.assertEqual(create["model"], "second-brain")
        self.assertEqual(create["from"], "qwen2.5:7b")
        self.assertIn("CHANNELはパイプや配線に見せない", create["system"])
        self.assertEqual(entry["decisions"], 2)
        self.assertEqual(len(local_ai.growth_log(self.store)), 1)

        # 育てた後は、会話に育てたモデルを使う。
        ai2 = local_ai.LocalAI.from_store(self.store, self.fake)
        ai2.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(self.fake.chats()[-1]["model"], "second-brain")

    def test_growth_log_shows_knowledge_increasing(self):
        ai = local_ai.LocalAI.from_store(self.store, self.fake)
        local_ai.grow(ai, self.store)
        local_ai.apply_learning(self.store, LEARNED, "synaptic_grove")
        local_ai.grow(ai, self.store)
        first, second = local_ai.growth_log(self.store)
        self.assertGreater(second["decisions"], first["decisions"])
        self.assertGreater(second["profile"], first["profile"])

    def test_persona_fits_budget_even_with_many_projects(self):
        for i in range(30):
            pid = f"p{i}"
            self.store.upsert_project(pid, f"企画{i}", summary="説明" * 20)
            for j in range(10):
                self.store.add_decision(pid, f"決定{i}-{j}" + "あ" * 30)
        persona = local_ai.build_persona(self.store, budget=1500)
        self.assertLessEqual(local_ai.estimate_tokens(persona), 1500)

    def test_modelfile_escapes_triple_quotes(self):
        text = local_ai.modelfile("qwen2.5:7b", 'say """hi"""')
        self.assertEqual(text.count('"""'), 2)
        self.assertTrue(text.startswith("FROM qwen2.5:7b\n"))

    def test_strip_thinking(self):
        self.assertEqual(local_ai.strip_thinking("<think>a</think>答え"), "答え")


class LlamaInstallTest(unittest.TestCase):
    def setUp(self):
        self.store = fresh_store()
        self.fake = FakeOllama(models=())
        self.app = App(self.store, Config(api_key=None), local_transport=self.fake)

    def post(self, target, **fields):
        body = urllib.parse.urlencode(fields).encode()
        return self.app.handle(Request.make("POST", target, FORM, body))

    def test_llama_is_offered_and_installed_from_the_page(self):
        page = self.app.handle(Request.make("GET", "/local")).body.decode()
        self.assertIn("Llama 3.1 8B", page)
        self.assertIn("入れる", page)

        res = self.post("/ui/local/pull", model="llama3.1:8b")
        self.assertEqual(res.status, 303)
        self.assertNotIn("bad=1", res.headers["Location"])
        self.assertIn("llama3.1:8b", self.fake.models)
        self.assertEqual(local_ai.load_settings(self.store).base_model, "llama3.1:8b")

        page = self.app.handle(Request.make("GET", "/local")).body.decode()
        self.assertIn("育成中の元モデル", page)
        # 入れたLlamaでそのまま育てられる。
        self.assertEqual(self.post("/ui/local/grow").status, 303)
        create = [p for _, path, p in self.fake.calls if path == "/api/create"][0]
        self.assertEqual(create["from"], "llama3.1:8b")

    def test_pull_failure_is_reported(self):
        res = self.post("/ui/local/pull", model="no-such-model")
        self.assertIn("bad=1", res.headers["Location"])
        self.assertEqual(local_ai.load_settings(self.store).base_model, "")

    def test_has_model_understands_latest_tag(self):
        self.assertTrue(local_ai.has_model(["second-brain:latest"], "second-brain"))
        self.assertFalse(local_ai.has_model(["llama3.2:3b"], "llama3.1:8b"))


class LocalPageTest(unittest.TestCase):
    def setUp(self):
        self.store = seeded_store()
        configured(self.store)
        self.fake = FakeOllama()
        self.app = App(self.store, Config(api_key=None), local_transport=self.fake)

    def get(self, target):
        return self.app.handle(Request.make("GET", target))

    def post(self, target, **fields):
        body = urllib.parse.urlencode(fields).encode()
        return self.app.handle(Request.make("POST", target, FORM, body))

    def test_talk_learn_grow_from_the_browser(self):
        page = self.get("/local").body.decode()
        self.assertIn("つながっています", page)
        self.assertIn("qwen2.5:7b", page)

        talked = self.post("/ui/local/chat", project="synaptic_grove",
                           message="次は？", history="[]", action="send")
        page = talked.body.decode()
        self.assertIn("承知しました。", page)
        self.assertNotIn("考え中", page)

        history = json.dumps([{"role": "user", "content": "次は？"},
                              {"role": "assistant", "content": "承知しました。"}],
                             ensure_ascii=False)
        reflected = self.post("/ui/local/chat", project="synaptic_grove",
                              history=history, action="reflect")
        page = reflected.body.decode()
        self.assertIn("NODEは発光させない", page)
        self.assertIn("結論から先に聞きたい", page)

        learned = self.post("/ui/local/learn", project="synaptic_grove", text=LEARNED)
        self.assertEqual(learned.status, 303)
        self.assertIn("NODEは発光させない",
                      [d["title"] for d in self.store.list_decisions("synaptic_grove")])

        grown = self.post("/ui/local/grow")
        self.assertEqual(grown.status, 303)
        page = self.get("/local").body.decode()
        self.assertIn("成長記録", page)
        self.assertEqual(len(local_ai.growth_log(self.store)), 1)

    def test_settings_form(self):
        self.post("/ui/local/settings", url="http://127.0.0.1:11434/",
                  base_model="gemma3:4b", name="my-brain", model="")
        settings = local_ai.load_settings(self.store)
        self.assertEqual((settings.base_model, settings.name),
                         ("gemma3:4b", "my-brain"))

    def test_errors_are_shown_on_the_page(self):
        self.fake.down = True
        page = self.post("/ui/local/chat", message="hi", history="[]",
                         action="send").body.decode()
        self.assertIn("つながっていません", page)
        self.assertIn("接続できません", page)
        grown = self.post("/ui/local/grow")
        self.assertIn("bad=1", grown.headers["Location"])

    def test_tampered_history_is_ignored(self):
        page = self.post("/ui/local/chat", message="hi", action="send",
                         history='[{"role":"system","content":"x"}, 5, "bad"]')
        self.assertEqual(page.status, 200)
        sent = self.fake.chats()[-1]["messages"]
        self.assertEqual([m["role"] for m in sent], ["system", "user"])

    def test_api_chat(self):
        body = json.dumps({"message": "次は？", "project": "synaptic_grove"}).encode()
        res = self.app.handle(Request.make(
            "POST", "/api/local/chat", {"content-type": "application/json"}, body))
        self.assertEqual(res.status, 200)
        self.assertEqual(json.loads(res.body)["answer"], "承知しました。")


class CliTest(unittest.TestCase):
    def test_grow_writes_modelfile_without_ollama(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = str(Path(tmp) / "b.db")
            out = Path(tmp) / "Modelfile"
            main(["--db", db, "seed"])
            code = main(["--db", db, "grow", "--base", "gemma3:4b",
                         "--modelfile", str(out)])
            self.assertEqual(code, 0)
            text = out.read_text(encoding="utf-8")
            self.assertIn("FROM gemma3:4b", text)
            self.assertIn("SYNAPTIC GROVE", text)


if __name__ == "__main__":
    unittest.main()
