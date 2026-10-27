# FX 自動売買 検証基盤

業者を決める前に「その売買ルールは本当に勝てるのか」を確かめるための土台。
**Python 標準ライブラリだけ**で動き、`pip install` は不要。second_brain / SOT21 とは連携しない独立ツール。

> 過去データで検証 → **MT5 デモ口座**で自動売買 → 少額の実弾、の順に進める前提です。リアル口座では既定で動きません。

## 最短手順

```bash
cd fx_bot
python run.py sample                                   # 配線確認用の合成データを作る
python run.py backtest --csv data/sample_usdjpy_h1.csv # 既定の戦略で検証
python -m unittest discover -s tests -t tests          # テスト
```

Windows なら `backtest.bat` をダブルクリックすると、合成データ作成 → バックテストまで流れます。

## MT5 とつなぐ（Windows）

MT5 が入っている PC で、**MT5 を起動してデモ口座にログインした状態**で使います。

1. MT5 の ツール → オプション → エキスパートアドバイザ で「アルゴリズム取引を許可」にチェック（ツールバーの「アルゴリズム取引」ボタンも緑に）
2. 気配値表示で銘柄名を確認（業者によって `USDJPY` / `USDJPY-` / `USDJPY.m` など）
3. 下のどちらかを実行（初回は `MetaTrader5` パッケージを自動で入れます）

| ダブルクリック | コマンド | 内容 |
| --- | --- | --- |
| `mt5_fetch.bat` | `python run.py fetch --symbol USDJPY --timeframe H1` | 過去データを `data/USDJPY_H1.csv` に保存 |
| `mt5_demo.bat` | `python run.py live --symbol USDJPY --timeframe H1 --strategy ma_cross` | デモ口座で自動売買 |
| `mt5_session_bo.bat` | `python run.py live ... --strategy session_bo --risk 0.5 --params ...,side=1,no_fri=1` | USDJPY の session_bo（買いのみ・金曜休み）をデモで前進テスト |
| `mt5_carry.bat` | `python run.py live --symbol USDJPY- --timeframe D1 --strategy carry --risk 3 --params regime=50 --magic 210002 --terminal ...` | 外為ファイネストのデモで carry を USDJPY- / AUDJPY- / GBPJPY- の3ウィンドウで前進テスト（ログは `data/carry_<銘柄>/`） |
| `mt5_ichimoku.bat` | `python run.py live --symbol USDJPY- --timeframe H1 --strategy combo --risk 0.25 --params sig=4,flt=0,tenkan=9,kijun=26,sl_atr=2,tp_atr=0 --magic 210003 ...` | 外為ファイネストのデモで 一目（転換線×基準線）を USDJPY- 1時間足で前進テスト（ログと約定は `data/ichimoku/`） |
| `autostart_on.bat` / `autostart_off.bat` | — | サインイン時に `mt5_session_bo.bat` を自動起動する／やめる（スタートアップのショートカット） |

`live` の動き:

- 新しい足が確定するたびに戦略を判断し、成行で発注。損切り・利確は **MT5 側に注文として置く**ので、このプログラムが止まっても損切りは効きます
- 起動直後は最新の確定足で判断するため、`ma_cross` はすぐにポジションを持ちます
- 自分の注文には目印（マジックナンバー）を付け、**手動で持っているポジションには触りません**
- 開始後の最高値から `--max-dd`% 有効証拠金が減ったら全決済して終了
- Ctrl+C で停止（ポジションは残る）。`--once` で1回だけ判断して終了（動作確認用）
- 約定は `data/fills_<銘柄>.csv` に「頼んだ価格・約定価格・滑り(pips)・スプレッド」を1行ずつ残します（`--fills ""` で無効）。MT5 側で約定した損切り・利確も、損切り価格との差を記録します
- 動作ログは画面と `data/live_YYYYMMDD.log` の両方に出ます（`--log-dir` で変更）
- MT5 との通信が切れても終了せず、待ち時間を延ばしながら取り直し、3回続けて失敗したら再接続します。起動時に MT5 につながらないときも1分おきに待ちます
- 常駐中は Windows のスリープを抑止します（電源設定は変えません。カバーを閉じる・電池切れでは止まります）
- `--notify https://ntfy.sh/<自分だけのトピック名>` を付けると、売買・エラーをスマホに通知します（既定は送りません）
- リアル口座だと起動を拒否します（`--allow-real` で解除できますが、デモで十分確かめてから）
- 同じ口座で2つ目の戦略を動かすときは `--magic 210002` のように**目印を変えます**（同じ目印だと互いのポジションを自分のものと思い込みます）。
  ただし最大ドローダウンの停止と数量計算は口座全体の有効証拠金で判断するので、相手の損益の影響は受けます。完全に分けるなら別の口座で
