# SOT21 LAN CONTROLLER

SONY Xperia Z2 Tablet au版 **SOT21 (Android 5.0.2)** を、同一LAN上のWindows PCを
操作する常設コントローラーとして再利用するための操作盤。

タブレット側は**ブラウザで開くだけ**。処理は全てメインPC側で動く。

```
   SOT21 (ブラウザ)
        │  Wi-Fi / HTTP :5000
   メインPC (Flask: この操作盤)
        │
   bat / Python / OBS / ファイル確認 / サブPC制御 / 第二の脳
```

## 起動方法

1. このフォルダを **メインPC** へ置く（例 `C:\KYOUKAI\SOT21_Controller`）
2. `start.bat` をダブルクリック
   - 仮想環境 `.venv` を自動作成
   - `requirements.txt` を自動インストール
   - ファイアウォールに **TCP 5000 / プライベートのみ** の許可を追加（要管理者権限）
   - Flask を `0.0.0.0:5000` で起動
3. 起動時に表示される `http://<このPCのIPv4>:5000` を SOT21 のブラウザで開く
4. Chrome メニュー →「ホーム画面に追加」でアイコン化する

手動で動かす場合:

```bat
pip install -r requirements.txt
python app.py
```

### SOT21側の設定

- 画面スリープ: 設定 → 画面 → スリープ を最長（または「点灯し続ける」開発者向けオプション）
- ブックマークをホーム画面へ追加し、全画面に近い状態で使用
- 常時設置時は充電しながら使用する

> **バッテリー注意**: 古い端末のため常時充電で膨張の恐れがある。80%前後で充電を止める、
> タイマー付きコンセントを使う、定期充電に切り替える等を検討する。
> 本体が異常に熱くなる場合は常時給電運用を中止すること。

## 画面

```
┌──────────────────────────────┐
│  HOME CONTROL          20:31 │
│  MAIN PC ● ONLINE            │
│  SUB PC  ● OFFLINE           │
│  CPU 18%  RAM 42%  DISK 63%  │
│  ─────────────────────────── │
│  完了 : テストPython 完了     │
│                              │
│  [ OBS起動 ] [ 録画開始 ] ... │
└──────────────────────────────┘
```

- ボタンは 170×96px（最小要件 140×90px 以上）
- 実行中は上部に「実行中...」→ 完了で「完了 : ...」／失敗で「エラー : ...」
- 詳細（コマンド出力、フォルダ一覧、AIコンテキスト全文）は下部パネルに表示
- 状態は15秒ごとに自動更新。CSS Grid / fetch / ES6 は不使用（Android 5.0.2 対応）

## ボタン一覧

| グループ | ボタン | 動作 |
| --- | --- | --- |
| SYSTEM | メインPC状態確認 / サブPC状態確認 / 状態更新 | psutil と ping/TCP |
| OBS | OBS起動 / 録画開始 / 録画停止 / OBS状態 | 起動は exe、録画は obs-websocket |
| AUTOMATION | Python処理実行 / BAT実行 / ShortFACTORY実行 | config.json 登録済みのみ |
| FILE | 共有フォルダ確認 / Output確認 / Render確認 | 件数・容量・最新5件・空き容量 |
| PC CONTROL | サブPC Wake-on-LAN / サブPC接続確認 | マジックパケット / ping・TCP |
| SECOND BRAIN | 企画の現在地 / 役割別コンテキスト / ハンドオフ確認 / 現フェーズ完了 / 第二の脳を開く・起動 | `../second_brain` のAPIを叩く |

## API

```
GET  /              操作盤（HTML）
GET  /api/status    {"main_pc":true,"sub_pc":true,"cpu":18,"memory":42,"disk":63,...}
GET  /api/actions   ボタン定義（グループ順）
POST /api/action    {"action":"obs_start"} -> {"success":true,"message":"OBSを起動しました"}
```

`POST /api/action` の応答は `success` / `message` に加え、詳細がある場合 `detail`、
構造化データがある場合 `data` を返す。

## config.json

