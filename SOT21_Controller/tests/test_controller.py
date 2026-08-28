import json
import tempfile
import unittest
from pathlib import Path

from _ctx import BASE, controller, make_app, make_config

import actions


class ConfigTest(unittest.TestCase):
    def test_shipped_config_is_valid_json_with_the_expected_keys(self):
        config = json.loads((BASE / "config.json").read_text(encoding="utf-8"))
        for key in ("server", "security", "sub_pc", "commands", "folders", "obs",
                    "brain"):
            self.assertIn(key, config)
        self.assertEqual(config["server"]["port"], 5000)
        self.assertEqual(config["server"]["host"], "0.0.0.0")

    def test_missing_keys_fall_back_to_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text('{"server": {"port": 5050}}', encoding="utf-8")
            config = controller.load_config(path)
            self.assertEqual(config["server"]["port"], 5050)
            self.assertEqual(config["server"]["host"], "0.0.0.0")
            self.assertTrue(config["security"]["lan_only"])

    def test_broken_config_fails_loudly(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "c.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(SystemExit):
                controller.load_config(path)


class LanRestrictionTest(unittest.TestCase):
    def setUp(self):
        self.config = make_config()

    def test_private_and_loopback_addresses_are_allowed(self):
        for ip in ("127.0.0.1", "192.168.1.50", "10.0.0.9", "172.16.4.4"):
            with self.subTest(ip=ip):
                self.assertTrue(controller.is_allowed(ip, self.config))

    def test_public_addresses_are_refused(self):
        for ip in ("8.8.8.8", "203.0.113.7", "", "not-an-ip"):
            with self.subTest(ip=ip):
                self.assertFalse(controller.is_allowed(ip, self.config))

    def test_request_from_outside_the_lan_is_403(self):
        app, _ = make_app(self.config)
        client = app.test_client()
        response = client.get("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
        self.assertEqual(response.status_code, 403)
        response = client.post("/api/action", json={"action": "status_main"},
                               environ_overrides={"REMOTE_ADDR": "203.0.113.9"})
        self.assertEqual(response.status_code, 403)

    def test_lan_only_can_be_switched_off(self):
        config = make_config(security={"lan_only": False})
        self.assertTrue(controller.is_allowed("8.8.8.8", config))


class PanelTest(unittest.TestCase):
    def setUp(self):
        self.app, self.log_path = make_app()
        self.client = self.app.test_client()

    def post(self, action, **params):
        return self.client.post("/api/action",
                                json={"action": action, "params": params}).get_json()

    def test_index_renders_every_group_and_big_buttons(self):
        html = self.client.get("/").get_data(as_text=True)
        for group in ("SYSTEM", "OBS", "AUTOMATION", "FILE", "PC CONTROL",
                      "SECOND BRAIN"):
            self.assertIn(group, html)
        for label in ("メインPC状態確認", "OBS起動", "録画開始", "録画停止",
                      "Python処理実行", "BAT実行", "ShortFACTORY実行",
                      "共有フォルダ確認", "Output確認", "Render確認",
                      "サブPC Wake-on-LAN", "サブPC接続確認"):
            self.assertIn(label, html)

    def test_buttons_meet_the_minimum_touch_size(self):
        css = (BASE / "static" / "style.css").read_text(encoding="utf-8")
        self.assertIn("width: 170px", css)
        self.assertIn("height: 96px", css)

    def test_button_params_survive_html_escaping_as_json(self):
        import re
        html = self.client.get("/").get_data(as_text=True)
        found = re.findall(r"data-params='([^']*)'", html)
        self.assertTrue(found)
        for raw in found:
            # This is what the browser hands JSON.parse after DOM decoding.
            decoded = (raw.replace("&amp;", "&").replace("&lt;", "<")
                       .replace("&gt;", ">").replace("&#34;", '"')
                       .replace("&#39;", "'").replace("\\u0027", "'"))
            self.assertIsInstance(json.loads(decoded), dict)

    def test_status_endpoint_shape_matches_the_spec(self):
        data = self.client.get("/api/status").get_json()
        for key in ("main_pc", "sub_pc", "cpu", "memory", "disk"):
            self.assertIn(key, data)
        self.assertIsInstance(data["main_pc"], bool)
        self.assertIsInstance(data["cpu"], int)

    def test_status_action_succeeds(self):
        result = self.post("status_main")
        self.assertTrue(result["success"])
        self.assertIn("CPU", result["detail"])

    def test_unknown_action_is_reported_not_crashed(self):
        result = self.post("rm_rf_everything")
        self.assertFalse(result["success"])
        self.assertIn("未登録", result["message"])

    def test_empty_action_is_400(self):
        response = self.client.post("/api/action", json={})
        self.assertEqual(response.status_code, 400)

    def test_actions_catalog_endpoint(self):
        catalog = self.client.get("/api/actions").get_json()
        groups = [section["group"] for section in catalog]
        self.assertEqual(groups[0], "SYSTEM")
        names = [b["name"] for section in catalog for b in section["buttons"]]
        self.assertIn("run_python", names)

    def test_every_action_is_logged_with_ip_and_outcome(self):
        self.post("status_main")
        self.post("rm_rf_everything")
        log = self.log_path.read_text(encoding="utf-8")
        self.assertIn("status_main | SUCCESS", log)
        self.assertIn("rm_rf_everything | FAILURE", log)
        self.assertIn("127.0.0.1", log)

    def test_blocked_request_is_logged(self):
        self.client.get("/", environ_overrides={"REMOTE_ADDR": "8.8.8.8"})
        self.assertIn("BLOCKED", self.log_path.read_text(encoding="utf-8"))


class CommandWhitelistTest(unittest.TestCase):
    def setUp(self):
        self.app, _ = make_app()
        self.client = self.app.test_client()

    def post(self, action, **params):
        return self.client.post("/api/action",
                                json={"action": action, "params": params}).get_json()

    def test_test_python_job_runs_and_returns_output(self):
        result = self.post("run_python")
        self.assertTrue(result["success"], result)
        self.assertIn("SOT21 TEST JOB", result["detail"])
        self.assertIn("result   : OK", result["detail"])

    def test_command_not_in_config_is_refused(self):
        result = self.post("run_python", command="calc")
        self.assertFalse(result["success"])
        self.assertIn("登録されていない", result["message"])

    def test_a_raw_command_line_cannot_be_injected(self):
        for attempt in ("notepad.exe", "cmd /c del /q C:\\*",
                        "python -c 'print(1)'"):
            with self.subTest(attempt=attempt):
                result = self.post("run_bat", command=attempt)
                self.assertFalse(result["success"])
                self.assertIn("登録されていない", result["message"])

    def test_missing_executable_is_reported(self):
        config = make_config(commands={"ghost": {"program": "C:\\nope\\ghost.bat",
                                                 "wait": True}})
        app, _ = make_app(config)
        result = app.test_client().post("/api/action", json={
            "action": "run_bat", "params": {"command": "ghost"}}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("見つかりません", result["message"])

    def test_short_string_command_form_is_supported(self):
        from actions.run_command import resolve
        ctx = controller.Context(make_config(commands={"x": "C:\\a\\b.bat"}),
                                 BASE, controller.build_logger())
        self.assertEqual(resolve(ctx, "x"), {"program": "C:\\a\\b.bat"})

    def test_a_failing_command_reports_its_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "boom.py"
            script.write_text("import sys; print('bad'); sys.exit(3)",
                              encoding="utf-8")
            config = make_config(commands={"boom": {
                "program": "python", "args": [str(script)], "wait": True}})
            app, _ = make_app(config)
            result = app.test_client().post("/api/action", json={
                "action": "run_python", "params": {"command": "boom"}}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("code 3", result["message"])

    def test_timeout_is_enforced(self):
        config = make_config(commands={"slow": {
            "program": "python", "args": ["-c", "import time; time.sleep(5)"],
            "wait": True, "timeout": 1}})
        app, _ = make_app(config)
        result = app.test_client().post("/api/action", json={
            "action": "run_python", "params": {"command": "slow"}}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("タイムアウト", result["message"])


class FolderTest(unittest.TestCase):
    def test_folder_check_counts_files_and_free_space(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.mp4").write_bytes(b"x" * 2048)
            (Path(tmp) / "b.mp4").write_bytes(b"y" * 1024)
            config = make_config(folders={"output": tmp})
            app, _ = make_app(config)
            result = app.test_client().post("/api/action", json={
                "action": "file_output"}).get_json()
        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["files"], 2)
        self.assertIn("a.mp4", result["detail"])

    def test_missing_folder_is_reported(self):
        config = make_config(folders={"render": "/no/such/folder"})
        app, _ = make_app(config)
        result = app.test_client().post("/api/action", json={
            "action": "file_render"}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("見つかりません", result["message"])


class NetworkTest(unittest.TestCase):
    def test_wake_on_lan_refuses_an_unset_mac(self):
        app, _ = make_app()
        result = app.test_client().post("/api/action", json={
            "action": "sub_pc_wol"}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("sub_pc.mac", result["message"])

    def test_magic_packet_is_built_and_sent(self):
        from actions.network_control import send_magic_packet
        send_magic_packet("AA:BB:CC:DD:EE:FF", "127.0.0.1", 9)  # no exception

    def test_bad_mac_is_rejected(self):
        from actions import ActionError
        from actions.network_control import send_magic_packet
        with self.assertRaises(ActionError):
            send_magic_packet("zz:zz", "127.0.0.1", 9)

    def test_ping_rejects_a_shell_ish_host(self):
        from actions.network_control import ping_host
        ok, detail = ping_host("127.0.0.1; rm -rf /")
        self.assertFalse(ok)
        self.assertIn("不正なホスト", detail)

    def test_tcp_probe_detects_a_closed_port(self):
        from actions.network_control import tcp_probe
        ok, _ = tcp_probe("127.0.0.1", 9, timeout=1)
        self.assertFalse(ok)


class ObsTest(unittest.TestCase):
    def test_missing_obs_path_is_reported(self):
        config = make_config(obs={"exe_path": "C:\\nope\\obs64.exe"})
        app, _ = make_app(config)
        result = app.test_client().post("/api/action", json={
            "action": "obs_start"}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("OBSが見つかりません", result["message"])

    def test_recording_without_websocket_explains_the_fix(self):
        config = make_config(obs={"websocket": {"enabled": False}})
        app, _ = make_app(config)
        result = app.test_client().post("/api/action", json={
            "action": "obs_record_start"}).get_json()
        self.assertFalse(result["success"])
        self.assertIn("WebSocket", result["message"])


if __name__ == "__main__":
    unittest.main()