- `carry` で起動すると、業者のスワップ（MT5 の表示値）をログに出します。受け取れる側と carry の方向が合っているか確認してください
- `--max-day-loss 1 --max-week-loss 2.5` のように付けると、**その目印の**損失（今日・今週の確定損益＋含み損益）が残高の 1% / 2.5% に達した時点で決済し、翌日・翌週の月曜（サーバー時刻）まで新規を止めます。同じ口座の別のボットの損益は数えません。既定は無効
- 日付が変わるたびに `[日報]` として前日の確定損益をログ（と通知）に出します
- 状態ファイル `<log-dir>/state_<銘柄>_<目印>.json` を5秒ごとに書き直します。次に起動したとき、これを読んで
  **止まっている間に MT5 側で損切り・利確されたポジションを報告**し、持ち越したポジション（損切りが無いものは `[注意]`）と損失上限の停止期間を引き継ぎます
- `--heartbeat-url` に healthchecks.io などの URL を渡すと5分おきにアクセスします。PC ごと止まったときは先方から知らせが来ます（先方の登録はご自身で）

## 見張り（watch）

```bash
python run.py watch --dir data --notify https://ntfy.sh/<トピック名>   # 常駐。10分更新が止まったボットを知らせる
python run.py watch --once                                              # 今の一覧を出すだけ
```

`data` の下の `state_*.json` をすべて見ます。落ちた・固まった・MT5 につながらないボットは `[停止の疑い]`、戻れば `[復旧]`。
Ctrl+C や停止ラインで止めたものは「停止済み」として扱い、知らせません。見張り自体は PC が動いている間しか働かないので、PC ごとの停止は `--heartbeat-url` で拾います。

