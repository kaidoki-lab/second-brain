# SECOND BRAIN + SOT21 CONTROLLER

連動する2つのシステム。どちらもこのリポジトリだけで完結する。

| ディレクトリ | 役割 | 依存 |
| --- | --- | --- |
| [`second_brain/`](second_brain/) | **第二の脳** — 複数AI（ChatGPT / Codex / Claude / Gemini / ローカルAI）へ、確定した事実は共有し思考方法は共有しないための中央管理層 | なし（Python標準ライブラリ + SQLite） |
| [`SOT21_Controller/`](SOT21_Controller/) | **SOT21 LAN操作盤** — 旧Androidタブレットをブラウザだけの操作端末にし、処理はメインPC側で実行する | Flask / psutil |

```
   SOT21 (ブラウザ)                    ChatGPT / Codex / Claude / Gemini
        │ :5000                              │ :8765  (HTTP / MCP)
   SOT21_Controller  ────────────────►  second_brain
        │                                （唯一の正本: 事実・決定・状態・ハンドオフ）
   bat / Python / OBS / ファイル / サブPC制御
```

2つは**隣同士のディレクトリのまま**使う。操作盤の既定設定が `../second_brain` を参照している。

## 最短の起動手順

```bash
# 1) 第二の脳
cd second_brain
python run.py init          # DB作成 + 役割5種を投入
python run.py seed          # サンプル企画（不要なら省略）
python run.py serve         # http://127.0.0.1:8765

# 2) 操作盤（別ウィンドウ / Windows は start.bat をダブルクリック）
cd SOT21_Controller
pip install -r requirements.txt
python app.py               # http://<このPCのIP>:5000
```

詳細は各ディレクトリの README を参照:

- [second_brain/README.md](second_brain/README.md) — API、ロールプロファイル、MCP設定、外部公開
- [SOT21_Controller/README.md](SOT21_Controller/README.md) — config.json、ボタン追加、SOT21側の設定

## 設計の芯

1. 会話全文は保存しない。保存するのは PROJECT / FACT / DECISION / STATE / HANDOFF / RELATION
2. ハンドオフ本文はコピーせず、パスを索引して参照するだけ
3. AIへ全コンテキストを渡さない。役割ごとに**見える情報も評価軸も禁止事項も変える**
4. 確定した事実だけは全AIで共有する
5. AI同士を直接同期させず、必ず第二の脳を介す

## テスト

```bash
python -m unittest discover -s second_brain/tests -t second_brain/tests   # 68件
cd SOT21_Controller && python -m unittest discover -s tests -t tests      # 42件
```
