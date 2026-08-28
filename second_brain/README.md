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

```bash
python run.py init            # DB作成＋既定ロール5種を投入
python run.py seed            # サンプル（SYNAPTIC GROVE）を投入
python run.py serve           # http://127.0.0.1:8765
```

LAN公開（タブレットや別PCから見る場合）は APIキー必須：

```bash
python run.py key                                  # キー生成
set SECOND_BRAIN_API_KEY=<生成されたキー>            # Windows (macOS/Linux は export)
python run.py serve --host 0.0.0.0                 # http://<PCのIP>:8765
```

キーなしで `0.0.0.0` にバインドしようとすると起動を拒否する。
ブラウザからは `http://<PCのIP>:8765/login?key=<キー>` で一度入るとCookieが入る。

DBの場所は `~/.second_brain/brain.db`（`--db` か `SECOND_BRAIN_DB` で変更可）。

## CLI

| コマンド | 内容 |
| --- | --- |
| `init` | DB作成と既定ロール投入 |
| `seed` | サンプルプロジェクト投入 |
| `serve [--host --port --api-key --budget]` | Webサーバー |
| `mcp` | MCP server (stdio) |
| `context <role> [--project] [--budget]` | 役割別コンテキストを標準出力へ |
| `index --project P --dir DIR [--pattern *.md] [--recursive]` | 既存ハンドオフを索引（本文は読まない） |
| `verify [--project P]` | 索引したファイルの存在確認 |
| `export [--out brain.md]` | brain.md を書き出す |
| `key` | APIキー生成 |

## ブラウザUI

| URL | 内容 |
| --- | --- |
| `/` | PROJECTS / ACTIVE PHASES / AI AGENTS / DECISIONS / HANDOFFS / DEPENDENCIES / RECENT CHANGES |
| `/project/{id}` | 現在地、フェーズ履歴、決定、事実、ハンドオフ、関係＋各種入力フォーム |
| `/agents` | ロールプロファイル（見せる情報／隠す情報／評価軸／禁止事項）一覧 |
| `/preview/context/{role}` | そのAIへ実際に渡るコンテキストとトークン数の確認 |

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
curl -H "Authorization: Bearer $KEY" http://192.168.1.10:8765/context/design
curl -H "Authorization: Bearer $KEY" -H 'Content-Type: application/json' \
     -d '{"project":"synaptic_grove","title":"CHANNELは分岐3方向まで","status":"LOCKED"}' \
     http://192.168.1.10:8765/api/decision
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

- Cloudflare Tunnel: `cloudflared tunnel --url http://127.0.0.1:8765`
- Tailscale Funnel: `tailscale funnel 8765`
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