`pip install MetaTrader5` が失敗するときは、その Python のバージョンにまだ対応していない可能性があります。
対応している Python（[PyPI のページ](https://pypi.org/project/MetaTrader5/) で確認）を入れてください。
MT5 が自動で見つからないときは `--terminal "C:\Program Files\...\terminal64.exe"` で指定します。

## 本物のデータで試す

合成データはランダムなので成績に意味はありません。実データは例えば:

- **MT5**: `mt5_fetch.bat`（上記）が一番簡単。手動なら 表示 → 銘柄 → チャートバー からエクスポートした `<DATE> <TIME> <OPEN>...` 形式もそのまま読めます
- **その他**: `time,open,high,low,close[,volume]` の見出し付き CSV（カンマ / タブ / セミコロン可）

`data/` に置いて:

```bash
python run.py backtest --csv data/USDJPY_H1.csv --symbol USDJPY --spread 0.2
python run.py backtest --csv data/EURUSD_H1.csv --symbol EURUSD --spread 0.4 --quote-rate 150
```

価格は **BID** として扱い、スプレッドは `--spread`（pips）で上乗せします。
円口座で EURUSD など円以外の決済通貨のペアを扱うときは、`--quote-rate` に USDJPY 等の概算レートを渡します。

## コマンド

| コマンド | 内容 |
| --- | --- |
| `strategies` | 戦略とパラメータの一覧 |
| `backtest` | 1つの設定で検証。`--params fast=10,slow=40` `--trades out.csv` |
| `optimize` | パラメータ総当たり。前半70%で選び、残り30%で**期間外検証**して過剰最適化を見抜く |
| `sample` | 合成データ作成 |
| `compare` | デモ口座の取引を、同じ期間のバックテストと1件ずつ照合（入り・出口の差 pips、片方だけの取引）。MT5 が必要。例: `python run.py compare --strategy session_bo --params ... --since 2026-10-27` |

共通オプション: `--swap`（政策金利表から推定したスワップを損益に入れる。`carry` では常に入る）`--swap-cut`（業者の取り分 年率%, 既定 1）`--slippage`（成行・損切りの滑り pips, 既定 0）`--equity`（初期資金, 既定 100万）`--risk`（1回の損失許容 %, 既定 1）`--leverage`（既定 25）`--max-dd`（停止ライン %, 既定 20）

```bash
python run.py optimize --csv data/USDJPY_H1.csv --grid fast=10,20,40 slow=50,100,200 sl_atr=1.5,2,3
```

## 収録戦略

| 名前 | ルール | パラメータ |
| --- | --- | --- |
| `ma_cross` | 短期SMA > 長期SMA なら買い、逆なら売り | `fast` `slow` |
| `breakout` | 直近 n 本の高値/安値を終値で抜けた方向に入る | `n` |
| `band_revert` | 移動平均から標準偏差 k 個分以上離れたら逆張り、平均を跨いだら手仕舞い | `n` `k` |
| `rsi_revert` | RSI が `lo` 未満で買い・`hi` 超で売り、50 を跨いだら手仕舞い | `n` `lo` `hi` |
| `pullback` | 終値が長期SMA(`trend`)より上なら RSI の押し目で買い、下なら戻りで売り。RSI が 50 を跨いだら手仕舞い | `trend` `n` `lo` `hi` |
| `session_bo` | その日の `rs`〜`re` 時の高値/安値を抜けたら入り、`exit_h` 時に必ず手仕舞い（時刻は MT5 サーバー時刻。H1 以下向け）。`side=1` で買いのみ・`-1` で売りのみ、`no_fri=1` で金曜は休む。`shift` は時計のずらし（業者が1時間進んでいれば `-1`） | `rs` `re` `exit_h` `side` `no_fri` `shift` |
| `carry` | スワップが受け取れる側に持ち続け、終値が `regime` 本SMAより不利側に来たら降りる（日足向け）。方向は金利表で自動（業者の取り分 `cut` を引いた受け取りが `edge` 未満なら持たない）。`side=1/-1` で固定。既定の損切りは ATR(20)×5 の遠い保険 | `regime` `edge` `cut` `side` |

| `combo` | 入る合図 `sig`（1 MACD がシグナル線を交差 / 2 ストキャスの %K が %D を `lo` 未満で上抜け・`hi` 超で下抜け / 3 パラボリックSARの反転 / 4 一目の転換線が基準線を交差 / 5 EMA(`fast`)×EMA(`slow`)）を、地合い `flt`（0 なし / 1 ADX≧`adx` かつ DI が同じ向き / 2 ADX<`adx` / 3 終値が SMA(`trend`) の同じ側 / 4 終値が一目の雲の外の同じ側）で絞る。フィルターに止められた合図では手仕舞い。`side` で片方向のみ | `sig` `flt` `fast` `slow` `signal` `k` `lo` `hi` `adx_n` `adx` `trend` `tenkan` `kijun` `side` |

どれも共通で `atr`（ATR期間）`sl_atr`（損切り = ATR × 倍率）`tp_atr`（利確倍率, 0 で無し）。

## シミュレーションの約束事（甘く見積もらないため）

1. 足の**確定後**に判断し、**次の足の始値**で約定（未来の価格は見ない）
2. 買いは ask（= bid + スプレッド）、売りは bid で約定
3. 同じ足で損切りと利確の両方に届いたら**損切り**を採用
4. 窓開けで損切り価格を飛び越えたら、損切り価格ではなく**始値**で約定
5. ロットは「損切りに掛かったら資金の `--risk`% を失う」量。レバレッジ上限で頭打ち、1,000通貨単位で切り捨て
6. 資金がピークから `--max-dd`% 減ったら全決済して**以後停止**
7. `--slippage` を付けると、成行の新規・決済と損切りの約定がその pips だけ不利にずれる（利確は指値なのでずれない）

8. `--swap`（と `carry`）では、日付をまたいで持ったポジションに、その日の金利差 − 業者の取り分 を暦日数ぶん加える（週末は3日分）。
   金利差は `swap.py` の政策金利表（2008年以降・手入力の概算）から。2008年より前はスワップ0で、`carry`（自動方向）は持たない

スワップは推定値で、約定拒否はまだ入っていません。実際の成績はこれより悪くなる前提で見てください。
業者のスワップは金利差どおりとは限りません（MetaQuotes-Demo はドル円の買いでもマイナス）。`carry` を試すなら実際のスワップ表を確認してください。

## 構成

```
fxbot/
  data.py        CSV 読み込み / 書き出し / 合成データ
  indicators.py  SMA, ATR, EMA, MACD, ストキャス, ADX, パラボリックSAR, 一目 など（足 i までしか見ない）
  strategy.py    戦略。方向と損切り幅を返すだけで、発注はしない
  risk.py        ロット計算、ドローダウン停止
  broker.py      Broker インターフェースと PaperBroker（仮想約定・スワップ計上）
  swap.py        政策金利表とスワップの推定
  backtest.py    step(): 1本ごとの判断→発注。run(): 過去データを流す
  mt5.py         MT5 から過去データ取得 / MT5Broker / 自動売買ループ
  metrics.py     成績集計
  compare.py     実際の取引とバックテストの照合
  watch.py       live の状態ファイルの見張り
  cli.py         コマンド
```

## 進め方

1. `mt5_fetch.bat` で実データを取り、`backtest` / `optimize` で検証。期間外検証でも崩れない設定だけ残す
2. その設定で `live` を**デモ口座で数週間**動かし、バックテストとの成績のずれ（スプレッド・滑り）を確認
3. 新しい戦略は `Strategy` を継承して `decide()` を書き、`STRATEGIES` に登録（backtest も live もそのまま使える）
4. MT5 以外の業者は `broker.py` の `Broker` を実装すれば同じ戦略で動く

## 注意

このツールは検証用で、利益を保証するものではありません。投資判断と損失はご自身の責任です。
