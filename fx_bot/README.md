# FX 自動売買 検証基盤

業者を決める前に「その売買ルールは本当に勝てるのか」を確かめるための土台。
**Python 標準ライブラリだけ**で動き、`pip install` は不要。second_brain / SOT21 とは連携しない独立ツール。

> 実際の発注機能はまだありません。過去データで検証 → デモ口座 → 少額の実弾、の順に進める前提です。

## 最短手順

```bash
cd fx_bot
python run.py sample                                   # 配線確認用の合成データを作る
python run.py backtest --csv data/sample_usdjpy_h1.csv # 既定の戦略で検証
python -m unittest discover -s tests -t tests          # テスト
```

Windows なら `backtest.bat` をダブルクリックすると、合成データ作成 → バックテストまで流れます。

## 本物のデータで試す

合成データはランダムなので成績に意味はありません。実データは例えば:

- **MT5**: ツール → ヒストリーセンター（または銘柄を右クリック →「チャート」→ バー）からエクスポート。`<DATE> <TIME> <OPEN>...` 形式のままで読めます
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

共通オプション: `--equity`（初期資金, 既定 100万）`--risk`（1回の損失許容 %, 既定 1）`--leverage`（既定 25）`--max-dd`（停止ライン %, 既定 20）

```bash
python run.py optimize --csv data/USDJPY_H1.csv --grid fast=10,20,40 slow=50,100,200 sl_atr=1.5,2,3
```

## 収録戦略

| 名前 | ルール | パラメータ |
| --- | --- | --- |
| `ma_cross` | 短期SMA > 長期SMA なら買い、逆なら売り | `fast` `slow` |
| `breakout` | 直近 n 本の高値/安値を終値で抜けた方向に入る | `n` |

どちらも共通で `atr`（ATR期間）`sl_atr`（損切り = ATR × 倍率）`tp_atr`（利確倍率, 0 で無し）。

## シミュレーションの約束事（甘く見積もらないため）

1. 足の**確定後**に判断し、**次の足の始値**で約定（未来の価格は見ない）
2. 買いは ask（= bid + スプレッド）、売りは bid で約定
3. 同じ足で損切りと利確の両方に届いたら**損切り**を採用
4. 窓開けで損切り価格を飛び越えたら、損切り価格ではなく**始値**で約定
5. ロットは「損切りに掛かったら資金の `--risk`% を失う」量。レバレッジ上限で頭打ち、1,000通貨単位で切り捨て
6. 資金がピークから `--max-dd`% 減ったら全決済して**以後停止**

スワップ・スリッページ・約定拒否はまだ入っていません。実際の成績はこれより悪くなる前提で見てください。

## 構成

```
fxbot/
  data.py        CSV 読み込み / 書き出し / 合成データ
  indicators.py  SMA, ATR など（足 i までしか見ない）
  strategy.py    戦略。方向と損切り幅を返すだけで、発注はしない
  risk.py        ロット計算、ドローダウン停止
  broker.py      Broker インターフェースと PaperBroker（仮想約定）
  backtest.py    step(): 1本ごとの判断→発注。run(): 過去データを流す
  metrics.py     成績集計
  cli.py         コマンド
```

## 次の段階（業者が決まったら）

1. `broker.py` の `Broker` を実装したクラスを追加（例: MT5 なら `MetaTrader5` パッケージ、OANDA なら REST API）
2. 足が確定するたびに `backtest.step(broker, strategy, bars, len(bars) - 1, risk)` を呼ぶループを書く
3. **まずデモ口座で**数週間動かし、バックテストと成績のずれ（スプレッド・滑り）を確認
4. 新しい戦略は `Strategy` を継承して `decide()` を書き、`STRATEGIES` に登録

## 注意

このツールは検証用で、利益を保証するものではありません。投資判断と損失はご自身の責任です。