| キー | 内容 |
| --- | --- |
| `server` | bind host / port（既定 `0.0.0.0:5000`） |
| `security.lan_only` | LAN内プライベートIPのみ許可（既定 true） |
| `security.allow_networks` | 許可するCIDR（既定 127/8, 192.168/16, 10/8, 172.16/12） |
| `main_pc.disk` | 使用率を見るドライブ（例 `C:\`） |
| `sub_pc` | サブPCの `ip` / `mac` / `port` / `broadcast` |
| `commands` | **実行を許可する処理の全リスト**（ここに無い処理は実行できない） |
| `folders` | share / output / render の確認先 |
| `obs` | `exe_path` と WebSocket 設定 |
| `brain` | 第二の脳の `url` / `api_key` / `project` / `roles` |

コマンドの書式:

```json
"commands": {
  "shortfactory": "C:\\KYOUKAI\\ShortFACTORY\\start.bat",
  "test_python": {
    "label": "テストPython",
    "program": "python",
    "args": ["scripts/test_job.py"],
    "cwd": null,
    "wait": true,
    "timeout": 30
  }
}
```

- 文字列で書けば「そのファイルを起動するだけ」
- `wait: true` で終了を待ち、標準出力をタブレットへ返す（テスト用処理向け）
- `wait: false`（既定）は起動しっぱなし（OBSやShortFACTORY向け）
- 相対パスはこのフォルダ基準で解決される
- `.bat` / `.cmd` は自動的に `cmd /c` 経由で実行される

## セキュリティ

- **ブラウザから任意のコマンド文字列は実行できない。** 送れるのはアクション名と、
  `config.json` に登録済みのコマンド *キー* のみ。未登録キーは拒否・ログ記録される。
- LAN外（グローバルIP）からのリクエストは全て 403。ログに `BLOCKED` として残る。
- ファイアウォールはプライベートプロファイルのみ許可。**インターネットへは公開しない。**
- ping のホスト名は正規表現で検証してから subprocess へ渡す（シェルは経由しない）。

## ログ

`logs/controller.log`（1MBで自動ローテート・3世代）

```
2026-08-28 20:27:58 | INFO  | 127.0.0.1 | run_python | SUCCESS | テストPython 完了
2026-08-28 20:27:58 | ERROR | 127.0.0.1 | run_bat | FAILURE | config.json に登録されていない処理です: cmd /c del C:\*
2026-08-28 20:28:10 | WARNING | 8.8.8.8 | / | BLOCKED | LAN外からの接続
```

日時 / 接続元IP / アクション / 成功・失敗 / メッセージ を記録する。

## 第二の脳との連動

`../second_brain`（SECOND BRAIN）が動いていれば、タブレットから直接:

- **企画の現在地** — 現フェーズ・状態・LOCKED決定・依存・担当を表示
- **PROGRESS / DESIGN / BUILDER コンテキスト** — 各AIへ貼り付ける用の圧縮コンテキスト
- **ハンドオフ確認** — 索引済みファイルと実ファイルの存在状況
- **現フェーズ完了** — 現在フェーズを COMPLETE にする（確認ダイアログあり）
- **第二の脳を起動** — 未起動なら `python ../second_brain/run.py serve` を起動

第二の脳側でAPIキーを設定している場合は `config.json` の `brain.api_key` に同じ値を入れる。

```json
"brain": {
  "enabled": true,
  "url": "http://127.0.0.1:8765",
  "api_key": "",
  "project": "synaptic_grove",
  "roles": ["progress", "design", "builder"]
}
```

## ボタンを増やす

`actions/` にモジュールを足し、デコレータを付けるだけでボタンが生える。
`app.py` を触る必要はない。

```python
from . import Result, action

@action("pc_shutdown", "PCシャットダウン", "PC CONTROL", confirm=True)
def pc_shutdown(ctx, params):
    ...
    return Result(True, "シャットダウンします")
```

`confirm=True` を付けるとタブレット側で確認ダイアログが出る。
新しいモジュールは `actions/__init__.py` の `load()` に追記する。

## テスト

```bash
python -m unittest discover -s tests -t tests
```

第二の脳が隣（`../second_brain`）にある場合は連動テストも実行される。
