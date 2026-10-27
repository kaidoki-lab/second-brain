//+------------------------------------------------------------------+
//| GoldBreakoutLong.mq5                                              |
//| 金（XAUUSD）1時間足・買いのみの高値ブレイク                         |
//|                                                                    |
//| fx_bot の breakout(n=200, sl_atr=3, tp_atr=0) を「買いのみ」で包んだ |
//| ものと同じ判断をする:                                               |
//|   確定足の終値 > 直前200本の高値 → 買い（持っていなければ）          |
//|   確定足の終値 < 直前200本の安値 → 手仕舞い                          |
//|   損切り = ATR(14, 真の値幅の単純平均) × 3。利確なし。               |
//| 損切りは注文と一緒にサーバー側へ置く。手動ポジションには触らない。  |
//| 収益の保証はなく、投資助言でもない。                                 |
//+------------------------------------------------------------------+
#property copyright "fx_bot"
#property version   "1.00"
#property description "金・1時間足・買いのみの200本高値ブレイク。損切りATR×3（サーバー側）。リアル口座は既定で拒否。"

#include <Trade\Trade.mqh>

input ENUM_TIMEFRAMES InpTimeframe   = PERIOD_H1; // 足（チャートの足とは無関係）
input int             InpLookback    = 200;       // 高値・安値を見る本数
input int             InpAtrPeriod   = 14;        // ATRの期間（真の値幅の単純平均）
input double          InpSlAtr       = 3.0;       // 損切り幅（ATRの何倍か）
input double          InpRiskPct     = 0.25;      // 1回の損失（有効証拠金の%）
input double          InpMinLotMaxPct = 0.0;      // 最小ロットでも上の%を超えるとき、この%までなら最小ロットで入る（0で入らない）
input double          InpMaxDayLoss  = 0.0;       // 1日の損失上限（残高の%、0で無効）
input double          InpMaxWeekLoss = 0.0;       // 1週間の損失上限（残高の%、0で無効）
input int             InpMaxSpread   = 0;         // 入るときのスプレッド上限（ポイント、0で無効）
input int             InpDeviation   = 50;        // 許容する滑り（ポイント）
input long            InpMagic       = 310001;    // マジックナンバー
input bool            InpAllowReal   = false;     // リアル口座で動かす（既定は拒否）

CTrade   g_trade;
datetime g_lastBar     = 0;
datetime g_lastDay     = 0;
datetime g_pausedUntil = 0;
string   g_pauseKey;

//+------------------------------------------------------------------+
int OnInit()
{
   if(AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_REAL && !InpAllowReal)
   {
      Alert("リアル口座です。動かすには入力の「リアル口座で動かす」を true にしてください。");
      return INIT_FAILED;
   }
   if(InpLookback < 2 || InpAtrPeriod < 1 || InpSlAtr <= 0 || InpRiskPct <= 0)
   {
      Alert("入力値が不正です。");
      return INIT_PARAMETERS_INCORRECT;
   }
   if(SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE) != SYMBOL_TRADE_MODE_FULL)
      PrintFormat("[注意] %s はこの口座で売買が制限されています（trade_mode=%d）。注文は通りません。",
                  _Symbol, (int)SymbolInfoInteger(_Symbol, SYMBOL_TRADE_MODE));
   if(StringFind(_Symbol, "XAU") < 0)
      PrintFormat("[注意] %s は金ではありません。検証したのは XAUUSD だけです。", _Symbol);

   g_trade.SetExpertMagicNumber(InpMagic);
   g_trade.SetDeviationInPoints(InpDeviation);
   g_trade.SetTypeFillingBySymbol(_Symbol);

   g_pauseKey = StringFormat("GoldBO_%I64d_%s_pause", InpMagic, _Symbol);
   if(GlobalVariableCheck(g_pauseKey))
      g_pausedUntil = (datetime)GlobalVariableGet(g_pauseKey);

   g_lastBar = iTime(_Symbol, InpTimeframe, 0);   // 起動直後の足では入らない。次の足の確定から判断する
   Reconcile();
   PrintFormat("起動: %s %s 買いのみ 高値ブレイク%d本 損切りATR(%d)×%.1f リスク%.2f%% マジック%I64d%s%s",
               _Symbol, EnumToString(InpTimeframe), InpLookback, InpAtrPeriod, InpSlAtr, InpRiskPct, InpMagic,
               InpMaxDayLoss > 0 ? StringFormat(" 日次上限%.1f%%", InpMaxDayLoss) : "",
               InpMaxWeekLoss > 0 ? StringFormat(" 週次上限%.1f%%", InpMaxWeekLoss) : "");
   EventSetTimer(10);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   PrintFormat("停止（理由 %d）。持っているポジションと損切り注文はサーバーに残ります。", reason);
}

