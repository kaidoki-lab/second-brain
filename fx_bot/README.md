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

`live` の動き:

- 新しい足が確定するたびに戦略を判断し、成行で発注。損切り・利確は **MT5 側に注文として置く**ので、このプログラムが止まっても損切りは効きます
- 起動直後は最新の確定足で判断するため、`ma_cross` はすぐにポジションを持ちます
- 自分の注文には目印（マジックナンバー）を付け、**手動で持っているポジションには触りません**
- 開始後の最高値から `--max-dd`% 有効証拠金が減ったら全決済して終了
- Ctrl+C で停止（ポジションは残る）。`--once` で1回だけ判断して終了（動作確認用）
- リアル口座だと起動を拒否します（`--allow-real` で解除できますが、デモで十分確かめてから）

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

共通オプション: `--slippage`（成行・損切りの滑り pips, 既定 0）`--equity`（初期資金, 既定 100万）`--risk`（1回の損失許容 %, 既定 1）`--leverage`（既定 25）`--max-dd`（停止ライン %, 既定 20）

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
| `session_bo` | その日の `rs`〜`re` 時の高値/安値を抜けたら入り、`exit_h` 時に必ず手仕舞い（時刻は MT5 サーバー時刻。H1 以下向け） | `rs` `re` `exit_h` |

どれも共通で `atr`（ATR期間）`sl_atr`（損切り = ATR × 倍率）`tp_atr`（利確倍率, 0 で無し）。

## シミュレーションの約束事（甘く見積もらないため）

1. 足の**確定後**に判断し、**次の足の始値**で約定（未来の価格は見ない）
2. 買いは ask（= bid + スプレッド）、売りは bid で約定
3. 同じ足で損切りと利確の両方に届いたら**損切り**を採用
4. 窓開けで損切り価格を飛び越えたら、損切り価格ではなく**始値**で約定
5. ロットは「損切りに掛かったら資金の `--risk`% を失う」量。レバレッジ上限で頭打ち、1,000通貨単位で切り捨て
6. 資金がピークから `--max-dd`% 減ったら全決済して**以後停止**
7. `--slippage` を付けると、成行の新規・決済と損切りの約定がその pips だけ不利にずれる（利確は指値なのでずれない）

スワップ・約定拒否はまだ入っていません。実際の成績はこれより悪くなる前提で見てください。

## 構成

```
fxbot/
  data.py        CSV 読み込み / 書き出し / 合成データ
  indicators.py  SMA, ATR など（足 i までしか見ない）
  strategy.py    戦略。方向と損切り幅を返すだけで、発注はしない
  risk.py        ロット計算、ドローダウン停止
  broker.py      Broker インターフェースと PaperBroker（仮想約定）
  backtest.py    step(): 1本ごとの判断→発注。run(): 過去データを流す
  mt5.py         MT5 から過去データ取得 / MT5Broker / 自動売買ループ
  metrics.py     成績集計
  cli.py         コマンド
```

## 進め方

1. `mt5_fetch.bat` で実データを取り、`backtest` / `optimize` で検証。期間外検証でも崩れない設定だけ残す
2. その設定で `live` を**デモ口座で数週間**動かし、バックテストとの成績のずれ（スプレッド・滑り）を確認
3. 新しい戦略は `Strategy` を継承して `decide()` を書き、`STRATEGIES` に登録（backtest も live もそのまま使える）
4. MT5 以外の業者は `broker.py` の `Broker` を実装すれば同じ戦略で動く

## 注意

このツールは検証用で、利益を保証するものではありません。投資判断と損失はご自身の責任です。
