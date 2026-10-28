@echo off
chcp 65001 > nul
setlocal
title MT5 デモ session_bo (USDJPY H1)
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。mt5_demo.bat と同じ準備をしてください。
  pause
  exit /b 1
)

echo ※ MT5 を起動してデモ口座にログインした状態で実行してください。
echo.
echo ============================================
echo   デモ口座で session_bo を動かします（前進テスト）
echo   USDJPY H1 / 0-10時のレンジ抜け / 22時に手仕舞い
echo   買いのみ・金曜は休み / 1回の損失 0.5%% / 損失上限 1日1.5%% 1週3%%
echo   約定の記録: data\fills_USDJPY.csv
echo   リアル口座では動きません。止めるときは Ctrl+C
echo ============================================
echo.
python run.py live --symbol USDJPY --timeframe H1 --strategy session_bo --risk 0.5 ^
  --params rs=0,re=10,exit_h=22,sl_atr=2,tp_atr=0,side=1,no_fri=1 --max-day-loss 1.5 --max-week-loss 3 ^
  --terminal "C:\Program Files\MetaTrader 5\terminal64.exe"
pause
endlocal
