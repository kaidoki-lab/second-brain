/* ES5 only: Android 5.0.2 の WebView には fetch も Promise もアロー関数もない。 */
(function () {
  "use strict";

  var message = document.getElementById("message");
  var panel = document.getElementById("panel");
  var panelTitle = document.getElementById("panel-title");
  var panelBody = document.getElementById("panel-body");
  var busy = false;

  function setMessage(text, kind) {
    message.className = kind || "idle";
    message.innerHTML = "";
    message.appendChild(document.createTextNode(text));
  }

  function showPanel(title, text) {
    if (!text) { panel.className = "hidden"; return; }
    panelTitle.innerHTML = "";
    panelTitle.appendChild(document.createTextNode(title));
    panelBody.innerHTML = "";
    panelBody.appendChild(document.createTextNode(text));
    panel.className = "";
  }

  function post(url, payload, onDone) {
    var xhr = new XMLHttpRequest();
    xhr.open("POST", url, true);
    xhr.setRequestHeader("Content-Type", "application/json");
    xhr.timeout = 120000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) { return; }
      var data = null;
      try { data = JSON.parse(xhr.responseText); } catch (e) { data = null; }
      if (!data) {
        data = { success: false, message: "応答を解釈できません (HTTP " + xhr.status + ")" };
      }
      onDone(data);
    };
    xhr.ontimeout = function () { onDone({ success: false, message: "タイムアウト" }); };
    xhr.onerror = function () { onDone({ success: false, message: "通信エラー" }); };
    xhr.send(JSON.stringify(payload));
  }

  function get(url, onDone) {
    var xhr = new XMLHttpRequest();
    xhr.open("GET", url, true);
    xhr.timeout = 20000;
    xhr.onreadystatechange = function () {
      if (xhr.readyState !== 4) { return; }
      try { onDone(JSON.parse(xhr.responseText)); } catch (e) { onDone(null); }
    };
    xhr.ontimeout = function () { onDone(null); };
    xhr.onerror = function () { onDone(null); };
    xhr.send();
  }

  function runAction(button) {
    if (busy) { return; }
    var name = button.getAttribute("data-action");
    var label = button.innerHTML;
    var params = {};
    try { params = JSON.parse(button.getAttribute("data-params") || "{}"); }
    catch (e) { params = {}; }
    if (button.getAttribute("data-confirm") === "1") {
      if (!window.confirm(label + " を実行しますか？")) { return; }
    }
    busy = true;
    button.className = "btn pending";
    setMessage("実行中... " + label, "busy");
    post("/api/action", { action: name, params: params }, function (data) {
      busy = false;
      button.className = "btn";
      if (data.success) {
        setMessage("完了 : " + data.message, "ok");
      } else {
        setMessage("エラー : " + data.message, "err");
      }
      showPanel(label, data.detail || (data.success ? "" : data.message));
      refreshStatus();
    });
  }

  function dot(element, online) {
    element.className = online ? "dot on" : "dot off";
  }

  function text(id, value) {
    var node = document.getElementById(id);
    node.innerHTML = "";
    node.appendChild(document.createTextNode(value === null || value === undefined
      ? "--" : String(value)));
  }

  function refreshStatus() {
    get("/api/status", function (data) {
      if (!data) {
        dot(document.getElementById("dot-main"), false);
        text("txt-main", "取得失敗");
        return;
      }
      dot(document.getElementById("dot-main"), data.main_pc);
      dot(document.getElementById("dot-sub"), data.sub_pc);
      text("txt-main", data.main_pc ? "ONLINE" : "OFFLINE");
      text("txt-sub", data.sub_pc ? "ONLINE" : "OFFLINE");
      text("cpu", data.cpu);
      text("ram", data.memory);
      text("disk", data.disk);
      text("free", data.disk_free_gb);
    });
  }

  function tick() {
    var now = new Date();
    var hh = ("0" + now.getHours()).slice(-2);
    var mm = ("0" + now.getMinutes()).slice(-2);
    text("clock", hh + ":" + mm);
  }

  var buttons = document.getElementsByClassName("btn");
  for (var i = 0; i < buttons.length; i++) {
    (function (button) {
      button.onclick = function () { runAction(button); };
    })(buttons[i]);
  }
  document.getElementById("panel-close").onclick = function () {
    panel.className = "hidden";
  };

  tick();
  refreshStatus();
  window.setInterval(tick, 20000);
  window.setInterval(refreshStatus, 15000);
})();
