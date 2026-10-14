# YOUTUBE STUDIO

YouTube チャンネルを **「AIが毎日1本作る → 人はスマホで見て承認するだけ」** で回すための仕組み。

```
 毎日 5:00（タスクスケジューラ）
   ① 再生数を取り込む ─ 伸びた型・伸びなかった型を覚える
   ② 企画を立てる    ─ 再生数・見送り理由・第二の脳の確定事実を踏まえる
   ③ 台本を書く      ─ ローカルAI（無料）か Claude
   ④ 読み上げる      ─ VOICEVOX
   ⑤ 動画にする      ─ 本編（横）＋ショート（縦）＋サムネ
   ⑥ 確認待ちへ
                          ↓
 あなた（スマホ・SOT21から数分）
   見る → 承認（予約投稿）／理由を書いて見送り
                          ↓
   見送り理由は次の台本に必ず反映される
```

## 収益化について（先に読む）

- 広告収益（YouTube パートナープログラム）の条件は、登録者 1,000 人に加えて、
  直近12か月の公開動画の総再生時間 4,000 時間か、直近90日のショート再生 1,000 万回
  （書いた時点の条件。変わることがあるので YouTube ヘルプで確認すること）。
  **最初の数か月は収益ゼロ** が普通です。
- YouTube は **量産型・使い回し・中身の薄い動画を収益化の対象外** にしています（「独自性のないコンテンツ」）。
  完全放置の自動投稿チャンネルは、審査で落ちるか後から収益化を止められやすい。
  そのためこの仕組みは、
  - 台本に「このチャンネルならではの切り口」と「人が確かめる点（checks）」を必ず書かせる
  - **人の承認なしには公開しない**
  - 確認待ちが3本溜まったら新しく作らない（見られない動画を量産しない）

  という作りにしています。承認画面の「公開前に確かめてください」は必ず読んでください。

## はじめかた（Windows）

1. **`setup.bat`** をダブルクリック
   - Python の部品、ffmpeg、VOICEVOX を入れて、チャンネルのテーマ等を聞きます
   - 最後に `check` が全部 `[OK]` になれば準備完了
2. 台本を書くAIを決める（setup の中で聞かれます）
   - `ollama`: 第二の脳で育てたローカルAI（`second_brain\llama.bat`）。無料。8B モデルでは文章が粗いことがあります
   - `claude`: Claude API。台本の質が上がります。環境変数 `ANTHROPIC_API_KEY` が必要（1本あたり数十円程度）
3. **`auto.bat`** をダブルクリック → 1本目ができます（数分〜十数分）
4. **`review.bat`** で確認画面が開きます。スマホ・SOT21 からは表示されたアドレス（`http://<PCのIP>:8950`）を開く
5. 良ければ **`schedule.bat`** で毎日 5:00 の自動実行を登録（`schedule.bat 07:30` で時刻変更、`schedule.bat off` で停止）

SOT21 操作盤の AUTOMATION にも「YouTube 1本作る」「YouTube確認画面」ボタンがあります。

## 承認したあとの投稿

| `youtube.upload` | 承認ボタンを押すと | 準備 |
| --- | --- | --- |
| `manual`（既定） | 画面にタイトル・概要欄・タグのコピー用ボタンが出る。YouTube Studio でアップロードして貼り、URLを記録 | なし |
| `api` | そのまま予約投稿（本編・ショート・サムネ） | 下の「YouTube API の設定」と **Google の API 監査** |

> Google の規約で、**監査を通っていない API プロジェクトから投稿した動画は強制的に非公開になり、公開に切り替えられません**。
> 監査の申請（YouTube API Services の Audit and Quota Extension フォーム）が通るまでは `manual` を使ってください。

### YouTube API の設定（再生数の取り込み・API投稿用）

1. Google Cloud Console でプロジェクトを作り、「YouTube Data API v3」を有効にする
2. 「OAuth 同意画面」を作る（公開ステータスは「テスト」で可。テストユーザーにチャンネルの Google アカウントを追加）
3. 「認証情報」→「OAuth クライアント ID」→ 種類 **デスクトップアプリ** → JSON をダウンロードし、
   `youtube_studio\secrets\client_secret.json` として保存
4. `python run.py auth` → ブラウザで許可。以後、毎朝の再生数の取り込みが自動で動きます

再生数の取り込みは読み取りだけなので、監査なしで使えます。

## 設定

`channel.json` が既定値、**自分の設定は `channel.local.json`** に書きます（`setup` が作ります）。
`update.bat` で更新しても `channel.local.json`・`secrets\`・`episodes\` は消えません。

| 項目 | 意味 |
| --- | --- |
| `channel.theme` / `audience` / `promise` | 何を・誰に・見ると何が得られるか。企画と台本の軸 |
| `channel.forbidden` | 台本で禁止すること |
| `format.long_minutes` | 本編の長さ（分）。既定 8 |
| `format.shorts` | ショートも作るか |
| `writer.backend` | `ollama` / `claude` |
| `voice.speaker` / `speed` / `credit` | VOICEVOX の話者番号・話速・概要欄に入れるクレジット（**キャラクターごとの規約で表記が必要**） |
| `render.font` / `background` / `accent` / `bgm` | 見た目。BGM は著作権フリーの音源のパスを書く |
| `youtube.publish_hour` | 予約投稿の時刻（1日1本ずつ空き枠に入れる） |
| `youtube.synthetic_media` | 実在の人物・出来事と見間違える合成映像を使うなら `true`（YouTube の開示義務） |
| `brain.enabled` / `project` | 第二の脳から確定事実を読み、公開した動画を FACT として残す |

## コマンド

```bash
python run.py setup        # チャンネル設定（対話）
python run.py check        # 準備の確認
python run.py auto         # 再生数 → 企画 → 1本（毎日の自動実行と同じ）
python run.py review       # 確認画面
python run.py list         # 一覧
python run.py plan -n 5    # 企画だけ足す
python run.py make -n 2    # 2本作る（確認待ち3本で止まる）
python run.py approve <id> / reject <id> "理由"
python run.py auth / stats # YouTube 認証 / 再生数の取り込み
```

## つくり

```
youtube_studio/
  run.py  channel.json  *.bat
  studio/
    pipeline.py  流れ全体（企画→台本→音声→動画→確認待ち→承認→投稿、振り返り）
    writer.py    企画・台本（Ollama / Claude）。JSONで受け取り、形を検査して1回だけ書き直させる
    voice.py     VOICEVOX。文ごとに音声を作り、長さで字幕を合わせる
    render.py    Pillow で画面、ffmpeg で mp4。本編・ショート・サムネ
    review.py    確認画面（標準ライブラリの http.server、LAN内のみ、動画のシーク対応）
    youtube.py   OAuth・再開可能アップロード・サムネ・再生数（urllib のみ）
    brain.py     第二の脳とのつなぎ（任意）
    episode.py   1本＝1フォルダ（episodes/<id>/）。状態は episode.json
  tests/
```

途中で止まっても（VOICEVOX が起動していなかった等）、次の実行はそのフォルダの続きから再開します。
止まった理由は確認画面の一覧に出ます。

## テスト

```bash
cd youtube_studio
python -m unittest discover -s tests -t tests   # 33件（ffmpeg と日本語フォントが必要）
```

AI・VOICEVOX・YouTube は偽物に差し替え、ffmpeg は本物で mp4 を作って長さと解像度を確かめます。