void OnTimer()
{
   CheckLimits(TimeTradeServer());
}

void OnTick()
{
   datetime bar = iTime(_Symbol, InpTimeframe, 0);
   if(bar == 0 || bar == g_lastBar)
      return;
   g_lastBar = bar;
   OnNewBar();
}

//+------------------------------------------------------------------+
//| 確定した足（shift=1）で判断する                                     |
//+------------------------------------------------------------------+
void OnNewBar()
{
   bool paused = CheckLimits(TimeTradeServer());
   if(Bars(_Symbol, InpTimeframe) < InpLookback + InpAtrPeriod + 3)
   {
      Print("足が足りないので判断しません。");
      return;
   }
   double close = iClose(_Symbol, InpTimeframe, 1);
   int hi = iHighest(_Symbol, InpTimeframe, MODE_HIGH, InpLookback, 2);
   int lo = iLowest(_Symbol, InpTimeframe, MODE_LOW, InpLookback, 2);
   double atr = Atr(1);
   if(close <= 0 || hi < 0 || lo < 0 || atr <= 0)
   {
      PrintFormat("足のデータが取れません（エラー %d）。", GetLastError());
      return;
   }
   double hh = iHigh(_Symbol, InpTimeframe, hi);
   double ll = iLow(_Symbol, InpTimeframe, lo);
   bool held = CountMine() > 0;
   PrintFormat("[足] %s 終値 %.2f  %d本高値 %.2f  安値 %.2f  ATR %.2f  %s%s",
               TimeToString(iTime(_Symbol, InpTimeframe, 1)), close, InpLookback, hh, ll, atr,
               held ? "保有中" : "なし", paused ? "  ※損失上限で停止中" : "");
   if(paused)
      return;
   if(close > hh && !held)
      OpenLong(atr * InpSlAtr);
   else if(close < ll && held)
      CloseAll("安値ブレイク");
}

// 真の値幅の単純平均（fx_bot の indicators.atr と同じ）
double Atr(int shift)
{
   double total = 0;
   for(int k = shift; k < shift + InpAtrPeriod; k++)
   {
      double h = iHigh(_Symbol, InpTimeframe, k), l = iLow(_Symbol, InpTimeframe, k);
      double pc = iClose(_Symbol, InpTimeframe, k + 1);
      if(h <= 0 || l <= 0 || pc <= 0)
         return 0;
      total += MathMax(h - l, MathMax(MathAbs(h - pc), MathAbs(l - pc)));
   }
   return total / InpAtrPeriod;
}

