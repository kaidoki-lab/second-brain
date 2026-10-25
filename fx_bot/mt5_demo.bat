@echo off
chcp 65001 > nul
setlocal
title MT5 デモ自動売買
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
echo ============================================
echo   デモ口座で自動売買を始めます
echo   リアル口座では動きません。止めるときは Ctrl+C
echo ============================================
echo.
set SYMBOL=USDJPY
set /p SYMBOL=銘柄名 (そのまま Enter で USDJPY): 
python run.py live --symbol %SYMBOL% --timeframe H1 --strategy ma_cross
pause
endlocal
