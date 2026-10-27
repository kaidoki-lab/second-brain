@echo off
chcp 65001 > nul
setlocal
title MT5 デモ 一目 USDJPY- H1 (外為ファイネスト)
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。mt5_demo.bat と同じ準備をしてください。
  pause
  exit /b 1
)

set "MT5EXE=C:\Program Files\Gaitame Finest MetaTrader 5 Terminal\terminal64.exe"

echo ※ 外為ファイネストの MT5 を起動してデモ口座にログインし、「アルゴリズム取引」を緑にしてから実行してください。
echo.
echo ============================================
echo   外為ファイネストのデモ口座で 一目（転換線×基準線 9/26）を動かします（前進テスト）
echo   USDJPY- を1時間足で。転換線が基準線を上に抜けたら買い、下に抜けたら売り（ドテン）
echo   1回の損失 0.25%% / 損切りは ATR(14)×2 / 利確なし / 目印 210003
echo   ログ: data\ichimoku\  約定: data\ichimoku\fills_USDJPY-.csv
echo   carry（目印 210002）と同じ口座で動きます。リアル口座では動きません。止めるときは Ctrl+C
echo ============================================
echo.
python run.py live --symbol USDJPY- --timeframe H1 --strategy combo --risk 0.25 --params sig=4,flt=0,tenkan=9,kijun=26,sl_atr=2,tp_atr=0 --magic 210003 --terminal "%MT5EXE%" --log-dir data\ichimoku --fills data\ichimoku\fills_USDJPY-.csv
echo.
echo 終了しました。
pause
endlocal