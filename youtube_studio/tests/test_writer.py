import json
import unittest
from types import SimpleNamespace

import _ctx
from studio import writer
from studio.writer import WriterError


class ExtractJsonTest(unittest.TestCase):
    def test_reads_fenced_and_prefixed_json(self):
        self.assertEqual(writer.extract_json('はい。\n```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(writer.extract_json('<think>考え中{</think>前置き {"a": [1]} 以上'),
                         {"a": [1]})

    def test_broken_json_is_a_writer_error(self):
        with self.assertRaises(WriterError):
            writer.extract_json("JSONはありません")
        with self.assertRaises(WriterError):
            writer.extract_json('{"a": }')


class ScriptCheckTest(unittest.TestCase):
    def test_accepts_a_full_script_and_normalises_fields(self):
        data = _ctx.script_json()
        data["tags"] = ["a", " ", "b"]
        out = writer.check_script(data, minutes=1)
        self.assertEqual(out["tags"], ["a", "b"])
        self.assertEqual(out["checks"], ["数字の出典を確認"])

    def test_rejects_too_short_narration(self):
        data = _ctx.script_json()
        for s in data["sections"]:
            s["narration"] = "短い。"
        with self.assertRaisesRegex(WriterError, "短すぎ"):
            writer.check_script(data, minutes=8)

    def test_missing_short_falls_back_to_hook(self):
        data = _ctx.script_json()
        del data["short"]
        out = writer.check_script(data, minutes=1)
        self.assertEqual(out["short"]["narration"], data["hook"])

    def test_retry_tells_the_model_what_was_wrong(self):
        bad = json.dumps({"title": "x"})
        good = json.dumps(_ctx.script_json(), ensure_ascii=False)
        llm = _ctx.FakeLLM([bad, good])
        cfg = _ctx.Sandbox().cfg
        script = writer.write_script(llm, cfg, {"title": "企画"}, {"feedback": []}, [])
        self.assertEqual(script["title"], "テスト動画")
        self.assertEqual(len(llm.calls), 2)
        self.assertIn("前回の返事の問題", llm.calls[1])


class PromptTest(unittest.TestCase):
    def test_plan_prompt_carries_stats_feedback_and_made_titles(self):
        cfg = _ctx.Sandbox().cfg
        llm = _ctx.FakeLLM()
        memory = {"feedback": [{"text": "前置きが長い"}],
                  "stats": {"a": {"title": "伸びた動画", "views": 900},
                            "b": {"title": "伸びなかった動画", "views": 3}}}
        topics = writer.plan_topics(llm, cfg, memory, [{"title": "作成済みの企画"}],
                                    brain_context="FACT: 確定した事実", count=2)
        self.assertEqual(len(topics), 2)
        prompt = llm.calls[0]
        for needle in ("家計の見直し", "前置きが長い", "伸びた動画", "作成済みの企画",
                       "確定した事実"):
            self.assertIn(needle, prompt)


class BackendTest(unittest.TestCase):
    def test_ollama_asks_for_json_without_proxy_transport(self):
        sent = {}

        def transport(url, payload, timeout):
            sent.update(url=url, payload=payload)
            return {"message": {"content": '{"ok": true}'}}

        out = writer.OllamaWriter("http://127.0.0.1:11434/", "second-brain", transport)
        self.assertEqual(out.complete("sys", "user"), '{"ok": true}')
        self.assertEqual(sent["url"], "http://127.0.0.1:11434/api/chat")
        self.assertEqual(sent["payload"]["format"], "json")
        self.assertEqual(sent["payload"]["model"], "second-brain")

    def test_ollama_down_is_explained(self):
        def transport(url, payload, timeout):
            raise ConnectionRefusedError("refused")
        with self.assertRaisesRegex(WriterError, "Ollama"):
            writer.OllamaWriter("http://x", "m", transport).complete("s", "u")

    def test_claude_returns_text_and_reports_refusal(self):
        try:
            import anthropic  # noqa: F401
        except ImportError:
            self.skipTest("anthropic が入っていない")
        calls = []

        class Messages:
            def __init__(self, reply):
                self.reply = reply

            def create(self, **kw):
                calls.append(kw)
                return self.reply

        def client(reply):
            return SimpleNamespace(beta=SimpleNamespace(messages=Messages(reply)))

        ok = SimpleNamespace(stop_reason="end_turn", content=[
            SimpleNamespace(type="thinking", thinking=""),
            SimpleNamespace(type="text", text='{"a": 1}')])
        w = writer.ClaudeWriter(client=client(ok))
        self.assertEqual(w.complete("sys", "user"), '{"a": 1}')
        self.assertEqual(calls[0]["model"], "claude-opus-5-5")
        self.assertEqual(calls[0]["fallbacks"], "default")
        refused = SimpleNamespace(stop_reason="refusal", content=[])
        with self.assertRaisesRegex(WriterError, "断られ"):
            writer.ClaudeWriter(client=client(refused)).complete("s", "u")


if __name__ == "__main__":
    unittest.main()
