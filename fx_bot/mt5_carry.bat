@echo off
chcp 65001 > nul
setlocal
title MT5 デモ carry (外為ファイネスト D1)
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。mt5_demo.bat と同じ準備をしてください。
  pause
  exit /b 1
)

set "MT5EXE=C:\Program Files\Gaitame Finest MetaTrader 5 Terminal\terminal64.exe"
set "COMMON=--timeframe D1 --strategy carry --risk 3 --params regime=50 --magic 210002 --terminal "%MT5EXE%""

echo ※ 外為ファイネストの MT5 を起動してデモ口座にログインし、「アルゴリズム取引」を緑にしてから実行してください。
echo.
echo ============================================
echo   外為ファイネストのデモ口座で carry を動かします（前進テスト）
echo   USDJPY- / AUDJPY- / GBPJPY- を日足で、それぞれ別ウィンドウ
echo   スワップが受け取れる側（今は買い）に持ち、終値が50日SMAより下なら降りる
echo   1回の損失 3%% / 損切りは ATR(20)×5 / 目印 210002
echo   ログ: data\carry_^<銘柄^>\  約定: data\fills_^<銘柄^>.csv
echo   リアル口座では動きません。止めるときは各ウィンドウで Ctrl+C
echo ============================================
echo.
for %%S in (USDJPY- AUDJPY- GBPJPY-) do (
  start "carry %%S" cmd /k python run.py live --symbol %%S %COMMON% --log-dir data\carry_%%S
)
endlocal