//+------------------------------------------------------------------+
void OpenLong(double stop)
{
   double ask = SymbolInfoDouble(_Symbol, SYMBOL_ASK);
   double bid = SymbolInfoDouble(_Symbol, SYMBOL_BID);
   double point = SymbolInfoDouble(_Symbol, SYMBOL_POINT);
   int digits = (int)SymbolInfoInteger(_Symbol, SYMBOL_DIGITS);
   if(ask <= 0 || bid <= 0)
   {
      Print("気配値がないので見送りました。");
      return;
   }
   int spread = (int)MathRound((ask - bid) / point);
   if(InpMaxSpread > 0 && spread > InpMaxSpread)
   {
      PrintFormat("スプレッド %d ポイントが上限 %d を超えているので見送りました。", spread, InpMaxSpread);
      return;
   }
   double sl = NormalizeDouble(ask - stop, digits);
   long level = SymbolInfoInteger(_Symbol, SYMBOL_TRADE_STOPS_LEVEL);
   if((bid - sl) / point < level)
   {
      PrintFormat("損切り幅 %.2f がブローカーの最小距離より狭いので見送りました。", stop);
      return;
   }

   double perLot;
   if(!OrderCalcProfit(ORDER_TYPE_BUY, _Symbol, 1.0, ask, sl, perLot) || perLot >= 0)
   {
      PrintFormat("損失額の計算に失敗しました（エラー %d）。", GetLastError());
      return;
   }
   perLot = -perLot;
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double vmin = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MIN);
   double vmax = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_MAX);
   double vstep = SymbolInfoDouble(_Symbol, SYMBOL_VOLUME_STEP);
   double lots = MathFloor(equity * InpRiskPct / 100.0 / perLot / vstep) * vstep;
   if(lots < vmin)
   {
      double pct = perLot * vmin / equity * 100.0;
      if(InpMinLotMaxPct <= 0 || pct > InpMinLotMaxPct)
      {
         PrintFormat("最小ロット %.2f でも損失が %.2f%% になり、上限を超えるので見送りました。", vmin, pct);
         return;
      }
      PrintFormat("[注意] 最小ロット %.2f で入ります（1回の損失 %.2f%%）。", vmin, pct);
      lots = vmin;
   }
   lots = MathMin(lots, vmax);
   lots = NormalizeDouble(lots, 2);

   double margin;
   if(OrderCalcMargin(ORDER_TYPE_BUY, _Symbol, lots, ask, margin) && margin > AccountInfoDouble(ACCOUNT_MARGIN_FREE))
   {
      PrintFormat("証拠金が足りないので見送りました（必要 %.0f）。", margin);
      return;
   }
   if(g_trade.Buy(lots, _Symbol, 0, sl, 0, "gold_bo") && g_trade.ResultRetcode() == TRADE_RETCODE_DONE)
      PrintFormat("[買い] %.2f ロット 約定 %.2f 損切り %.2f（%.2f 下）想定損失 %.0f %s",
                  lots, g_trade.ResultPrice(), sl, g_trade.ResultPrice() - sl,
                  perLot * lots, AccountInfoString(ACCOUNT_CURRENCY));
   else
      PrintFormat("[失敗] 買い注文が通りませんでした: %d %s", g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
}

int CountMine()
{
   int n = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic && PositionGetString(POSITION_SYMBOL) == _Symbol)
         n++;
   return n;
}

void CloseAll(string why)
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != InpMagic || PositionGetString(POSITION_SYMBOL) != _Symbol)
         continue;
      double profit = PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
      if(g_trade.PositionClose(ticket) && g_trade.ResultRetcode() == TRADE_RETCODE_DONE)
         PrintFormat("[手仕舞い] #%I64u（%s）約定 %.2f 損益 %+.0f", ticket, why, g_trade.ResultPrice(), profit);
      else
         PrintFormat("[失敗] #%I64u を決済できませんでした: %d %s", ticket, g_trade.ResultRetcode(), g_trade.ResultRetcodeDescription());
   }
}

// 起動時: 自分のポジションを引き継ぎ、おかしなものを知らせる
void Reconcile()
{
   int mine = 0, others = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetInteger(POSITION_MAGIC) != InpMagic || PositionGetString(POSITION_SYMBOL) != _Symbol)
      {
         others++;
         continue;
      }
      mine++;
      double sl = PositionGetDouble(POSITION_SL);
      PrintFormat("引き継ぎ: #%I64u %s %.2f ロット 建値 %.2f 損切り %.2f", ticket,
                  PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY ? "買い" : "売り",
                  PositionGetDouble(POSITION_VOLUME), PositionGetDouble(POSITION_PRICE_OPEN), sl);
      if(sl <= 0)
         PrintFormat("[注意] #%I64u に損切りがありません。", ticket);
   }
   if(mine > 1)
      PrintFormat("[注意] 自分のポジションが %d 個あります（通常は1個まで）。", mine);
   if(others > 0)
      PrintFormat("ほかのポジション %d 個（手動・別EA）には触りません。", others);
   if(g_pausedUntil > 0)
      PrintFormat("損失上限の停止を引き継ぎました（%s まで）。", TimeToString(g_pausedUntil));
}

