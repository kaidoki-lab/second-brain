# SECOND BRAIN

複数のAI（ChatGPT / Codex / Claude / Gemini / ローカルAI）を同じ企画へ参加させるための
中央管理層。**確定した事実は共有し、思考方法は共有しない。**

- 会話全文は保存しない。保存するのは PROJECT / FACT / DECISION / STATE / HANDOFF / RELATION。
- ハンドオフ本文はコピーせず、ファイルパスを索引するだけ。
- 各AIは自分専用に圧縮されたコンテキスト（目安 500〜2000 tokens）だけを取得する。

依存ライブラリなし（Python 3.10+ 標準ライブラリのみ / DBは SQLite）。

```
                 SECOND BRAIN DB
        ┌──────────┼──────────┬──────────┐
      FACTS    DECISIONS   HANDOFFS  RELATIONS
        └──────────┼──────────┴──────────┘
                CONTEXT ROUTER
      ┌──────────┬────┴─────┬──────────┬──────────┐
   Progress    Design    Builder    Critic    Explorer
      └────────── 別々の思考方式 ──────────────────┘
```

## 起動

**Windows: `start.bat` をダブルクリックするだけ。** ブラウザが自動で開きます。

既定のポート 8900 を他のアプリが使っていた場合は、**空いている次の番号で自動的に起動します**
（黒い画面に実際のアドレスが表示され、ブラウザもそのアドレスで開きます）。
起動中のアドレスは `~/.second_brain/server_url.txt` にも記録されるので、SOT21操作盤など
他のツールはポートが変わっても自動で追従します。

コマンドで起動する場合:

```bash
python run.py init            # 初回のみ: DB作成＋既定ロール5種を投入
python run.py serve           # http://127.0.0.1:8900
python run.py seed            # 任意: サンプル（SYNAPTIC GROVE）を投入
```

LAN公開（タブレットや別PCから見る場合）は APIキー必須：

```bash
python run.py key                                  # キー生成
set SECOND_BRAIN_API_KEY=<生成されたキー>            # Windows (macOS/Linux は export)
python run.py serve --host 0.0.0.0                 # http://<PCのIP>:8900
```

キーなしで `0.0.0.0` にバインドしようとすると起動を拒否する。
ブラウザからは `http://<PCのIP>:8900/login?key=<キー>` で一度入るとCookieが入る。

DBの場所は `~/.second_brain/brain.db`（`--db` か `SECOND_BRAIN_DB` で変更可）。

## CLI

| コマンド | 内容 |
| --- | --- |
| `init` | DB作成と既定ロール投入 |
| `seed` | サンプルプロジェクト投入 |
| `serve [--host --port --api-key --budget --open]` | Webサーバー（`--open` でブラウザ自動起動） |
| `mcp` | MCP server (stdio) |
| `context <role> [--project] [--budget]` | 役割別コンテキストを標準出力へ |
| `index --project P --dir DIR [--pattern *.md] [--recursive]` | 既存ハンドオフを索引（本文は読まない） |
| `scan --project P --dir DIR [--keywords ハンドオフ,handoff]` | 名前で自動検出して一括登録 |
| `verify [--project P]` | 索引したファイルの存在確認 |
| `export [--out brain.md]` | brain.md を書き出す |
| `key` | APIキー生成 |

## ブラウザUI（日本語・コマンド不要）

| URL | 内容 |
| --- | --- |
| `/` | ダッシュボード。企画一覧、最近の変更、行方不明ファイルの警告 |
| `/import` | **ハンドオフの取り込み**。フォルダを指定すると、名前に「ハンドオフ」を含むファイルを自動で探して登録 |
| `/handoffs` | **ハンドオフ一覧と検索**。企画の付け替え、存在確認、一覧からの除外 |
| `/projects` | 企画の一覧と作成（名前だけ入れればIDは自動生成、日本語可） |
| `/project/{id}` | 現在の工程、決定事項、事実、ハンドオフ＋入力フォーム |
| `/project/{id}/bundle` | **ハンドオフ本文をまとめてAIに渡す**（保存はしない） |
| `/project/{id}/intake` | **AIの回答を工程表として取り込む**（確認してから保存） |
| `/agents` | AIごとの「見せる情報／見せない情報／評価軸／禁止事項」 |
| `/preview/context/{role}` | そのAIへ実際に渡る文章とトークン数（コピーして貼るだけ） |

### ハンドオフを読ませて工程を組み立てる

索引だけでなく、**中身をAIに読ませて工程表を作る**ところまでできる。

1. `/project/{id}/bundle` — ハンドオフを選ぶと本文を読み出して1つの文章にまとめる
   （`.md .txt .csv .json .docx` 対応。Shift-JIS も自動判別。`.pdf` は非対応）
2. その文章をChatGPTやClaudeへ貼る → 工程表・決定事項が返る
3. `/project/{id}/intake` — 返ってきた文章を貼り付けると、確認画面を経て保存される

読み込んだ本文は**保存しない**。保存するのはAIが出した工程・決定事項・依存関係だけ。
以後は `/context/{role}` に工程表が反映され、どのAIも同じ現在地を見る。

取り込める書式:

```
PHASE: 工程名 | 状態(未着手/作業中/完了/停止中) | 担当 | 成果物をセミコロン区切り
DECISION: 決まったこと | 補足
FACT: 前提や制約 | タグ
DEPENDS: 後の工程 -> 先に必要な工程
OPEN: まだ決まっていないこと
```

