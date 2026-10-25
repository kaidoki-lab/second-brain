@echo off
chcp 65001 > nul
setlocal
title MT5 過去データ取得
cd /d "%~dp0"

where python > nul 2>&1
if errorlevel 1 (
  echo [エラー] python が見つかりません。python.org から Python 3 をインストールし、
  echo         "Add python.exe to PATH" にチェックを入れてください。
  pause
  exit /b 1
)

python -c "import MetaTrader5" > nul 2>&1
if errorlevel 1 (
  echo MetaTrader5 パッケージを入れます（初回のみ）...
  python -m pip install MetaTrader5
  if errorlevel 1 (
    echo [エラー] インストールに失敗しました。README.md の「MT5 とつなぐ」を参照してください。
    pause
    exit /b 1
  )
)

echo ※ MT5 を起動してログインした状態で実行してください。
echo.
set SYMBOL=USDJPY
set /p SYMBOL=銘柄名 (そのまま Enter で USDJPY。業者によっては USDJPY- など): 
python run.py fetch --symbol %SYMBOL% --timeframe H1
echo.
echo  続けて data\%SYMBOL%_H1.csv でバックテストできます:
echo    python run.py backtest --csv data\%SYMBOL%_H1.csv --symbol %SYMBOL%
pause
endlocal