//+------------------------------------------------------------------+
//| 損失上限（fx_bot の LossLimit と同じ考え方）                        |
//| 損失 = −(期間内の確定損益 + 含み損益)。上限に達したら全決済し、     |
//| 日次なら翌日、週次なら翌週月曜（サーバー時刻）まで新規を止める。    |
//+------------------------------------------------------------------+
datetime DayStart(datetime t)  { return t - t % 86400; }
datetime WeekStart(datetime t) { MqlDateTime d; TimeToStruct(t, d); return DayStart(t) - ((d.day_of_week + 6) % 7) * 86400; }

double Realized(datetime from, datetime to)
{
   double sum = 0;
   if(!HistorySelect(from, to))
      return 0;
   for(int i = HistoryDealsTotal() - 1; i >= 0; i--)
   {
      ulong d = HistoryDealGetTicket(i);
      if(d == 0 || HistoryDealGetInteger(d, DEAL_MAGIC) != InpMagic || HistoryDealGetString(d, DEAL_SYMBOL) != _Symbol)
         continue;
      datetime t = (datetime)HistoryDealGetInteger(d, DEAL_TIME);
      if(t < from || t >= to)
         continue;
      sum += HistoryDealGetDouble(d, DEAL_PROFIT) + HistoryDealGetDouble(d, DEAL_SWAP)
           + HistoryDealGetDouble(d, DEAL_COMMISSION) + HistoryDealGetDouble(d, DEAL_FEE);
   }
   return sum;
}

double Floating()
{
   double sum = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
      if(PositionGetTicket(i) > 0 && PositionGetInteger(POSITION_MAGIC) == InpMagic && PositionGetString(POSITION_SYMBOL) == _Symbol)
         sum += PositionGetDouble(POSITION_PROFIT) + PositionGetDouble(POSITION_SWAP);
   return sum;
}

// 新規を止めているなら true
bool CheckLimits(datetime now)
{
   datetime day = DayStart(now);
   if(g_lastDay != 0 && day != g_lastDay)
      PrintFormat("[日報] %s の確定損益 %+.0f %s", TimeToString(g_lastDay, TIME_DATE),
                  Realized(g_lastDay, day), AccountInfoString(ACCOUNT_CURRENCY));
   g_lastDay = day;

   if(g_pausedUntil > 0)
   {
      if(now < g_pausedUntil)
         return true;
      Print("[再開] 損失上限による停止を解除しました。");
      g_pausedUntil = 0;
      GlobalVariableDel(g_pauseKey);
   }
   if(InpMaxDayLoss <= 0 && InpMaxWeekLoss <= 0)
      return false;

   double balance = AccountInfoDouble(ACCOUNT_BALANCE);
   double floating = Floating();
   if(InpMaxDayLoss > 0)
   {
      double loss = -(Realized(day, now + 86400) + floating);
      if(loss >= balance * InpMaxDayLoss / 100.0)
         return Halt("本日", loss, InpMaxDayLoss, day + 86400);
   }
   if(InpMaxWeekLoss > 0)
   {
      datetime week = WeekStart(now);
      double loss = -(Realized(week, now + 86400) + floating);
      if(loss >= balance * InpMaxWeekLoss / 100.0)
         return Halt("今週", loss, InpMaxWeekLoss, week + 7 * 86400);
   }
   return false;
}

bool Halt(string span, double loss, double pct, datetime until)
{
   PrintFormat("[停止] %sの損失 %.0f %s が上限 %.1f%% に達しました。全決済し、%s まで新規を止めます。",
               span, loss, AccountInfoString(ACCOUNT_CURRENCY), pct, TimeToString(until));
   CloseAll("損失上限");
   g_pausedUntil = until;
   GlobalVariableSet(g_pauseKey, (double)until);
   return true;
}
//+------------------------------------------------------------------+