説明文が混じっていても、読める行だけ拾う。

### PC内のハンドオフを取りまとめる

ファイル名に「ハンドオフ」または「handoff」が入っていれば、置き場所がバラバラでも拾えます。

1. `/import` を開く
2. 探すフォルダを入力（例 `D:\projects`）
3. 「この条件で取り込む」を押す

サブフォルダも辿ります。`node_modules` `.git` `Windows` `Program Files` などは自動で除外。
同じファイルを二度取り込んでも重複しません。**中身は読まず、移動もしません。**

コマンドで一括登録する場合:

```bash
python run.py scan --project 未分類 --dir "D:\projects" --keywords "ハンドオフ,handoff"
python run.py verify        # 登録したファイルがまだ存在するか確認
```

## AI向け API

読み取り:

```
GET /context/{role}?project=&budget=      役割別コンテキスト（text/plain、?format=json も可）
GET /project/{id}/current                 現在地（text/plain、?format=json も可）
GET /decisions/{project}?status=LOCKED
GET /handoffs/{project}?status=ACTIVE
GET /api/context?role=&project=
GET /api/project/{id}   /api/projects   /api/agents   /api/roles   /api/changes
GET /api/brain          /brain.md       /api/health（認証不要）
```

書き込み（JSON body）:

```
POST /api/decision   {project, title, body, status, phase, tags}
POST /api/state      {project, phase, status, owner, note, deliverables[]}
POST /api/handoff    {id, project, file_path, title, phase, owner, status}
POST /api/relation   {project, src, rel, dst}
POST /api/fact       {project, body, tags[]}
POST /api/project    {id, name, status, summary}
POST /api/agent      {id, name, role, context_profile}
POST /api/role       {id, name, goal, visible_context[], hidden_context[], ...}
POST /api/handoffs/verify {project}
```

認証は `Authorization: Bearer <key>` または `X-API-Key: <key>`。

```bash
curl -H "Authorization: Bearer $KEY" http://192.168.1.10:8900/context/design
curl -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
     -d '{"project":"synaptic_grove","title":"CHANNELは分岐3方向まで","status":"LOCKED"}' \
     http://192.168.1.10:8900/api/decision
```

## ロールプロファイル

既定で5種。`/agents` かAPIで自由に追加・変更できる。

| role | 見る | 見ない | 評価軸 | 禁止 |
| --- | --- | --- | --- | --- |
| progress | 工程・依存・担当・変更履歴 | 世界観・アセット・API | 依存関係／停滞／完了条件／次工程 | 不要なデザイン変更、仕様の再議論 |
| design | 世界観・採用素材・制約・現フェーズ | 実装状態・API・ファイル | 一貫性／可読性／独自性／体験 | 実装都合だけでデザインを決める |
| builder | 確定仕様・API・ファイル・依存 | 世界観・未確定案・失敗履歴 | 正確性／安定性／保守性／再現性 | 勝手な仕様変更 |
| critic | 現在案・決定・失敗履歴・依存 | アセット・ハンドオフ | 破綻点／依存リスク／矛盾／見落とし | 無条件な賛成 |
| explorer | 目的・制約・確定事項のみ | 既存案の細部すべて | 新規性／差別化／可能性 | 現行案の言い換え |

`visible_context` に指定できるセクション名:
`project, summary, current_phase, status, owner, locked_decisions, open_decisions,
facts, constraints, world, assets, failures, api, dependencies, deliverables,
handoff, files, implementation_state, relations, agents, recent_changes`

`role / goal / evaluation_axes / prohibitions` は常に付与される（＝思考の分離）。
トークン上限を超える場合は、長いリストの切り詰め → 優先度の低いセクションの削除、の順に縮む。
`project / current_phase / status / role / goal` は削られない。

## 既存ハンドオフの登録（本文は読まない）

```bash
python run.py index --project synaptic_grove --dir "D:\projects\synaptic_grove\handoff" --recursive
python run.py verify --project synaptic_grove
```

## MCP Server

ChatGPT / Claude / Codex から同じ第二の脳を直接操作する。

```bash
python run.py mcp     # stdio / JSON-RPC 2.0
```

公開ツール: `list_projects, get_project_state, get_context, get_decisions,
get_handoffs, get_dependencies, write_decision, update_state, write_handoff,
write_relation`

Claude Desktop / Claude Code の設定例:

```json
{
  "mcpServers": {
    "second-brain": {
      "command": "python",
      "args": ["D:\\projects\\second_brain\\run.py", "mcp"]
    }
  }
}
```

## 外部AIからの接続

`127.0.0.1` / `192.168.x.x` はクラウドAIから直接参照できない。HTTPS入口を用意する:

- Cloudflare Tunnel: `cloudflared tunnel --url http://127.0.0.1:8900`
- Tailscale Funnel: `tailscale funnel 8900`
- 自前VPS + リバースプロキシ

いずれの場合も `SECOND_BRAIN_API_KEY` を必ず設定する。

## 運用ルール

1. 文章を無制限に溜めない
2. 会話ではなく決定事項を保存する
3. AIへ全コンテキストを渡さない
4. AIごとに表示情報を変える
5. AIごとに思考パターンを変える
6. 確定した事実だけ全AIで共有する
7. ハンドオフ本文はコピーせず参照する
8. プロジェクト状態を唯一の正本とする
9. AI同士を直接同期させず、第二の脳を介す
10. トークン削減を優先する

## テスト

```bash
python -m unittest discover -s tests -t tests
```
